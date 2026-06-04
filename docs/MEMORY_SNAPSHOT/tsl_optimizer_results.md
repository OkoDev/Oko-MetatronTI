---
name: tsl-optimizer-results
description: "🏆 TSL Optimizer на 15m nested entries. Best Fixed TSL act=2R trail=2R: avgR улучшен с +1.46 до +2.44 (+68%). Эскалирующий BE@1R хуже — забирает 25% WR"
metadata: 
  node_type: memory
  type: project
  originSessionId: 7eb11094-8711-4e7a-9c69-bf18fb7e5f76
---

# 🏆 TSL Optimizer — оптимальная стратегия выхода

## Контекст бэктеста

- **Entry**: HTF золотой паттерн + LTF `bull_ob_near_15m` = 167 entry points
- **Симуляция**: каждый entry × разные TSL стратегии
- **Период**: 2024-01-01 → 2026-05-17 (2 года), 11 пар

## Результаты сравнения

| Стратегия | n | avgR | WR | max_R |
|-----------|---|------|-----|-------|
| **Baseline** (TP=2R fixed) | 167 | +1.456 | 82.6% | +2.00 |
| 🏆 **Fixed TSL** (act=2R, trail=2R, time=24h) | 167 | **+2.442** | **82.6%** | **+11.40** |
| Escalating `be_then_runner` (BE@1R + trail 1.5R@3R) | 167 | +1.781 | 57.5% | +8.05 |
| Escalating `patient_step` | 167 | +1.390 | 66.5% | +4.75 |
| Escalating `ladder_4step` (BE@0.5R → trail 1R@1R → 0.5R@2R → 0.3R@3R) | … | … (хуже) | … | … |

## 🏆 ВЫИГРАВШИЕ ПАРАМЕТРЫ

```yaml
exit_strategy: "fixed_tsl"
tsl_activation_r: 2.0       # активировать только после +2R от entry
tsl_trail_r:      2.0       # trail на 2R от peak (новый SL = peak - 2R*sl_dist)
time_limit_bars:  96        # 24 часа (на 15m TF)
```

**Поведение:**
1. Entry → SL = swing_low × 0.999 (фиксированный)
2. Пока R < +2: SL не двигается
3. Когда R достигает +2: активируется TSL
4. После активации: каждый новый peak обновляет SL = peak - 2R × sl_dist
5. Выход при касании TSL ИЛИ через 24 часа

**Результат:**
- avgR: +2.442 (vs baseline +1.456 — улучшение +68%)
- WR: 82.6% (не пострадал!)
- Max R: +11.4 (захватываем большие движения)
- Distribution exit: 64% TSL / 17% SL / 19% time

## ⚠️ Почему эскалирующий BE@1R НЕ работает

`be_then_runner` (steps=[(1.0, 0.0), (3.0, 1.5)]):
- BE при +1R = слишком рано
- Цена часто откатывается на 1-2R после первого импульса → BE вышибает
- Теряем сделки которые могли долететь до +5R, +10R
- **WR падает с 82% до 57%**

**Урок:** в условиях когда TP легко достижим (HTF + LTF фильтры дают 82% WR), **не торопиться с BE**. Лучше дать сделке развернуться полностью.

## Расчёт обновлённой доходности

Стратегия `bull_ob_near_15m + atr_up_15m` + Best Fixed TSL:
- 73 сделки за 11 мес (test) ≈ **6.6 сделок/мес** (12 пар)
- avgR = +2.44
- Per trade (1% risk): +2.44% × 1% = +2.44% депозита за сделку
- Monthly: 6.6 × 2.44% = **+16% в месяц** (compound)
- APR ≈ **+520%**

При расширении на 30-40 пар → ~20-30 сделок/мес → ~50%+ в месяц.

## TODO: дополнительные тесты

1. Попробовать эскалирующий с **BE@2R** (поздний breakeven) — может дать лучше Fixed
2. ATR-based trail (вместо R-based) — может быть лучше для волатильных пар
3. Partial close (50% at +2R, 50% trail) — снижение риска при сохранении upside
4. Сравнение по парам — TSL может быть разный для разных активов

## Source

- Скрипт: `tools/pattern_mining/tsl_optimizer.py`
- Результаты: `data/research/2026-05-19/tsl_optimizer_15m_results.csv`
- Эскалирующие: `data/research/2026-05-19/tsl_optimizer_esc_15m_results.csv`

## How to apply

При реализации в боте:
1. Stage 1 (до +2R): фиксированный SL = swing_low × 0.999
2. Stage 2 (после +2R): TSL trail @ 2R от peak
3. Time exit: 24h после entry (если ни TSL ни SL не сработали)
4. Логировать exit reason (TSL / SL / TIME) — для мониторинга что чаще срабатывает
