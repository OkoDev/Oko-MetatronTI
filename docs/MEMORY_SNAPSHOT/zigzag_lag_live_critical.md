---
name: zigzag-lag-live-critical
description: "🔴🔴 КРИТИЧНО для LIVE-движка: zigzag последняя нога НЕ real-time — pivot подтверждается через depth//2 баров СПРАВА (lookforward). На 4h (depth=11) лаг=5 баров=20ч! Цена пробила last-low на 7.86%, а zigzag держит старое дно → OTE на свежем импульсе устаревает → движок СЛЕП к текущему движению (не поймал обвал XLM). Пользователь нашёл 04.06. Решение: provisional last leg (текущий rolling-экстремум как unconfirmed pivot)."
metadata:
  node_type: memory
  type: project
  triggers:
    - zigzag_atr / OTE-зона / live генерация / последняя нога
    - лаг подтверждения pivot / real-time структура
    - движок не видит текущий слом/импульс
    - provisional leg / unconfirmed pivot
  originSessionId: 9d582948-c9be-42e6-8444-4165a225d1fa
---

# 🔴🔴 zigzag НЕ real-time на последней ноге (критично для live)

**Находка пользователя 04.06 (XLM 4h live):** zigzag последняя нога не дорисовывается
в реальном времени, даже когда цена пробила предыдущий экстремум.

## Доказательство (XLM 4h)
```
последняя zz-точка: L=0.215 (9 баров назад)
цена пробила до 0.1981 = −7.86% НИЖЕ
zigzag ВСЁ ЕЩЁ держит 0.215 — новая нога вниз НЕ дорисована
лаг: ~5 баров (depth//2) = 20ч на 4h до подтверждения
```

## Корень
`zigzag_atr`: pivot подтверждается через `length=depth//2` баров СПРАВА (lookforward для
разворота). На истории не важно (есть будущие бары). В LIVE последняя нога ВИСИТ
неподтверждённой → структура отстаёт на depth//2 баров (4h=20ч, 1h=4ч, 15m=...).

## 🔴 Влияние на движок (КРИТИЧНО)
OTE-зоны строятся на zigzag-импульсах (find_setups_zz). Последний/актуальный импульс
НЕ виден до подтверждения → движок работает с УСТАРЕВШЕЙ OTE-зоной → СЛЕП к текущему
движению. Поэтому live-генератор не поймал обвал XLM (zigzag не дорисовал ногу вниз).
Опаснее лага detect_structure_breaks — OTE = ЯДРО входа.

## РЕШЕНИЕ: Provisional Last Leg (живая нога)
```
zigzag(подтверждённые) + ТЕКУЩИЙ формирующийся экстремум:
  от последней zz-точки до now → rolling min/max противоположного/нового типа
  → дорисовать как provisional pivot, флаг unconfirmed=True
движок: OTE на провизорной ноге = свежая зона, но риск выше (помечена unconfirmed)
```
Альтернативы: меньший depth на конце; real-time pivot по close-пробою (без lookforward);
комбо с detect_structure_breaks(length=5) для свежего конца.

## ✅ РЕШЕНИЕ ПРОВЕРЕНО (прототип `e:/tmp/prov_leg.py`, XLM 1h live)
Provisional leg: zigzag(подтв.) + текущий экстремум (rolling min/max после последней zz-точки)
как unconfirmed pivot → find_setups_zz → СВЕЖИЙ сетап.
**Результат: движок построил SHORT OTE [0.21625..0.22678] = эталон OKO-SM, ВСЕ 6 фибо совпали:**
```
0.0=0.1981 0.5=0.21625 0.62=0.22061 0.705=0.22369 0.79=0.22678 1.0=0.2344  ← все ✅ vs OKO-SM
```
Без provisional: 12 сетапов (свежий SHORT пропущен). С provisional: 13 (свежий пойман, цена в зоне).
Подтверждено: provisional last leg даёт движку real-time зрение = эталон Pine.

## NEXT (реализация)
1. Встроить provisional last leg в `ote_retest_setups`/генератор: после zigzag добавлять
   текущий формирующийся экстремум как unconfirmed pivot ПЕРЕД find_setups_zz.
2. Флаг `unconfirmed=True` на сетапе из provisional-ноги (риск выше — pivot не подтверждён).
3. Бэктест: provisional vs confirmed — ловит свежие движения без лага, не плодит ложные.

Связь: [[bug-zigzag-peak-dropped]] (тоже zigzag), [[calib-choch-length5]] (лаг detect_structure_breaks),
[[ote-nested-mtf-strategy]] (движок), [[reference-oko-sm-indicator]]. smc_engine.zigzag_atr.
