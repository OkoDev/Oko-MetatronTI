# Легенда `tp_source` — расшифровка магнитов TP

> Поле `tp_source` (и `sl_source`) в `simulated_trades` + `tp_selector_tp1_label`/`tp2_label` в features_json.
> Формат: `источник1+источник2+...@цена_кластера`. Чем больше источников — тем сильнее кластер (gravity).

---

## Токены источников магнитов (TPSelector, ARCH-113 + ARCH-122)

| Токен | Источник | Вес | TF/откуда |
|-------|----------|-----|-----------|
| `fvg_5m` | Fair Value Gap 5m | 2.0 | SMC Sub-куб |
| `fvg_15m` | Fair Value Gap 15m | 3.0 | SMC Sub-куб |
| `fvg_1h` | Fair Value Gap 1h | 4.0 | SMC Sub-куб |
| `fvg_4h` | Fair Value Gap 4h | 5.0 | SMC Sub-куб |
| **`ob`** | **Order Block** (midpoint) | 3.5 | SMC Sub-куб (ARCH-122) |
| **`eqh`** | **Equal Highs** (ликвидность сверху) | 3.0 | SMC Sub-куб (ARCH-122) |
| **`eql`** | **Equal Lows** (ликвидность снизу) | 3.0 | SMC Sub-куб (ARCH-122) |
| **`fib_ext`** | **Fibonacci extension** (1.272/1.618) | 2.5 | SMC Sub-куб (ARCH-122) |
| `pdh` | Prev Day High (R1 1D прокси) | 3.0 | Pivot |
| `pdl` | Prev Day Low (S1 1D прокси) | 3.0 | Pivot |
| `pwh` | Prev Week High (R1 1W прокси) | 4.0 | Pivot |
| `pwl` | Prev Week Low (S1 1W прокси) | 4.0 | Pivot |
| `swing` | Swing High/Low | 2.5 | SMC структура |
| `psycho` | Психологический круглый уровень | 2.0 | расчёт |
| `std_r2` / `std_s2` | Pivot R2/S2 | 1.0 | Pivot |

**Жирным** — добавлены в ARCH-122 (30.05.2026).

---

## Примеры чтения

```
eqh+fvg_1h+ob@0.00621765
└┬┘ └─┬──┘ └┬┘ └────┬────┘
 │    │     │       └─ цена кластера (взвешенный центр)
 │    │     └───────── order block
 │    └─────────────── FVG на 1h
 └──────────────────── equal highs (пул ликвидности)
= ТРОЙНОЙ кластер (gravity = 3.0+4.0+3.5 = 10.5) → сильная цель
```

| Метка | Прочтение |
|-------|-----------|
| `psycho@89` | одиночный психоуровень (слабый) |
| `fvg_1h+psycho@90.18` | FVG + психо (умеренный) |
| `eqh+fvg_1h@0.2544` | ликвидность + FVG |
| `eqh+fvg_1h+ob@0.0062` | ликвидность + FVG + OB (сильный) |

---

## Другие `tp_source` (НЕ TPSelector — fallback пути)

| Значение | Откуда |
|----------|--------|
| `pivot_1D:S1` / `pivot_1D:R2` | pivot-иерархия (get_pivot_tp / get_next_tp_by_hierarchy) |
| `atr_rr_3.0` | ATR fallback (RR=3.0) |
| `tsl_only` | сделка без фикс TP (TSL трейлит) |
| `range_bounce_pivot` | RANGE BOUNCE стратегия |
| `...|capped_rr_2.5` | суффикс — TP обрезан max_rr cap |

---

## ⚠️ Важно: магниты пока только у TP1

| Уровень | Источник цены | Метка магнита? |
|---------|--------------|----------------|
| **tp1** | TPSelector магниты | ✅ да (`tp_source`) |
| **tp2** | pivot-иерархия (`get_next_tp_by_hierarchy`) | ❌ нет (TPSelector tp2 вычислен, но в `tp2_price` идёт pivot) |
| **TSL** | ATR/swing трейл (cascade 15m→1h→4h) | ❌ магниты не участвуют |

→ Унификация tp2/TSL на магниты = **ARCH-122 Часть 1** (Exit Manager сфера).
`tp_selector_tp2_label` в features_json показывает что TPSelector ВЫБРАЛ БЫ для tp2 (shadow).

---

## Связанные

- `core/smc/tp_selector.py` — `_WEIGHTS`, `_collect_magnets`, `_magnets_from_snap`
- `core/smc/sub_cube.py` — SMC Sub-куб (источник OB/FVG/EQH/Fib)
- TASKS.md → ARCH-122, ARCH-120, ARCH-113
