@echo off
chcp 65001 >nul
REM ═══════════════════════════════════════════════════════════════════════════════════════════
REM  Перенос баз на NVMe (16.09.2026, Егор: «все сразу, на C: NVMe, создай отдельную папку»).
REM  Что делает: останавливает сервисы pm2 → переносит ohlcv_cache.db (19 ГБ) и subscriptions.db
REM  на C:\oko_data → ставит на их место символические ссылки (пути в коде не меняются) → запускает сервисы.
REM  Зачем: обе базы лежат на SATA-SSD E: вместе с репозиторием и логами; NVMe быстрее, а чтение
REM  замеров перестаёт мешать записи бота.
REM  🔴 ЗАПУСКАТЬ ОТ АДМИНИСТРАТОРА (правый клик → «Запуск от имени администратора») — только у
REM  администратора есть право создавать символические ссылки на файлы.
REM ═══════════════════════════════════════════════════════════════════════════════════════════
setlocal
set REPO=E:\MTF BOT\CURSOR\crypto_volume_bot
set DEST=C:\oko_data

net session >nul 2>&1
if errorlevel 1 (
  echo [ОШИБКА] Нужны права администратора: правый клик по файлу — «Запуск от имени администратора».
  pause & exit /b 1
)

echo.
echo === 1/5 остановка сервисов pm2 (бот, тень, терминал и прочие) ===
call pm2 stop all
timeout /t 5 /nobreak >nul
for /f "tokens=2" %%p in ('tasklist /FI "IMAGENAME eq python.exe" /FO LIST ^| findstr /i "PID"') do taskkill /PID %%p /F >nul 2>&1
timeout /t 3 /nobreak >nul

echo.
echo === 2/5 перенос баз на %DEST% ===
if not exist "%DEST%" mkdir "%DEST%"
for %%F in (ohlcv_cache.db subscriptions.db) do (
  if exist "%REPO%\%%F" (
    echo   %%F ...
    move /Y "%REPO%\%%F" "%DEST%\%%F" >nul || (echo   [ОШИБКА] не удалось перенести %%F & pause & exit /b 1)
  )
  for %%S in (-wal -shm) do if exist "%REPO%\%%F%%S" move /Y "%REPO%\%%F%%S" "%DEST%\" >nul
)

echo.
echo === 3/5 ссылки на прежних местах ===
for %%F in (ohlcv_cache.db subscriptions.db) do (
  if exist "%DEST%\%%F" (
    mklink "%REPO%\%%F" "%DEST%\%%F" || (
      echo   [ОШИБКА] ссылка не создана — возвращаю %%F на место
      move /Y "%DEST%\%%F" "%REPO%\%%F" >nul
      call pm2 start all
      pause & exit /b 1
    )
  )
)

echo.
echo === 4/5 запуск сервисов ===
call pm2 start all
timeout /t 10 /nobreak >nul

echo.
echo === 5/5 проверка ===
dir "%REPO%\ohlcv_cache.db" "%REPO%\subscriptions.db" | findstr /i "SYMLINK ohlcv subscriptions"
call pm2 list
echo.
echo Готово. Базы лежат в %DEST%, в проекте — ссылки, пути в коде не менялись.
pause
