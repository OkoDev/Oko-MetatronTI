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

### TR-010 — Решение по 17 плохим breach-позициям 🔴
**Статус:** 🔴 срочно — ждёт ответа TRADER
**Источник:** DEV DISCUSSION 23.03

**Контекст:** 17/18 WL breach позиций открыты как LONG при TREND_DOWN (DEV-32 bypass, исправлен DEV-41). Они продолжают жить в БД и влияют на статистику.

**Что нужно решить:**
- [ ] Смотришь ли эти позиции в TR-001 (25.03)?
- [ ] Рекомендуешь A (закрыть руками) или B (ждём SL/TSL)?
- [ ] Если закрывать — указать критерий: все 17, или только те что в просадке >1R?

→ DEV-43 ждёт этого решения.

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
**Статус:** ✅ выполнено 24.03.2026 — ответы в DISCUSSION.md

**Ответы TRADER (24.03):**
- [x] Статические 1.5%/3.0% — неправильные для крипты. ATR-adaptive (`tier1 = max(1.0%, ATR*1.5)`) — правильный подход, DEV-37 уже реализовал. Добавить cap сверху: `min(ATR*1.5, 5.0%)`
- [x] ATR-адаптация нужна и уже есть. Floor 1.0% защищает стейблы/медленные пары.
- [x] Пивоты: только классические 1D/1W/1M. Future PP — нет (он уже в DEV-36 score modifier, дублировать не нужно).

**→ DEV:** в DEV-37, в формуле tier1 изменить `max(1.0%, ATR*1.5)` → `max(1.0%, min(ATR*1.5, 5.0%))`. Статические пороги из pseudocode выше не использовать.

---

### TR-005 — Future PP как Direction Gate: спецификация
**Статус:** ✅ выполнено 24.03.2026 — спек ARCH-33 подтверждён полностью, DEV-36 реализован корректно

**Ответы TRADER (24.03):**
- [x] Порог 0.985 (1.5%) правильный для 15m. Пороги по ТФ: 15m=0.985, 1h=0.990, 4h=0.993 — подтверждены.
- [x] Weekly vs Daily конфликт: Weekly приоритет, доп. -5 при конфликте — правильно, уже в DEV-36.
- [x] SHORT — зеркально симметрично: price > future_pp × 1.015 → +5 (PREMIUM хорошо), price < future_pp → -10 (DISCOUNT плохо). Уже в спеке ARCH-33.

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
**Статус:** 🟡 важно (24.03.2026) — данных достаточно, запускать

**Цель:** найти систематические паттерны в SL-сделках. Не "почему конкретная пара", а "какой тип входа всегда заканчивается SL?"

**Формат:** DEV предоставляет выборку 30-50 SL-сделок с данными. TRADER анализирует: что общего? Вход в PREMIUM? Слабый MTF? HIGH_VOL режим? Конфлюэнций не было?

**→ DEV:** выгрузить последние 50 SL-сделок (не считая WL breach):
```sql
SELECT symbol, signal_type, direction, regime, strength, confidence,
       entry_price, stop_loss, take_profit, created_at, features_json
FROM simulated_trades
WHERE status = 'SL' AND signal_type != 'watch_list_breach'
ORDER BY closed_at DESC LIMIT 50;
```
Вставить результат в DISCUSSION.md → TRADER разберёт.

---

## 🏛️ Задачи ARCH

> Архитектурные решения — дизайн, приоритеты, спецификации. Выполняются до передачи DEV.

---

### ARCH-37 — Guards в register_trade_async(): архитектурное решение 🔴
**Статус:** ✅ выполнено 24.03.2026 — решение принято, спек передан DEV-43
**Источник:** TRADER 24.03 — WL breach bypass DEV-32 (DISCUSSION.md 24.03)

**Контекст после ревью кода:**
- DEV-41 уже реализовал все три фикса в `_handle_wl_breach_entry()` (DEV-32 gate, ATR fallback TP, R:R cap, rate-limit)
- WL breach trades от 23.03T01:xx — легаси до перезапуска бота, не баги текущего кода
- `register_trade_async()` уже имеет DEV-38 Correlation Guard — паттерн established

**Решение ARCH: Вариант B (partial) — второй рубеж в register_trade_async()**

