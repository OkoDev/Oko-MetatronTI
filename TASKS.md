# 📋 TASKS — Координация агентов

Файл координации между агентами проекта.

## 👥 Роли

| Роль | Кто | Зона ответственности |
|---|---|---|
| **ARCH** | yogoru | Архитектура системы, постановка задач, review, приоритеты |
| **DEV** | oko.webdev | Разработка, интеграция, бэктест, анализ данных |
| **TRADER** | Claude (TRADER) | Торговая экспертиза, разбор сигналов, валидация стратегий, живой анализ рынка, видение автоматизации |

**Workflow:** ARCH ставит задачу → DEV берёт в работу → ARCH делает review → TRADER валидирует с точки зрения реальной торговли

**Коммуникация между ролями:** любая роль **задаёт вопросы** другим ролям когда нужно уточнение, решение или экспертиза. Вопросы пишутся в [DISCUSSION.md](DISCUSSION.md) с явным тегом получателя.

| От \ К | → ARCH | → DEV | → TRADER |
|---|---|---|---|
| **ARCH** | — | Уточнения по реализации, оценка сложности | Валидация стратегии, приоритет фичи с торговой точки зрения |
| **DEV** | Неясность в спеке, архитектурный выбор, приоритет | — | Как это поведение выглядит в реальной торговле? |
| **TRADER** | Как реализована логика X? Что планируется в Фазе N? | Нужна команда Y, данные Z для анализа | — |

**Формат вопроса в DISCUSSION.md:**
```
→ ARCH: [вопрос]
→ DEV: [вопрос]
→ TRADER: [вопрос]
```

---

## 💬 Discussion — живой диалог агентов

> Хронологический лог перенесён в **[DISCUSSION.md](DISCUSSION.md)** (файл стал слишком большим).
> Новые сообщения добавлять туда же.

---

## 🎯 Задачи TRADER

> Торговые задачи — исследования, спецификации, валидации. Выполняются в [DISCUSSION.md](DISCUSSION.md) или отдельными постами.
> **Статусы:** 🔴 срочно | 🟡 важно | 🟢 в плане | ✅ выполнено

---

### TR-001 — Ежедневный разбор Watch List с живыми свечами
**Статус:** 🔄 периодическая
**Последний разбор:** 24.03.2026 | 33 открытых сделок | найдено 3 критических бага WL breach → DEV-41
**Следующий:** 25.03.2026 (утро)

**Что делать:** взять 4-6 пар из Watch List или свежих сигналов, посмотреть живые свечи (WT, тренд, wick structure), дать оценку: подтверждает рынок сигнал или нет?

**Периодичность:** не реже 3 раз в неделю.

**Почему важно:** DEV смотрит на цифры, TRADER смотрит на свечи. BEAT с wick↑=1.54% при теле 0.45% виден сразу на графике — в логе нужно считать.

#### Где хранить разборы

**Файл:** `memory/trader_analyses/YYYY-MM-DD.md` — один файл в день.

В TASKS.md Discussion — только краткая ссылка:
```
TRADER 22.03 — разбор 5 пар live → memory/trader_analyses/2026-03-22.md
```

Почему не в TASKS.md напрямую: TASKS уже большой. Отдельные файлы — поиск по дате тривиален, в будущем можно агрегировать скриптом для паттерн-анализа или ML-разметки.

#### Что включать в разбор (шаблон)

```markdown
## [YYYY-MM-DD HH:MM UTC] TRADER — Разбор N пар live

### СИМВОЛ/USDT
- **Цена:** X.XXX (+Y.Y% за 24ч)
- **Режим:** TREND_UP / RANGE / HIGH_VOL
- **ATR:** 0.XXX (Y.Y% от цены)
- **WT1/WT2:** -32 / -28 (нейтраль, выходит из OS)
- **Тренд:** UP / DOWN (supertrend не пробит / пробит)
- **Пивоты:** PP=X.XX (-1.9%), R1=X.XX (+3.4%), S1=X.XX (-5.6%)
- **В WL с:** 21.03 19:42 UTC | Причина: wt_b_signal str=78 conf=0.61
- **Сделка в БД:** OPEN (entry=X.XX, SL=X.XX, TP=X.XX, R текущий=+0.7)
  — или: нет открытой сделки
- **Свечная картина (4h/1h):** описание — FVG, wicks, структура
- **Вывод:** держу / выхожу / идея отработана / жду пробой
```

