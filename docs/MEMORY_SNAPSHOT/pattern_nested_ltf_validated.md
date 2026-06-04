---
name: pattern-nested-ltf-validated
description: "🚀 LTF nested entries внутри золотого HTF паттерна. Baseline n=262 avgR+1.14 WR=75%. Топ LTF triggers: bull_ob_near_15m даёт 167 сделок avgR+1.46 WR=83%. x10 больше сделок чем чистый HTF паттерн"
metadata: 
  node_type: memory
  type: project
  originSessionId: 7eb11094-8711-4e7a-9c69-bf18fb7e5f76
---

# 🚀 LTF Nested Entries внутри золотого HTF паттерна

## Идея

Золотой HTF паттерн `bull_div_1d + bull_fvg_4h + wt_os_4h` — это **режим**, не сигнал.
Активен часами/днями. Внутри этого режима на LTF (15m) ищем точки входа.

## Бэктест на 12 парах × 2 года (15m данные Binance Vision)

### Baseline: HTF активен, без LTF фильтра

| Метрика | Значение |
|---------|----------|
| n | 262 |
| avgR | +1.138 |
| WR | 74.8% |
| sumR | +298.3 R |

**Это уже x10 от чистого HTF паттерна (n=29).** Просто внутри HTF режима — открывай LONG в любой момент → 75% побед.

## Топ LTF entry triggers (улучшают baseline)

### 🏆 ТОП-1: `bull_ob_near_15m + bull_fvg_15m + atr_up_15m`
- n=79, avgR=+1.859, **WR=96.2%**, sumR=+146.8R

### ТОП-2: `bull_ob_near_15m + atr_up_15m`
- n=96, avgR=+1.727, WR=91.7%

### ТОП-3 (одиночный): `bull_ob_near_15m`
- **n=167, avgR=+1.457, WR=82.6%** — лучший баланс n × WR

### 1-факторные LTF (упорядочены по score)

| Фактор | n | avgR | WR% |
|--------|---|------|-----|
| `bull_ob_near_15m` | 167 | +1.457 | 82.6% |
| `bull_ob_15m` | 185 | +1.391 | 83.8% |
| `bull_fvg_15m` | 148 | +1.368 | 85.1% |
| `atr_up_15m` | 145 | +1.284 | 80.7% |
| `above_ema50_15m` | 205 | +1.148 | 76.1% |
| `bull_mom_15m` | 34 | +1.379 | 82.4% |
| `bull_bos_15m` | 37 | +1.226 | 81.1% |
| `discount_15m` | 81 | +1.074 | 69.1% |
| `vol_spike_15m` | 77 | +1.046 | 75.3% |

## Параметры симуляции

- TP = 2R, SL = swing_low за 10 баров 15m × 0.999
- Окно симуляции: 48 баров 15m (12 часов)
- HTF mask reindex с +1h shift (lookahead-safe)

## Использование на практике

### Минимальная стратегия (часто):
```
WHEN: bull_div_1d AND bull_fvg_4h AND wt_os_4h
THEN ENTRY when: bull_ob_near_15m
→ ~167 LONG/2 года (7/мес), avgR+1.46, WR 83%
```

### Сбалансированная (умеренно):
```
+ atr_up_15m → ~96 сделок (4/мес), avgR+1.73, WR 92%
```

### Максимальное качество:
```
+ atr_up_15m + bull_fvg_15m → ~79 сделок (3/мес), avgR+1.86, WR 96%
```

## Source

Скрипт: `tools/pattern_mining/combinator_v3_nested.py`
Результаты: `data/research/2026-05-19/nested_v3_15m_results.csv`
Полная история: `docs/PATTERN_MINING_2026-05-19.md`

## TODO

1. **Walk-forward validation** на nested результаты (train 2024/test 2025+)
2. **Запустить на 5m** — ещё больше точек входа
3. **Реализовать в `ConfirmationRegistry`** как Composite Confirmation:
   - HTF context (`bull_div_1d`, `bull_fvg_4h`, `wt_os_4h`) = required
   - LTF entry trigger (`bull_ob_near_15m`) = required
   - LTF amplifier (`atr_up_15m`, `bull_fvg_15m`) = optional weights

## Why

Один HTF золотой паттерн = 29 сделок за 11 мес. Слишком мало.
Внутри HTF режима на LTF можем найти 200+ сделок с тем же качеством.
Это и есть профессиональный SMC подход: HTF = bias, LTF = timing.

## How to apply

- Когда обсуждаем `entry signals` — спрашивать в каком HTF контексте
- HTF золотой паттерн = primary filter
- LTF тригеры = entry timing внутри primary filter
- Не использовать LTF сигналы без HTF context — там noise