Логика двух уровней защиты:
```
Уровень 1 (analyze_symbol / _handle_wl_breach_entry):
  → видимый пользователю — action=WATCH с причиной, логирование

Уровень 2 (register_trade_async):
  → тихий аварийный — return None, INFO лог
  → срабатывает только если Уровень 1 пропустил (будущие code-path, баги)
```

**Что переходит в `register_trade_async()` (второй рубеж):**
1. `regime_direction_block` (DEV-32) — silent fallback
2. `blocked_regimes` / HIGH_VOL (DEV-33) — silent fallback

**Что НЕ переходит:**
- `max_rr` — это параметр уровней SL/TP, а не guard регистрации. Если TP уже посчитан правильно — cap не нужен как guard.
- Rate-limit WL breach — специфична для WL breach, не для всех регистраций.

**Спек для DEV-43 (новая задача):**
```python
# В register_trade_async(), после DEV-38 Correlation Guard блока:

# ARCH-37: Второй рубеж — regime/direction guard
try:
    from core.config_loader import config as _cfg_a37
    _rdb = (_cfg_a37.get("trading", {}).get("regime_direction_block", {})
            if _cfg_a37 else {})
    _br  = (_cfg_a37.get("trading", {}).get("blocked_regimes", [])
            if _cfg_a37 else [])
    if regime and (_rdb.get("enabled", False) or _br):
        _sym_a37 = _get_recommendation_value(recommendation, "symbol") or ""
        _dir_a37 = _direction_str(_get_recommendation_value(recommendation, "direction"))
        # DEV-32 fallback
        if _rdb.get("enabled", False):
            _blocked = _rdb.get(regime)
            if _blocked and _dir_a37 == _blocked:
                logger.info("[ARCH-37] %s: второй рубеж — %s блокирует %s при %s",
                            _sym_a37, "regime_direction_block", _dir_a37, regime)
                return None
        # DEV-33 fallback
        if regime in _br:
            logger.info("[ARCH-37] %s: второй рубеж — %s в blocked_regimes",
                        _sym_a37, regime)
            return None
except Exception as _e37:
    logger.debug("[ARCH-37] guard error: %s", _e37)
```

**Важно:** `regime` уже вычислен выше в `register_trade_async()` (строка 506). Блок вставить ПОСЛЕ блока определения `regime`, ПОСЛЕ DEV-38 guard.

---

### ARCH-38 — Singleton PivotCalculatorFixed для DEV-36 🟡
**Статус:** ✅ выполнено 24.03.2026 — решение принято, спек передан DEV-45

**Анализ после ревью кода:**
- `PivotCalculatorFixed()` вызывается БЕЗ `db_path` в DEV-36/DEV-37/DEV-41 блоках → кеш из БД не загружается (строки 59-65 pivot_calculator_fixed.py)
- `PivotCalculatorFixed(db_path=...)` загружает всё из БД при `__init__` → кеш горячий с первого вызова
- `TradingIntelligence.__init__` не имеет `self._pivot_calc` (подтверждено чтением кода)

**Решение ARCH: Вариант A — singleton с db_path**

**Спек для DEV-45:**

1. В `TradingIntelligence.__init__()` (~строка 96, после `self._db_path = db_path`):
```python
# ARCH-38: Singleton PivotCalculatorFixed — кеш живёт весь цикл
from core.pivot_calculator_fixed import PivotCalculatorFixed as _PCF
self._pivot_calc_shared: _PCF = _PCF(db_path=db_path)
```

2. Заменить все `PivotCalculatorFixed()` / `PivotCalculatorFixed(...)` в `trading_intelligence.py` на `self._pivot_calc_shared`:
   - строка 615: `_PCF41()` → `self._pivot_calc_shared`
   - строка 817: `_PCF()` → `self._pivot_calc_shared`
   - строка 899: `_PCF37()` → `self._pivot_calc_shared`
   - строка 1150: `PivotCalculatorFixed()` → `self._pivot_calc_shared`

**Ожидаемый эффект:** ~600 инстансов/час → 1 инстанс. DB загрузка при старте once.

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

### DEV-42 — DEV-37 shadow review → включить ✅
**Статус:** ✅ выполнено 23.03.2026
**Источник:** ARCH (DISCUSSION 23.03) + DEV наблюдение

**Результат анализа логов (crypto_bot.log, 23.03):**
- Всего событий DEV-37: 48 (near=26, penalty=22, hard_block=0)
- hard_block rate = 0% (порог: <20% → включаем)
- Дистанции penalty: 3.09%–7.03% — разумные
- **Решение:** `pivot_proximity_filter.enabled: true` (было false)