**Минимум без которого разбор неполный:**
1. Режим — TREND_UP/RANGE/HIGH_VOL
2. WT1/WT2 числами (не только OS/OB/N)
3. % до ближайшего пивота (фильтр входа)
4. Когда попало в WL и почему (signal_type + strength + conf)
5. Есть ли открытая сделка и текущий R

**Данные берём:** `/intelligence SYMBOL` в боте + таблица open_trades на дашборде.

---

### TR-002 — Спецификация Watch List breach → вход
**Статус:** ✅ выполнено 22.03.2026 19:55 UTC — полный спек в [DISCUSSION.md](DISCUSSION.md), DEV может реализовывать

**Спек закрыт (все 4 вопроса):**
- [x] Re-analyze: НЕТ. Используем orig_score + gate (regime, open trade, cooldown) в момент breach
- [x] SL: ВСЕГДА пивот ± 0.5% буфер (не ATR)
- [x] TP: следующий пивот в направлении ≤5%, иначе TSL-only. Min R:R = 1.5
- [x] TTL: 4 часа, не продлевать. Истёк = удалить. Если идея актуальна — следующий цикл добавит снова

**Передать DEV:** задача DEV-WL-BREACH готова к реализации. Детали в [DISCUSSION.md](DISCUSSION.md) пост 19:55 UTC.

---

### TR-003 — Спецификация двухступенчатого TP1+TP2
**Статус:** ✅ выполнено 22.03.2026 20:15 UTC — полный спек в [DISCUSSION.md](DISCUSSION.md), DEV-TP2 готов к Фазе 2

**Спек закрыт (все 4 вопроса):**
- [x] ATR TF: entry_tf (15m для 15m-входа, 1h для 1h-входа, cap 1h для 4h/1D). Маппинг как в ENTRY_TO_TSL_TF
- [x] Мультипликатор: TREND=2.0×, RANGE=1.0×, дефолт=1.5×
- [x] SL в б/у: entry ± 0.1% (не точно entry — покрывает комиссию и слипаж)
- [x] Цена пролетела TP1 к TP2: код уже обрабатывает корректно (последовательные проверки в одном цикле)
- [x] TSL активация: ТОЛЬКО после tp1_hit_at, не по current_r (для DUAL_TP/TRIPLE_TP_TSL стратегий)

**Передать DEV:** задача DEV-TP2. Изменений в схеме БД нет — все поля уже существуют. Изменения в `register_trade_async()` (ATR-based tp1_price) и в `check_open_trades_with_tsl()` (TSL gate по tp1_hit_at).

---

### TR-004 — Pivot Proximity Filter: пороги для крипты
**Статус:** 🟢 в плане (Фаза 1, после ARCH-33)

**Предложенный псевдокод:**
```python
distance = min_dist(current_price, all_pivot_levels) / price * 100
if distance < 1.5%:  signal_multiplier = 1.0  # пивот рядом
elif distance < 3.0%: signal_multiplier = 0.9  # умеренно
else:                 min_score += 10           # нужен сильный сигнал
```

**Что нужно от TRADER:**
- [ ] Пороги 1.5% / 3.0% — правильные для крипты? Или для BTC нужно 0.8%/2.0%, для альтов 2.5%/5.0%?
- [ ] Нужна ли адаптация порогов под ATR пары (высоковолатильные vs стейблы)?
- [ ] Какие пивоты включать: только классические (1D/1W/1M) или добавить Future PP тоже?

