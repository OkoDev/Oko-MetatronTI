---
name: signal_health_map_18jun
description: "Карта здоровья сигналов 18.06 на ЧЕСТНОМ R (после fake-R фикса). ote_nested+arch104 SHORT зарабатывают, arch104 LONG+atr_change 15m сжигают"
metadata: 
  node_type: memory
  type: project
  originSessionId: 01a80823-46cc-4251-9bdf-bf45da105c68
---

🗺️ **КАРТА ЗДОРОВЬЯ СИГНАЛОВ (18.06.2026, честный clamp R после [[bug_phantom_exit_resolve]])**

Контекст: реальный equity упал −63% за неделю ($849→$312). Разбор показал — не «всё сломано», а 2 канала несут, 2 сжигают.

| Сигнал | n | avgR | WR | $net | вердикт |
|---|---|---|---|---|---|
| 🟢 ote_nested | 2551 | +0.748 | 60% | +$289 | КОРМИЛЕЦ, усилить |
| 🟢 arch104 SHORT | 2890 | +0.155 | 52% | +$1.5 | рабочий (UP +0.212) |
| 🔴 arch104 LONG | 1273 | −0.162 | 41% | −$32 | ОТКЛЮЧИТЬ |
| 🔴 atr_change 15m | 1056 | −0.014 | 42% | минус | edge<комиссий → 4h |

**ote_nested = доказанная MTF-машина** (НЕ «только 15m» — это ТФ исполнения; OTE-зона на 1h/4h, триггер 5m, фаза 4h в `features.ote_htf/ote_ltf/ote_setup_id`). Иерархия качества:
- ТИП: **pull +0.895** > cont +0.685
- TIER: **tier1 +1.027** > tier2 +0.684
- HTF: 4h +0.764 ≈ 1h +0.743
- Чемпион setup: **4h_1h_pull +1.230 WR78%** (n=36); 1h_5m_pull +1.029; 4h_5m_pull +1.024.

**arch104 LONG мёртв ВЕЗДЕ:** LONG в UP −0.194 / в DOWN −0.144 (WR 41% оба); паттерны DS_L052_bullfv −0.139, DS_L082 −0.278. Контр-тренд НЕ причина. **arch104 SHORT** жив (UP +0.212, DOWN +0.038). Совпало с памятью ARCH-104 «SHORT S1-S8 устойчивы».

**ПЛАН ОЗДОРОВЛЕНИЯ:** (1) отключить arch104 LONG; (2) отключить atr_change 15m (→4h после валидации, [[atr_change_tf_4h_backlog]]); (3) усилить вес ote_nested pull/tier1 + arch104 SHORT. ⚠️ ВАЖНО: adaptive weights учились на fake-R → возможно усиливали мусор. После миграции [[bug_phantom_exit_resolve]] веса переучатся.

**🌊 ВОЛНА × сигналы (18.06, n_down/n_up 4h на момент сделки, no lookahead — reuse calculate_n_down/up period=5):**
- arch104 LONG минусит во ВСЕХ волновых фазах (−0.17 при n_dir 0-1, −0.06 при 2-3) → волна НЕ спасает, резать.
- arch104 SHORT ЧЕМПИОН при n_dir **4+** (зрелый 4h-импульс вниз): **+0.279 WR56%** (n=439) vs общий +0.146. Тренд-следование!
- atr_change мёртв во всех фазах (−0.01..−0.11) → подтверждает off 15m.
- ⚠️ ЗЕРКАЛЬНОСТЬ как у пивотов: для arch104 SHORT (ТРЕНД) n_dir≥4 = ЛУЧШЕ; для ote cont (РАЗВОРОТ) n_dir≥3 = ЛОВУШКА ([[atr_change_ote_insight]] phase-gate). Волновой гейт ДОЛЖЕН знать тренд vs разворот.
- arch104/atr_change НЕ пишут phase_* в features (только ote_nested) → дать волну = добавить calculate_n_down/up в их генерацию.

**🎯 ПИВОТЫ × природа сигнала (18.06, бэктест+БД):** связь с PPW/PPD ЗЕРКАЛЬНА для тренда vs разворота:
- atr_change (тренд-следящий, trend-flip): на **1h** PPW-gate работает — согласован (над=LONG) +0.115 vs против −0.023 (n=347/335). На 15m/4h нет/шум. PPD слабее.
- ote_nested (разворотный, n=2552/429 пар, честный R): ЧЕМПИОН = **SHORT над уровнем** (PPW +1.126 WR71% / PPD +1.073 WR70%). Все срезы +. LONG слабее (над PPD +0.646). Логика: откат от сопротивления.
- ВЫВОД: единый PPW-фильтр «над=LONG» НЕ универсален — верен для тренда, ОБРАТЕН для разворота. Гейт должен знать природу сигнала.

Связь: [[atr_change_tf_4h_backlog]], [[bug_phantom_exit_resolve]], [[ote_nested_mtf_strategy]], [[gravity_rocket_mtf_validated]], [[mtf_weight_hierarchy_universal]].
