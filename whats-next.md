# What's Next — Handoff Document

> Сессия 18.04.2026. Агент: ARCH.

---

## Что сделано за спринт 14-18.04

### DEV-175 ✅ — slippage fix (16.04)
`config.yaml`: `min_volume_usd: 5000000` (было 0, отсекаем 1-5M бакет WR=18%).
`bingx_client.py`: `place_stop_order()` поддерживает `limit_price` → STOP-LIMIT.
`order_manager.py`: `place_sl_order()` читает `sl_limit_buffer_pct` из config.
`position_sync.py`: sanity check R < -2 при SL → WARNING лог.

### ARCH-78 ✅ — BTCRegimeProvider production (16-17.04)
`core/exchange/btc_regime_provider.py` создан (ATR Supertrend 4h, TTL 5 мин).
`bot/core/bot.py` — singleton + wire в TI.
`monitoring.py` 5.3 — gate production: SHORT при BTC BULL блокируется str<75 (если не pivot_reversal).
`btc_4h_regime` пишется в каждую сделку `features_json`.

### DEV-174 ✅ — TSL системный аудит + 3 бага (16.04)
1. WS pre-filter глушил TSL-трекинг → `_tsl_active_pre` теперь учитывается
2. `current_r` от TSL'нутого SL → теперь от `original_sl`
3. Нет direction guard на fallback TF → fallback только при совпадающем тренде

### DEV-173 ✅ — Orphan epidemic fix (15.04)
`bingx_client.py`: dynamic contract precision (`quantize_qty`/`quantize_price`).
`tsl_updater.py`: биржа как источник истины (live `get_sl_order_id`), stale DB ID → чистим.
`order_manager.py`: `quantize_qty()` в `place_sl_order`.

### DEV-121 ✅ — Self-diagnostics L13/L14/L15 (16.04)
`core/selftest_cube.py`: 13 сфер + 10 рёбер + 4 feedback loop.
Интегрирован в `run_all()` → автономный запуск `python core/selftest_cube.py`.

### docs/CUBE_ARCHITECTURE.md ✅ — Полная схема Куба (18.04)
8 Mermaid-диаграмм: граф всех сфер и рёбер, Intelligence Layer, Lifecycle, Детекторы, SMC, ML, Фазы.

---

## Незакоммиченные изменения

```
Все изменения 14-17.04 применены и бот перезапущен.
docs/CUBE_ARCHITECTURE.md — НОВЫЙ файл (18.04)
.claude/CLAUDE.md — добавлены триггеры обновления MD файлов (18.04)
START.md — обновлён до 18.04
whats-next.md — этот файл
```

---

## Следующие задачи по приоритету

| Приоритет | ID | Описание | Дедлайн |
|---|---|---|---|
| 🟡 | **DEV-172** | Entry Matrix priority=None — найти и починить баг (не пишет данные) | ASAP |
| 🟡 | **ARCH-55-VAL** | RANGE BOUNCE валидация shadow | 23.04 |
| 🟢 | **ARCH-45** | OutcomePredictor ревью (AUC=0.41) | 20.04 |
| 🟡 | **DEV-89** | OTE C1 shadow 20 пар / 90 дней | ~26.04 |
| 🟡 | **ARCH-77** | Миникуб WTMTF: 3 ребра | — |
| 🔵 | **DEV-163** | CircuitBreaker не срабатывает при WR=0% | — |
| 🔵 | **DEV-164** | VST path пропускает min_sl_dist guard | — |

---

## Критический контекст

### BTCRegimeProvider — production с 17.04
```
gate: SHORT при BTC BULL str<75 → BLOCK (кроме pivot_reversal)
pivot_reversal всегда проходит (разворотный сетап у уровня — max прибыль)
btc_4h_regime пишется в features_json каждой сделки
TTL провайдера: 5 мин
```

### Профитабельность — апрель 2026
```
Убыточный рынок (whipsaw после обвала BTC).
confluence — полный стоп (DEV-171, убыток -348R).
Эксперимент: time_gate(09-18) + volume≥5M + BTCRegimeProvider gate.
Наблюдаем WR до 28.04 перед следующими решениями.
```

### Entry Priority Matrix — DEV-172
```
entry_matrix.py создан 14.04, вызов в register_trade_async.
Но priority=None для всех 335+ сделок за 2+ дней shadow.
Возможная причина: wt_snap не передаётся в момент вызова evaluate_entry_priority().
Нужна диагностика: grep "entry_priority" в логах + Read entry_matrix.py.
```

### OTE shadow — DEV-88/89
```
C1 winner: [0.705-0.786] + 4h + CHoCH, WR=41.7%, Sharpe=2.68
Shadow запущен 12.04, 20 пар, критерий к ~26.04: WR≥40% ∧ Sharpe≥1.5 ∧ n≥150
```