---

### TR-005 — Future PP как Direction Gate: спецификация
**Статус:** 🟢 в плане (Фаза 1, ARCH-33)

**Принятый подход (из Discussion):** score modifier, не hard gate.

```python
if direction == "LONG" and price > future_daily_pp:
    score -= 10  # PREMIUM
elif direction == "LONG" and price < future_daily_pp * 0.985:
    score += 5   # DISCOUNT > 1.5%
```

**Что нужно от TRADER:**
- [ ] Порог 0.985 (1.5%) — правильный? Или 0.99 (1.0%)?
- [ ] Как комбинировать Future Daily PP и Future Weekly PP? Если они противоречат — какой приоритет?
- [ ] Для SHORT: инвертированная логика (выше future PP = SHORT разрешён)? Или симметрично?

---

### TR-006 — 6-условный чеклист Level 3 авто-входа: детальная спецификация
**Статус:** 🟢 в плане (Фаза 3)

**Из Discussion (22.03) — базовый чеклист:**
```
□ 4h зона интереса активна (FVG или OB, незаполненный)
□ Цена в DISCOUNT для LONG / PREMIUM для SHORT
□ 1h структура не противоположна сигналу
□ 15m/5m дал триггер (WT кросс + пивот)
□ score ≥ 85
□ Портфельный лимит позволяет (< 3 открытых / нет перекоса)
```

**Спек уточнён TRADER 23.03 — все вопросы закрыты:**
```
FVG активна: fill_pct < 80% AND bars_since_creation <= 10 (4h баров = 40 часов)
BOS против направления    → hard block (условие НЕ выполнено)
CHoCH против направления  → soft block (условие выполнено, но score -= 8)
5/6 условий → Watch List + уведомление "Сетап 5/6, ждём условие N"
4/6 условий → тихое логирование без уведомления
Лимиты: max 2 LONG одновременно + max 2 SHORT + max 4 OPEN всего
```

---

### TR-007 — Валидация новых детекторов перед внедрением
**Статус:** 🟢 постоянная задача

**Когда включается:** когда DEV или ARCH говорит "→ TRADER: проверь работает ли это в реальной торговле?"

**Формат:** TRADER смотрит на 5-10 живых примеров сигнала детектора и даёт вердикт: "Вижу смысл", "Вижу ложный сигнал потому что...", "Нужна доработка условия N".

**Текущая очередь:**
- [ ] После включения `use_outcome_predictor: false` — подтвердить что TAKE/BEAT-подобные сигналы появляются в регистрации
- [ ] Pivot Proximity Filter (после реализации) — живой тест на 10 парах

---

### TR-009 — Команда /wlr (DEV задача для TRADER)
**Статус:** ✅ выполнено 23.03.2026

**Проблема:** для разбора одной пары нужно два источника — `/intelligence SYMBOL` + дашборд. Ручная сборка 5-6 полей замедляет TR-001.

**Что сделать:** команда `/wlr SYMBOL` — выводит одним сообщением всё нужное:

```
📊 DASHUSDT — WL Report
Режим:    TREND_UP  |  ATR: 0.048 (1.5%)
WT1/WT2: -32 / -28 (нейтраль)
Тренд:    UP
PP: 3.180 (-1.9%) | R1: 3.350 (+3.4%) | S1: 3.060 (-5.6%)
В WL с:  21.03 19:42 UTC (25ч назад)
Причина: wt_b_signal  str=78  conf=0.61
Сделка:  OPEN  entry=3.190  SL=3.100  TP=3.470  R=+0.71
```

**Источники:** режим/ATR/WT из `indicators`, пивоты из `pivot_calculator_fixed`, WL-запись из `SignalWatchList`, сделка из `trade_simulator.get_open_trade(symbol)`.

**Приоритет:** после DEV-WL-BREACH.

---

