# ARCH-95 — Полные результаты аудита торговой системы

**Дата:** 25-26.04.2026
**Автор:** ARCH (Claude)
**Покрытие:** 1379 закрытых сделок post-fix эры (created_at >= 15.04.2026)
**Цель:** установить корневые причины убыточной торговли (WR 10.4%, avgR −0.27)

> Главный вывод: торговая система имеет **двойное пробитие** — на входе (поздние входы режут 50% потенциала) и на выходе (TSL+BE ломаются у 70% активаций). Точечные фиксы одной стороны не починят систему.

---

## 1. Контекст и методология

### 1.1. Почему запущено расследование

Депозит уходит на SL-ах. WR ~10% на 1379 закрытых сделках post-fix (15.04 — 26.04). Все signal_type убыточны. Запрос пользователя: найти корень проблемы данными, не предположениями.

### 1.2. 7 гипотез

| ID | Гипотеза | Скрипт |
|---|---|---|
| H1 | Поздние входы — сигнал на close 15m, импульс уже произошёл | [audit_entry_timing.py](../scripts/audit_entry_timing.py) |
| H2 | Тесный SL после позднего входа | [audit_entry_timing.py](../scripts/audit_entry_timing.py) |
| H3 | Pivot direction несогласован (LONG у R, SHORT у S) | [audit_pivot_direction.py](../scripts/audit_pivot_direction.py) |
| H4 | Куб не замкнут — smc_verdict ≠ narrative ≠ факт | [audit_cube_snapshots.py](../scripts/audit_cube_snapshots.py) |
| H5 | Detector price ≠ entry price (slippage) | [audit_slippage_mtf.py](../scripts/audit_slippage_mtf.py) |
| H6 | MTF alignment не работает | [audit_slippage_mtf.py](../scripts/audit_slippage_mtf.py) |
| H7 | Адаптивные веса инерционны | [audit_signal_performance_ema.py](../scripts/audit_signal_performance_ema.py) |

Дополнительно — Слой A (TSL механика): [audit_tsl_efficiency.py](../scripts/audit_tsl_efficiency.py) + ручной разбор кода.

### 1.3. Coverage features_json (Слой B — валидация)

| field | cov % | first_seen | вердикт |
|---|---|---|---|
| atr_trend_1h_bias | **99.3%** | 15.04 09:12 | ok — выводы H6 валидны |
| weekly_bias | 97.2% | 15.04 | ok |
| rr_at_entry | 90.6% | 15.04 | ok |
| wt1_value / wt_zone | 88.0% | 15.04 | ok |
| mtf_* (5 полей) | 70.4% | 15.04 | ⚠️ нижняя граница |
| distance_to_pivot_pct | 67.7% | 15.04 | ⚠️ |
| entry_priority | 63.7% | 15.04 | ⚠️ |
| **btc_4h_regime** | **45.3%** | **17.04** | 🚩 нельзя использовать |

Выводы из полей с покрытием ≥70% статистически валидны. `btc_4h_regime` появилось 17.04 — на нём НЕ строить решений.

---

## 2. Базовая статистика post-fix

### 2.1. По signal_type

| signal_type | n | WR% | avgR |
|---|---|---|---|
| pivot_reversal | 858 | 10.8% | -0.27 |
| watch_list_breach | 273 | 10.6% | -0.34 |
| confluence | 80 | 3.8% | -0.92 (выключен) |
| wt_b_signal | 49 | 8.2% | -0.43 |
| wt_signal | 29 | **3.4%** | **-0.88** |
| mtf_bias | 20 | 15.0% | -0.17 |
| trend_signal | 12 | 8.3% | -0.55 |

### 2.2. По regime — все убыточны

| Режим | n | WR% | avgR |
|---|---|---|---|
| RANGE | 473 | 3.6% | -0.31 |
| HIGH_VOL | 228 | 3.9% | -0.28 |
| TREND_UP | 287 | 2.4% | -0.59 |
| TREND_DOWN | 209 | 2.9% | -0.69 |

### 2.3. Strength не работает как фильтр

