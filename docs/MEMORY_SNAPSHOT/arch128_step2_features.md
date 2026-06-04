---
name: arch128-step2-features
description: "ARCH-128 Шаг 2 (03.06.2026): новые эталонные поля в features_json/trade_features — fvg_overlap, elliott, regime ТРОИЧНЫЙ, ob_mitigated. schema_version 2→3 (data-era граница, backfill невозможен). Все через smc_engine bridge ETL (один калькулятор)."
metadata:
  node_type: memory
  type: project
  originSessionId: 9d582948-c9be-42e6-8444-4165a225d1fa
---

# ARCH-128 Шаг 2 — новые поля снимка (семантика)

Коммит 58b9088. ETL в `tools/pattern_mining/swing_service_bridge.py` (поверх DS-313/314),
подключены в `combinator_v2.compute_flags`. Домен снимка = **smc**. schema_version **2→3**
(новое = новая data-era, старые сделки этих полей НЕ имеют — backfill невозможен).

## Новые признаки (что значат, в какой момент true)

| Поле | Значение | Когда true |
|---|---|---|
| `bull/bear_fvg_overlap` | bull-FVG перекрыл bear-FVG (или наоборот) = зона разворота | на баре формирования overlap |
| `bull/bear_fvg_overlap_held` | overlap-зона удержалась на откате (подтверждение) | overlap + цена не закрыла за границей |
| `elliott_bull/bear_impulse` | завершённый 5-волновой импульс (флаг на баре волны 5) | ⚠️ ПОСТФАКТУМ |
| `elliott_textbook` | фибо-соотношения волн в норме (сильная разметка) | импульс + textbook=True |
| `regime_bull/range/bear` | рыночный РЕЖИМ — ТРОИЧНЫЙ контекст | последний слом (ZigZag) + не equilibrium |
| `regime_dir` | числовой канон режима **+1/0/−1** (для ML) | всегда (value-колонка) |
| `bull/bear_ob_mitigated` | OB пробит/митигирован | на баре пробоя блока |

## 🔴 Нюанс elliott — ПОСТФАКТУМ
`detect_elliott_impulse` использует **extension волны 5** (lookforward — данные ПОСЛЕ конца импульса).
`snapshot_features_at` берёт срез ДО entry (independent-last, без lookahead) → elliott на entry-снимке
**не созревает**. Полезен для **бэктеста** (полные данные), для live-снимка почти всегда false.
regime + fvg_overlap — полноценно на entry (не требуют будущего).

## regime троичный — источник
Канон рынка ↑↓→ ([[market-three-directions]]). regime по последнему слому ZigZag-структуры
(`find_setups_zz`, чувствительнее swing-50) + equilibrium-зона Premium/Discount → range/0.
Канон направления DS-314 (bull/range/bear, +1/0/−1).

## Дальше: Шаг 3 — ре-майнинг 187 паттернов на эталонных признаках (+regime +fvg_overlap)
→ [[arch128-detector-parity]] (карта), [[arch118-snapshot-decision]] (хранилище).
