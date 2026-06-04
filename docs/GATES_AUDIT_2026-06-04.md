# Аудит гейтов регистрации сделок — находки 04.06.2026

> Собрано в ходе подключения OTE-движка (ARCH-128). Гейты вскрывались по `signal_drops`
> и чтению кода. **Это база для отдельного БОЛЬШОГО аудита** — много технического долга
> и скрытых гейтов, раскиданных по `register_trade_async` inline (комментарий в коде:
> «Cleanup Этап 1.Е перенесёт всю эту логику в core/trading/gates/»).

---

## 1. Полный путь сигнала → регистрация

```
ote_observer/_register_ote_trade (или arch104_observer/_try_register_vst_trade)
  → bot.trade_router.submit(rec, source="ote_nested"/"arch104")   [signal_router.enabled=true]
    ├── HARD gates (router)        — любой drop → POSITION_DROPPED, return
    ├── SOFT gates (router)        — для ote/arch104 = soft_gates_enabled:[] ОТКЛЮЧЕНЫ
    ├── min_strength check (router) — strength < policy.min_strength(40) → drop
    └── register_trade_async       — СВОИ внутренние гейты (≥10 штук!)
        → exchange placement (если live + strength≥min)
```

**КЛЮЧЕВОЕ:** два независимых слоя гейтов — router (core/trading/gates/) И register_trade_async
(inline в trade_simulator.py). Часть гейтов ДУБЛИРУЕТСЯ, часть есть только в register.

---

## 2. Router HARD gates (core/trading/gates/)

| Гейт | Порог | Файл |
|---|---|---|
| ValidateInputs | поля не None | validate_inputs.py |
| DedupOpen | symbol + trade_mode | dedup_open.py |
| SlCooldown | 1ч после SL по паре | sl_cooldown.py (`signal_quality.sl_cooldown_hours`) |
| MinSlDist | SL ≥ 0.3% | min_sl_dist.py (`trading.min_sl_dist_pct`) |
| RrFilter | RR ≥ 2.0 строго | rr_filter.py (`trading.min_rr_ratio`) |

Router SOFT gates (7, для ote/arch104 ОТКЛЮЧЕНЫ через `soft_gates_enabled:[]`):
strength_threshold, regime_safety, btc_market, time_gate, correlation_guard, market_stress, pair_cooldown_streak.

---

## 3. register_trade_async ВНУТРЕННИЕ гейты (trade_simulator.py) — СКРЫТЫЙ СЛОЙ

Не видны в первом аудите router'а. Порядок выполнения:

| # | Гейт | Условие drop | Строка | Статус |
|---|---|---|---|---|
| 1 | input checks | no_entry / neutral_dir / no_sl_tp | ~331 | — |
| 2 | **dedup** | symbol + trade_mode совпал | ~358 | ⚠️ cross-mode дыра (см. §5) |
| 3 | DEV-14 corr_guard | open_count ≥ max_positions_per_direction | ~404 | ✅ ОТКЛЮЧЁН (`max_per_dir=0`) |
| 4 | DEV-157/164 MinSlDist | sl_dist% < 0.3% | ~459 | 🔁 ДУБЛЬ router |
| 5 | **rr_filter** | RR < 2.0 | ~474 | 🔁 ДУБЛЬ router |
| 6 | **DEV-64A RR-cap** | RR > 3.0 → take_profit обрезается | ~732 | 🔴 резал OTE runner → мизерный TP |
| 7 | **DEV-44 blocked_regime** | regime ∈ [HIGH_VOL], не в exceptions | ~1087 | 🔴 блокировал OTE в HIGH_VOL |
| 7b | DEV-44 regime_direction | rdb.enabled & rdb[regime]==dir | ~1093 | ✅ off (`regime_direction_block.enabled=false`) |
| 7c | DEV-64B signal_regime_block | signal_type×regime в списке | ~1100 | ote/arch104 не в списке |
| 8 | **DEV-155 min_strength** | strength < eff_min(regime) | ~1145 | словари пусты → порог 50 |
| 9 | DEV-98 | pivot_reversal strength≥80 | ~1155 | только pivot_reversal |
| 10 | apply_regime_to_strategy | DUAL_TP/TSL по regime; RANGE→SINGLE | ~768 | 🔴 RANGE-мислейбл влияет на TP/SL |

---

## 4. 🔴 КОРНЕВАЯ ПРОБЛЕМА: regime «прячется» в register (ARCH-124 не довершён)

