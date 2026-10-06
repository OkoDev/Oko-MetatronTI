---
name: cube_codes_are_letters_not_numbers
description: "🔢→🔤 04.10 РЕШЕНО (Егор «я за В»): числа остаются у сфер КАРТЫ (производители событий шины), селфтест зовёт компоненты по имени — DC WS WT SMC XM RGM TI TS EXIT PTA NB ML BUS MKT WAVE PHASE. Причина: S8 значил три разных вещи, а S1-S3 в 74 файлах — уровни пивотов"
metadata:
  node_type: memory
  type: project
  originSessionId: ea98197f-5cfa-4b48-ab76-1b2fcebf5d0d
  modified: 2026-10-04T15:18:25.594Z
---

**Чем было больно.** «S8» значил три разных вещи одновременно:
- **карта и реестр** (`core/context/sphere_registry.py`, `docs/SIGNAL_BUS_CUBE_MAP.md`) нумеруют
  ПРОИЗВОДИТЕЛЕЙ СОБЫТИЙ шины (`_EVENT_TO_SPHERE`: `pivot_snap_updated`→8, `narrative_built`→9):
  S8 Pivot Levels · S9 Narrative · S10 Exit · S11 Post-Trade · S12 Self-Diagnostics · S13 Phase;
- **селфтест** (`core/selftest_cube.py`) проверяет ОБЪЕКТЫ БОТА: S8 TradeSimulator · S9 Exit ·
  S10 PostTrade · S11 Narrative · S12 ML · S13 PairContextBus. Narrative и Exit/Post-Trade были
  переставлены крест-накрест;
- **`S1`/`S2`/`S3` в 74 файлах проекта** — это УРОВНИ ПОДДЕРЖКИ пивотов (и `R1`–`R3` — сопротивления).

**Решение (вариант В).** Числа остаются у сфер Куба; компоненты селфтеста зовутся по имени:
`DC WS WT SMC XM RGM TI TS EXIT PTA NB ML BUS MKT WAVE PHASE` (`e3c34aa`, дашборд `ecd62d5`).
Таблица соответствия кодов сферам карты — в докстринге `core/selftest_cube.py`.

**Почему НЕ «назначить одну правильную нумерацию»:** карта и селфтест описывают разные сущности,
у половины компонентов селфтеста номера в карте нет вовсе (TradeSimulator, ML Outcome), а у Pivot
Levels и Self-Diagnostics нет своих объектов. Единая нумерация передвинула бы коллизию, а не убрала.
Побочный выигрыш: исчез вынужденный `S13_PHASE`, появившийся днём раньше из-за занятой S13.

**How to apply:** «сфера 9» теперь значит ровно одно — сферу КАРТЫ (Narrative). Компонент в отчёте
селфтеста называешь буквами. Добавляешь компонент — дай буквенный код, не число.
Связано: [[cube_selftest_sees_outside_spheres]], [[cube_dashboard_is_built_from_selftest]],
[[state_lives_outside_the_code]].