**Файлы:** `config.yaml` → `trading.pivot_proximity_filter.enabled: true`

---

### DEV-43 — Закрыть "плохие" WL breach позиции
**Статус:** ✅ Решение ARCH 24.03 — **Вариант B: ждём SL/TSL/EXPIRED**
**Источник:** DEV DISCUSSION 23.03 — 17/18 breach позиций LONG/TREND_DOWN

**Решение ARCH:** Не закрывать вручную. Симуляция — не реальные деньги. Позиции закроются сами по SL/TSL/EXPIRED. Статистика этих сделок полезна: будет видно как ведут себя контр-трендовые входы. Ручное закрытие = манипуляция данными.

**Мониторинг:** при следующем TR-001 (25.03) TRADER смотрит на эти позиции — сколько выжило, SL или EXPIRED.

---

### DEV-44 — Guards в register_trade_async(): Вариант B ✅
**Статус:** ✅ выполнено 23.03.2026
**Источник:** ARCH решение 24.03 (DISCUSSION.md), проблема обнаружена в DEV-41 WL breach

**Зачем:** `analyze_symbol()` — не единственный путь. WL breach, Level 3 (Фаза 3) обходят его. Guards только в `analyze_symbol` = дыры. Guards в `register_trade_async()` = защита любого code-path.

**Что добавить** в начало `register_trade_async()` **после Correlation Guard (DEV-38)**:

```python
# Safety gate: режим vs направление (дублирует DEV-32, защищает все code-paths)
_regime = getattr(recommendation, 'regime', None) or (
    recommendation.metadata.get("mtf_context", {}).get("regime") if recommendation.metadata else None
)
_direction = getattr(recommendation, 'direction', None)
if _regime and _direction:
    _rdb = cfg.get("trading.regime_direction_block", {})
    if _rdb.get("enabled"):
        _blocked_dir = _rdb.get(_regime)
        if _blocked_dir and str(_direction).upper() == _blocked_dir:
            logger.info("[register_trade] %s БЛОК regime_direction: %s/%s", symbol, _regime, _direction)
            return None
    _blocked_regimes = cfg.get("trading.blocked_regimes", [])
    if _regime in _blocked_regimes:
        logger.info("[register_trade] %s БЛОК blocked_regime: %s", symbol, _regime)
        return None
```

**Файлы:** `core/trade_simulator.py` — `register_trade_async()` (~строка 480)

**Важно:** guards в `analyze_symbol()` (DEV-32/33) **остаются** — они снижают action до WATCH (пользователь видит причину). Guards в `register_trade_async()` — второй рубеж (return None тихо).

**Уточнение ARCH-37 (24.03):** вставлять ПОСЛЕ блока определения `regime` (~строка 510 в trade_simulator.py), не в начало. Использовать уже вычисленный `regime`, не `recommendation.regime`.

---

### DEV-45 — Singleton PivotCalculatorFixed в TradingIntelligence 🟡
**Статус:** 🟡 важно (24.03.2026)
**Источник:** ARCH-38 спек (24.03.2026)

**Проблема:** 4 места в `trading_intelligence.py` создают `PivotCalculatorFixed()` без db_path → пустой кеш каждый раз → 600 инстансов/час.

**Что сделать:**

1. В `TradingIntelligence.__init__()` (~строка 96):
```python
from core.pivot_calculator_fixed import PivotCalculatorFixed as _PCF_cls
self._pivot_calc_shared = _PCF_cls(db_path=db_path)
```

2. Заменить в `trading_intelligence.py`:
   - строка ~615: `PivotCalculatorFixed as _PCF41` + `_PCF41()` → `self._pivot_calc_shared`
   - строка ~817: `PivotCalculatorFixed as _PCF` + `_PCF()` → `self._pivot_calc_shared`
   - строка ~899: `PivotCalculatorFixed as _PCF37` + `_PCF37()` → `self._pivot_calc_shared`
   - строка ~1150: `PivotCalculatorFixed()` → `self._pivot_calc_shared`

**Проверка после:** `grep -c "PivotCalculatorFixed()" core/trading_intelligence.py` → должно быть 0.

**Файлы:** `core/trading_intelligence.py`

---