```
trade_simulator.py:1004  regime = MarketRegimeClassifier().classify_from_ohlcv(ohlcv)
```
ARCH-124 свернул regime-ГЕЙТ в scan/сигналах, НО `register_trade_async` независимо
гоняет классификатор на КАЖДОЙ регистрации. RANGE/HIGH_VOL живут здесь и влияют на:
- DEV-44 блок (HIGH_VOL)
- DEV-155 min_strength_by_regime (сейчас пусто)
- DEV-64A RR-cap (max_rr_range для RANGE)
- apply_regime_to_strategy: RANGE→DUAL_TP/SINGLE, TREND→DUAL_TSL

**RANGE-мислейбл (78% по ARCH-124) → ненадёжный regime навешивает стратегию/cap/блок.**
OTE обошёл через exceptions (DEV-44, DEV-64A), но apply_regime_to_strategy ещё влияет
(SINGLE форсится для ote — частично закрыто).

---

## 5. ⚠️ ДВОЙНАЯ ЭКСПОЗИЦИЯ: arch104 + ote_nested не дедупятся

```
dedup_open + register dedup: блок ТОЛЬКО при совпадении trade_mode
arch104 trade_mode='arch104' ≠ ote_nested trade_mode='ote_nested'
→ обе МОГУТ открыть позицию на ОДНОЙ паре в ОДНОМ направлении
→ 2× риск (1R+1R = 2R на пару), концентрация
факт 04.06: ULTIMA LONG уже с обеими открытыми; после рестарта arch104 (200 патт) — массово
```
**Вопрос для аудита:** нужен cross-mode dedup ИЛИ лимит позиций на пару (независимо от mode)?
`max_positions_per_direction` отключён (=0) — глобальной защиты концентрации НЕТ.

---

## 6. Дубли и долг

- **rr_filter ×2** (router gate + register inline ~474) — одинаковая формула, два места.
- **MinSlDist ×2** (router + register ~459).
- **DEV-44/64A/155/98** — inline в register, комментарий обещает вынос в gates/ (Этап 1.Е). Не сделано.
- **corr_guard** отключён (max_per_dir=0) — защита концентрации утеряна (компенсируется?).

---

## 7. signal_drops статистика (7 дней, что реально режет)

```
dedup                    29277  (в осн. liquidity_sweep — много дублей по символу)
strength_too_low          2518  (scan-prefilter, до router)
arch104_d051_no_wt_cross  1196  (спец-gate arch104 — wt_cross обязателен)
dedup_open                1175
validate_inputs            553
rr_filter                  427  (режет даже RR=2.00 — строгое <)
below_min_strength         372
register_returned_none     332  (внутренние гейты register, в т.ч. DEV-44)
sl_cooldown                237
```

---

## 8. Что сделано для OTE в эту сессию (фиксы-exceptions)

- `ote_nested` в `blocked_regimes_exceptions` (DEV-44 обход HIGH_VOL).
- `ote_nested` исключён из DEV-64A RR-cap (runner полный, не 3R).
- `ote_nested` → `strategy_type=SINGLE` (без частичного TP1, живёт по TSL; DEV-124: SINGLE +1866R).
- RR-скип заранее в генераторе (не плодить мёртвый FIRE в rr_filter).

---

## 9. 🔴 ОТКРЫТЫЕ ВОПРОСЫ ДЛЯ БОЛЬШОГО АУДИТА

1. **Cross-mode dedup / лимит на пару** — arch104+ote двойная экспозиция (§5). corr_guard off.
2. **regime прячется в register** (§4) — довершить ARCH-124: убрать/изолировать MarketRegimeClassifier из register или сделать regime-free путь для всех.
3. **Дубли rr_filter/MinSlDist** (§6) — консолидировать router vs register.
4. **Вынос DEV-44/64A/155/98 в gates/** (Этап 1.Е долг) — сейчас inline, трудно аудировать.
5. **apply_regime_to_strategy на ненадёжном RANGE** — DUAL_TP/TSL по мислейбл-режиму.
6. **Порядок гейтов** — router→register двойной проход, часть проверок дважды (лишний расчёт).
7. **min_strength_by_regime пусто** — DEV-155 спит, но комментарий «HIGH_VOL=85/LONG_RANGE=75» намекает на план. Решить: включать или удалить.

---

**Связь:** `memory/arch124_regime_audit.md` (regime мислейбл), `memory/ote_trade_edits_data_era.md`
(эры сделок), `core/trading/trade_router.py`, `core/trading/trade_simulator.py`, `core/trading/gates/`.
