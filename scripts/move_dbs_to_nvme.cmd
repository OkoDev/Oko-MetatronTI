@echo off
chcp 65001 >nul
REM ═══════════════════════════════════════════════════════════════════════════════════════════
REM  Перенос баз на NVMe (16.09.2026, Егор: «все сразу, на C: NVMe, создай отдельную папку»).
REM  Останавливает pm2 → переносит ohlcv_cache.db (19 ГБ) и subscriptions.db на C:\oko_data →
REM  ставит на прежние места символические ссылки (пути в коде не меняются) → поднимает сервисы.
REM  Запускать обычным двойным кликом: скрипт САМ запросит права администратора (UAC),
REM  они нужны только для создания ссылок на файлы. Весь ход пишется в C:\oko_data\move_log.txt.
REM ═══════════════════════════════════════════════════════════════════════════════════════════
setlocal EnableExtensions
set "REPO=E:\MTF BOT\CURSOR\crypto_volume_bot"
set "DEST=C:\oko_data"
set "LOG=%DEST%\move_log.txt"

net session >nul 2>&1
if errorlevel 1 (
  echo Нужны права администратора — запрашиваю их (подтвердите окно Windows)...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b 0
)

if not exist "%DEST%" mkdir "%DEST%"
call :log "=== старт %DATE% %TIME% ==="

call :log "1/5 остановка сервисов pm2"
call pm2 stop all >>"%LOG%" 2>&1
timeout /t 5 /nobreak >nul
taskkill /F /IM python.exe >nul 2>&1
timeout /t 3 /nobreak >nul

call :log "2/5 перенос баз (19 ГБ — несколько минут)"
for %%F in (ohlcv_cache.db subscriptions.db) do (
  if exist "%REPO%\%%F" (
    call :log "   перенос %%F"
    move /Y "%REPO%\%%F" "%DEST%\%%F" >>"%LOG%" 2>&1
    if errorlevel 1 (
      call :log "   [ОШИБКА] не удалось перенести %%F — поднимаю сервисы и выхожу"
      call pm2 start all >>"%LOG%" 2>&1
      goto :finish
    )
  )
  for %%S in (-wal -shm) do if exist "%REPO%\%%F%%S" move /Y "%REPO%\%%F%%S" "%DEST%\" >>"%LOG%" 2>&1
)

call :log "3/5 создание ссылок на прежних местах"
for %%F in (ohlcv_cache.db subscriptions.db) do (
  if exist "%DEST%\%%F" (
    mklink "%REPO%\%%F" "%DEST%\%%F" >>"%LOG%" 2>&1
    if errorlevel 1 (
      call :log "   [ОШИБКА] ссылка для %%F не создана — возвращаю файл на место"
      move /Y "%DEST%\%%F" "%REPO%\%%F" >>"%LOG%" 2>&1
    ) else (
      call :log "   ссылка %%F создана"
    )
  )
)

call :log "4/5 запуск сервисов"
call pm2 start all >>"%LOG%" 2>&1
timeout /t 10 /nobreak >nul

call :log "5/5 проверка"
dir "%REPO%\ohlcv_cache.db" "%REPO%\subscriptions.db" >>"%LOG%" 2>&1
dir "%DEST%" >>"%LOG%" 2>&1

:finish
call :log "=== готово, лог: %LOG% ==="
echo.
echo ============================================================
type "%LOG%"
echo ============================================================
echo Лог сохранён: %LOG%
echo.
pause
exit /b 0

:log
echo %~1
echo [%TIME%] %~1 >>"%LOG%"
exit /b 0
