# What's Next — Handoff Document

> Последнее обновление: **2026-06-14** (Агент: Даат/Opus 4.8).

---

## 🎯 СЕССИЯ 14.06 — МАРАФОН: min_rr + arch104 + EXEC-WS + MARKET-WS (v1 откат / v2 дизайн)

### ✅ Закоммичено (ядро чисто)
- min_rr ote=3.0 (39d31bc, подтв.), CONFIG-SLTP merge (743cc64)
- arch104: 67 LONG off (93097a5) — SHORT=ядро (+1743R/7d), LONG=балласт
- EXEC-WS оживлён (d649f01): фикс VST WS-домена `vst-open-api-ws` → order events в проде
- MARKET-WS v1 откат (c88fd94): GIL душил scan → market_ws OFF

### ⚠️ СОСТОЯНИЕ БОТА
- ЖИВ, scan baseline **351с**, **market_ws OFF**, **EXEC-WS ON** (order events идут)
- Незакоммичено (doc): TASKS/DISCUSSION/DETAILS. `arch104_observer/ote_observer.py` M = НЕ мои (DS/чужие)

### 🔄 ПЕРВЫМ ДЕЛОМ (следующая сессия)
1. **MARKET-WS v2 = ПРОЦЕСС** (главный рычаг loop, дизайн роя готов): `multiprocessing.Queue` (НЕ Redis) + producer-процесс spawn + агрегация + QueueReaderThread + супервайзер. Код market_ws.py переиспользуем (за флагом off). 1-2 дня, multiprocessing деликатно. → memory `market_ws_kline_proven`
2. **EXEC-WS 2b** (sync_close: ACCOUNT_UPDATE pa=0 → close БД) — лечит orphan/zombie/drift. 2a (write_exch_id) можно SHADOW-наблюдать
3. Loop-рычаги мелкие: scan_semaphore 5→8, SIM-DEPRIO
4. Backlog: DS-325 CONFIG-TYPED (рой план), EXEC-SIM-SPLIT (вектор, не сейчас)

### 🔴 УРОК ДНЯ
Время/эра подвело 4× (data-era split по моменту активации фикса; SQLite `created_at` ISO `T` vs `datetime('now')` пробел ломает фильтр в пределах дня). → `feedback_verify_fix_dataera_first`, `feedback_sqlite_time_compare`. Всегда сверять MIN/MAX диапазона фактом.

---

## 🎯 СЕССИЯ 13.06 — Dashboard Account-фильтр (KPI / Trades / Analytics)

### ✅ Что сделано

**Backend (`crypto_volume_bot`, закоммичено):**
- `feat(ARCH-DB-V2 Ф2)`: `/api/kpi?account_id=N` — лёгкий KPI endpoint
- `feat(ARCH-DB-V2 Ф2)`: `/api/stats/analytics?account_id=N` — расширен (добавлен by_signal_type + by_regime с фильтром)
- `engine.by_signal_type/by_regime/pnl_calendar(account_id=None)` — параметризованы

**Frontend (`oko-dashboard`, на диске, без git):**
- `fetchKpiCards(template, accountId?)` → `/api/kpi`
- `fetchTradesFiltered(accountId?, mode?, status?)` → `/api/trades_filtered`
- `fetchSignalStats/fetchRegimeStats/fetchPnlCalendar(accountId?)` → `/api/stats/analytics`
- **overview.tsx**: KPI cards следуют глобальному account
- **trades.tsx**: AccountSwitch (глобальный) + mode filter SIM/VST/LIVE + server-side фильтрация
- **analytics.tsx**: AccountSwitch + live KPI row (было мок) + все charts фильтруются по account

### ⚠️ ПЕРВЫМ ДЕЛОМ: ПЕРЕЗАПУСТИТЬ БОТ
Новые endpoints (api/kpi, api/stats/analytics расширен) активируются только после рестарта aiohttp.

### 🔑 Архитектурный паттерн (установлен)
```
AccountContext(global topbar) + useEffectiveAccount(local widget override)
AccountSwitch в виджете: withGlobal=true → кнопка "⟳" = follow topbar
Смена account → useEffect → refresh() каждого useLive
```

### 🔄 NEXT

**Dashboard (ещё не подключено):**
- Signals-экран — account filter (fetchSignalWeights не per-account, но history/patterns — да)
- MFE scatter — сейчас мок, можно подключить `engine.mfe_scatter(account_id?)`

**Стратегический спринт STRATEGY-DISSECTION (параллельно DS):**
- DISSECT-OTE: code-разбор (Claude) + data (DS, уже есть docs/DISSECT_ote_nested_DATA.md)
- DISSECT-ARCH104: TP-тюнинг
- DISSECT-ATR: atr_change×OTE конверсия

**ARCH-128 ветка (висит):**
- `swing_bridge.py` + `pair_context.py` + `smc_snapshot.py` — незакоммичены, закоммитить

**Бот работает:**
- VST observer — 202 пары (proxy_pool.enabled=true, 3 Singapore proxies)
- ote_nested торгует (веер 18 пар, RR3.2)

---

## Ссылки
- `memory/current_state.md` — детали сессии 13.06
- `docs/DISSECT_DS_TASK.md` — задание DS по стратегиям
- ARCH-DB-V2: `docs/DB_REDESIGN_SYNTHESIS.md`
