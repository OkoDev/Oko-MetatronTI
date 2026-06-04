---
name: tr241-confirmation-finding
description: DEV-200 Phase 2 предварительный анализ — confirmations помогают НЕ всем сигналам; для wt_signal коррелируют с худшим R; fillrate≠качество
metadata: 
  node_type: memory
  type: project
  originSessionId: ee9ba90d-1cf2-4c71-8c17-eaf3c127d50f
---

# TR-241 / DEV-200 Phase 2 — предварительный анализ confirmations (04.06.2026)

**Источник:** `scripts/tr241_confirmation_fillrate.py --since 2026-05-15`, n=4575 закрытых.
**⚠️ Это ДО-инструментовочные данные** (confirmations из старого DEV-201/202 confluence_factors, НЕ новый helper-пайплайн). Корреляция, не причинность. Реальный замер нового пайплайна (smc/fvg/div_cascade/wt_cross) — после накопления post-instrumentation сделок ~06.06.

## Находка 1: эффект confirmations РАЗНОНАПРАВЛЕН по signal_type
- **pivot_reversal**: confirm>0 avgR +0.095 (n=76) vs ==0 −0.054 (n=159) → Δ **+0.149R** (слабый плюс)
- **wt_signal**: confirm>0 avgR **−0.472** (n=51) vs ==0 **+0.305** (n=111) → Δ **−0.777R** 🔴
  - Для wt_signal наличие confirmations коррелирует с ХУДШИМ результатом.
- watch_list_breach Δ−0.002, wt_sideways Δ−0.021 (нейтрально); confluence Δ+0.511 (но это сам тип, confirm==0=−0.93).

**Вывод:** слепой Phase 3 (SOFT penalty за `confirmations==0`) НАКАЗАЛ БЫ лучшие wt_signal-сделки. Phase 3 нельзя катить вслепую — только per-signal_type, по данным нового пайплайна. См. [[arch124_regime_audit]] (аналогично: классификатор «помогает» не везде).

## Находка 2: заполняемость ≠ качество
Сильнейшие сигналы имеют 0% confirmations, но топ avgR:
- divergence 0/177 → avgR **+0.727** WR54%
- ote_nested 0/44 → avgR **+1.493**
- arch104 0/131 → avgR +0.286

**Вывод:** критерий TR-241 «заполняемость >50%» как gate качества ОШИБОЧЕН. Эти сигналы самодостаточны. Acceptance переформулирован: «заполняемость как факт покрытия, НЕ как proxy качества; вердикт по avgR-split per signal_type, не по %».

## Что мерить на post-instrumentation (~06.06)
Новые helper-источники (smc_bos/choch, fvg_fill, smc_eql/eqh_swept, wt_extreme, div_cascade_1h_15m, wt_cross_same_dir) ведут себя ИНАЧЕ, чем старый confluence (pivot_touch/zone). Сплит confirm>0 vs ==0 + trigger-path vs observe-path per signal_type, фокус wt_signal/pivot_reversal. Связь: [[ote_nested_mtf_strategy]].
