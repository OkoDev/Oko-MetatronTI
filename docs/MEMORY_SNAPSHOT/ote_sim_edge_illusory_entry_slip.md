---
name: ote_sim_edge_illusory_entry_slip
description: "SIM-эдж ote_nested +0.34% частично иллюзорен — 91% VST-входов adverse +0.81%; SIM считает идеальный fib-вход, живьё фила там нет. Корень дрифта = вход, эпик CUTOVER"
metadata: 
  node_type: memory
  type: project
  originSessionId: 53ad2006-69eb-4389-9eb0-02df4e0d45ab
  modified: 2026-07-22T19:05:51.217Z
---

# Дрифт ote_nested SIM→VST локализован: ВХОД, эдж частично иллюзорен (22.07)

Копали «почему качественное ядро (+0.24-0.34% SIM) льёт на VST». Корень — **вход**.

## Данные
| ote_nested | n | net | SL% | WIN% |
|---|---|---|---|---|
| SIM | 4156 | +0.336% | 39 | 61 |
| VST | 4773 | +0.013% | **53** | **47** |

**Входной слиппедж VST (n=1703 с фактом филла): 91% ХУЖЕ сигнала, средн +0.81%; лишь 9% чистых.**
Однородно adverse (НЕ бимодально) → это НЕ «чистые лимиты + market-догон».
oko_ote ещё хуже: слиппедж +2.52%. Чистые входы = плюс: radar_spring −0.01% слиппедж → net +0.24%.
65% VST ote имеют actual_entry_price=NULL (FAKE-R баг) → реальный дрифт ещё хуже, прячется.

## Вывод (жёсткий, честный)
Для честного LIMIT на сигнальной fib-цене 91% adverse НЕВОЗМОЖНО (limit-buy filled ≤ price).
Значит **SIM-эдж +0.34% частично ИЛЛЮЗОРЕН**: SIM входит по идеальной fib (0.618/0.705), живьё
фила там нет — фактический на 0.81% хуже = весь эдж + сверху. ote_nested УЖЕ config LIMIT
(entry_order_type, trade_router.py:269 → bingx_client &price=entry_price), но филы всё равно adverse.

## Модель реального входа (шаг 2, scripts/sim_realistic_net.py) — НИКТО не выживает
Вычли измеренный медианный per-source слиппедж из SIM net (era≥11.07): ote_nested +0.317→
**−0.222%** (слип 0.54%), liquidity_sweep +0.037→+0.010 (грань), остальное глубоко в минусе.
**ВЫВОД ДОКАЗАН ЧИСЛОМ: эдж НЕ в отборе сигнала, а в КАЧЕСТВЕ ИСПОЛНЕНИЯ.** При идеальном
входе ote +0.32%, при догоне −0.22% — разница 0.54% восстановима ТОЛЬКО чистым limit-входом.

Три возможных корня (каждый = точечное копание в execution):
1. Ордер де-факто НЕ лимит на fib, а market/текущая.
2. Adverse selection резонного лимита (filled только на пробое против, отскок пропущен).
3. Порча actual_entry_price через WS-реконсиляцию (exec_ws_integration REST≠WS-fill).

**Why:** объясняет месяцы «нет результатов» — не стратегии/детекторы, а КАЧЕСТВО ИСПОЛНЕНИЯ входа
съедает доказанный сигнал. Плюс SIM systematically завышает (идеальный вход). **How to apply:**
(1) не верить SIM-эджу mean-reversion без модели реалистичного филла; (2) это эпик
[[cutover_blocker_ws_closefill]] / [[exec_sim_split_epic]] — ПАУЗА юзера, переоткрывать осознанно;
(3) чинить actual_entry_price NULL ([[bug_phantom_exit_resolve]]) — без факта филла дрифт невидим.
Связано: [[ote_nested_live_vst_bleeding]], [[ote_production_drift_root]], [[detectors_two_poison_atr_wt]]
(отбор входа), [[principle_measure_pct_not_r_LAW]].
