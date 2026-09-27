# Залить .pine прямо в Monaco через CDP: файл читается здесь и уходит в редактор,
# минуя контекст ассистента. Ctrl+V через ui_keyboard после перезапуска TW не доходит,
# а pine_set_source гоняет весь текст через диалог — дорого на 50 КБ.
param([Parameter(Mandatory = $true)][string]$Path)

$text = Get-Content $Path -Raw -Encoding UTF8
# ConvertTo-Json в PS 5.1 отдаёт объект при подстановке в here-string — экранируем сами
$esc = $text.Replace('\', '\\').Replace("'", "\'").Replace("`r", '').Replace("`n", '\n')

$js = @"
(function(){
  var text = '$esc';
  var ta = document.querySelector('.monaco-editor textarea');
  if (!ta) return 'no monaco textarea';
  ta.focus();
  var dt = new DataTransfer();
  dt.setData('text/plain', text);
  var ev = new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true});
  document.execCommand('selectAll');
  ta.dispatchEvent(ev);
  return 'pasted ' + text.length + ' chars';
})()
"@

$targets = (Invoke-WebRequest "http://127.0.0.1:9222/json/list" -TimeoutSec 5 -UseBasicParsing).Content | ConvertFrom-Json
$pages = $targets | Where-Object { $_.type -eq 'page' -and $_.webSocketDebuggerUrl }

foreach ($p in $pages) {
    $ws = New-Object System.Net.WebSockets.ClientWebSocket
    $ct = [System.Threading.CancellationToken]::None
    try {
        $ws.ConnectAsync([Uri]$p.webSocketDebuggerUrl, $ct).Wait(4000) | Out-Null
        if ($ws.State -ne 'Open') { continue }
        $payload = @{ id = 1; method = 'Runtime.evaluate'; params = @{ expression = $js; returnByValue = $true } } | ConvertTo-Json -Depth 8 -Compress
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
        $ws.SendAsync((New-Object System.ArraySegment[byte] (, $bytes)), 'Text', $true, $ct).Wait(8000) | Out-Null

        $buf = New-Object byte[] 262144
        $sb = New-Object System.Text.StringBuilder
        do {
            $t = $ws.ReceiveAsync((New-Object System.ArraySegment[byte] (, $buf)), $ct)
            if (-not $t.Wait(8000)) { break }
            $r = $t.Result
            [void]$sb.Append([System.Text.Encoding]::UTF8.GetString($buf, 0, $r.Count))
        } while (-not $r.EndOfMessage)

        $txt = $sb.ToString()
        if ($txt -and $txt -notmatch '"method"') {
            $val = ($txt | ConvertFrom-Json).result.result.value
            if ($val) { Write-Output ("[{0}] {1}" -f $p.id.Substring(0, 6), $val) }
        }
    }
    catch { }
    finally { try { $ws.Dispose() } catch { } }
}