### TR-008 — Разбор закрытых сделок: паттерны SL
**Статус:** 🟢 в плане

**Цель:** найти систематические паттерны в SL-сделках. Не "почему конкретная пара", а "какой тип входа всегда заканчивается SL?"

**Формат:** DEV предоставляет выборку 30-50 SL-сделок с данными. TRADER анализирует: что общего? Вход в PREMIUM? Слабый MTF? HIGH_VOL режим? Конфлюэнций не было?

**Когда:** запустить после стабилизации #1 (через 3-5 дней).

---

## 🏛️ Задачи ARCH

> Архитектурные решения — дизайн, приоритеты, спецификации. Выполняются до передачи DEV.

---

### ARCH-33 — Future PP score modifier 🟡
**Статус:** ✅ выполнено 23.03.2026 — спек готов, передан в DEV-36
**Что:** Future PP уже вычисляется (`pivot_calculator_fixed.get_future_daily_pivots`). Нужна интеграция в скоринг.
**Где:** `trading_intelligence.py` → `_calculate_adaptive_weighted_strength()`

**Спек (TRADER 23.03, принят ARCH):**
```python
# Пороги по ТФ входа:
# 15m: discount_threshold = 0.985 (1.5% ниже future_pp)
# 1h:  discount_threshold = 0.990 (1.0%)
# 4h:  discount_threshold = 0.993 (0.7%)

# LONG:
if price > future_daily_pp:         score -= 10  # PREMIUM → против
if price < future_daily_pp * threshold: score += 5  # DISCOUNT → в пользу

# SHORT (зеркально):
if price > future_daily_pp * 1.015: score += 5   # PREMIUM → в пользу
if price < future_daily_pp:         score -= 10  # DISCOUNT → против

# При конфликте Weekly PP vs Daily PP:
# Weekly приоритет → score -= 5 дополнительно (не блок)
# Weekly нейтральный (±0.5% от Weekly PP) → смотреть только Daily
```

---

### ARCH-34 — Pivot Proximity Filter 🟡
**Статус:** ✅ выполнено 23.03.2026 — спек готов, передан в DEV-37

**Архитектурные решения (ARCH):**

**1. Точка вставки:** `analyze_symbol()` — после блока DEV-32/33 (~строка 741), до `return recommendation`. Там уже есть `current_price` и `mtf_context`.

**2. Источники данных** (без новых API-запросов):
- `ATR(4h)` → из `snapshot["4h"]` (уже в `collect_mtf_data`), поле `atr`. Если нет — фильтр пропускается (не блокирует).
- `Daily PP` → `PivotCalculatorFixed.get_daily_pivots(symbol, data_collector)` — лёгкий вызов, кешируется.
- `Weekly PP` → уже есть в `mtf_context.weekly_pivots` (загружается в `_build_mtf_context`).

**3. Поведение:**
```python
# distance > tier2 → WATCH (не блокируем жёстко — score penalty)
# distance ∈ [tier1, tier2] → score_modifier = -10 (требуем сильнее)
# distance < tier1 → без изменений
```
Не хардкодим `action = "WATCH"` — только score modifier. Жёсткий блок только если distance > 3×tier1.

**4. Режим запуска:** `enabled: false` по умолчанию (shadow mode). Логировать срабатывания 3-5 дней, потом включать.

**5. Конфиг:**
```yaml
trading:
  pivot_proximity_filter:
    enabled: false      # shadow mode → true после наблюдения
    hard_block_mult: 3  # distance > tier1*3 → WATCH
```

---

### ARCH-35 — Correlation Guard (связанные активы) 🟡
**Статус:** ✅ выполнено 23.03.2026 — спек готов, передан в DEV-38

**Архитектурные решения (ARCH):**

**1. Точка вставки:** `trade_simulator.py` → `register_trade_async()` — в начале, до любых расчётов SL/TP. `get_open_trades()` уже существует (строка 479), дополнительных запросов не нужно.