| Бакет | n | WR% | avgR |
|---|---|---|---|
| <60 | 141 | 0.7% | -0.48 |
| 60-65 | 190 | 3.7% | -0.33 |
| 70-75 | 162 | 1.9% | -0.24 |
| **80+** | **428** | **4.0%** | -0.39 |

Корреляция strength→исход отсутствует. Поднимать `min_strength_register` бессмысленно.

---

## 3. ПОЛОМКИ ПО ВХОДАМ

### A1. Поздние входы — поток (H1+H3 ✅ ПОДТВЕРЖДЕНО)

**pivot_reversal — distance_to_pivot_pct vs исход:**
| dist_to_pivot | n | avgR | WR% |
|---|---|---|---|
| <1% (свежий) | **7** | **+1.13** | 14.3% |
| ≥1% (поздний) | **699** | **-0.39** | 9.7% |

7 сделок ≤1% дали +1.13R. 699 сделок при 1.5–6% дали −0.39R. **Граница чёткая.** Триггер близости 0.5% в коде [pivot_reversal.py:48-50](../core/pivots/pivot_reversal.py#L48-L50) фактически не работает в production — `pivot_proximity_hard` блокирует только 2 из 908 сделок. Где-то downstream proximity не применяется.

**Распределение по статусу (pivot_reversal):**
| status | n | dist_to_pivot p50 | mean |
|---|---|---|---|
| SL | 637 | 4.32% | 5.64 |
| TSL | 42 | 3.53% | 6.44 |
| TP | 27 | 3.79% | 5.02 |

SL median=4.32%, WIN median=3.57%, Δ=+0.75% — поздние чаще закрываются SL.

### A2. WT_SIGNAL входит ВНЕ зоны OS/OB (H1 ✅ ПОДТВЕРЖДЕНО)

Триггер требует `wt1 < -60` (LONG) или `wt1 > +60` (SHORT). Реальные значения wt1 на момент входа:

| direction | status | n | wt1 p50 | wt1 mean | эталон |
|---|---|---|---|---|---|
| LONG | SL | 6 | **−15.6** | −14.0 | < −60 |
| LONG | TP | 1 | +5.2 | +5.2 | < −60 |
| SHORT | SL | 61 | **+32.7** | +39.0 | > +60 |
| SHORT | TP | 3 | +3.2 | +18.3 | > +60 |

Стратегия открывает позиции когда WT уже отыграл зону. WR=3.4%, avgR=−0.88 — прямое следствие.

**Гипотезы:**
- `wt1_value` пишется в features_json post-factum (после регистрации сделки), когда WT уже сместился
- Триггер `wt1_last < _os_gate` в [signal_checkers.py:234](../core/signals/signal_checkers.py#L234) не работает как заявлено
- `cross_up` детектится на бар-запоздавших данных (свеча уже закрыта, импульс прошёл)

**Действие:** найти call-chain, где формируется `wt1_value`, и где конкретно срабатывает condition. Добавить `wt1_at_detection` отдельным полем.

### A3. SL подменяется downstream (H3 ✅ ПОДТВЕРЖДЕНО)

[pivot_reversal.py](../core/pivots/pivot_reversal.py) рассчитывает tight SL = `level_price × (1 - 0.3%)` с источником `pivot_S1:0.3%`. **В БД `simulated_trades.sl_source` записаны 0 таких сделок.** Доминирует `atr_1.5` (664) и `atr_14` (131). Tight-SL логика пивотов не применяется нигде в production.

**Действие:** найти call-chain от `check_pivot_level_signal` до `register_trade_async`. Где-то sl/sl_source перезаписывается стандартным ATR-расчётом.

### A4. Куб незамкнут — MTF gate не фильтрует (H4 ✅ ПОДТВЕРЖДЕНО)

| Alignment | n | WR% | avgR | avgR при SL |
|---|---|---|---|---|
| ALIGNED | 413 | 10.7% | −0.52 | −0.96 |
| NEUTRAL | 413 | 8.5% | −0.41 | **−0.86** |
| MISALIGNED | 80 | 5.0% | −0.21 | −0.48 |

**NEUTRAL теряет МЕНЬШЕ чем ALIGNED при SL.** MTF gate подтверждает плохие входы — circular logic (Куб строит direction_bias на 15m данных → подтверждает тот же сигнал).

Дополнительно: 919 сделок имеют категорию "MTF не изменил" (multiplier не работает). bias_strength weak vs strong даёт WR 8.7% vs 10.8% — почти нет разницы.

### A5. atr_trend_1h_bias — единственный работающий gate (H6 ✅ ПОДТВЕРЖДЕНО)

| atr_1h gate | n | WR% | avgR |
|---|---|---|---|
| ALIGNED | 671 | **13.4%** | −0.22 |
| AGAINST | 661 | **7.0%** | −0.46 |

Простое условие `atr_trend_1h_bias == direction` отрезает 661 сделку с avgR −0.46. **Сокращает потери почти вдвое.** Покрытие 99.3% — статистика валидна.

**Парадокс двойного gate (MTF + atr_trend):**
| gate | n | WR% | avgR |
|---|---|---|---|
| BOTH_ALIGNED | 354 | 10.5% | -0.42 |
| ONE_ALIGNED | 235 | 11.5% | -0.20 |
| NONE_ALIGNED | 356 | 5.3% | -0.47 |

`BOTH_ALIGNED` (10.5%) **хуже** одиночного `atr_trend ALIGNED` (13.4%). MTF Куба портит atr-gate (подтверждение A4: circular MTF из 15m).

### A6. senior_matches gate выключен для не-MTF стратегий ✅

| matches | n | WR% | avgR |
|---|---|---|---|
| **0/3** | **431** | 8.1% | -0.39 |
| 2/3 | 370 | 8.1% | -0.42 |
| 3/3 | 150 | 12.0% | -0.29 |

**431 сделка (54% post-fix)** с 0/3 senior_matches — старшие ТФ ни один не согласен. Эталон требует ≥2/3. Gate работает только для signal_type=MTF_BIAS, остальные стратегии открываются без senior gate.

### A7. mtf_aligned_pct: эффект только в крайнем хвосте

| bucket | n | WR% | avgR |
|---|---|---|---|
| 50-65% | 431 | 8.1% | -0.39 |
| 65-75% | 297 | 8.4% | -0.40 |
| 75-85% | 156 | 5.8% | -0.34 |
| **≥85%** | **67** | **20.9%** | -0.41 |

≥85% даёт WR 20.9% — заметный пик, но выборка 67. Не статзначимо для построения hard gate.

### A8. Slippage НЕ корень (H5 опровергнута как driver)

Adverse slippage в среднем 0.01–0.05% — порядки меньше SL distance (1–2%). Только wt_b_signal: SL p50 +0.053% vs WIN +0.000%, малая выборка (n=10). У pivot_reversal slippage съедает 12% SL distance в среднем, p75=8.3% — усугубляет H2, но не корень.

### A9. EMA адаптивные веса актуальны (H7)

Per-signal_type EMA(50) post-fix не сильно отличается от full-history после фикса 15.04. Адаптивные веса корректно реагируют. Не источник проблемы.

---

## 4. ПОЛОМКИ ПО TSL

### B1. TSL fate — 70% активаций уходят в полный SL ✅ КАТАСТРОФА

Из 693 активированных TSL (50% post-fix):

| Исход | n | % от активаций |
|---|---|---|
| TSL exit | 96 | 14% |
| TP exit | 48 | 7% |
| **SL exit** | **488** | **70%** 🚩 |
| EXPIRED | 61 | 9% |

В сравнении с эталоном: TSL должен закрыть >80% активаций с avgR ≥ +0.5. Реально закрывает 14%. **Защита прибыли не работает.**

**Per signal_type ACT=1→SL:**
| signal_type | n SL | avg R |
|---|---|---|
| pivot_reversal | 331 | -0.59 |
| watch_list_breach | 85 | -0.37 |
| confluence | 24 | -0.95 |
| wt_b_signal | 16 | -0.18 |
| wt_signal | 16 | -0.58 |
| mtf_bias | 8 | -0.42 |

### B2. SINGLE strategy_type — НЕТ BE НИКОГДА ✅ КРИТИЧНО

[trade_simulator.py:1568-1570](../core/trading/trade_simulator.py#L1568-L1570):
```python
_be_trigger_r = (use_breakeven and not be_activated and current_r >= breakeven_activation_r)
_be_trigger_tp1 = (use_be_after_tp1 and not be_activated and tp1_hit_at is not None)
```

**Конфиг:** `use_breakeven: false`, `use_be_after_tp1: true`.

- `_be_trigger_r` всегда False (use_breakeven выключен)
- `_be_trigger_tp1` требует tp1_hit_at — для SINGLE tp1=None → всегда False

| strategy_type | n | tp1_set | tp1_hit | be_act |
|---|---|---|---|---|
| **SINGLE** | **654** | **0** | **0** | **0** |
| DUAL_TSL | 479 | 479 | 49 (10%) | 45 |
| DUAL_TP | 246 | 246 | 26 (11%) | 25 |

**SINGLE = НЕТ BE НИКОГДА.** 654 сделок (47% выборки) полностью без BE-защиты.

### B3. TP1 редко достигается даже у DUAL ✅ ПОДТВЕРЖДЕНО

Только 10–11% DUAL-сделок достигают TP1 (TP1=+1R слишком далеко). Из 488 ACT=1→SL:
- 71 (15%) когда-либо имели BE-защиту
- **417 (85%)** ушли в SL без какой-либо BE

**Парадокс:** TSL активируется при +1R, TP1=+1R — они конкурируют. Если TSL передвинул SL раньше чем цена коснулась TP1 → TP1 не считается hit → BE не срабатывает.

### B4. TSL не двигает БД stop_loss для sim-only ✅ БАГ КОДА

[trade_simulator.py:1980-2005](../core/trading/trade_simulator.py#L1980-L2005):
```python
_is_real_move = (
    _exch_order_id and tsl_price and _old_sl > 0
    and abs(tsl_price - _old_sl) / _old_sl * 100 >= _min_move
)
if _is_real_move:
    tsl_moved.append(...)
    # Обновляем stop_loss в БД
    _c.execute("UPDATE simulated_trades SET stop_loss=? WHERE id=? AND status='OPEN'", ...)
```

**БД-update обёрнут в `if _is_real_move`, требующий exchange_order_id.** Для sim_only сделок exchange_order_id=NULL → блок не выполняется → БД stop_loss остаётся изначальный atr_14.

| Группа ACT=1→SL | n | % |
|---|---|---|
| **exchange_order_id=NULL (sim)** | **182** | **37.3%** |
| exch_id есть, sl_id пусто | 21 | 4.3% |
| Полная связь с биржей | 285 | 58.4% |

**Логика SL hit check** в той же итерации использует `sl = trade["stop_loss"]` (старое значение) — но это нормально для cycle-based check (следующий цикл прочитает новый sl). **Проблема:** для sim_only БД never updates → следующий цикл читает то же старое значение.

### B5. sl_source подтверждает: 75% не получили перенос TSL ✅

| sl_source у ACT=1→SL | n | avg R |
|---|---|---|
| atr_1.5 (изначальный) | 325 | -0.60 |
| atr_14 (изначальный) | 39 | -0.36 |
| tsl_line (TSL применил) | 23 | -0.99 |
| wl_pivot_tsl_line:* | 41 | -0.16 to -0.32 |
| range_bounce:pivot | 9 | -2.44 |

**364 из 488 (75%)** ушли в SL с изначальным atr-source. TSL формула считалась, но stop_loss в БД — оригинал.

### B6. captured_R_pct — преждевременный TSL ✅ ПОДТВЕРЖДЕНО

| TSL exit bucket | n | avg R | captured % MFE |
|---|---|---|---|
| **1.0–1.5R (преждевр.)** | **27** | +1.17 | **46%** |
| 1.5–3.0R (норма) | 49 | +2.13 | 62% |
| 3.0–5.0R (хорошо) | 11 | +3.81 | 73% |
| 5.0+R (отлично) | 9 | +6.54 | 74% |

**28% TSL-выходов срабатывают сразу после активации.** Берём 46–62% от MFE — формула слишком чувствительна к шуму.

### B7. tsl_tf 15m доминирует у SL ✅

| status | 15m | 1h | 4h |
|---|---|---|---|
| TSL | 77 (+2.55) | 17 (+2.26) | 2 (+1.01) |
| **SL** | **838 (-0.92)** | 161 (-0.55) | 144 (-0.98) |
| TP | 28 (+4.87) | 9 (+4.38) | 11 (+4.43) |

**838 SL произошли когда tsl_tf=15m** — реактивный шумный TF. Cascade поднимает TF только в 30% случаев.

### B8. TSL формула слишком рыхлая ✅

SuperTrend(atr=43, factor=1.25) на 1h ставит линию entry-0.5..1% от текущей цены. Floor = entry × 0.997 (-0.3%). Даже когда TSL работает корректно (exchange-managed group): avg R = −0.57. **Защита срабатывает только при движении 3R+, на малых движениях TSL = no-op до floor.**

---

## 5. СВЯЗЬ ВХОД ↔ TSL — двойное пробитие

```
1379 закрытых сделок post-fix
│
├─ ВХОД (Слой 1: H1+H3)
│  ├─ 90% pivot_reversal входят на >1% от уровня → MFE мал (медиана 0.58R)
│  ├─ wt_signal входит вне OS/OB → реверс не отыгрывается
│  └─ MTF/Куб не фильтрует мусор
│
├─ 686 (50%) — даже не дошли до +1R
│   └─ ранний SL = поломка ВХОДА (-686R потерь)
│
└─ 693 (50%) — активировали TSL
   ├─ 96 (14%) TSL exit — берут 46-62% MFE
   ├─ 48 (7%) TP exit
   └─ 488 (70%) SL exit ← поломка ВЫХОДА (-488R потерь)
       ├─ 264 SINGLE без BE никогда
       ├─ 182 sim-only — TSL не пишет в БД
       ├─ 21 биржевая без SL_id
       └─ 21 DUAL без TP1 hit
```

**Каждое пробитие режет ~50% net денег. Точечный фикс одной стороны = 0 net эффекта.**

---

## 6. КОРНЕВЫЕ ПРИЧИНЫ — ранжированы по влиянию

| # | Причина | Влияние | Класс | Приоритет |
|---|---|---|---|---|
| 1 | TSL не пишет stop_loss в БД для sim-only | 182 сделки, потеря ~+150R | **БАГ КОДА** | 🔴 P0 |
| 2 | SINGLE без BE никогда (use_breakeven=false) | 654 сделки без защиты | **МИСКОНФИГ** | 🔴 P0 |
| 3 | sl_source подменяется (pivot:0.3% → atr_1.5) | tight SL не применяется | **БАГ КОДА** | 🔴 P0 |
| 4 | TSL формула слишком рыхлая для 15m шума | 838 SL на tsl_tf=15m | АРХИТЕКТУРА | 🟠 P1 |
| 5 | Поздние входы pivot_reversal | 699 сделок avgR -0.39 | ЛОГИКА | 🟠 P1 |
| 6 | wt_signal входит вне зоны OS/OB | wt-семейство WR 3-8% | **БАГ КОДА** | 🟠 P1 |
| 7 | MTF Куба циклична, ухудшает atr-gate | gate выключен фактически | АРХИТЕКТУРА | 🟡 P2 |
| 8 | TP1 редко достигается → BE не срабатывает | 85% DUAL без BE | АРХИТЕКТУРА | 🟡 P2 |
| 9 | senior_matches gate работает только для MTF_BIAS | 431 сделка с 0/3 | АРХИТЕКТУРА | 🟡 P2 |
| 10 | Cascade TSL не успевает поднять TF | 838 SL на 15m | АРХИТЕКТУРА | 🟡 P2 |

---

## 7. План исправлений — ФАЗАМИ

### Фаза 1 — TSL код-баги (1-2 дня, ноль архитектурных рисков)

Цель: починить то что просто сломано в коде/конфиге.

**1.1. Безусловный update БД stop_loss при движении TSL**
- Файл: [trade_simulator.py:1980-2005](../core/trading/trade_simulator.py#L1980-L2005)
- Текущее: БД-update обёрнут в `_is_real_move` (требует exchange_order_id)
- Фикс: разделить два действия:
  - БД-update stop_loss — безусловно при `tsl_price ≠ stop_loss` и `is_tighter`
  - Push в `tsl_moved` (для биржевого update) — оставить под `_is_real_move`
- Эффект: 182 sim-only сделок начнут получать TSL-защиту (≈+150R)

**1.2. Включить BE для SINGLE (current_r-trigger)**
- Файл: [config.yaml:266](../config.yaml#L266)
- Текущее: `use_breakeven: false`
- Фикс: `use_breakeven: true` + `breakeven_activation_r: 0.5`
- Эффект: 654 SINGLE-сделок получают BE+0.1% при +0.5R (≈+260R)

**1.3. Найти подмену sl_source pivot:0.3% → atr_1.5**
- Грep по `sl_source` от check_pivot_level_signal до register_trade_async
- Кандидаты подмены: recommendation_generator.py, trading_intelligence.py, monitoring.py
- Фикс: сохранять pivot:0.3% если он рассчитан в детекторе
- Эффект: tight pivot SL начнёт применяться (по бэктесту EV=0.256 vs ATR 0.115)

**1.4. wt1_value: где пишется?**
- Найти где формируется features_json при register_trade_async
- Если post-factum после регистрации — добавить `wt1_at_detection` в momentum детекции
- Без этого нельзя проверить реально ли wt_signal-триггер OS/OB ломается или просто диагностика отстаёт
- Эффект: либо подтверждение бага (фикс), либо снятие гипотезы

### Фаза 2 — TSL архитектура (3-5 дней, после стабилизации Фазы 1)

**2.1. Per-strategy TSL-параметры**
- Структура `trading.tsl_per_strategy.<name>` в [config.yaml](../config.yaml)
- pivot_reversal (структурный): `atr_period=21, factor=1.0, activation_r=0.5`
- wt_signal/wt_b (импульсный): `atr=43, factor=1.25, activation_r=1.0` (текущее)
- mtf_bias/trend (тренд): `atr=43, factor=2.0, activation_r=1.5`
- Чтение в [trade_simulator.py:1623-1624](../core/trading/trade_simulator.py#L1623-L1624)

**2.2. Reactive SL move в entry+0.3R при +1R**
- Новая логика в `check_open_trades_with_tsl` перед TSL-формулой
- При первом достижении +1R: hard move SL → entry+0.3R (фикс 30% прибыли)
- TSL формула применяется сверху как мягкий trail (только если is_tighter чем +0.3R)
- Опт-аут для trend/mtf_bias через config
- Эффект: защита от ситуации «TSL формула слишком далеко»

**2.3. Cascade TSL стартовый TF per-strategy**
- pivot_reversal — структурная сделка, шум 15m её убивает → start_tf=1h
- wt_signal — импульсный, 15m ok
- Параметр `cascade_start_tf_per_strategy` в config

**2.4. BE через current_r параллельно с TP1**
- Текущее: `use_be_after_tp1` ИЛИ `use_breakeven` — выбор один
- Фикс: оба триггера независимо. BE+0.1% сразу при +1R через current_r, плюс bonus при TP1 hit (фиксация 20%)
- Эффект: не зависит от TP1 hit (который редок)

### Фаза 3 — Вход-фильтры (после Фаз 1-2)

⚠️ **Критично:** не включать раньше Фазы 1+2. Без починки TSL gate сократит входы на 50%, оставшиеся всё равно потеряют → нулевой net эффект.

**3.1. atr_trend_1h_bias hard gate**
- Блок входа если `atr_trend_1h_bias` ≠ direction
- Эффект (по аудиту): -661 сделка с avgR -0.46, +671 с avgR -0.22

**3.2. Pivot proximity gate ужесточить до ≤1.5%**
- Найти где применяется `pivot_proximity_hard` (decision_trace показывает 2/908 блокировок — порог не работает)
- Эффект: отрезать 699 сделок на 1.5%+ от уровня (avgR -0.39)

**3.3. senior_matches=0 hard block для не-MTF стратегий**
- 431 сделка (54%) открывается с 0/3 senior matches
- Эффект: блок отчасти повторит atr_trend gate, но добавит независимый сигнал

**3.4. wt_signal — расследовать триггер OS/OB**
- После решения 1.4: если wt1 действительно <-60 на детекции но не записывается — это диагностический баг
- Если `cross_up and wt1_last < _os_gate` не срабатывает в реальной торговле — найти причину и починить

---

## 8. Что подтверждено / опровергнуто

| Гипотеза | Статус |
|---|---|
| H1 поздний вход | ✅ ПОДТВЕРЖДЕНА |
| H2 тесный SL | ⚠️ ЧАСТИЧНО (только wt_b_signal, мало значимо) |
| H3 pivot direction | ✅ ПОДТВЕРЖДЕНА (proximity не работает) |
| H4 Куб не замкнут | ✅ ПОДТВЕРЖДЕНА (circular MTF) |
| H5 slippage | ❌ ОПРОВЕРГНУТА как driver (~0.05% порядки меньше SL) |
| H6 MTF deep | ✅ ПОДТВЕРЖДЕНА (atr_trend_1h работает) |
| H7 EMA веса | ⚠️ Не источник проблемы |
| **Слой A (TSL)** | **🚨 КАТАСТРОФА** — 70% активаций в SL, 4 уровня поломок |

---

## 9. Ожидаемый эффект починки (грубо)

| Фаза | Действие | Эффект |
|---|---|---|
| Фаза 1 | sim-only TSL пишет БД | +150R |
| Фаза 1 | SINGLE BE через current_r | +260R |
| Фаза 1 | sl_source tight pivot | +50R |
| Фаза 1 | wt1_value диагностика | +50R (если фикс) |
| Фаза 2 | per-strategy TSL | +100R |
| Фаза 2 | reactive +0.3R фикс | +150R |
| Фаза 3 | atr_trend gate | -100R (срез сделок) +200R (avgR sift) |

**Net (грубо): +750R** в избежании потерь vs текущее состояние.
**avgR:** −0.27 → ~+0.20.
**WR:** останется ~10-15% (вход не радикально меняется), но avgR-бюджет переворачивается.

---

## 10. Риски и неизвестные

### Риски
- **Reactive +0.3R фикс** может рубить будущий потенциал в трендовых сделках — нужен per-strategy опт-аут
- **Включение `use_breakeven`** может переключать SL→BE рано на волатильных входах — нужна калибровка `breakeven_activation_r`
- **atr_trend_1h gate** включать только после Фазы 1-2, иначе 0 эффекта
- **Изменения в горячем коде TSL** требуют интеграционных тестов

### Неизвестные
- Где именно `wt1_value` пишется в features_json — детекция или post-register?
- Где именно `atr_trend_1h_bias` рассчитывается — независимо от 15m или нет?
- Реально ли `cross_up` детектится на бар-запоздавших данных?
- 286 ACT=1→SL exchange-managed сделок: где TSL формула проиграла биржевой механике? Нужен живой репро.

---

## 11. Связанные документы

- [DISCUSSION.md](../DISCUSSION.md) — диалог по H1-H7 + Слой A
- [TASKS.md](../TASKS.md) — ARCH-95 главная задача
- [docs/STRATEGY_TRIGGERS.md](STRATEGY_TRIGGERS.md) — реестр триггеров входа
- [memory/current_state.md](../memory/current_state.md) — текущее состояние сессии

## 12. Скрипты-аудиторы (read-only, переиспользуемые)

| Скрипт | Назначение |
|---|---|
| [audit_entry_timing.py](../scripts/audit_entry_timing.py) | H1+H2 entry timing, SL distance |
| [audit_pivot_direction.py](../scripts/audit_pivot_direction.py) | H3 pivot direction & proximity |
| [audit_cube_snapshots.py](../scripts/audit_cube_snapshots.py) | H4 Куб alignment & decision_trace |
| [audit_slippage_mtf.py](../scripts/audit_slippage_mtf.py) | H5+H6 slippage & MTF deep |
| [audit_signal_performance_ema.py](../scripts/audit_signal_performance_ema.py) | H7 EMA per signal_type |
| [audit_tsl_efficiency.py](../scripts/audit_tsl_efficiency.py) | Слой A TSL fate, captured_R, exit-R, coverage |

Все скрипты read-only, без модификации БД, фильтр post-fix эры (>=15.04).
