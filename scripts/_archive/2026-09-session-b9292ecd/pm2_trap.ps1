# Ловушка: кто вызывает pm2 restart/stop для oko-bot (15.09). Опрос раз в секунду, до 3 часов; пишет цепочку родителей.
$log = "C:\Users\yogoru\AppData\Local\Temp\claude\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad\pm2_trap.log"
$seen = @{}
$end = (Get-Date).AddHours(3)
while ((Get-Date) -lt $end) {
  $ps = Get-CimInstance Win32_Process -Filter "Name='node.exe' OR Name='cmd.exe' OR Name='powershell.exe' OR Name='python.exe' OR Name='pwsh.exe'" -ErrorAction SilentlyContinue
  foreach ($p in $ps) {
    $cl = [string]$p.CommandLine
    if ($cl -match 'pm2' -and $cl -match '(restart|stop|reload|delete)' -and -not $seen.ContainsKey($p.ProcessId)) {
      $seen[$p.ProcessId] = 1
      $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ПОЙМАН pid=$($p.ProcessId) :: $cl"
      $cur = $p.ParentProcessId; $depth = 0
      while ($cur -and $depth -lt 8) {
        $pp = Get-CimInstance Win32_Process -Filter "ProcessId=$cur" -ErrorAction SilentlyContinue
        if (-not $pp) { $line += "`n    parent $cur (уже завершён)"; break }
        $line += "`n    parent $($pp.ProcessId) $($pp.Name) start $($pp.CreationDate) :: $([string]$pp.CommandLine)"
        $cur = $pp.ParentProcessId; $depth++
      }
      Add-Content -Path $log -Value $line -Encoding UTF8
    }
  }
  Start-Sleep -Milliseconds 700
}
