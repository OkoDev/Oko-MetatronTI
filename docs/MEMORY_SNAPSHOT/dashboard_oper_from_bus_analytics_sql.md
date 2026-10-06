---
name: dashboard_oper_from_bus_analytics_sql
description: "Направление 16.06 (юзер) — дашборд оперативки ЧИТАЕТ ШИНУ (быстро, live), тяжёлый SQL только для аналитики. Не лепить заплатки на медленные SQL-эндпоинты."
metadata: 
  node_type: memory
  type: project
  originSessionId: 0218674a-a04f-4556-9b18-087dfa1838c8
---

16.06.2026, юзер остановил заплатки (я лез оптимизировать тяжёлый SQL) и задал направление.

**Архитектурная ИНВЕРСИЯ (корень мигания дашборда):** оперативный дашборд (oko-dashboard :3000) — открытые сделки/позиции/live-KPI — ходит в ТЯЖЁЛЫЙ SQL (`/api/trades_filtered`, `/api/kpi`: агрегаты по 29K сделок, ЕЩЁ И завязано на sim) → таймаут → фронт падает в **MOCK** → «скачет». Самое частое повесили на самое медленное.

**НАПРАВЛЕНИЕ (вектор, не патч):** разделить данные дашборда по природе:
- **Оперативка** (открытые/свежие сделки, позиции, live-KPI, риск, цена/плечо) → **ШИНА** (push/pull, мгновенно). Доказано: `/api/live` из шины = 51 поз ×3 без проблем, тогда как SQL-эндпоинты таймаутят.
- **Аналитика** (история 30д, WR/Sharpe, паттерны, equity-кривая) → SQL (async + кэш, подождать НОРМАЛЬНО).

**Принцип:** дашборд мониторинга = СЛУШАТЕЛЬ ШИНЫ (LISTENER-CANON Слой 2, [[exec_ws_vst_userdata_proven]] / BUS-L2), а не SQL-клиент. НЕ дёргать SQL по всей базе на старте, тем более с sim-завязкой ([[exec_sim_split_epic]] — sim не должен мешать).

**Даёт:** дашборд не виснет/не мигает/не MOCK; не завязан на размер БД и sim; один быстрый источник (шина) для оперативки.

**Что НЕ делать:** заплатки на медленные SQL (увеличить timeout, оптимизировать запрос «чтобы успел») — это лечение симптома. Сначала перевести оперативку на шину.

**Связь:** [[principle_reuse_not_duplication]] (один источник), vision «всё из шины», LISTENER-DASH. Два фронта (старый aiohttp :8000 ∥ Next.js oko-dashboard :3000) = ОДИН бэкенд :8000, разные эндпоинты — унифицировать на шину для оперативки.

**Статус (обновл. 16.06 вечер):** ✅ РЕАЛИЗОВАНО + ПРОВЕРЕНО ВЖИВУЮ. 5 кирпичей:
- `/api/open` ИЗ ШИНЫ (trade_tracker публикует снапшот открытых в `PairContextBus.set_open_trades`, /api/open читает `open_trades_snapshot`). 20с→мгновенно, `source=bus`.
- `_KeyedJSONCache` (TTL+single-flight+stale-while-revalidate+detached) на `trades_filtered`/`exchange_history`/`balances`/`positions`/`accounts` → флуд ECONNRESET снят. [[dashboard_keyed_cache_pattern]]
- payload trades_filtered −83% (allow-list 22 поля, без features_json). Пул дашборда 4→8 воркеров.
- SyncPanel→шина (фикс equity/risk=0: live.balance стал скаляром→беру live.kpi). Вёрстка Overview: скролл-контейнеры под 56 живых позиций.
**Детали:** `memory/current_state.md` (repo/git) + `whats-next.md`. **✅ ИСПРАВЛЕНО 22.06: фронт oko-dashboard В ГИТЕ** — repo `github.com/OkoDev/Oko-Dashboard` (`e:/MTF BOT/CURSOR/oko-dashboard`, :3000). Прежнее «НЕ git» устарело. На 22.06 там незакоммичено: `income-truth.tsx` (новый IncomeTruthPanel /api/income) + правки overview/trades/lib/api.ts/page.tsx.
**Остаток (опц):** balances/positions из bus `_accounts` напрямую (нужны margin/available в шине); publish открытых и в register_trade_async (мгновенно); кэш /api/kpi.
