---
name: feedback-backtest-realistic-sl
description: Бэктест-edge в R фантомен при узком SL — R считается от SL; фиксировать прод-SL перед выводом об edge
metadata: 
  node_type: memory
  triggers: 
    - бэктест
    - R-мультипл
    - стоп
    - edge
    - замер
  type: feedback
  originSessionId: d4a14296-c294-48b2-b1c5-22a12bc2b789
---

При оценке бэктест-edge в R **обязательно фиксировать реалистичный SL = боевой**: прод `min_sl_dist_pct=0.5%`, `sl_max_pct=2.0%` — НЕ бэктест-дефолт (`backtest_wt_b_ltf_entry.MIN_SL_PCT=0.003`/MAX 8%).

**Почему:** R = movement / SL_dist. Узкий SL искусственно раздувает R. DS-326 (18.06): wt_b ADX<25 gross **+0.204 при SL 0.3% → +0.048 при прод-SL 0.5%** (вчетверо меньше!). WR неизменен (47.1%) — иллюзия только в R-масштабе, не в реальном исходе. А комиссия (фикс % от notional) в R = 0.10%/SL% → при узком SL = 0.32R/сделку, съедает всё → net убыток на боевых условиях.

**Как применять — перед любым выводом «edge +X R»:**
1. Прогнать на ПРОД-SL границах (патч `bt.MIN_SL_PCT`/`MAX_SL_PCT` или config).
2. Посчитать net после комиссии (BingX round-trip 0.10% taker / 0.07% maker-выход) — `scripts/ds326_fees.py`.
3. Учесть проскальзывание (на узких SL критично).
Только **net на прод-SL** = реальный edge. Gross на узком SL = фантом.

**Why:** иначе бэктест показывает прибыль, которой в бою нет (узкий SL + комиссия). Корень самообмана метрик.
**How to apply:** `python scripts/ds326_fees.py --min-sl 0.005 --max-sl 0.02`; сравнить с дефолтом; если edge исчезает на прод-SL — он был артефактом.

Связано: [[ds326-wtb-adx-filter]] [[feedback_metrics_hygiene]] [[feedback_data_era_first]] [[vision_bot_as_anchor_against_emotion]]
