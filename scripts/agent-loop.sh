#!/bin/bash
# Автономный цикл для Claude агента в Docker
# Запуск: ./scripts/agent-loop.sh ARCHITECT  или  ./scripts/agent-loop.sh DEVELOPER
#
# Требует: claude CLI в PATH, /workspace смонтирован как корень проекта

ROLE=${1:-ARCHITECT}
TASKS_FILE="/workspace/TASKS.md"
SCRIPT_DIR="/workspace/scripts"
INTERVAL=15  # секунд между проверками

export AGENT_ROLE="$ROLE"

echo "🤖 Agent loop started: $ROLE"
echo "Tasks: $TASKS_FILE"
echo "---"

while true; do
    # Спросить check_tasks.py — есть ли задача
    RESULT=$(python3 "$SCRIPT_DIR/check_tasks.py" 2>/dev/null)
    DECISION=$(echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('decision','approve'))" 2>/dev/null)

    if [ "$DECISION" = "block" ]; then
        REASON=$(echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('reason',''))" 2>/dev/null)
        TIMESTAMP=$(date '+%H:%M:%S')
        echo "[$TIMESTAMP] Задача найдена → запускаем Claude..."
        echo "  $REASON"
        echo ""

        # Запустить claude с задачей
        if [ "$ROLE" = "TRADER" ]; then
            COMPLETION="После завершения обнови статус задачи на ✅ в секции '🎯 Задачи TRADER' в TASKS.md и опубликуй результат как пост в Discussion."
        else
            COMPLETION="После завершения задачи обнови TASKS.md (перемести в ✅ ГОТОВО) и memory/current_state.md."
        fi

        cd /workspace && claude -p "$REASON. $COMPLETION" \
            --allowedTools "Read,Write,Edit,Bash,Glob,Grep" 2>&1

        echo ""
        echo "[$TIMESTAMP] Claude завершил. Пауза ${INTERVAL}s..."
    else
        echo "[$(date '+%H:%M:%S')] Нет задач в очереди. Сплю ${INTERVAL}s..."
    fi

    sleep "$INTERVAL"
done
