---
name: ote_all_setups_honest_map
description: "Честная карта всех 7 OTE-сетапов (post-fake-R cutoff, VST) — SHORT=pull, LONG=cont; avgR от сломанного выхода, MFE=правда входа"
metadata: 
  node_type: memory
  type: project
  originSessionId: 0b9885d0-84da-4125-92df-2c24b01a41a7
---

# Карта всех 7 OTE-сетапов — честный R (20.06.2026)

Методология: `closed_at ≥ 2026-06-19T06:00 UTC` (после fake-R фикса 02beb18), VST-only, санити R∈[−1.5, MFE+0.2], split direction. ⚠️ avgR отражает **СЛОМАННЫЙ выход** (BE не синкался — починено e762449 в 23:14). **MFE = правда входа** (от выхода независим). Разрыв MFE−avgR = что вернёт exit-фикс.

| setup | dir | n | WR% | avgR | MFE | %≥1R | оценка |
|---|---|---|---|---|---|---|---|
| cont_1h_5m | LONG | 156 | 59 | **0.694** | 1.46 | 49 | 🟢 лучший LONG |
| cont_1h_5m | SHORT | 123 | 49 | 0.07 | 0.85 | 33 | 🔴 МЁРТВ (вход) |
| cont_4h_5m | LONG | 76 | 47 | 0.362 | 1.11 | 36 | 🟡 слабый |
| cont_4h_5m | SHORT | 27 | 56 | 0.435 | 0.85 | 26 | 🔴 вход мёртв (MFE<1, мал n) |
| pull_4h_5m | SHORT | 39 | 62 | 0.47 | 1.31 | 49 | 🟢 |
| pull_4h_5m | LONG | 15 | 40 | 0.311 | 1.17 | 40 | 🟡 medR −0.55 |
| pull_4h_15m | SHORT | 26 | 69 | **1.228** | 1.76 | 58 | 🟢 сильный |
| pull_4h_15m | LONG | 16 | 38 | 0.264 | 0.97 | 38 | 🟡 |
| pull_1h_5m | SHORT | 24 | 88 | **1.192** | 1.88 | 67 | 🟢 сильный |
| pull_1h_5m | LONG | 17 | 47 | 0.802 | 1.97 | 47 | 🟢 (MFE высок) |
| pull_1h_15m | SHORT | 7 | 71 | **1.585** | 2.18 | 86 | 🟢 топ (мал n) |
| pull_4h_1h | SHORT | 12 | 67 | 0.76 | 1.42 | 42 | 🟢 (мал n) |

## ЗАКОН (на всех сетапах)
- **SHORT = PULL** (все pull SHORT в плюсе 0.47→1.585; меньше ТФ-входа → выше WR).
- **LONG = CONT** (cont_1h_5m LONG 0.694 лучший; pull_1h_5m LONG исключение — высокий MFE).
- **Крест мёртв:** cont SHORT (medR 0), pull LONG (medR ≤0).

## ДЕЙСТВИЯ
- **Резать сейчас** (мёртвы на ВХОДЕ, MFE<1, exit-фикс не спасёт): cont_1h_5m SHORT, cont_4h_5m SHORT. → config/ote_setups.yaml direction both→long для cont.
- **Держать/усилить:** pull SHORT (все), cont_1h_5m LONG, pull_1h_5m LONG.
- **🔵 ПЕРЕМЕРИТЬ через 3-5 дней на post-фикс данных** (после e762449 выход не течёт → capture/avgR вырастут): 🟡 LONG-варианты могут ожить, не резать вслепую.
Связь: [[bug_be_not_synced_to_exchange]] [[cont_setups_honest_exit_diagnosis]] [[feedback_data_era_first]] [[mtf_weight_hierarchy_universal]]
