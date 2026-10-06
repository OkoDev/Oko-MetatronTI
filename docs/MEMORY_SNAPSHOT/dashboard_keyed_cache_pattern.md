---
name: dashboard_keyed_cache_pattern
description: "Паттерн кэша тяжёлых dashboard-эндпоинтов: TTL+single-flight+detached refresh. Ключевой урок: client-abort убивает request-bound compute → кэш не греется → refresh ДЕТАЧИТЬ через create_task."
metadata: 
  node_type: memory
  type: reference
  originSessionId: c111b672-541f-4da0-9af4-b12fcf9281cd
---

`web/dashboard_server.py` → класс `_KeyedJSONCache` (16.06.2026). Лечит флуд ECONNRESET, когда фронт каждые 10с долбит тяжёлые SQL-эндпоинты, а пул дашборда (`_get_dash_executor`, был 4 → стал 8 воркеров) насыщается → очередь → рвутся даже лёгкие эндпоинты.

**Три свойства (зеркало `/api/live` кэша, но keyed по параметрам):**
- **HIT** (age<ttl) — готовый JSON, 0 SQL.
- **STALE** (age≥ttl) — отдаём прошлый СРАЗУ + фоновый refresh (клиента не блокируем).
- **COLD** (кэша нет) — запускаем refresh, ждём `cold_timeout`; не успел → `None` (handler отдаёт warming-пусто).

**🔴 КЛЮЧЕВОЙ УРОК (почему «вечный ECONNRESET, кэш не греется»):** если compute привязан к запросу (`await` в хендлере), то фронт-таймаут (AbortController 12с) отменяет хендлер → aiohttp отменяет корутину → compute умирает ДО записи в кэш → кэш НИКОГДА не прогревается → каждый следующий поллинг стартует заново. **Фикс: refresh — ДЕТАЧНУТЫЙ `asyncio.create_task` (single-flight: один таск на ключ).** Хендлер ждёт его через `wait_for(shield(task), cold_timeout)`, но таск живёт независимо → переживает client-abort → кэш гарантированно греется → следующий поллинг = HIT.

**Применён к:** `trades_filtered`(TTL15), `exchange_history`(TTL30), `balances`/`positions`/`accounts`(`_PORTFOLIO_CACHE` TTL20).

**Сопутствующее:** payload урезать allow-list'ом (`_TRADES_FILTERED_COLS` — без `features_json` ≈80% веса; 1MB→177KB). Менять список синхронно с фронт-маппером `lib/api.ts`.

**Когда применять:** любой новый тяжёлый dashboard-эндпоинт, который поллится. НЕ заплатка «поднять timeout» ([[dashboard_oper_from_bus_analytics_sql]] — оперативку лучше вообще из шины, кэш для аналитики).
