# Oko MTF — Энциклопедия проекта

> Живой справочник. Пополняется по мере работы над проектом.
> Формат: идея → реализация → где используется → подводные камни.

---

## Навигация

- [Типы сигналов (SignalType)](#типы-сигналов-signaltype)
- [Стратегии](#стратегии)
- [Ключевые концепции](#ключевые-концепции)
- [Ключевые модули](#ключевые-модули)
- [Параметры конфига](#параметры-конфига)

---

## Типы сигналов (SignalType)

> Enum в `core/signals/signal_models.py`. Каждый тип — отдельный детектор.
> Хранится строкой в `simulated_trades.signal_type`.

---

### SignalType.CONFLUENCE

**Другое название:** WT Reversal Signal (неофициально)
**Детектор:** `core/signals/wt_15m_reversal_scanner.py` → `scan_wt_15m_reversal()`
**Старый детектор:** `core/confluence/confluence_scanner.py` → `scan_confluence()` (оба живы)

#### Идея

Искать точки входа где несколько факторов совпали одновременно в коротком окне:
WaveTrend в перепроданности/перекупленности, тренд развернулся, цена у пивота.
Один индикатор ненадёжен. Совпадение трёх-четырёх = сетап с высокой вероятностью.
Название "confluence" = схождение факторов в одной точке.

#### Условия и очки (текущий детектор, `wt_15m_reversal_scanner`)

Lookback: **8 баров × 15m = 2 часа**. Порог: **strength ≥ 60**.

| Условие | Очки | Обязателен? |
|---|---|---|
| WT кросс прямо в зоне OS/OB | +25 | gate (один из двух) |
| WT кросс вне зоны (но WT ранее был в OS/OB) | +15 | gate (один из двух) |
| TSL пересечение + close confirmation | +25 | gate (обязателен) |
| Касание пивота (≤ 0.15%) | +25 | бонус |
| Дивергенция WT (регулярная) | +20 | бонус |
| Скрытая дивергенция WT | +15 | бонус |
| Пивот конфлюэнция 1W+1D | +15 | бонус |
| Пивот конфлюэнция 1M | +20 | бонус |

Минимальный сигнал: TSL(25) + WT_CROSS(15) = 40 → не хватает, нужен ещё один фактор.

#### Условия (старый детектор, `confluence_scanner`)

Lookback: **20 баров × 15m = 5 часов**. Те же базовые факторы, другие веса.
Активен в `confluence_state_machine` как параллельный источник.

#### Как создаётся (pipeline)

```
scan_loop.py → scan_one(sym)
  └─ если есть confluence_sm → bot.confluence_sm.update()
  │    └─ вызывает оба сканера + state machine логику
  └─ иначе → scan_wt_15m_reversal() напрямую
        └─ возвращает List[SignalData(signal_type=CONFLUENCE)]
              └─ добавляется в all_scan_signals
                    └─ trading_intelligence → WtEntryStrategy или MultiSignalStrategy
```

#### Где используется

- `WtEntryStrategy.analyze()` — берёт ТОЛЬКО CONFLUENCE сигналы (фильтр по типу)
- `MultiSignalStrategy.analyze()` — получает вместе с другими, вес = **0.35** (самый высокий)
- `confidence_calculator.py` — если CONFLUENCE сигнал имеет 2+ факторов → бонус к confidence
- `trading_intelligence.py` — вес в adaptive weights: **0.15**

#### Подводные камни

1. **Имя совпадает со стратегией.** Бывшая стратегия `confluence` (теперь `multi_signal`)
   работает с ВСЕМИ типами сигналов, не только CONFLUENCE. Путаница была системной.

2. **`SignalType.CONFLUENCE` ≠ "конфлюэнция стратегий".** Это один конкретный детектор
   (WT-based reversal), который внутри себя проверяет несколько условий.

3. **Имя в БД не менялось.** В `simulated_trades.signal_type` хранится строка `"confluence"`.
   Переименование потребует миграции ~2400 записей.

4. **Два детектора одновременно.** Старый (`confluence_scanner`) и новый
   (`wt_15m_reversal_scanner`) могут оба сгенерировать сигнал. State machine управляет приоритетом.

---

### SignalType.MTF_BIAS

**Детектор:** `core/mtf/mtf_checker.py`
**Вес в системе:** 0.50 (самый высокий)

> TODO: добавить полное описание

---

### SignalType.PIVOT_REVERSAL

**Детектор:** `core/pivots/pivot_reversal.py`
**Вес в системе:** 0.20

> TODO: добавить полное описание

---

### SignalType.DIVERGENCE

**Детектор:** `core/indicators/divergence_detector.py`
**Вес в системе:** 0.10

> TODO: добавить полное описание

---

### SignalType.WT_SIGNAL

**Детектор:** `core/signals/signal_checkers.py`
**Вес в системе:** 0.10

> TODO: добавить полное описание

---

### SignalType.TREND_SIGNAL

**Детектор:** `core/indicators/trend_signals.py`
**Вес в системе:** 0.10

> TODO: добавить полное описание

---

### SignalType.ANOMALY

**Детектор:** `core/signals/signal_checkers.py` (был отдельный `anomaly_detector.py`, удалён)
**Вес в системе:** 0.05

> TODO: добавить полное описание

---

## Стратегии

> Стратегия = правила отбора и агрегации сигналов + расчёт SL/TP.
> Регистр: `strategies/registry.py`. Активные: `config.yaml → trading.active_strategies`.
> Результат хранится в `simulated_trades.strategy_name`.

---

### WtEntryStrategy ("wt_entry")

**Файл:** `strategies/built_in/reversal_scanner_strategy.py`
**Бывшее имя:** `reversal_scanner` (переименовано 28.03.2026)
**Данные в БД:** 729 сделок

#### Что делает

Берёт из входящих сигналов только `SignalType.CONFLUENCE`. Выбирает сильнейший LONG или SHORT.
Если конфликт равной силы — возвращает None.

SL: TSL-линия × (1 - 0.3%). Если TSL слишком близко (< `tsl_min_dist`) — fallback ATR×1.5.
TP: entry ± sl_dist × `tp_rr` (3.0 по умолчанию).

#### Данные

avg_R = **−0.377**, WR = **4.5%** (729 сделок).

Плохой результат объясняется не буфером SL, а тем что стратегия входит по CONFLUENCE сигналу
вне зависимости от общего тренда. CONFLUENCE в тренде (+3.84R для `tsl_line:trendup`)
принципиально лучше чем CONFLUENCE против тренда.

#### Приоритет в оркестровке

Priority-1 в `_pick_best_recommendation()`. Если есть — берётся сразу, другие стратегии игнорируются.

---

### MultiSignalStrategy ("multi_signal")

**Файл:** `strategies/built_in/confluence.py`
**Бывшее имя:** `confluence` (переименовано 28.03.2026)
**Данные в БД:** 511 сделок

#### Что делает

Принимает ВСЕ типы сигналов. Требует 2+ от разных источников.
Считает взвешенный score, проверяет конфликты. Генерирует рекомендацию с адаптивным SL/TP.

Веса сигналов:
- MTF_ALERT: 0.30 | MTF_BIAS: 0.30 | CONFLUENCE: 0.35 | PIVOT_REVERSAL: 0.20
- DIVERGENCE: 0.15 | WT_SIGNAL: 0.10 | TREND_SIGNAL: 0.10 | ANOMALY: 0.05

#### Данные

avg_R = **+3.486**, WR = **2.0%** (511 сделок).
Высокий avg_R при низком WR означает редкие но крупные победители.

---

### PivotReversalStrategy ("pivot_reversal")

**Файл:** `strategies/built_in/pivot_reversal_strategy.py`
**Данные в БД:** 52 сделки

SL: ATR(14)×1.5, зажат [1%, 4%]. TP: entry ± sl_dist × tp_rr (3.0).
avg_R = −0.315, WR = 10%.

> TODO: расширить описание

---

## Ключевые концепции

---

### TSL — Trailing Stop Loss

**Реализация:** `core/trading/trade_simulator.py` → `check_open_trades_with_tsl()`
**Индикатор:** `calculate_trend()` из `core/indicators/indicators.py` (Supertrend)
**Параметры:** `analysis.indicators.trend.atr_period: 43`, `factor: 1.25`

#### Как работает

TSL = линия Supertrend (`trendup`/`trenddown`). Следует за ценой, не уходит назад.

1. **Активация:** только после достижения `+tsl_activation_r` (= 1.0R) прибыли
2. **Проверка:** по `CLOSE` свечи (не по LOW/HIGH — фитили не вышибают)
3. **Срабатывание:** LONG → `close <= tsl_trenddown` → STATUS=TSL, exit=close
4. **Хранение:** `tsl_tf` в БД — таймфрейм активного TSL

#### Cascade TSL (DEV-29)

Иерархия TF: 15m → 1h → 4h. Поднимается когда тренд подтверждён на старшем TF.
De-escalation: если `current_r >= cascade_tsl_deescalation_r (2.5)` и нижний TF даёт тighter стоп.

#### DEV-87 (28.03.2026)

До фикса: 11 мест в коде использовали `factor=1.0` (дефолт), хотя в конфиге `factor=1.25`.
TSL-линия с factor=1.0 шире (дальше от цены), с factor=1.25 — ещё шире.
Все вызовы `calculate_trend()` теперь читают factor из конфига.

---

### WL Breach — Watch List Breach Entry

**Реализация:** `bot/loops/scan_loop.py` → `_handle_wl_breach_entry()`
**Config:** `signal_quality.wl_sl_buffer_pct: 0.5`

#### Идея

Пара добавляется в Watch List когда приближается к ключевому уровню (пивоту).
При пробое уровня на `watch_list_breach_pct` (0.8%) — авто-вход без `analyze_symbol`.

#### SL logic

```python
sl = pivot_level * (1.0 - wl_sl_buffer_pct/100)  # LONG: 0.5% ниже пробитого уровня
```

#### Проблема (кейс SHAPE/USDT)

Когда `wl_pivot_key = "tsl_line"` (а не реальный pivot), `pivot_level` = значение TSL-линии,
которая в RANGE режиме может быть 5%+ от цены. SL получается катастрофически широкий.

Нужен gate: если нет реального пивота в разумной близости (≤8%) → не входить.

---

### SL проверка: CLOSE vs LOW

**Реализация:** `core/trading/trade_simulator.py` → строки ~1175

#### Логика

По умолчанию SL проверяется по LOW свечи (для LONG) или HIGH (для SHORT).
Это реалистично для ценовых уровней (swing_low, pivot, FVG) — фитиль дошёл = вышло.

Для TSL-линии (индикаторный уровень) — другая логика.
Фитиль через TSL-линию ≠ разворот тренда. Подтверждение = закрытие за линией.

**DEV-88 (28.03.2026):** для `sl_source` начинающихся с `tsl_line` или `wl_pivot_tsl` —
проверка по CLOSE:

```python
_sl_check_close = sl_source.startswith("tsl_line") or sl_source.startswith("wl_pivot_tsl")
hit_sl = close <= sl if _sl_check_close else low <= sl  # LONG
```

---

## Ключевые модули

> TODO: добавить описания по мере работы с модулями

| Модуль | Назначение | Строк |
|---|---|---|
| `bot_with_subscriptions.py` | точка входа, TradingAlertBot | ~75 |
| `core/trading_intelligence.py` | агрегация сигналов → рекомендация | ~1850 |
| `core/trading/trade_simulator.py` | SL/TP/TSL трекинг, запись сделок | ~1300 |
| `bot/loops/scan_loop.py` | основной цикл сканирования | ~700 |
| `bot/monitoring.py` | мониторинг, WL breach, broadcast | ~600 |
| `core/signals/wt_15m_reversal_scanner.py` | детектор CONFLUENCE (WT reversal) | ~450 |
| `core/confluence/confluence_scanner.py` | старый CONFLUENCE детектор (lookback) | ~350 |

---

## Параметры конфига

> TODO: добавить по мере работы с конфигом

| Параметр | Значение | Описание |
|---|---|---|
| `analysis.indicators.trend.factor` | 1.25 | Ширина TSL-полосы Supertrend |
| `analysis.indicators.trend.atr_period` | 43 | Период ATR для Supertrend |
| `trading.tsl_activation_r` | 1.0 | R-кратность для активации TSL |
| `trading.cascade_tsl_deescalation_r` | 2.5 | R для de-escalation TSL на нижний TF |
| `signal_quality.wl_sl_buffer_pct` | 0.5 | Буфер SL от пробитого пивота при WL breach (%) |
| `trading.sl_tp.struct_sl_buffer_pct` | 0.3 | Буфер SL от swing_low/high (%) |
| `trading.strategies.wt_entry.sl_buffer_pct` | 0.3 | Буфер SL от TSL-линии для wt_entry (%) |
