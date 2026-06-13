# What's Next — Handoff Document

> Последнее обновление: **2026-06-13** (Агент: Даат/Sonnet 4.6).

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
