# 📋 BACKLOG CONSOLIDATED — единый реестр незакрытого

> **Источник правды** для «что осталось». Сведено 15.06.2026 (Даат) из TASKS / DISCUSSION /
> AUDIT_2026-06-09 / DATA-AUDIT-2 / BUS_SUBSCRIBER_ROADMAP / ENCYCLOPEDIA-сфер.
> Против бардака: один файл, приоритеты, статус. Обновлять по ходу работы.
>
> **Статусы:** 🔴 критично · 🟠 важно · 🟢 в плане · 🔵 гигиена/долг · 🌌 вектор ·
> ✅ done · 🔄 в работе · ⏸ ждёт

---

## 🔴 КРИТИЧНО — ДЕНЬГИ / РИСК

| # | Статус | Задача | Источник |
|---|---|---|---|
| 1 | 🔄 | **Позиции со SL в БД, но БЕЗ биржевого SL-ордера** — ликвидация-риск. **ДИАГНОЗ 15.06:** `audit_missing_stops.py` → СЕЙЧАС 1 (INIT-USDT, было 211 на пике/суммарно). Корень: нет авто-reconcile SL (поле exchange_sl_order_id ≠ живой ордер). **NEXT:** (а) выставить SL для INIT, (б) SL-reconcile loop (периодич. audit→авто-place), (в) проверить acc2 multiacct | DATA-AUDIT-2 A2.4 |
| 2 | ✅ | **РАЗОБРАНО 15.06.** Sizing УЖЕ от `availableMargin` (bingx get_balance) ✅. Корень был — `l3_checker.enabled: false` (shadow) → 134 поз/риск 150%. ФИКС: enabled=true, max 50/25/25 (юзер). Старые доживут, новые блок >50 | DS слив, аудит |
| 3 | ✅ | **`pivot_reversal` ОТКЛЮЧЁН** — `pivot_reversal_enabled: false` (monitoring.py:468), 0 сделок/3 дня. Проверено 15.06 (сделано ранее) | SIGNAL-AUDIT |
| 4 | 🔴 | **Sanity-guard форс-клоуз** если цена >X% за SL (защита от инцидента #1910 −9.74R), время биржевое | AUDIT #2 |
| 5 | 🟠 | **Комиссии 104% прибыли** (arch104 8 сд/$1) + аллокация (60% капитала / 10% прибыли) → деаллокация в ote | DS слив |

## 🟠 ДАННЫЕ / МЕТРИКИ

| # | Статус | Задача | Источник |
|---|---|---|---|
| 6 | 🔴 | **`captured_R_pct` формула сломана** (avg −14.3%, физически невозможно) — ломает ML/аналитику. max_price/min_price OK (97%) | DATA-AUDIT-2 A2.1 |
| 7 | 🟠 | **ML-честность**: TimeSeriesSplit, selection bias в RPredictor (realized R не MFE), OOS gate | AUDIT, DATA-AUDIT-2 A2.3 |
| 8 | 🟢 | **SIM убыточны (VST=весь edge)** — переосмыслить sim-генерацию / вес в обучении | DATA-AUDIT-2 A2.2 |

## 🟢 LISTENERS / BUS (фундамент L2 готов 15.06)

| # | Статус | Задача | Источник |
|---|---|---|---|
| 9 | ✅ | **НЕ НУЖЕН** — sizing уже от `availableMargin` (REST в главном loop, не cross-loop). available точнее total_equity из шины. Закрыто разбором #2 | BUS-L2, слив |
| 10 | 🟢 | **Канонизировать push/pull контракт** «как слушать Куб» (стандарт для новых слушателей) | юзер 15.06 |
| 11 | 🟢 | **Risk Monitor** (drawdown realtime) + **Circuit Breaker** на L2 → затем **SubscriberHub** | BUS-L3 роадмап |
| 12 | 🔵 | **NOTIF-TIER2** (CHoCH/OTE/OB/Pivot) + Dashboard real-time лента (SMC_SNAP push) | роадмап Слой 2 |

## 🔵 ГИГИЕНА / ДОЛГ (источник «бардака»)

| # | Статус | Задача | Источник |
|---|---|---|---|
| 13 | 🔵 | **DOC-SYNC**: ENCYCLOPEDIA-статусы сфер устарели (Сфера 3/4 «❌», хотя WT/SMC service готовы) — синхронизировать карту Куба | аудит сфер |
| 14 | 🔵 | **orphan-cleanup при старте** — Windows зомби market_ws workers (daemon mp не умирает) | сессия 15.06 |
| 15 | 🔵 | **DS-325 Ф3** — миграция callsites на pydantic + удалить дубль `config_validator` | DS-325 |
| 16 | 🟠 | **SEC**: токен-auth + CSRF на POST дашборда (bind localhost ✅) | AUDIT #1 |
| 17 | 🔵 | **Мёртвый код** (infrastructure/presentation/bot/main.py), разнести dashboard_server | AUDIT LONG |

## 🌌 ВЕКТОРЫ / НЕРЕАЛИЗОВАННЫЕ СФЕРЫ

| # | Статус | Задача | Источник |
|---|---|---|---|
| 18 | 🌌 | **Сферы**: 9 Narrative (Decision Core), 10 Exit Manager (вынести из монолита trade_simulator), 12 Self-Diagnostics, 5 Cross-Market (только BTC 4h) | ENCYCLOPEDIA |
| 19 | 🌌 | **BUS-L3 TraderState** — DATA-AUDIT-2 ГОТОВ → Capital Allocator разблокирован. Порядок: Correlation Shield → Regime Router → Capital Allocator → Strategy Evolution → Market Memory | BUS роадмап |
| 20 | 🌌 | **STRATEGY-DISSECTION** (OTE/ARCH104/ATR), **PERF-LOOP-DRIFT B** (торговый loop), **EXEC-SIM-SPLIT**, **DASHBOARD-эпик**, **ARCH-DB-V2 Ф4** | TASKS |

---

## ✅ Закрыто в сессии 14-15.06.2026 (для контекста)

- TSL gear1_be_atr=1.5, Config validator, Repair API, NOTIF-MVP, ARCH-130
- LISTENER-CANON (NotificationDispatcher → подписчик шины), LISTENER-DASH (SSE event-driven)
- DS-325 Ф1+Ф2 (pydantic-схема), BUS-ACCOUNT-EPIC спроектирован
- PERF-расследование: dashboard в поток (латентность ~30×), market_ws (5m hit 18→91%, REST 2792→~620, +3m)
- Анти-бан сага (persist guard + rps=40 + stagger WS → холодный старт 0 банов)
- SIM-TIME-EXIT (анти-орфан 48ч), 27 старых орфанов убито
- BUS-L2-BRICK: баланс + позиции через шину (trading/status + /api/live слушают шину, конец мигания)
- DATA-AUDIT-2 (DS, 4 аудита готовы)
