# Выполнить JS во ВСЕХ page-таргетах TradingView и вернуть результаты.
# Нужно потому, что Pine Editor у Егора — ОТДЕЛЬНОЕ окно Electron: MCP-инструменты
# ui_click/ui_evaluate работают только с окном графика, кнопки редактора им не видны.
param([Parameter(Mandatory = $true)][string]$Js)

$targets = (Invoke-WebRequest "http://127.0.0.1:9222/json/list" -TimeoutSec 5 -UseBasicParsing).Content | ConvertFrom-Json
$pages = $targets | Where-Object { $_.type -eq 'page' -and $_.webSocketDebuggerUrl }

foreach ($p in $pages) {
    $ws = New-Object System.Net.WebSockets.ClientWebSocket
    $ct = [System.Threading.CancellationToken]::None
    try {
        $ws.ConnectAsync([Uri]$p.webSocketDebuggerUrl, $ct).Wait(4000) | Out-Null
        if ($ws.State -ne 'Open') { continue }
        $payload = @{ id = 1; method = 'Runtime.evaluate'; params = @{ expression = $Js; returnByValue = $true; awaitPromise = $true } } | ConvertTo-Json -Depth 8 -Compress
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
        $seg = New-Object System.ArraySegment[byte] (, $bytes)
        $ws.SendAsync($seg, 'Text', $true, $ct).Wait(4000) | Out-Null

        $buf = New-Object byte[] 65536
        $sb = New-Object System.Text.StringBuilder
        do {
            $rseg = New-Object System.ArraySegment[byte] (, $buf)
            $t = $ws.ReceiveAsync($rseg, $ct)
            if (-not $t.Wait(5000)) { break }
            $r = $t.Result
            [void]$sb.Append([System.Text.Encoding]::UTF8.GetString($buf, 0, $r.Count))
        } while (-not $r.EndOfMessage)

        $txt = $sb.ToString()
        if ($txt -and $txt -notmatch '"method"') {
            $obj = $txt | ConvertFrom-Json
            $val = $obj.result.result.value
            if ($null -ne $val -and "$val" -ne '') {
                Write-Output ("[{0}] {1}" -f $p.id.Substring(0, 6), $val)
            }
        }
    }
    catch { }
    finally { try { $ws.Dispose() } catch { } }
}
