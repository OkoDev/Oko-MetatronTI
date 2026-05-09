---
tags: [doc/status, session, current-state]
type: status-daily
date: "2026-04-30"
parent: "[[Project-MOC]]"
---

## Now
Спринт «РЕАЛЬНЫЕ УБИЙЦЫ» (25.04–02.05): DEV-184 ✅ (DUAL_TSL отключен), DEV-185 ✅ (buffer=1.0%), DEV-185.2 ✅ (watchdog готов), DEV-190 ✅ (effective_status). Требует deploy: DEV-186 (второй рестарт). В очереди: DEV-187/188.
ARCH-95 Слои A–D: скрипты H1–H4 завершены, ARCH-74-EXT (Smart TSL) принято как расширенный тех-долг.

## Blocked on
DEV-186: требует второго рестарта для полного покрытия (regime source fix).
ARCH-74-EXT skeleton: после стабилизации спринта (~1-я неделя мая 2026).

## Next
- DEV-186: второй рестарт (туже 27–28.04)
- DEV-187/188: адаптивные пороги + TREND_DOWN gate
- Data era v4 validation: smc_snap fix verification (2026-04-29 22:00+)
- ML retrain: все specialists на data_era v4 данных
- ARCH-74-EXT skeleton: Smart TSL architecture
- ARCH-95 H5/H6: atr_trend_1h_bias gate анализ

_Updated: 2026-04-30 by Claude_
