---
name: reference-vue-dashboard-build
description: "Команда для билда Vue v2 dashboard через Docker (Windows host, нет глобального Node)"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 7eb11094-8711-4e7a-9c69-bf18fb7e5f76
---

# Vue v2 Dashboard Rebuild — Docker node:lts

**Контекст:** на Windows host'е (yogoru-Desk) нет глобального Node.js / npm в PATH. Был только Node v6 из Brackets — не годится для Vite. Docker установлен.

## Команда (запускать из PowerShell)

```powershell
docker run --rm -v "e:\MTF BOT\CURSOR\crypto_volume_bot\web\dashboard:/app" -w /app node:lts sh -c "npm install --no-save @rollup/rollup-linux-x64-gnu && npm run build"
```

**Что делает:**
1. Mount `web/dashboard/` как `/app` внутри контейнера
2. Доустанавливает Linux native rollup binary (node_modules установлены под Windows — без этого vite падает с `Cannot find module '@rollup/rollup-linux-x64-musl'`)
3. Запускает `vite build` → dist/

**Время:** ~5 секунд build (после первого pull node:lts image)

**Output:** `dist/assets/index-XXXX.js` ~110KB / gzip 43KB

## Почему не Alpine

Пробовал `node:lts-alpine` — нужен `@rollup/rollup-linux-x64-musl`, не `-gnu`. И musl-вариант часто отсутствует. `node:lts` (Debian, glibc) проще.

## Bash (Git Bash MINGW) — не работает напрямую

`docker run` из Git Bash трансформирует `-w /app` в `C:/Program Files/Git/app` (path mangling). Использовать PowerShell или префикс `MSYS_NO_PATHCONV=1`.

## Альтернатива на будущее

Если устанем от Docker — глобальный Node LTS .msi с https://nodejs.org/ + restart Claude Code. После этого просто `cd web/dashboard && npm run build`.

## Связь

- [[dev-144-dashboard-redesign]] — Vue v2 проект
- [[d-076-cryptohopper-status-link]] — последний rebuild
