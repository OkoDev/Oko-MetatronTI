---
name: pattern-1h-wt-os-smc-long
description: "Базовый LONG паттерн — 1h WT OS + SMC bull context + ATR change UP. Бэктест 231 сигнал WR=59.3% avgR=+0.149 (лучший вариант FVG+OB на 1h: WR=75.8% avgR=+0.383)"
metadata: 
  node_type: memory
  type: project
  originSessionId: 7eb11094-8711-4e7a-9c69-bf18fb7e5f76
---

# Базовый LONG паттерн: 1h WT OS + SMC (1h) + ATR change

## Условия паттерна (все обязательны)

1. **1h WT < -60** — WaveTrend oversold на 1h (последние 3-4 бара)
2. **Bull SMC контекст** на 1h или 15m — любое из:
   - 1h FVG открыт (незаполненный bull FVG)
   - 1h bull OB не mitigated
   - 15m bull FVG + 15m bull OB
3. **ATR supertrend cross UP** — на 1h или 15m (atr_change сигнал)
4. **Вход в OTE/FVG зону** — цена в 0.62-0.79 Fib ИЛИ вблизи bull OB

## Результаты бэктеста (19.05.2026, 12 пар, ~7 дней)

| Вариант | n | avgR | WR% |
|---------|---|------|-----|
| Весь паттерн | 231 | +0.149 | 59.3% |
| **1h FVG + 1h OB** | 66 | **+0.383** | **75.8%** ← лучший |
| ob_15m + fvg_1h | 73 | +0.300 | 68.5% |
| Вход в OTE | 73 | +0.256 | 68.5% |
| 1h FVG (без OB) | 91 | +0.270 | 68.1% |
| 1h OB (без FVG) | 107 | +0.211 | 61.7% |
| choch_15m (один) | 19 | -0.006 | 36.8% ← НЕ работает |

**Лучшие пары:** STX (WR=94%), ENS (WR=89%), RENDER (WR=78%), DOT (WR=69%)

## Что НЕ работает

- CHoCH 15m как единственный фактор: WR=36.8% — слабо
- Точное попадание в FVG зону (+0.031) < наличие FVG (+0.270)
- Ждать точного входа в FVG не нужно — важнее само наличие зоны

## Следующий шаг (в работе)

Поиск лучших точек входа на **младших ТФ** (5m/3m) внутри паттерна:
- Когда паттерн 1h активен → ищем сигнал на 5m
- Варианты: WT cross UP 5m, CHoCH 5m, FVG 5m заполнен, OTE 5m

## Скрипт бэктеста

`e:\tmp\smc_pattern_backtest.py` — полный бэктест с OHLCV через BingX

## Why

Паттерн описан пользователем. Бэктест подтвердил работоспособность.
Это основа для нового SMC-based entry сигнала на базе atr_change.

**How to apply:** При реализации новых entry сигналов — проверять наличие этого паттерна.
Реализация: ConfirmationRegistry типы `smc_1h_fvg_bull` (+15) + `smc_1h_ob_bull` (+12) + `smc_ote_entry` (+10).
