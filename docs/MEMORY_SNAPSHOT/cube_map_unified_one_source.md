---
name: cube_map_unified_one_source
description: "🧭 КАРТА КУБА СВЕДЕНА В ОДНУ (27.08): было ЧЕТЫРЕ противоречащих нумерации — код 13 сфер, Obsidian 17, ENCYCLOPEDIA 13+14, TASKS 14-18 с дублем номера 14. Теперь единая таблица в SIGNAL_BUS_CUBE_MAP, остальные ссылаются. Занято 1-19"
metadata:
  node_type: memory
  type: project
  triggers:
    - карта Куба
    - сферы
    - номер сферы
    - новая сфера
    - sphere_registry
    - забыли что в кубе
  originSessionId: 9a19646e-5506-497f-b946-1c75aeb88a81
  modified: 2026-08-27T21:25:49.703Z
---

# 🧭 КАРТА КУБА СВЕДЕНА В ОДНУ (27.08.2026)

Егор: «карту куба объединить в одну и не дублировать по правилам».

## Что было: ЧЕТЫРЕ карты, ни одна не сходилась

| источник | сфер | расхождение |
|---|---|---|
| `core/context/sphere_registry.py` (код) | 13 | 2=WSFeed · 13=Фаза |
| `obsidian/Concepts/Cube-Metatron.md` | **17** | 2=Regime · 13=Portfolio · 16=PositionSync |
| `docs/ENCYCLOPEDIA.md` | 13 + 14=WaveService | внутри себя противоречил: «13 сфер» и «12 сфер» |
| `TASKS.md` ARCH-96…107 | 14–18 | 🔴 номер 14 занят ДВАЖДЫ: ARCH-96 Execution ↔ ARCH-121 WaveService |
| `core/selftest_cube.py` | своя | S7=TradingIntelligence · S13=PairContextBus |

🔑 **Это и была механическая причина «забываем, что в Кубе есть»** — карт много,
и каждая говорила своё.

## Что стало

**ЕДИНАЯ КАРТА:** `docs/SIGNAL_BUS_CUBE_MAP.md` → «СЛОЙ 4 — Сферы Куба».
Одна таблица, сферы **1–19**, статусы ✅ACTIVE ⚠️SHADOW ❌MISSING 🔌NOT WIRED.
**Источник истины — КОД** `sphere_registry.py` `SPHERE_NAMES`.

Остальные документы теперь ССЫЛАЮТСЯ (правило [[principle_reuse_not_duplication]]):
- `obsidian/Concepts/Cube-Metatron.md` — блок из 17 сфер удалён, стоит ссылка + пометка «устарело»;
- `docs/ENCYCLOPEDIA.md` — теория остаётся, нумерация и статусы не дублируются;
- `docs/REGISTRY.md` — только ссылка на карту;
- `docs/BUS_CATALOG.md` — авто-генерация `bus_catalog.to_markdown()`, руками не править
  (мой дубль `_bus_menu.md` удалён в тот же день).

**Занято 1–19, следующая свободная — 20.** Перед заведением новой сферы свериться
с таблицей, иначе номер уйдёт в дубль (так уже случилось с 14).

## Попутная находка: карта ВРАЛА про данные

`SIGNAL_BUS_CUBE_MAP` утверждал «история funding ❌ отсутствует» и «USDT.D нет в RAW».
В кэше при этом лежало **1 557 170 строк фандинга за 2022-2026** и три таблицы доминации.
**Фандинг ни разу не использовался в замерах именно потому, что по карте его не было.**
Исправлено: раздел «Отсутствует в RAW» разделён на «действительно нет» и «есть, но
🔌 NOT WIRED» с объёмами.

Урок: **сверять карту с БД, а не верить документу на слово.**

Связано: [[bus_sees_only_candles]], [[matrix_covers_six_percent]],
[[principle_reuse_not_duplication]], `docs/REGISTRY.md`.
