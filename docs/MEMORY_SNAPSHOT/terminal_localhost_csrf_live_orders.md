---
name: terminal_localhost_csrf_live_orders
description: "🔴 Терминал :8010 защищает торговлю только проверкой req.remote==localhost — это не защита от CSRF: любая открытая в браузере страница может POST'нуть /api/trade mode=live с плечом до 125. Дашборд :8000 — мутирующие POST без авторизации"
metadata:
  node_type: memory
  type: project
  originSessionId: ea98197f-5cfa-4b48-ab76-1b2fcebf5d0d
  modified: 2026-09-27T12:24:32.328Z
---

Аудит 26.09.2026, проверено по коду (НЕ эксплуатировалось):
- `web/structure_terminal.py:1399` `_is_local` = `req.remote in (127.0.0.1, ::1)`; сервер на `0.0.0.0` (:4269).
- `api_trade` (:1594) читает тело через `req.json()` (aiohttp не проверяет Content-Type) → «простой» POST
  `text/plain` из браузера проходит без preflight; `mode=live`, `lev` до 125. Так же `/api/protect`, `/api/close`.
  Нет проверки Origin/Host, нет токена → CSRF и DNS-rebinding. LIVE-ключи `BINGX_API_KEY/SECRET` в `.env` заданы.
- Дашборд :8000 (`web/dashboard_server.py:3441-3503`) слушает 127.0.0.1, но `/api/settings`, `/api/toggles`,
  `/api/trades/{id}/close`, `/api/cube/event`, `/api/repair/expire_bulk` — без авторизации (тот же класс CSRF).

**✅ ЗАКРЫТО 27.09 (`17353c2`):** `web/local_guard.py` — для изменяющих запросов Host локальный + Origin локальный
или отсутствует. Терминал — внутри `_is_local`; дашборд :8000 и oko-api :8001 — middleware. 🔴 Обход был через прокси:
oko-api пересылал на :8000 только Content-Type (Origin терялся), Next :3000 проксирует на :8001 — поэтому защита на ВХОДЕ.
Живая проверка: чужой Origin/Host → 403 на всех четырёх портах. LIVE-флаг терминала НЕ введён (меняет работу Егора).
Новый сервер с изменяющими POST → подключить `local_origin_guard`.

**Why:** «только localhost» защищает от соседей по сети, но не от браузера самого Егора.
**How to apply:** правка (с подтверждения): проверка `Origin`/`Host` ∈ {localhost:PORT} + токен из `.env` в
заголовке для всех POST; LIVE-режим терминала — отдельный флаг окружения, выключен по умолчанию.
Связано: [[safety_vst_live_isolation_proven]].
