---
name: leg_span_bars_can_be_negative
description: "leg_span_bars бывает отрицательным (экстремум ноги левее origin): 5.1% ног при swing_len=50, 14.8% при 5 — фильтр ARCH-137 «≤86» пропускает их все"
metadata: 
  node_type: memory
  type: project
  originSessionId: b9292ecd-40bf-480f-b583-11c47310bf19
  modified: 2026-09-08T03:30:32.977Z
---

# 🔴 `leg_span_bars` БЫВАЕТ ОТРИЦАТЕЛЬНЫМ — и фильтр «≤ 86» этого не видит

Найдено 08.09.2026 при сверке Pine-порта ([[okowave_pine_port_verified]]): индикатор показал
`minor_leg_span_bars = −9`. Проверка ПИТОНОВСКОГО движка на тех же 500 барах
(BINGX:SEIUSDT.P 1h, `oko_sm_engine.run_structure`, `record_legs=True`):

| масштаб | ног | отрицательных | доля | минимум |
|---|---|---|---|---|
| swing_len=50 / internal=5 | 197 | 10 | **5.1%** | −41 |
| swing_len=5 / internal=3 | 486 | 72 | **14.8%** | −11 |

Значит это свойство самого движка, а не артефакт Pine. Механика: `current_leg` берёт
origin = последний подтверждённый свинг (его бар лежит `length` назад), а extreme = бегущий
trail, который мог быть выставлен РАНЬШЕ этого свинга.

🔑 **Почему это важно.** Набор ARCH-137 ([[wave_leg_1h_long_candidate]]) стоит на условии
`leg_span_bars_1h ≤ 86` — отрицательные проходят его автоматически, вместе с «короткими
чистыми ногами». То есть в наборе сидят ноги ДВУХ разных геометрий, и какая из них несёт
эдж — не проверялось. Перед любым выводом по набору разрезать по знаку `leg_span_bars`.

Связано: [[waves_in_matrix_leg_discount]] · [[smc_canon_engine_is_oko_sm]] ·
[[law_no_finding_means_no_feature]]
