#!/bin/bash
# Автономный цикл для Claude агентов
# Запуск: ./scripts/agent-loop.sh ARCHITECT  или  ./scripts/agent-loop.sh DEVELOPER

ROLE=${1:-DEVELOPER}
TASKS_FILE="/workspace/TASKS.md"
INTERVAL=30  # секунд между проверками

echo "🤖 Agent loop started: $ROLE (polling every ${INTERVAL}s)"
echo "Watching: $TASKS_FILE"
echo "---"

LAST_HASH=""

while true; do
    CURRENT_HASH=$(md5sum "$TASKS_FILE" 2>/dev/null | cut -d' ' -f1)

    if [ "$CURRENT_HASH" != "$LAST_HASH" ]; then
        LAST_HASH="$CURRENT_HASH"

        # Ищем PENDING задачи для нашей роли
        PENDING=$(grep -A1 "\*\*Агент:\*\* $ROLE" "$TASKS_FILE" | grep -v "Агент" | head -1)

        TIMESTAMP=$(date '+%H:%M:%S')
        echo "[$TIMESTAMP] TASKS.md изменился"

        # Проверяем есть ли задачи в DONE раздел (для Architect — ревью)
        if [ "$ROLE" = "ARCHITECT" ]; then
            NEW_DONE=$(grep "✅ DONE\|→ DONE" "$TASKS_FILE" | wc -l)
            echo "  Завершённых задач: $NEW_DONE"
        fi

        echo "  → Проверь TASKS.md и возьми следующую задачу!"
        echo ""
    fi

    sleep "$INTERVAL"
done
