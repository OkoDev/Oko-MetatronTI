---
name: bug-ote-impulse-period5
description: "🔴 Root cause OTE-промаха: импульс от мелких свингов period=5, нужен period=50 (значимый)"
metadata: 
  node_type: memory
  type: project
  originSessionId: 9d582948-c9be-42e6-8444-4165a225d1fa
---

**🔴 Root cause найден 11.06.2026 (сверка с эталоном OKO-SM по XLM).**

**Симптом:** бот считает `current_retracement=105%`, `price_in_ote=False` для XLM, хотя на эталонном чарте OKO-SM (4h) цена ЧЁТКО в OTE golden pocket (откат 71.7%, между 0.705 и 0.79). Бот пропускает валидные bull OTE сетапы / готовит SHORT вместо LONG.

**Корень:** `core/smc/smc_snapshot.py:142` → `detect_structure(df)` БЕЗ `swing_period` → дефолт `swing_period=5` (`structure.py:344`). OTE-импульс = `sa.last_high`/`sa.last_low` = **ПОСЛЕДНИЕ два свинга от мелкого period=5**. Юзер сформулировал точнее: «бот видит ПОСЛЕДНИЙ импульс, а мы (трейдер) — значимый, 3 импульса назад». Двойная беда: (1) `last_` без фильтра значимости, (2) period=5 = рябь.

**ЗАМЕР подтвердил гипотезу** (`scripts/ote_impulse_check.py`, XLM 4h, ccxt bingx):
| | импульс | retracement | OTE 0.705 | dir |
|---|---|---|---|---|
| period=5 (бот) | 0.18463→0.21785 (мелкий, 44 свинга) | **100.8%** ❌ | 0.19443 | LONG |
| period=50 | 0.13955→0.29782 (майский, 6 свингов) | **71.7%** ✅ | 0.18624 | LONG |
| эталон OKO-SM | 0.13955→0.29763 | 71.7% | 0.18618 | LONG |

period=50 совпал с эталоном пиксель-в-пиксель. Оба LONG → bull OTE реален, бот промахивался ЗОНОЙ (не направлением).

**Контекст эталона:** в OKO-SM настройка swing length **ЕДИНАЯ для всех ТФ** (юзер). Динамичность по ТФ обсуждали как опцию на потом, пока — единый.

**Фикс (направление, НЕ катать наспех):** OTE-импульс брать от ЗНАЧИМЫХ свингов — `swing_period=50` (LuxAlgo major, как в `smc_engine` major_len=50) ИЛИ + фильтр амплитуды/BOS. period=5 оставить для structure breaks/CHoCH ([[calib_choch_length5]] — там 5 правильный). Разные нужды = разные period.

**⚠️ Меняет ВСЮ ote_nested** (раннеры SKYAI+40R, ONDO+27R — не сломать). ОБЯЗАТЕЛЕН бэктест period=5 vs period=50 ПЕРЕД катом. Связано: [[bug_zigzag_peak_dropped]], [[ote_nested_mtf_strategy]].

**🟢 УТОЧНЕНИЕ (важно!):** баг ТОЛЬКО в дашборд-снапшоте. РЕАЛЬНАЯ торговля (`ote_signal_generator` → `ote_retest_setups`, `smc_engine.py:799`) использует `zigzag_atr(depth=11, dev=3)` калиброванный под OKO-SM (ARCH-128 «метод пользователя») — НЕ period=5. Замер подтвердил: zigzag(11,3) для XLM нашёл МАЙСКИЙ импульс 0.13955→0.29782, OTE-зона (0.173-0.219), цена В зоне=True — как эталон. **Стратегия ЗДОРОВА, бэктест НЕ нужен.**

**= ДВА независимых OTE-калькулятора (дрейф):** zigzag(11,3) торгует ✅ ∥ detect_structure(period=5) дашборд ❌. Вотчлист микширует: ote_ltf теги (FIRE/ARMED) от zigzag (верно), а price_in_ote/retracement/OTE-armed от period=5 snapshot (баг 105%).

**ФИКС (безопасный, только отображение):** в `smc_snapshot.py` OTE-блок (price_in_ote/current_retracement/ote_direction, строки ~205-246) заменить `detect_structure(period=5)` импульс на `ote_retest_setups(zigzag 11/3)` — тот же что генератор. Унификация одного калькулятора ([[principle_reuse_not_duplication]], тема централизации юзера). Торговлю НЕ трогать.

**Найдено через:** сверку дашборда (вотчлист OTE) с живым чартом XLM OKO-SM. Дашборд окупился — выявил рассогласование двух OTE-расчётов. `scripts/ote_impulse_check.py` — замер period5/period50/zigzag/эталон.
