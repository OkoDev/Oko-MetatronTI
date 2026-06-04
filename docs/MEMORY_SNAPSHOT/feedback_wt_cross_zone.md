---
name: feedback-wt-cross-zone
description: wt_cross в scan_loop = сырой кросс без зоны; zone-фильтр добавляется потребителями (WTSpecialist). Фикс scan_loop отложен — запомнить перед ARCH-117.
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9d582948-c9be-42e6-8444-4165a225d1fa
---

scan_loop.py строки 1292-1300: `wt_cross` = просто wt1×wt2 пересечение БЕЗ зоны OS/OB.

Зона добавляется позже потребителями:
- **WTSpecialist** (строка 74): `abs(cross) >= 1 and zone in ("OB","OS")` — использует отдельное поле `zone`
- **signal_checkers.py**: cross + затем фильтр `wt1_last < _os_gate`
- **combinator_v2** (после DEV-234): cross + зона В ОДНОМ условии (`wt[i-1] < WT_OS`)

**Тонкое различие:** combinator проверяет зону ДО кросса (wt[i-1]), WTSpecialist — ПОСЛЕ (текущий zone). Практически разница минимальная.

**Фикс отложен:** при реализации ARCH-117 (WTService единая сфера) — унифицировать под combinator-стиль: cross + was_in_zone_prev_bar.

**Why:** пользователь явно попросил запомнить ("пока про фикс — запомни!") — вопрос семантики wt_cross возник при анализе D-073 данных и DEV-234 фикса.

**How to apply:** при любой работе с wt_cross — уточнять контекст (сырой cross или cross-в-зоне). При ARCH-117 — это первый вопрос дизайна.

[[feedback-wt-cross-zone]] связан с [[ARCH-117]] и [[DEV-234]].
