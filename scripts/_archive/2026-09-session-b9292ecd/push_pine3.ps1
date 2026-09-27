# Fast one-shot push of a .pine file into the TradingView Pine editor via CDP.
# Ctrl+V from ui_keyboard stopped working after the app restart, ClipboardEvent is
# ignored by Monaco, and pine_set_source pushes 57 KB through the assistant context.
# Input.insertText behaves like typing, so Monaco accepts it.
param([Parameter(Mandatory = $true)][string]$Path)

$text = Get-Content $Path -Raw -Encoding UTF8
$targets = (Invoke-WebRequest "http://127.0.0.1:9222/json/list" -TimeoutSec 5 -UseBasicParsing).Content | ConvertFrom-Json
$page = $targets | Where-Object { $_.type -eq 'page' -and $_.url -like '*tradingview.com/chart*' } | Select-Object -First 1
if (-not $page) { "chart page not found"; exit 1 }

$ws = New-Object System.Net.WebSockets.ClientWebSocket
$ct = [System.Threading.CancellationToken]::None
$ws.ConnectAsync([Uri]$page.webSocketDebuggerUrl, $ct).Wait(5000) | Out-Null
if ($ws.State -ne 'Open') { "cdp connect failed"; exit 1 }

function Fire($id, $method, $params) {
    $payload = @{ id = $id; method = $method; params = $params } | ConvertTo-Json -Depth 10 -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
    $ws.SendAsync((New-Object System.ArraySegment[byte] (, $bytes)), 'Text', $true, $ct).Wait(15000) | Out-Null
}

Fire 1 'Runtime.evaluate' @{ expression = "(function(){var ta=document.querySelector('.monaco-editor textarea'); if(ta){ta.focus();} return !!ta;})()"; returnByValue = $true }
Start-Sleep -Milliseconds 400
Fire 2 'Input.dispatchKeyEvent' @{ type = 'keyDown'; modifiers = 2; key = 'a'; code = 'KeyA'; windowsVirtualKeyCode = 65 }
Fire 3 'Input.dispatchKeyEvent' @{ type = 'keyUp'; modifiers = 2; key = 'a'; code = 'KeyA'; windowsVirtualKeyCode = 65 }
Start-Sleep -Milliseconds 200
# 57 КБ одним insertText Chrome молча роняет — шлём кусками, курсор сам едет в конец
$id = 4
$chunk = 8000
for ($i = 0; $i -lt $text.Length; $i += $chunk) {
    $part = $text.Substring($i, [Math]::Min($chunk, $text.Length - $i))
    Fire $id 'Input.insertText' @{ text = $part }
    $id++
    Start-Sleep -Milliseconds 250
}
Start-Sleep -Milliseconds 600
$ws.Dispose()
"sent $($text.Length) chars in $($id - 4) chunks"