**2. Логика:**
```python
# В начале register_trade_async():
corr_groups = cfg.get("trading.correlation_groups", [])
if corr_groups:
    open_symbols = {t["symbol"].split("/")[0] for t in self.get_open_trades()}
    new_base = symbol.split("/")[0]  # "PAXG" из "PAXG/USDT"
    for group in corr_groups:
        if new_base in group:
            conflict = open_symbols & set(group) - {new_base}
            if conflict:
                logger.info("[%s] Correlation Guard: блок — уже открыта %s из той же группы", symbol, conflict)
                return None
```

**3. Конфиг:**
```yaml
trading:
  correlation_groups:
    - [PAXG, XAUT]        # gold tokens
    - [BTC, WBTC]         # wrapped bitcoin
    - [ETH, STETH, WETH]  # wrapped ether
```

**4. Поведение:** тихий блок (return None) + INFO лог. Не WATCH — просто не регистрируем, сигнал уже ушёл в TG без сделки.

---

### ARCH-36 — Market Event Marker 🟢
**Статус:** ✅ выполнено 23.03.2026 — спек готов, передан в DEV-39

**Архитектурные решения (ARCH):**

**1. In-memory счётчик** в `TradeSimulator.__init__`:
```python
self._sl_timestamps: List[datetime] = []  # скользящее окно SL
```

**2. Точка вставки:** `close_trade()` после успешного закрытия с `STATUS_SL`:
```python
if status == STATUS_SL:
    now = datetime.now(timezone.utc)
    self._sl_timestamps.append(now)
    # Прунинг окна 30 минут
    window_start = now - timedelta(minutes=30)
    self._sl_timestamps = [t for t in self._sl_timestamps if t >= window_start]
    # Порог: 5+ SL за 30 минут = market event
    if len(self._sl_timestamps) >= cfg.get("trading.market_event_marker.sl_count", 5):
        self._mark_market_event_in_window(window_start)
```

**3. Метод `_mark_market_event_in_window()`:**
```python
# UPDATE features_json для всех SL-сделок внутри окна:
UPDATE simulated_trades
SET features_json = json_patch(features_json, '{"market_event": true}')
WHERE status = 'SL' AND closed_at >= window_start
```
SQLite не имеет json_patch — использовать Python: читать features_json, merge dict, записать обратно.

**4. Конфиг:**
```yaml
trading:
  market_event_marker:
    enabled: true
    sl_count: 5      # сколько SL за окно = событие
    window_minutes: 30
```

**5. Использование:** поле `market_event: true` в `features_json` → ML фильтрует аномальные сессии при обучении. Не влияет на live-торговлю.

---

## 🛠️ Задачи DEV

> **Статусы:** 🔴 срочно | 🟡 важно | 🟢 в плане | ✅ выполнено | 🔄 в работе

---

### DEV-41 — WL breach: 3 критических фикса 🔴
**Статус:** 🟡 важно (24.03.2026)
**Источник:** TRADER TR-001 разбор 24.03 → DISCUSSION.md

**Фикс 1 — DEV-32 bypass:** добавить `regime_direction_block` guard в `_handle_wl_breach_entry()` в `bot/loops/scan_loop.py`. 17/18 WL breach сделок прошли как LONG/TREND_DOWN.

**Фикс 2 — TP=None:** fallback в `_handle_wl_breach_entry()` когда `get_tp_by_hierarchy` возвращает None → ATR-based TP (2.5×ATR) + проверка min R:R 1.5. 16/18 сделок без TP.

**Фикс 3 — R:R cap:** применить `sl_cfg.get("max_rr", 6.0)` к tp_price в WL breach code-path.

**Архитектурный вопрос → ARCH:** решить Вариант A или B (guards в analyze_symbol vs register_trade_async). Детали в DISCUSSION.md 24.03.

**Дополнительно:** rate-limit на WL breach — не более 3 входов за 30 минут.

---

