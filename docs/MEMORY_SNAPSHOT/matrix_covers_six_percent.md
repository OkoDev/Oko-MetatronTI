---
name: matrix_covers_six_percent
description: "🔴🔴 МАТРИЦА ЗАМЕРОВ ПОКРЫВАЕТ 6% РЕШАЮЩИХ ПРИЗНАКОВ: в combinator_core 79 шаблонов, в features_json боевых сделок 230 ключей, покрыто 14, ВНЕ МАТРИЦЫ 216. Плюс 86 модулей с логикой решений, из которых в матрицу входит один"
metadata:
  node_type: memory
  type: project
  triggers:
    - матрица признаков
    - что вне матрицы
    - research_harness
    - полный замер
    - чего не мерили
  originSessionId: 9a19646e-5506-497f-b946-1c75aeb88a81
  modified: 2026-08-27T20:48:50.035Z
---

# 🔴🔴 МАТРИЦА ПОКРЫВАЕТ 6% РЕШАЮЩИХ ПРИЗНАКОВ (27.08.2026)

Егор: «матрицу дополнить всем что вне её сейчас, пусть будет полной и не раздробленной».
Сверка сделана через graphify-граф (8442 узла) + `features_json` 400 последних сделок.

| | |
|---|---|
| шаблонов в `combinator_core.compute_flags` | 79 (→446 после разворота по ТФ и старшим) |
| ключей в `features_json` боевых сделок | 230 |
| покрыто матрицей | **14** |
| 🔴 **ВНЕ МАТРИЦЫ** | **216** |

## Группы вне матрицы

| группа | признаков | примеры |
|---|---|---|
| не классифицировано | 125 | entry_priority · atr_trend_1h_bias · htf_wt1_1h · wt1_at_signal · confirmations · market_event · trigger_source · sideways_mode |
| магниты и уровни | 21 | radar_magnet_above/below_pct · pivot_real_touch · pivot_close_rejection · pivot_volume_z |
| маршрутизация и риск | 21 | soft_penalties · router_final_strength · gate_features · smc_verdict · verdict_gate |
| механика impulse | 15 | if_age · if_amp_pct · if_vratio · if_score · if_size_mult · rr_at_entry |
| рыночный контекст | 14 | phase · mkt_ac_regime · btc_4h_regime · ud_d30/d90/d180 · ud_slope |
| ML и советники | 9 | ds_feature_mult · ds_confidence · wl_score · tp_selector_tp2_score |
| исполнение и лаг | 8 | session · entry_lag_seconds · shadow_scan_loop_late · entry_price_lag_pct |
| деривативы | 6 | radar_oi_d5/d15 · radar_funding · radar_oi_px_quadrant · mkt_funding |
| управление позицией | 3 (в коде 15 методов) | conf_f_tsl_cross_up/down · tsl_degraded |

## Модули с логикой решений: 86 файлов, в матрице ОДИН

`core/smc` 27 · `core/intelligence` 20 · `core/signals` 13 · `core/context` 11 ·
`core/indicators` 8 · `core/ml` 7 · `core/calculators` 2 (из них `combinator_core`
и ЕСТЬ матрица).

То есть замеры видят один модуль из 86. Детекторы фандинга, OI, магнитов, ликвидности,
фаз, доминации, ML-специалисты, калибраторы уверенности, decision_fusion, entry_matrix —
всё это влияет на боевые решения и НИ РАЗУ не проходило слепой отбор.

## 🔑 Почему это объясняет «0 из 446»

Три дня слепой отбор давал ноль на обеих сторонах и обоих ТФ. Вывод «признаков нет»
был преждевременным: **мы перебирали 6% пространства**. Остальные 94% — контекст,
деривативы, магниты, ML, исполнение — в переборе не участвовали.

Отдельно: слой УПРАВЛЕНИЯ (15 методов выхода, из них мерены 3) не входит в матрицу
по определению — она про вход. При том что 75% прибыли механики даёт ход к цели,
а не её достижение, то есть управление этим ходом.

## Что делать

Свести матрицу воедино: `compute_flags` + боевые признаки `features_json` + слой
управления + слой риска. Тогда `blind_select` будет судить всё пространство, а не
шестую часть его двадцатой доли.

Связано: [[research_harness_single_entry]], [[feedback_confluence_not_moment]],
[[wt_freshness_gate_candidate]], TASKS.md → «РЕЕСТР ИНСТРУМЕНТОВ И MTF-СВЯЗОК».
