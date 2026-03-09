#!/bin/bash

echo "🚀 Starting Crypto Bot with Dual Claude Agents..."
echo ""

# Запуск контейнеров
docker compose up -d

sleep 2

echo "✅ Containers started:"
docker ps --filter "name=crypto_bot" --format "table {{.Names}}\t{{.Status}}"
echo ""

echo "🔐 NEXT STEPS:"
echo ""
echo "1️⃣ AGENT 1 (Architect):"
echo "   docker exec -it crypto_bot_architect bash"
echo "   claude login"
echo ""
echo "2️⃣ AGENT 2 (Developer):"
echo "   docker exec -it crypto_bot_developer bash"
echo "   claude login"
echo ""
echo "✨ После логина можно использовать:"
echo "   claude analyze <file>"
echo "   claude implement <task>"
echo "   claude write tests for <module>"
