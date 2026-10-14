#!/usr/bin/env bash
# deploy_web.sh — синк docs/product/deploy/public/ → metatronti-web (remote "web")
# Использование: bash scripts/deploy_web.sh
# Первый раз: git subtree push (долго, перебирает историю)
# Потом: git subtree push (быстро, только дельта)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PREFIX="docs/product/deploy/public"
REMOTE="web"
BRANCH="main"

cd "$REPO_ROOT"

# Проверить что remote настроен
if ! git remote get-url "$REMOTE" >/dev/null 2>&1; then
  echo "❌ Remote '$REMOTE' не найден. Добавь: git remote add web https://github.com/OkoDev/metatronti-web.git"
  exit 1
fi

# Проверить что нет незакоммиченных изменений в public/
if ! git diff --quiet -- "$PREFIX"; then
  echo "❌ Есть незакоммиченные изменения в $PREFIX — сначала закоммить."
  exit 1
fi

echo "🚀 Деплой $PREFIX → $REMOTE/$BRANCH"
# Pre-push хук гоняет тесты бота — к статике не относится, пропускаем
OKO_SKIP_GATE=1 git subtree push --prefix="$PREFIX" "$REMOTE" "$BRANCH"
echo "✅ Готово. Cloudflare Pages подхватит автоматически."
