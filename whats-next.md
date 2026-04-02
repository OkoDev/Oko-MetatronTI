# What's Next — Handoff Document

> Сессия 30.03.2026. Агент: ARCH.

---

## Что сделано в этой сессии

### DEV-118 ✅ — Фикс дублирования analyze_symbol
**Файл:** `bot/loops/scan_loop.py`
- Добавлен `_SIGNAL_PRIORITY = {confluence:100, wt_b:90, wt_signal:80, liquidity_sweep:70, anomaly:50}`
- `for`-цикл по сигналам заменён на `max()` — один лучший signal_type на пару за цикл
- `pre_signals` (все сигналы) передаётся полным — контекст анализа не теряется

### DEV-119 ✅ — TRIPLE убран, DUAL_TP на пивотах
**Файлы:** `pivot_calculator_fixed.py`, `trade_simulator.py`, `regime_strategy.py`, `config.yaml`, `dashboard_server.py`
- `get_next_tp_by_hierarchy(tp1_price, ...)` — новая функция, второй пивот по иерархии
- TRIPLE_TP_TSL удалён полностью из всех файлов
- TP1 = первый пивот (`take_profit`), TP2 рассчитывается async и пишется в `tp2_price`
- Баг exit исправлен: после TP2 hit теперь `exit_status = STATUS_TP`
- RANGE: `max_strategy_type = "SINGLE"` (было DUAL_TP)
- `config.yaml`: `trading.dual_tp: {enabled: true, tp1_fix_pct: 70}`
- Dashboard: toggle «DUAL TP» + слайдер «TP1 fix %»

### DEV-120 ✅ — DUAL_TSL для TREND (данные 119 сделок)
**Файлы:** `regime_strategy.py`, `trade_simulator.py`, `config.yaml`
- `_STRATEGY_ORDER = ["SINGLE", "DUAL_TP", "DUAL_TSL"]`
- TREND_UP/DOWN: `min_strategy_type = "DUAL_TSL"` — 70% на TP1, 30% под TSL
- `close_trade()`: взвешенный R = `0.70 × R_tp1 + 0.30 × R_exit` (читает `tp1_fix_pct` из конфига)
- `config.yaml`: `trend_strategy_type: DUAL_TSL`
- Данные: TREND_UP TSL avg=4.6R vs TP avg=2.1R → +0.6R/сделку на 30% остатке

### ARCH-63 ✅ + ARCH-66 ✅ — Спеки готовы в DISCUSSION.md
- BTC 4h market gate shadow mode → DEV-111 реализует
- RANGE BOUNCE SL/TP calculator → DEV-110 реализует

---

## Незакоммиченные изменения

```
M bot/loops/scan_loop.py               (DEV-118: best signal priority)
M core/pivots/pivot_calculator_fixed.py (DEV-119: get_next_tp_by_hierarchy)
M core/trading/trade_simulator.py       (DEV-119/120: DUAL_TSL, async TP2, фикс exit, взвешенный R)
M core/trading/regime_strategy.py       (DEV-119/120: DUAL_TSL, _STRATEGY_ORDER)
M config.yaml                           (DEV-119/120: dual_tp блок, DUAL_TSL)
M web/dashboard_server.py               (DEV-119: dual_tp toggle + param)
M DISCUSSION.md                         (спеки + решения)
M TASKS.md                              (DEV-118/119/120 ✅)
M PROJECT-LOG.md                        (записи добавлены)
M memory/current_state.md               (обновлено)
```

**⚠️ Нужен рестарт бота** — все изменения вступят в силу после перезапуска.

---

## Следующие задачи по приоритету

| Приоритет | Задача | Описание |
|---|---|---|
| 🔥 | DEV-103 | Exchange Health Loop + TG алерт — **блокирует VST** |
| 🔥 | DEV-113/114 | Dashboard VST P1: auto-refresh + Risk Exposure карточка |
| 🟡 | DEV-111 | BTC 4h market gate shadow mode (спек ARCH-63) |
| 🟡 | DEV-110 | RANGE BOUNCE SL/TP calculator (спек ARCH-66) |
| 🟡 | DEV-102 | chart_builder: blacklist малоликвидных пар |
| 🔵 | DEV-104 | Dead-Man Timer (только перед LIVE) |

---

## Открытые вопросы

- **→ TRADER**: проверить новые сделки через 24-48ч — TP2 появляется как следующий пивот, TSL 30% захватывает продолжение тренда?
- **→ DEV**: 74 SL SHORT 30.03 с avg_max_R=+2.27R — диагностировать почему TSL не активировался (файл: `trader_analyses/2026-03-30.md`)

---

## Критический контекст

### DUAL_TSL — как работает
```
TREND_UP/DOWN → strategy_type = DUAL_TSL
  tp1_price = take_profit (первый пивот по иерархии)
  tp1_hit_at записывается при касании TP1 (сделка остаётся OPEN)
  TSL продолжает трекать 30% остатка
  close_trade(): R = 0.70×R_tp1 + 0.30×R_exit
```

### RANGE → всегда SINGLE
```
RANGE → max_strategy_type = "SINGLE"
  Вся позиция фиксируется на первом пивоте
  avg_R RANGE+DUAL = -0.942 (подтверждено данными)
```

### Иерархия пивотов для TP (DEV-75)
```
1. 1D пивот (avg_R +1.536 — самый эффективный)
2. 1W пивот
3. Конфлюенция 1W+1D
4. Конфлюенция 1M+1W
5. 1M пивот
6. Fib extension (fallback)
```

### Python
`python3` (не `python`) — команда в этом окружении.