### DEV-40 — Двухступенчатый TP1+TP2: реализация 🟡
**Статус:** ✅ выполнено 23.03.2026
**Источник:** TR-003 спек (TRADER 22.03.2026), анализ кода ARCH 22.03.2026

#### Что не так сейчас
- `tp1_price` = доля от RR (50% tp_dist для DUAL_TP, 33% для TRIPLE) — достигается нескоро, часто = 3-6R
- `be_activated` и `breakeven_activation_r` — **поля есть в БД/сигнатуре, но логика не реализована** (заглушки)
- TSL активируется по `current_r >= tsl_activation_r` без учёта `tp1_hit_at`

#### Что изменить

**1. ATR-based TP1 в `trade_simulator.py` → `register_trade_async()`**

Сейчас `tp1_price` считается как фракция от `take_profit`. Заменить на ATR × мультипликатор:

```python
# ENTRY_TO_TP1_TF маппинг (как ENTRY_TO_TSL_TF в entry_config.py):
ENTRY_TO_TP1_TF = {"15m": "15m", "1h": "1h", "4h": "4h", "1D": "1h"}  # cap 1h

# Мультипликатор по режиму:
TP1_REGIME_MULT = {
    "TREND_UP": 2.0, "TREND_DOWN": 2.0,   # тренд — даём больше места
    "RANGE": 1.0,                           # диапазон — быстро берём
}
regime_mult = TP1_REGIME_MULT.get(regime, 1.5)  # дефолт 1.5

# ATR берём из rec.atr_entry_tf (см. пункт 3)
if rec.atr_entry_tf and rec.atr_entry_tf > 0:
    atr_dist = rec.atr_entry_tf * regime_mult
    tp1_price = entry + sign * atr_dist      # LONG: +, SHORT: -
else:
    tp1_price = entry + sign * tp_dist * 0.5  # fallback: текущая логика
```

**2. Реализовать breakeven в `check_open_trades_with_tsl()`**

Сейчас `be_activated` не используется. Добавить в цикл по открытым сделкам:

```python
# После расчёта current_r, до TSL-блока:
if use_breakeven and breakeven_activation_r > 0:
    if not be_activated and current_r is not None and current_r >= breakeven_activation_r:
        # Перенести SL в entry ± 0.1%
        be_sl = entry_price * (1.001 if direction == "LONG" else 0.999)
        if direction == "LONG" and stop_loss < be_sl:
            # UPDATE stop_loss = be_sl, be_activated = 1
        elif direction == "SHORT" and stop_loss > be_sl:
            # UPDATE stop_loss = be_sl, be_activated = 1
```

**3. Добавить `atr_entry_tf` в `TradingRecommendation` (signal_models.py)**

```python
@dataclass
class TradingRecommendation:
    ...
    atr_entry_tf: Optional[float] = None  # ATR(entry_tf) для расчёта TP1
```

В `trading_intelligence.py` → `analyze_symbol()` после сбора snapshot:
```python
entry_tf = rec.timeframe  # "15m", "1h", etc.
atr_tf = ENTRY_TO_TP1_TF.get(entry_tf, entry_tf)
atr_data = snapshot.get(atr_tf, {})
rec.atr_entry_tf = atr_data.get("atr")  # уже есть в snapshot
```

**4. TSL gate по tp1_hit_at для DUAL_TP / TRIPLE_TP_TSL**

В `check_open_trades_with_tsl()` (~строка 804):
```python
# Было:
if use_tsl and current_r is not None and current_r >= tsl_activation_r:

# Стало (добавить условие для multi-TP стратегий):
is_multi_tp = strategy_type in ("DUAL_TP", "TRIPLE_TP_TSL")
tsl_gate = (tp1_hit_at is not None) if is_multi_tp else (current_r >= tsl_activation_r)
if use_tsl and tsl_gate:
```