### DEV-42b — Rate-limit WL breach входов
**Статус:** ✅ выполнено 23.03.2026 — уже в DEV-41, строки 53–61 scan_loop.py
**Источник:** TRADER TR-001 24.03 (добавлено как задача, но уже было реализовано)

Rate-limit hardcoded: max 3 входа за 30 минут через `_wl_breach_timestamps` deque. Работает.

---

### DEV-41 — WL breach: 3 критических фикса 🔴
**Статус:** ✅ выполнено 23.03.2026
**Источник:** TRADER TR-001 разбор 24.03 → DISCUSSION.md

**Фикс 1 — DEV-32 bypass:** добавить `regime_direction_block` guard в `_handle_wl_breach_entry()` в `bot/loops/scan_loop.py`. 17/18 WL breach сделок прошли как LONG/TREND_DOWN.

**Фикс 2 — TP=None:** fallback в `_handle_wl_breach_entry()` когда `get_tp_by_hierarchy` возвращает None → ATR-based TP (2.5×ATR) + проверка min R:R 1.5. 16/18 сделок без TP.

**Фикс 3 — R:R cap:** применить `sl_cfg.get("max_rr", 6.0)` к tp_price в WL breach code-path.

**Архитектурный вопрос → ARCH:** ✅ Решено 24.03 — **Вариант B принят**. Реализация в DEV-44.

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

### DEV-41b — wt_signal + NEAR_PIVOT → силовой апгрейд
**Статус:** ✅ выполнено 24.03.2026 (git: 7af842a, именовался DEV-41 — конфликт имён с WL breach)
**Источник:** ARCH-23 спек (21.03.2026). Данные: wt_signal avg_R=+0.32 без пивота, avg_R=+1.27 с пивотом.

#### Суть
`wt_signal` у пивотного уровня статистически идентичен `confluence`, но регистрируется с низкими весами и без пивотного TP. Задача: детектировать `wt_signal` вблизи пивота (±1%) и бустить strength +20.

#### Точка вставки
`core/trading_intelligence.py` → `analyze_symbol()` — **после `_apply_mtf_context()` (~строка 536)**, до `_analyze_signals_advanced()` (~строка 634).

#### Алгоритм

```python
# DEV-41: wt_signal + NEAR_PIVOT boost
_daily_pivots_41 = None
for sig in filtered_signals:
    if sig.signal_type != "wt_signal":
        continue
    # Ленивый fetch daily pivots (PivotCalculatorFixed кеширует)
    if _daily_pivots_41 is None:
        try:
            from core.pivot_calculator_fixed import PivotCalculatorFixed as _PCF41
            _daily_pivots_41 = await _PCF41().get_daily_pivots(symbol, self.data_collector) or {}
        except Exception:
            _daily_pivots_41 = {}

    # Собрать уровни: 1D + 1W
    _all_levels = dict(_daily_pivots_41)
    if mtf_context and mtf_context.weekly_pivots:
        _all_levels.update({f"1W_{k}": v for k, v in mtf_context.weekly_pivots.items()})

    # Найти ближайший в ±1%
    price = (market_context.current_price if market_context else 0) or sig.data.get("price", 0)
    nearest_name, nearest_dist = None, float("inf")
    for lvl_name, lvl_price in _all_levels.items():
        if lvl_price and lvl_price > 0:
            dist = abs(price - lvl_price) / lvl_price * 100
            if dist < nearest_dist:
                nearest_dist, nearest_name = dist, lvl_name

    if nearest_dist > 1.0:
        continue  # не у пивота

    # Защита от дублирования с confluence
    has_confluence = any(s.signal_type in ("confluence", "wt_b_signal") for s in filtered_signals)
    if has_confluence:
        continue

    # Буст
    old_str = sig.strength
    sig.strength = min(100, sig.strength + 20)
    sig.data["near_pivot"] = nearest_name
    sig.data["near_pivot_dist_pct"] = round(nearest_dist, 3)
    logger.info("[DEV-41] %s wt_signal NEAR_PIVOT=%s (%.2f%%), str %d->%d",
                symbol, nearest_name, nearest_dist, old_str, sig.strength)
```

#### Файлы
| Файл | Изменение |
|------|-----------|
| `core/trading_intelligence.py` | Вставить блок DEV-41 после `_apply_mtf_context()` |

#### Что не трогать
- `signal_type` остаётся `wt_signal` (не менять на confluence — разная статистика)
- TP расчёт — оставить текущую логику (пивотный TP подтянется через recommend_generator)

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
