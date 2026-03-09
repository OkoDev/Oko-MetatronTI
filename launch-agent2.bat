@echo off
echo ============================================
echo  Agent 2: yogoru@gmail.com
echo  Oko MTF Bot - Developer Agent
echo ============================================
echo.

set USERPROFILE=C:\ClaudeAgents\agent2
set HOME=C:\ClaudeAgents\agent2
set APPDATA=C:\ClaudeAgents\agent2\AppData\Roaming
set LOCALAPPDATA=C:\ClaudeAgents\agent2\AppData\Local

if not exist "C:\ClaudeAgents\agent2" (
    echo Создаю папку для Agent 2...
    mkdir C:\ClaudeAgents\agent2
    mkdir C:\ClaudeAgents\agent2\AppData\Roaming
    mkdir C:\ClaudeAgents\agent2\AppData\Local
)

cd /d "e:\MTF BOT\CURSOR\crypto_volume_bot"

if not exist "C:\ClaudeAgents\agent2\.claude.json" (
    echo.
    echo Первый запуск! Нужна авторизация:
    echo Войди как: yogoru@gmail.com
    echo.
    claude login
)

echo.
echo Запуск Claude Code...
claude --dangerously-skip-permissions