#### Файлы
| Файл | Изменение |
|------|-----------|
| `core/signal_models.py` | Добавить `atr_entry_tf: Optional[float] = None` в TradingRecommendation |
| `core/intelligence/entry_config.py` | Добавить `ENTRY_TO_TP1_TF` маппинг |
| `core/trade_simulator.py` | ATR-based tp1_price + breakeven логика + TSL gate |
| `core/intelligence/trading_intelligence.py` | Заполнять `rec.atr_entry_tf` из snapshot |

#### Что НЕ менять (Фаза 1)
- Доля закрытия при TP1 (остаётся 50% — в симуляторе это логически так, фактический размер не меняется)
- Схема БД — все поля уже есть
- `strategy_type` выбор (DUAL_TP / TRIPLE_TP_TSL) по RR — остаётся

#### Проверка после реализации
```bash
python -c "
from core.performance_engine import PerformanceEngine
pe = PerformanceEngine('subscriptions.db')
# Смотреть: be_activated (% сделок), tp1_hit_at (% сделок), сравнить avg_R DUAL_TP до/после
"
```

---

### DEV-39 — Market Event Marker: реализация 🟢
**Статус:** ✅ выполнено 23.03.2026
**Источник:** ARCH-36 спек (23.03.2026)

**Что сделано:**
- `trade_simulator.__init__`: `self._sl_timestamps: List[datetime] = []`
- `close_trade()`: после STATUS_SL → append + prune окна + если ≥5 → `_mark_market_event_in_window()`
- `_mark_market_event_in_window()`: UPDATE features_json всех SL-сделок в окне → `{"market_event": true}`
- `config.yaml`: `trading.market_event_marker.enabled/sl_count/window_minutes`
- Влияние на live: нулевое — только ретроактивный UPDATE в БД для ML-фильтрации

---

### DEV-38 — Correlation Guard: реализация 🟡
**Статус:** ✅ выполнено 23.03.2026
**Источник:** ARCH-35 спек (23.03.2026)

**Что сделано:** в начале `register_trade_async()` — если новый символ принадлежит группе и уже есть открытая сделка по другому активу той же группы → `return None` + INFO лог.
- `config.yaml`: `trading.correlation_groups: [[PAXG, XAUT], [BTC, WBTC], [ETH, STETH, WETH]]`

---

### DEV-37 — Pivot Proximity Filter: реализация 🟡
**Статус:** ✅ выполнено 23.03.2026
**Источник:** ARCH-34 спек (23.03.2026)

**Что сделано:** блок в `trading_intelligence.analyze_symbol()` после DEV-36.
- 4h ATR → `tier1 = max(1.0%, ATR*1.5)`, `tier2 = tier1*2`
- PP уровни: Daily PP + Weekly PP (через PivotCalculatorFixed, кешировано)
- `dist < tier1` → ok | `dist < hard_mult*tier1` → -10 str | `dist > hard_mult*tier1` → WATCH
- `enabled: false` (shadow mode) — логирует без изменений; `enabled: true` → применяет
- `config.yaml`: `trading.pivot_proximity_filter.enabled: false / hard_block_mult: 3`

---

### DEV-36 — Future PP score modifier: реализация 🟡
**Статус:** ✅ выполнено 23.03.2026
**Источник:** ARCH-33 спек (23.03.2026)

**Что сделано:** блок в `trading_intelligence.py` после DEV-33 (перед metadata).
- LONG: price > future_pp → -10 (PREMIUM плохо), price < future_pp * threshold → +5 (DISCOUNT хорошо)
- SHORT: зеркально
- Порог DISCOUNT по ТФ: 15m=0.985, 1h=0.990, 4h=0.993
- Weekly PP конфликт → дополнительный -5
- `config.yaml`: `trading.future_pp_score_modifier.enabled: true`

---

### DEV-WL-BREACH — Watch List breach → автовход 🔴
**Статус:** ✅ выполнено 23.03.2026
**Источник:** TR-002 спек (TRADER 22.03.2026)

