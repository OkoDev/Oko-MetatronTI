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

try { pm2 resurrect 2>&1 | ForEach-Object { Write-Log "pm2: $_" } }
catch { Write-Log "pm2 resurrect упал: $_" }

Start-Sleep -Seconds 40

# Проверка 1: сколько процессов online
try {
    $list = pm2 jlist | ConvertFrom-Json
    $online = @($list | Where-Object { $_.pm2_env.status -eq 'online' })
    Write-Log ("процессов online: {0} из {1}" -f $online.Count, @($list).Count)
    foreach ($n in @('oko-bot', 'structure-term', 'oko-api', 'wave5-shadow')) {
        $st = ($list | Where-Object { $_.name -eq $n } | Select-Object -First 1).pm2_env.status
        Write-Log ("  {0}: {1}" -f $n, $(if ($st) { $st } else { 'НЕТ В СПИСКЕ' }))
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
