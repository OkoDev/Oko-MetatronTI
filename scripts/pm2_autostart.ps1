# Автоподъём стенда после перезагрузки/BSOD (26.09.2026, Егор: «да, но с задержкой и проверкой»).
# Причина: простой 24-25.09 длился 36.5 ч — машина умерла, а автозапуска pm2 не было вовсе.
# Ставится один раз:  powershell -ExecutionPolicy Bypass -File scripts\pm2_autostart.ps1 -Install
# Проверить:          schtasks /query /tn "OkoBot-pm2-resurrect" /v /fo LIST
# Снять:              schtasks /delete /tn "OkoBot-pm2-resurrect" /f

param(
    [switch]$Install,          # создать задачу «при запуске системы» (нужен запуск от АДМИНИСТРАТОРА)
    [switch]$AtLogon,          # запасной режим: «при входе в систему», ставится БЕЗ админ-прав
    [int]$DelayMinutes = 3     # пауза перед подъёмом: ждём диски G: и C:\oko_history
)

$ErrorActionPreference = 'Stop'
$TaskName = 'OkoBot-pm2-resurrect'
$Self     = $MyInvocation.MyCommand.Path
$LogFile  = 'E:\MTF BOT\CURSOR\crypto_volume_bot\data\pm2_autostart.log'

function Write-Log($msg) {
    $line = "{0} {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Write-Output $line
    try { Add-Content -Path $LogFile -Value $line -Encoding utf8 } catch { }
}

if ($AtLogon) {
    # Без админ-прав: задача от текущего пользователя, срабатывает при его входе в систему.
    # Слабее ONSTART (нужен логин), но переживает перезагрузку при автовходе.
    try {
        $act = New-ScheduledTaskAction -Execute 'powershell.exe' `
               -Argument ('-ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File "{0}"' -f $Self)
        $trg = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
        $trg.Delay = 'PT{0}M' -f $DelayMinutes
        $set = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
        Register-ScheduledTask -TaskName "$TaskName-logon" -Action $act -Trigger $trg -Settings $set -Force | Out-Null
        Write-Log "задача '$TaskName-logon' создана (при входе в систему), задержка $DelayMinutes мин"
    } catch {
        Write-Log "не удалось создать задачу при входе: $_"
    }
    return
}

if ($Install) {
    # schtasks спотыкается о пробелы в пути («MTF BOT») — ставим через Register-ScheduledTask.
    # Триггер AtStartup + Delay: ждём, пока система поднимет диски и сеть.
    try {
        $act = New-ScheduledTaskAction -Execute 'powershell.exe' `
               -Argument ('-ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File "{0}"' -f $Self)
        $trg = New-ScheduledTaskTrigger -AtStartup
        $trg.Delay = 'PT{0}M' -f $DelayMinutes
        $set = New-ScheduledTaskSettingsSet -StartWhenAvailable `
               -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 5)
        Register-ScheduledTask -TaskName $TaskName -Action $act -Trigger $trg -Settings $set `
               -User 'SYSTEM' -RunLevel Highest -Force | Out-Null
        Write-Log "задача '$TaskName' создана, задержка $DelayMinutes мин"
    } catch {
        Write-Log "не удалось создать задачу: $_ — запусти PowerShell ОТ АДМИНИСТРАТОРА и повтори"
    }
    return
}

# ── рабочий ход: поднять сохранённый список процессов и проверить, что стенд ожил
Write-Log '--- автоподъём после старта системы'

# Диски должны быть на месте: G: — кэш ТФ, C:\oko_history — паркеты 1m (junction)
foreach ($p in @('G:\oko_lab', 'C:\oko_history')) {
    for ($i = 0; $i -lt 10 -and -not (Test-Path $p); $i++) { Start-Sleep -Seconds 10 }
    if (Test-Path $p) { Write-Log "путь доступен: $p" } else { Write-Log "ВНИМАНИЕ: путь НЕ доступен: $p" }
}

# Таблицу pm2 в лог не тащим: она давала ~10 КБ на каждый подъём и топила настоящие строки.
# Статусы всё равно проверяются ниже через jlist; сюда — только жалобы pm2 и размер вывода.
try {
    $out = pm2 resurrect 2>&1 | Out-String
    $bad = @($out -split "`r?`n" | Where-Object { $_ -match '(?i)error|not found|failed' })
    if ($bad.Count) { $bad | ForEach-Object { Write-Log "pm2: $_" } }
    Write-Log ("pm2 resurrect отработал ({0} строк вывода, жалоб: {1})" -f @($out -split "`r?`n").Count, $bad.Count)
} catch { Write-Log "pm2 resurrect упал: $_" }

Start-Sleep -Seconds 40

# Проверка 1: сколько процессов online.
# 🔴 ConvertFrom-Json на PowerShell 5.1 ЗДЕСЬ ПАДАЛ: pm2 отдаёт env и с `username`, и с
# `USERNAME` — для 5.1 это «повторяющиеся ключи», и вся проверка процессов молча терялась
# (лог 27.09: «pm2 jlist не прочитался»). Разбираем питоном — он и так есть, pm2 крутит
# на нём сам бот. Регистр ключей питону безразличен.
$py = 'C:\Users\yogoru\AppData\Local\Programs\Python\Python312\python.exe'
if (-not (Test-Path $py)) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $py = $cmd.Source } else { $py = $null }
}
try {
    if (-not $py) { throw 'python не найден — статусы процессов не проверить' }
    # Литералы в питоне ТОЛЬКО в одинарных кавычках ('' внутри строки PS): двойные PowerShell
    # съедает при передаче нативному exe, и питон падает с «name is not defined».
    # chr(91)='[' (отрезаем возможный мусор pm2 перед JSON), chr(9)=TAB, chr(10)=LF.
    $code = 'import sys,json;t=sys.stdin.read();t=t[t.find(chr(91)):];a=json.loads(t);print(chr(10).join(str(p.get(''name''))+chr(9)+str((p.get(''pm2_env'') or {}).get(''status'')) for p in a))'
    $rows = (pm2 jlist 2>$null | Out-String) | & $py -c $code
    $st = @{}
    foreach ($r in @($rows)) {
        if ($r -match '^(.+)\t(.+)$') { $st[$Matches[1]] = $Matches[2] }
    }
    $online = @($st.Values | Where-Object { $_ -eq 'online' })
    # «online меньше половины» — это НОРМА: 18 из 38 записей — cron-задачи с autorestart=False,
    # между запусками они законно stopped. Смотреть надо на четыре имени ниже.
    Write-Log ("процессов online: {0} из {1} (cron-задачи между запусками stopped — норма)" -f $online.Count, $st.Count)
    foreach ($n in @('oko-bot', 'structure-term', 'oko-api', 'wave5-shadow')) {
        Write-Log ("  {0}: {1}" -f $n, $(if ($st.ContainsKey($n)) { $st[$n] } else { 'НЕТ В СПИСКЕ' }))
    }
} catch { Write-Log "pm2 jlist не прочитался: $_" }

# Проверка 2: терминал структуры отвечает на :8010 (признак живого стека, а не пустой обёртки)
$ok = $false
for ($i = 0; $i -lt 6 -and -not $ok; $i++) {
    try {
        $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8010/' -TimeoutSec 5 -UseBasicParsing
        if ($r.StatusCode -eq 200) { $ok = $true }
    } catch { Start-Sleep -Seconds 20 }
}
Write-Log $(if ($ok) { 'порт 8010 отвечает — стенд поднялся' } else { 'ПОРТ 8010 МОЛЧИТ — поднять руками' })
