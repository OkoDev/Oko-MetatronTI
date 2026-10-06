---
name: bug_fvg_overlap_survivorship_held
description: "🔴 Третий look-ahead в FVG-семье: detect_fvg_overlap брал только НИКОГДА не митигированные FVG (survivorship) + held проверял до КОНЦА истории. Давал WR 92% PF 68 на 15m. Починено"
metadata: 
  node_type: memory
  type: project
  originSessionId: 696399f2-16be-4ffc-97be-acad52cc3fb5
  modified: 2026-08-13T17:30:05.623Z
---

# 🔴🔴 FVG-OVERLAP: SURVIVORSHIP + `held` ДО КОНЦА ИСТОРИИ (13.08.2026)

Пойман на перемере 15m-паттернов arch104: топы показали **WR 89–92%, PF 49–71,
+4.49%/сд** — те же невозможные числа, что были у смещённого флага
([[bug_fvg_flag_shifted_two_bars]]). Все топы стояли на `bull_fvg_overlap_15m` /
`bull_fvg_overlap_held_15m`. Второй красный флаг: весь результат лежал в ОДНОМ 2026 году.

## Два look-ahead в одной функции

`core/smc/smc_engine.py::detect_fvg_overlap` (было):
```python
for bu in [f for f in bulls if f[5] is None]:            # (1) SURVIVORSHIP
    held = all(close[j] >= lo for j in range(i0+1, n))   # (2) до КОНЦА данных
```
1. `f[5]` = бар митигации. Условие `is None` = «FVG не был закрыт **за всю оставшуюся
   историю**». Зона попадала в набор за то, что ВЫЖИВЕТ в будущем.
2. `held` на баре `since` утверждал, что цена **никогда** не закроется за границей зоны.

## 🔑 МЕТОДОЛОГИЧЕСКИЙ УРОК: тест видимости их НЕ ловит

`scripts/flags_realtime_visibility.py` спрашивает «виден ли флаг на своём баре» и ловит
ЗАПАЗДЫВАЮЩИЕ флаги (FVG лаг 2, OTE лаг >20). Здесь ошибка ЗЕРКАЛЬНАЯ — флаг-**выживший**:
при обрезке до своего бара он ЕСТЬ (будущего нет → не митигирован → проходит),
а в полном расчёте остаётся только если выжил. Тест считал такие случаи чистыми.

**Нужен тест в ОБЕ стороны:** не только «есть в полном, но нет в причинном» (запаздывание),
но и «есть в причинном, но ИСЧЕЗАЕТ в полном» (survivorship). Второе направление
в `flags_realtime_visibility.py` пока не реализовано — долг.

## Фикс
- активность FVG проверяется **на момент бара обнаружения**: `pos[f[5]] > i0`
  (митигация позже — не наше знание);
- `held` считается на КОНЕЧНОМ окне `hold_bars=5` и возвращается вместе с `held_ts`
  = `since + hold_bars` — баром, где удержание становится известно;
- `etl_fvg_overlap` ставит флаг `*_overlap_held` на `held_ts`, а не на `since`.

Регрессий нет: 59 passed (SMC + narrative + arch104_integration + контракт FVG).

## Счёт по FVG-семье: три бага, все причинные

| # | где | суть | статус |
|---|---|---|---|
| 1 | `swing_bridge.etl_fvg` | флаг на баре i−2 вместо i (`f[0]` вместо `f[4]`) | ✅ починен |
| 2 | `swing_bridge.etl_ote_premium` | одна зона от последнего CHoCH на всю историю | ✅ починен |
| 3 | `smc_engine.detect_fvg_overlap` | survivorship + `held` до конца данных | ✅ починен |
| 4 | `smc_engine.detect_fvg` | авто-порог `threshold` по всему df | ⬜ НЕ починен (меняет отбор везде) |
| 5 | `smc_engine.ote_retest_setups` | 35.4% сетапов не существуют причинно (zigzag) | ⬜ НЕ починен |

Связано: [[flags_realtime_lag_audit]], [[arch104_remeasured_causal_fvg]],
[[law_recorded_pf_needs_remeasure]] — «PF 49–71» обязан был вызвать подозрение сразу.
