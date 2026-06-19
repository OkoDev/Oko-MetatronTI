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
| 4 | ✅ | **РЕАЛИЗОВАНО (DEV-185.2).** emergency_close_check: overshoot >0.5% за SL → market close (enabled=true, срабатывал 15.06 05:40). + OPS-01b #1910 fix (created_at от биржевого времени). Проверено 15.06 | AUDIT #2 |
| 5 | 🟢 | **R vs $ расхождение — комиссии/funding съедают $-прибыль.** 🆕 **19.06 (Даат, данные, блокер #6 captured_R ✅ СНЯТ → разблокировано):** разложение просадки −$412/нед = бумага(Δunreal) +$21 + стратегия(tracked) +$2 + **REST −$435**. REST = комиссии tracked **−$169** (6835 сделок/нед, оборот $187K, taker 0.045%×2) + funding/untracked/ликвидации **−$266** (74% на acc2-CROSS). КОРЕНЬ = ИЗДЕРЖКИ гиперчастоты + cross, НЕ сигналы (стратегия+открытые ≈ ноль). **🔪 maker-выход = ТУПИК (проверено 19.06):** выходы VST = SL 69% ($145K) / EXPIRED 19% / **TP только 9% ($20K)** / TSL 2%. maker применим ТОЛЬКО к TP-leg → экономия **+$5** (не −$94). 69% выходов = SL → taker неизбежен. **Корень комиссий = ЧАСТОТА входов в SL (3257 SL vs 424 TP), НЕ taker-vs-maker.** Реальный рычаг = МЕНЬШЕ/ЛУЧШЕ входов: **OTE-CASCADE** (1D-трендфильтр, построен shadow 19.06) + Режим В (1772→181/день) + качество входа. slippage исключён (VST-SLIPPAGE ✅ 0.07-0.18%). funding-split via income-леджер `/user/income` (опц). arch104 ЗАКРЫТ. | DS слив + Даат 19.06 |
| 21 | 🔴 | **EXEC-SIM-SPLIT** (ТЗ юзера 15.06): SIM→research-слой, VST=истина. **Логика входа/выхода ИДЕНТИЧНА** (один калькулятор, [[principle_reuse_not_duplication]]) — различие ТОЛЬКО режим. 4 компонента: (1) ЕДИНАЯ exit-логика (свести wick/close `trade_simulator:2680` к 1 реалистичной; кирпич1 VST-exit из WS-fill = часть, готов); (2) режим-переключатель config `execution_mode: sim\|vst\|both` (сейчас НЕЛЬЗЯ выключить SIM); (3) БД sim.db↔live.db; (4) SIM=снятие лимитов (полный охват mining). Корень: APEX #29750 fake −15R. 217 VST R≤−10 искажены. [[exec_sim_split_epic]] | юзер 15.06 |

## 🟠 ДАННЫЕ / МЕТРИКИ

| # | Статус | Задача | Источник |
|---|---|---|---|
| 6 | ✅ | **ПОЧИНЕНО (c6aa6e9).** clamp [0,100] в формуле (новые) + backfill 16252 строк. avg −13.3→34.3, <0/>100→0. Корень: realized/MFE без clamp (убыток<0, раннер>clamp_MFE). Метрики достоверны → разблокирует #5/#19 | DATA-AUDIT-2 A2.1 |
| 7 | 🔄 | **ML-честность**: аудит DS ✅ — `r_predictor:66 random_state=42` (НЕ TimeSeriesSplit) = leak 85%→34%. Фикс TimeSeriesSplit + realized-R таргет + OOS gate — pending (согласовать, ML) | AUDIT, DS 15.06 |
| 8 | ✅ | **SIM убыточны (VST=edge)**: фикс `AND execution_mode='VST'` ЗАКАТАН (4b22a0c) — веса учатся только на VST-выборке (SIM-шум убран). ⚠️ Сами VST-R ещё искажены смешением логик закрытия (217 R≤−10) → точность даст EXEC-SIM-SPLIT (#21) | DS 15.06 |

## 🟢 LISTENERS / BUS (фундамент L2 готов 15.06)

| # | Статус | Задача | Источник |
|---|---|---|---|
| 9 | ✅ | **НЕ НУЖЕН** — sizing уже от `availableMargin` (REST в главном loop, не cross-loop). available точнее total_equity из шины. Закрыто разбором #2 | BUS-L2, слив |
| 10 | ✅ | **КОНТРАКТ ЗАФИКСИРОВАН (15.06).** push (subscribe_async) / pull (get/get_account/total_equity/all_positions) / produce (publish/update_*). В docstring `PairContextBus` + `BUS_SUBSCRIBER_ROADMAP`. Правило: данные живут в шине, не REST из потребителя | юзер 15.06 |
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