**Что сделано:**
- `core/signal_watch_list.py`: добавлен метод `check_breach_entry_direction()` — проверяет пробой В направлении (противоположен `check_breach`)
- `bot/loops/scan_loop.py`: в DEV-22 блок добавлен `elif` — при breach entry → `_handle_wl_breach_entry()`
- `_handle_wl_breach_entry()` — async функция: gates (HIGH_VOL, cooldown), SL=pivot±0.5%, TP через `get_tp_by_hierarchy` ≤5%, min R:R=1.5, `signal_type="watch_list_breach"`, TG-алерт
- `config.yaml`: добавлен `wl_sl_buffer_pct: 0.5`

**Спек:** orig_score (не re-analyze), SL=пробитый_пивот±0.5%, TP=ближайший пивот ≤5%, min R:R=1.5, TTL=4h

---

### DEV-32 — Блокировка контр-тренд входов 🔴
**Статус:** ✅ выполнено 23.03.2026
**Источник:** TRADER-анализ 23.03 — CAKE LONG/TREND_DOWN str=98, SAHARA SHORT/TREND_UP str=94

**Что сделано:** guard в `trading_intelligence.py` (строки 721–741) + в `config.yaml`:
```yaml
trading:
  regime_direction_block:
    enabled: true
    TREND_DOWN: LONG   # блокировать LONG при нисходящем тренде
    TREND_UP: SHORT    # блокировать SHORT при восходящем тренде
```

**ARCH review:** реализация корректная. Блок срабатывает до регистрации, логируется с тегом DEV-32. Наблюдаем эффект 2-3 дня.

---

### DEV-33 — Блокировка HIGH_VOL входов 🔴
**Статус:** ✅ выполнено 23.03.2026
**Источник:** DB-анализ: HIGH_VOL WR=0%, avg_R=-0.25

**Что сделано:** `config.yaml` → `blocked_regimes: [HIGH_VOL]` + guard в `trading_intelligence.py` (после DEV-32 блока) → `action=BUY/SELL + regime in blocked_regimes → WATCH`

---

### DEV-34 — ATR factor 1.25→1.1 🟡
**Статус:** ✅ выполнено 23.03.2026
**Что:** `config.yaml` → `analysis.indicators.trend.factor: 1.1`
**Эффект:** TSL менее агрессивный, меньше ложных выходов на волатильности.

---

### DEV-35 — R:R cap max 6.0 🟡
**Статус:** ✅ выполнено 23.03.2026
**Источник:** TRADER 23.03 — PAXG R:R=24.6x, CRCLX R:R=32.1x — TP на monthly pivot недостижим.

**Что сделано:** `config.yaml` → `trading.sl_tp.max_rr: 6.0` + guard в `recommendation_generator.py:calculate_levels()` (перед return). Использует `sl_cfg.get("max_rr")` — согласован с существующим стилем. Синхронизирует `tp1_price` с обрезанным `take_profit`. Добавляет `|capped_rr_6.0` в `tp_source` для диагностики.

---

## 📏 Правила

1. **Не редактировать один файл одновременно** — договариваться через этот файл
2. Architect задаёт архитектуру → Developer реализует
3. Каждая задача = отдельный git commit с внятным сообщением
4. После реализации — Architect делает `git diff HEAD~1` и пишет review здесь
5. **Любая роль задаёт вопросы** другим ролям при необходимости — не блокируется и не молчит. Вопрос без ответа лучше чем неверное решение молча.
6. **Алгоритм подключения для каждой роли:**
   1. [DISCUSSION.md](DISCUSSION.md) — **первым**. Найти `→ своя роль:` — ответить до любой другой работы.
   2. [TASKS.md](TASKS.md) — статусы задач, что в работе, что ждёт.
   3. `whats-next.md` — handoff от предыдущей сессии.
   4. `memory/MEMORY.md` — архитектурные решения и паттерны.
