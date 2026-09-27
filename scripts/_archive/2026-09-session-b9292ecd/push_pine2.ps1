# Залить .pine в редактор через CDP Input.insertText (Monaco принимает его как ввод).
# ClipboardEvent Monaco игнорирует, Ctrl+V из ui_keyboard после перезапуска TW не доходит,
# а pine_set_source гоняет 57 КБ через контекст ассистента — дорого на каждой правке.
param(
    [Parameter(Mandatory = $true)][string]$Path,
    [int]$ChunkSize = 12000
)

$text = Get-Content $Path -Raw -Encoding UTF8
$targets = (Invoke-WebRequest "http://127.0.0.1:9222/json/list" -TimeoutSec 5 -UseBasicParsing).Content | ConvertFrom-Json
# редактор живёт в том же page, где график (проверено: monaco=2)
$page = $targets | Where-Object { $_.type -eq 'page' -and $_.url -like '*tradingview.com/chart*' } | Select-Object -First 1
if (-not $page) { "chart page not found"; exit 1 }

$ws = New-Object System.Net.WebSockets.ClientWebSocket
$ct = [System.Threading.CancellationToken]::None
$ws.ConnectAsync([Uri]$page.webSocketDebuggerUrl, $ct).Wait(5000) | Out-Null
if ($ws.State -ne 'Open') { "cdp connect failed"; exit 1 }

function Send-Cdp($id, $method, $params) {
    $payload = @{ id = $id; method = $method; params = $params } | ConvertTo-Json -Depth 10 -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
    $ws.SendAsync((New-Object System.ArraySegment[byte] (, $bytes)), 'Text', $true, $ct).Wait(8000) | Out-Null
    $buf = New-Object byte[] 65536
    do {
        $t = $ws.ReceiveAsync((New-Object System.ArraySegment[byte] (, $buf)), $ct)
        if (-not $t.Wait(8000)) { return }
        $r = $t.Result
    } while (-not $r.EndOfMessage)
}

$id = 1
# фокус в область кода + выделить всё + удалить
Send-Cdp $id 'Runtime.evaluate' @{ expression = "(function(){var ta=document.querySelector('.monaco-editor textarea'); if(ta) ta.focus(); return !!ta;})()" ; returnByValue = $true }
$id++
foreach ($mod in @(2)) {
    # Ctrl+A
    Send-Cdp $id 'Input.dispatchKeyEvent' @{ type = 'keyDown'; modifiers = $mod; key = 'a'; code = 'KeyA'; windowsVirtualKeyCode = 65 }; $id++
    Send-Cdp $id 'Input.dispatchKeyEvent' @{ type = 'keyUp'; modifiers = $mod; key = 'a'; code = 'KeyA'; windowsVirtualKeyCode = 65 }; $id++
}
# Delete
Send-Cdp $id 'Input.dispatchKeyEvent' @{ type = 'keyDown'; key = 'Delete'; code = 'Delete'; windowsVirtualKeyCode = 46 }; $id++
Send-Cdp $id 'Input.dispatchKeyEvent' @{ type = 'keyUp'; key = 'Delete'; code = 'Delete'; windowsVirtualKeyCode = 46 }; $id++

$sent = 0
for ($i = 0; $i -lt $text.Length; $i += $ChunkSize) {
    $chunk = $text.Substring($i, [Math]::Min($ChunkSize, $text.Length - $i))
    Send-Cdp $id 'Input.insertText' @{ text = $chunk }
    $id++
    $sent += $chunk.Length
}
$ws.Dispose()
"inserted $sent of $($text.Length) chars"

