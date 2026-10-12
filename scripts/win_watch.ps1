param([int]$Dur = 1200, [string]$Out, [int]$StopAfter = 1)
# Запуск:  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\win_watch.ps1 -Dur 900 -Out C:\tmp\win.log
# 12.10.2026: так найден traffic-log (окно терминала каждые 10 минут). Файл хранить в UTF-8 С BOM —
# Windows PowerShell 5.1 читает .ps1 без BOM как cp1251 и портит кириллицу в журнале.
# Ловушка ОКОН: раз в ~60 мс перечисляем видимые окна верхнего уровня. Новое окно консоли / Windows Terminal →
# пишем время, класс, заголовок, владельца и все процессы моложе 5 с (с родителями). После $StopAfter пойманных
# консольных окон выходим — чтобы сессию позвали сразу.
Add-Type @"
using System; using System.Text; using System.Collections.Generic; using System.Runtime.InteropServices;
public class WW {
  delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc f, IntPtr l);
  [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr h, out RECT r);
  public struct RECT { public int L, T, R, B; }
  public static List<string> Snap() {
    var res = new List<string>();
    EnumWindows((h, l) => {
      if (IsWindowVisible(h)) {
        var c = new StringBuilder(256); GetClassName(h, c, 256);
        var t = new StringBuilder(256); GetWindowText(h, t, 256);
        uint pid; GetWindowThreadProcessId(h, out pid);
        RECT r; GetWindowRect(h, out r);
        res.Add(h.ToInt64() + "\t" + pid + "\t" + c + "\t" + (r.R - r.L) + "x" + (r.B - r.T) + "\t" + t);
      }
      return true;
    }, IntPtr.Zero);
    return res;
  }
}
"@
function W($s) { Add-Content -Path $Out -Value $s -Encoding utf8 }
$seen = @{}
foreach ($l in [WW]::Snap()) { $seen[$l.Split("`t")[0]] = 1 }
W ("{0:HH:mm:ss.fff} СТАРТ ловушки окон, видимых окон сейчас {1}" -f (Get-Date), $seen.Count)
$end = (Get-Date).AddSeconds($Dur); $hits = 0; $open = @{}
while ((Get-Date) -lt $end) {
    $now = Get-Date
    $cur = @{}
    foreach ($l in [WW]::Snap()) {
        $f = $l.Split("`t"); $cur[$f[0]] = 1
        if ($seen.ContainsKey($f[0])) { continue }
        $seen[$f[0]] = 1
        $pn = '?'
        try { $pn = [System.Diagnostics.Process]::GetProcessById([int]$f[1]).ProcessName } catch {}
        $isCon = ($f[2] -match 'ConsoleWindowClass|CASCADIA|PseudoConsole') -or ($pn -match '^(conhost|OpenConsole|WindowsTerminal|cmd|powershell|pwsh)$')
        W ("{0:HH:mm:ss.fff} {1} hwnd={2} pid={3} {4} класс={5} размер={6} заголовок=«{7}»" -f $now, $(if ($isCon) { '🔴 КОНСОЛЬ' } else { 'окно' }), $f[0], $f[1], $pn, $f[2], $f[3], $f[4])
        if ($isCon) {
            $open[$f[0]] = $now
            $all = Get-CimInstance Win32_Process
            $byId = @{}; foreach ($p in $all) { $byId[[int]$p.ProcessId] = $p }
            $own = $byId[[int]$f[1]]
            $chain = @(); $x = $own; $n = 0
            while ($x -and $n -lt 6) { $cl = [string]$x.CommandLine; $chain += ("{0}({1}) {2}" -f $x.Name, $x.ProcessId, $cl.Substring(0, [Math]::Min(160, $cl.Length))); $x = $byId[[int]$x.ParentProcessId]; $n++ }
            W ("      цепочка владельца: " + ($chain -join "  ←  "))
            foreach ($p in ($all | Where-Object { $_.CreationDate -gt $now.AddSeconds(-5) } | Sort-Object CreationDate)) {
                $par = $byId[[int]$p.ParentProcessId]; $cl = [string]$p.CommandLine; $pcl = if ($par) { [string]$par.CommandLine } else { '' }
                W ("      свежий {0:HH:mm:ss.fff} {1}({2}) {3} | родитель {4}({5}) {6}" -f $p.CreationDate, $p.Name, $p.ProcessId, $cl.Substring(0, [Math]::Min(170, $cl.Length)), $(if ($par) { $par.Name } else { '?' }), $p.ParentProcessId, $pcl.Substring(0, [Math]::Min(120, $pcl.Length)))
            }
            $hits++
        }
    }
    foreach ($h in @($open.Keys)) {
        if (-not $cur.ContainsKey($h)) { W ("{0:HH:mm:ss.fff}      окно hwnd={1} закрылось, прожило {2:N0} мс" -f (Get-Date), $h, ((Get-Date) - $open[$h]).TotalMilliseconds); $open.Remove($h) }
    }
    if ($hits -ge $StopAfter -and $open.Count -eq 0) { Start-Sleep -Seconds 2; W ("{0:HH:mm:ss.fff} СТОП: поймано {1}" -f (Get-Date), $hits); break }
    Start-Sleep -Milliseconds 60
}
if ($hits -eq 0) { W ("{0:HH:mm:ss.fff} СТОП по времени: консольных окон не было" -f (Get-Date)) }
