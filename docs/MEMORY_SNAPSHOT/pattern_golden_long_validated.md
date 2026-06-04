---
name: pattern-golden-long-validated
description: "🏆 ЗОЛОТОЙ LONG паттерн прошедший walk-forward валидацию. bull_div_1d + bull_fvg_4h + wt_os_4h. Test WR=100% n=29, avgR=+1.892 на out-of-sample 11 мес"
metadata: 
  node_type: memory
  type: project
  originSessionId: 7eb11094-8711-4e7a-9c69-bf18fb7e5f76
---

# 🏆 ЗОЛОТОЙ LONG паттерн (walk-forward validated)

## Паттерн (минимальный, 3-факторный)

```
LONG  ⇐  bull_div_1d  AND  bull_fvg_4h  AND  wt_os_4h
```

1. **Bull divergence на 1d** — цена сделала LL, RSI сделал HL (за окно 14 баров 1d)
2. **Bull FVG на 4h** — есть незаполненный bullish FVG (gap up между свечами), цена в его зоне
3. **WT OS на 4h** — WaveTrend (n1=10, n2=21) wt1 < -60

## Результаты валидации (19.05.2026)

| Период | n | avgR | WR% |
|--------|---|------|-----|
| Train 2024-01 → 2025-06 | 32 | +1.064 | 93.8% |
| **Test 2025-07 → 2026-05** | 29 | **+1.892** | **100.0%** |

- TP = 2R, SL = swing_low за 10 баров × 0.999, окно симуляции 12h
- **Деградация = -0.83** (паттерн стал ЛУЧШЕ на out-of-sample)
- 0 overfitted (deg > 1.0) среди 12 устойчивых из топ-100

## Расширения паттерна (k=4-5, всё ещё устойчивые)

Все дают test WR=100%, train avgR+1.064..+1.166:

- `+ bull_ob_1h` — бычий OB на 1h как entry confirmation
- `+ discount_1d` / `+ discount_4h` — цена ниже 50% swing range
- `+ atr_up_1h` — ATR supertrend cross UP на 1h
- `+ bull_fvg_1h` — bull FVG также на 1h

## Источник

`e:/tmp/smc_combinator_v2.py` + `e:/tmp/smc_walkforward.py v2`
Результаты: `e:/tmp/smc_walkforward_v2_results.csv`

Данные: Binance Vision 1h, 46 пар, 2024-01-01 → 2026-05-17.
Combinator: 22835 паттернов → dedup 5224 → top-100 → walk-forward → **12 устойчивых**.

## Что НЕ прошло валидацию

- **Все SHORT паттерны** (даже n=331 `bear_bos_1d + atr_cross_down_1d + premium_4h`) — не хватило n на test или WR<50%
- **5-факторные с большим train_n** — overfit на 2024
- **88 из 100 топ-паттернов** не прошли — реальный фильтр

## Why

Систематический Pattern Mining + walk-forward — единственный честный способ найти эджи без переподгонки. Все остальные SMC рекомендации (роя, теории) — спекуляции без out-of-sample проверки.

## How to apply

- Реализовать как `Confirmation(name="smc_golden_long", weight=15)` в ConfirmationRegistry
- Shadow mode 1-2 месяца — логировать срабатывания, проверить частоту (ожидание: ~3-5 сигналов/месяц на 46 парах)
- SL = swing_low за 10 баров 1h × 0.999, TP = entry + sl_dist × 2.0
- Если live результат подтверждает test (avgR > +0.5) — активировать как entry trigger
