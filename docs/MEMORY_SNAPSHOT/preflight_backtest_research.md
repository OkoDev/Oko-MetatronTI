---
name: preflight-backtest-research
description: Pre-flight чек-лист перед бэктестом / анализом данных / pattern mining исследованием
metadata: 
  node_type: memory
  type: preflight
  triggers: 
    - бэктест
    - pattern mining
    - walkforward
    - анализ за период
    - tools/pattern_mining/* запустить
    - статистика по сделкам
    - avgR / Sharpe / WR
  originSessionId: 7eb11094-8711-4e7a-9c69-bf18fb7e5f76
---

# Pre-flight: бэктест / data research

> Read **прежде чем** делать выводы по данным или запускать pattern mining.

## 1. Data era split — ВСЕГДА первым

→ [[feedback_data_era_first]]

Любой анализ начинается с разреза:
- `confluence` (dead с 31.03.2026) — НЕ включать
- `micro_sl` (sl_dist<0.2% или is_micro_sl) — артефакт pre-DEV-157
- `pre_tsl_fix` (< 2026-04-15) — DEV-174 баги
- `post_tsl_fix` (>= 2026-04-15) — единственная валидная выборка

**Минимум 10+ сделок post-15.04 для решения "блэклист/отключение"**. Меньше — "наблюдать".

## 2. Метрики — не avgR в одиночку

→ [[feedback_metrics_hygiene]]

Всегда считать:
- median_R, Sharpe, гистограмма по бакетам
- top-10% contribution (single events?)
- Без этого — `+3.486 avgR` может скрывать 3 ARIA-pumps по +112R при медиане -0.5

## 3. Семантика метрики — проверена

→ [[feedback_verify_metric_semantics]]

Перед утверждением "N% сделок имеют X":
- Grep где `field_name` записывается в коде
- Прочитать что туда пишется (источник + момент)
- Сравнить с моей интерпретацией
- Если уверенности нет — "не проверил семантику, нужно проверить"

## 4. Lookahead safety

→ [[backtest_lookahead_bug]]

- WR > 90% в backtest — почти всегда lookahead bug
- MTF reindex (4h на 1h) → сдвинуть индекс на `+4h Timedelta` ДО reindex
- WT/SMC флаги должны быть `shift(1)` если использую `.iloc[i]` для предсказания

## 5. Multiple Hypothesis Testing

Если перебираю N комбинаций факторов и беру топ-10:
- Bonferroni: `p_threshold = 0.05 / N`
- Benjamini-Hochberg FDR — более liberal (используется в ARCH-104 walkforward_full)
- Без correction — 5% результатов false positive просто по случайности

## 6. Существующие данные (не пересчитывать)

| Что нужно | Где взять |
|---|---|
| OHLCV исторические | `data/history/{tf}/*.parquet` (46 пар × 2 года Binance Vision) |
| Combinator flags | `tools/pattern_mining/combinator_v2.py::compute_flags()` |
| Walk-forward результаты | `data/research/2026-05-20--ph1/walkforward_full.csv` (12K passed) |
| Anti-patterns | `data/research/2026-05-20--ph1/antipatterns_v1.csv` (214 kill switches) |
| TP/exit grid | `data/research/2026-05-20--ph2/tp_exit_grid_*.csv` |
| Realistic-adjusted | `data/research/2026-05-20--ph4/realistic_adjusted.csv` |
| 15 production patterns | `config/arch104_patterns.yaml` |

## 7. Прежде чем запустить новый walkforward

- Проверить, не сделано ли уже в Phase 1-7 (см. `docs/PATTERN_MINING_2026-05-19.md`)
- Скриптовать через `tools/pattern_mining/_run_registry.py` (audit trail для reproducibility)
- Выходной CSV → `data/research/<YYYY-MM-DD>--<phase>/`

## 8. Realism layer

Любой "сырый" avgR из walkforward — это **gross**. Для решения нужен **real-adjusted**:
- commission: 2 × 0.04% × leverage
- slippage: 1-5 bps в зависимости от volume пары
- funding cost: per 8h holding
- Скрипт: `tools/pattern_mining/realistic_costs.py`

## 9. Что НЕ делать

- ❌ Делать вывод "стратегия X прибыльна" по 10 сделкам без проверки era + metrics + semantics
- ❌ Использовать `pd.read_sql` с join'ами без проверки что в JOIN правильные ключи (DEV-215 datetime bug — string compare наказывал нас)
- ❌ Гипотезу "atr_change_1d работает" принимать без walk-forward валидации
- ❌ Пересоздавать combinator/walkforward вместо использования готовых данных в `data/research/`

## Связано
- [[feedback_data_era_first]] · [[feedback_metrics_hygiene]] · [[feedback_verify_metric_semantics]]
- [[backtest_lookahead_bug]]
- [[pattern_golden_long_validated]] · [[pattern_nested_15m_walkforward_validated]]
- [[tsl_no_trail_insight]]
