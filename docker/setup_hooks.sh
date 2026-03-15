#!/bin/bash
# Настройка Stop hook для агентов (Architect / Developer).
# Запускать ОДИН РАЗ внутри контейнера:
#
#   docker exec -it crypto_bot_architect bash /workspace/docker/setup_hooks.sh
#   docker exec -it crypto_bot_developer bash /workspace/docker/setup_hooks.sh

set -e

SETTINGS_DIR="$HOME/.claude"
SETTINGS_FILE="$SETTINGS_DIR/settings.json"

mkdir -p "$SETTINGS_DIR"

cat > "$SETTINGS_FILE" << 'EOF'
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /workspace/scripts/check_tasks.py"
          }
        ]
      }
    ]
  }
}
EOF

echo "✅ Hook настроен: $SETTINGS_FILE"
echo "   Теперь при завершении задачи Claude автоматически проверит TASKS.md"
echo "   и возьмёт следующую задачу из очереди."
echo ""
echo "   Переменная AGENT_ROLE=${AGENT_ROLE:-не задана} (из docker-compose.yml)"
