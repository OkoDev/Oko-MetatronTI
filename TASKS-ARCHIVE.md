# 📦 TASKS-ARCHIVE — Выполненные задачи

> Перенесено из TASKS.md 24.03.2026. Всего задач: 55.

---

### TR-010 — Решение по 17 плохим breach-позициям 🔴
**Статус:** ✅ решено 24.03.2026 — **Вариант B принят TRADER**
**Источник:** DEV DISCUSSION 23.03

**Контекст:** 22/18 WL breach позиций открыты как LONG при TREND_DOWN (DEV-32 bypass, исправлен DEV-41). Реальное кол-во по запросу — 22 позиции.

**Итог на 24.03:** 4 закрылись по SL (-1R) — WIF, PUMP, SOMI, AVNT. 18 OPEN.

**Решение TRADER:**
- [x] TR-001 (25.03) — наблюдать сколько осталось OPEN
- [x] **Вариант B** — ждать SL/TSL. Процесс работает: 4 уже закрыты -1R. Без TP остальные придут туда же.
- [x] Не закрывать вручную — данные ML (negative примеры контр-тренда) ценны

→ DEV-43 подтверждён (ARCH и TRADER — оба Вариант B).

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
**Статус:** ✅ спек готов 23.03.2026 — DISCUSSION.md + memory/trader_analyses/TR-006-spec.md

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
**Статус:** ✅ выполнено 23.03.2026 — предварительный анализ TRADER (DISCUSSION.md)
**Вывод:** выборка нерепрезентативна (dump night), 25/50 контр-тренд (DEV-32 решит), RR>10 у 56% → DEV-35 нужен cap ниже. Повторный TR-008 через 2 недели с чистыми данными.

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

### ARCH-51 — Multi-TF SMC: MTFSMCSnapshot в MTFContext (4h + 1D) 🟡
**Статус:** ✅ спек уточнён 25.03.2026 (ARCH → TRADER) → DEV-63 реализация ≈06-08.04
**Источник:** TRADER 24.03.2026 — 15m SMC слеп к 4h/1D OB. Пример: система шортит прямо у 4h Bull OB.

**Проблема:** `analyze_smc(df_15m)` видит только 25 часов. 4h Bull OB — невидим. Конфликт 15m bearish + 4h Bull OB nearby = ложный сигнал SHORT.

**Архитектура (уточнение от 25.03.2026):**
- НЕ отдельный `MTFSMCContext` — добавить `smc_h4: MTFSMCSnapshot` и `smc_d1: MTFSMCSnapshot` прямо в `MTFContext` (signal_models.py)
- `MTFSMCSnapshot` — лёгкий срез (8 полей), не полный `SMCContext` (без списков swings/FVGs)
- `build_mtf_smc_snapshot(smc_ctx, current_price, proximity_pct)` в `core/smc/models.py`

```python
# core/signal_models.py — добавить:
@dataclass
class MTFSMCSnapshot:
    bull_ob_nearby: bool = False    # цена в proximity_pct% от Bull OB
    bear_ob_nearby: bool = False
    fvg_support: bool = False       # незакрытый FVG под ценой (поддержка LONG)
    fvg_resistance: bool = False    # незакрытый FVG над ценой (сопротивление LONG)
    choch_direction: str = "none"   # "bullish"|"bearish"|"none"
    bos_direction: str = "none"
    ob_proximity_pct: float = 0.0   # % до ближайшего OB (для score)

# В MTFContext добавить:
smc_h4: Optional[MTFSMCSnapshot] = None   # ARCH-51, proximity=1.5%
smc_d1: Optional[MTFSMCSnapshot] = None   # ARCH-51, proximity=2.5%
```

**Вызов в `trading_intelligence.py` (~строка 618):**
```python
# После smc_context = analyze_smc(df_entry), рядом:
df_4h = await self.data_collector.get_ohlcv(symbol, "4h", limit=100)
df_1d = await self.data_collector.get_ohlcv(symbol, "1d", limit=50)
if df_4h is not None and len(df_4h) >= 20 and mtf_context:
    mtf_context.smc_h4 = build_mtf_smc_snapshot(analyze_smc(df_4h), price, 1.5)
if df_1d is not None and len(df_1d) >= 20 and mtf_context:
    mtf_context.smc_d1 = build_mtf_smc_snapshot(analyze_smc(df_1d), price, 2.5)
```

**Score-модификаторы (shadow на старте, в `_analyze_signals_advanced()`):**
```python
# [ARCH-51 shadow]
if mtf_context and mtf_context.smc_h4:
    h4 = mtf_context.smc_h4
    if direction==LONG and h4.bull_ob_nearby:  metadata["arch51_h4_bull_ob"] = True  # +15
    if direction==LONG and h4.bear_ob_nearby:  metadata["arch51_h4_bear_ob_conflict"] = True  # -20
    if direction==LONG and h4.fvg_support:     metadata["arch51_h4_fvg_sup"] = True  # +10
    if direction==SHORT and h4.bull_ob_nearby: metadata["arch51_short_near_h4_bull_ob"] = True  # -25
```

**DEV задача: DEV-63** — реализовать ARCH-51 спек. Приоритет 🟡 (≈06-08.04, после ARCH-45 ревью).

**Pre-валидация (DEV, до реализации ARCH-51):**
При работе над Phase B — добавить в логи: `[ARCH-51-pre] 15m=bearish, pivot_proximity=X%` когда 15m SMCContext bearish И цена в ±2% от любого пивот-уровня. Даст данные для валидации масштаба проблемы.

---
> ⚠️ RANGE guard → см. **DEV-61** (max_rr_range=2.5 + min_strength RANGE=70, решено сессией 17)
> ⚠️ EXPIRED+profit → см. **DEV-62** (tiered EXPIRED→TSL для TREND R≥1.5, решено сессией 17)

---

### ARCH-50 — MTF Interpreter v2: паттерны волновой теории 🔴
**Статус:** 🔄 Phase A ✅ выполнено 24.03.2026 (phase+cascade shadow) → Phase B (DEV-58-61) ждёт верификации TRADER
**Источник:** TRADER запрос 24.03.2026 — система говорит "НЕЙТРАЛЬ 56%" вместо структуры

**Проблема:** MTF система считает `% TF в одном направлении` — это одно число без контекста. Одинаковый aligned_pct может означать принципиально разные торговые сценарии (импульс vs коррекция, перекупленность vs нормальная зона). Система не читает СТРУКТУРУ рынка.

**Ключевые концепции для реализации:**

#### 1. PHASE DETECTOR (критично 🔴)
```python
# В mtf_interpreter.py → добавить в analyze_context()
d1_trend = snapshot["1d"]["trend"]  # "UP" / "DOWN"
h4_trend = snapshot["4h"]["trend"]

if d1_trend == h4_trend:
    phase = "impulse_up" if d1_trend=="UP" else "impulse_down"
else:
    if d1_trend=="DOWN" and h4_trend=="UP":
        phase = "correction_up_in_bear"  # 4h corrects against 1d downtrend
    else:
        phase = "correction_down_in_bull"  # 4h corrects against 1d uptrend
```

**Влияние на торговые решения:**
- `correction_up_in_bear` → LONG guard: не открывать LONG позиции как основную стратегию (только скальп)
- `impulse_up` → SHORT guard: не шортить без сильного reversal сигнала
- `correction_down_in_bull` → SHORT guard: не шортить как основную стратегию
- `impulse_down` → LONG guard: не покупать без reversal

#### 2. ZONE CASCADE DETECTOR (критично 🔴)
```python
# Старшие TF (1d, 4h, 1h) в OS/OB
senior_os = sum(1 for tf in ["1d","4h","1h"] if snap.get(tf,{}).get("zone")=="OS")
senior_ob = sum(1 for tf in ["1d","4h","1h"] if snap.get(tf,{}).get("zone")=="OB")

zone_state = "cascade_os" if senior_os >= 2 else \
             "cascade_ob" if senior_ob >= 2 else \
             "partial_os" if senior_os == 1 else \
             "partial_ob" if senior_ob == 1 else "normal"
```

**Значение:**
- `cascade_os` (2+ старших в OS) = Maximum reversal zone для LONG. Повышать confidence разворотных сигналов на +15
- `cascade_ob` (2+ старших в OB) = Maximum reversal zone для SHORT. Аналогично
- `partial_os` в восходящем тренде = RELOAD ZONE (лучшая точка входа в LONG)

#### 3. AVOID_REASON (критично 🔴)
```python
# Добавить в MTFContext
avoid_reason: Optional[str] = None  # Почему НЕ открывать сейчас

# Примеры:
"younger_tfs_oversold"   # 3m/5m в OS при нисходящем тренде — не шортить (снесёт отскок)
"correction_active"      # 4h корригирует — ждать завершения
"cascade_ob_short_only"  # Все перекуплены — только SHORT с reversal
```

#### 4. NAMED PATTERN (важно 🟡)
```python
pattern_name: str  # в MTFContext

# Примеры паттернов:
"IMPULSE_UP"             # Все aligned вверх, нейтральные зоны
"IMPULSE_DOWN"           # Все aligned вниз, нейтральные зоны
"CORRECTION_UP_IN_BEAR"  # 4h вверх в нисходящем 1d тренде
"CORRECTION_DOWN_IN_BULL" # 4h вниз в восходящем 1d тренде
"CASCADE_OS_REVERSAL"    # 2+ старших в OS — reversal zone
"CASCADE_OB_REVERSAL"    # 2+ старших в OB — reversal zone
"WAVE_3_RELOAD_UP"       # 1d+4h UP, 1h в OS — reload zone
"WAVE_3_RELOAD_DOWN"     # 1d+4h DOWN, 1h в OB — reload zone
"EXHAUSTION_UP"          # 1d OB + 4h начинает DOWN (дистрибуция)
"EXHAUSTION_DOWN"        # 1d OS + 4h начинает UP (аккумуляция)
```

#### 5. WT_SPREAD → CONFIDENCE (важно 🟡)
```python
# Использовать wt_spreads (уже вычисляется, не применяется)
# Слабый spread = слабый тренд → снизить confidence
# Сильный spread = сильный тренд → повысить

entry_spread = wt_spreads.get(entry_tf, 0)
spread_mult = 1.2 if entry_spread > 30 else 0.8 if entry_spread < 5 else 1.0
```

**Новые поля в MTFContext:**
```python
phase: str                          # "impulse_up/down", "correction_up/down_in_bull/bear"
zone_state: str                     # "cascade_os/ob", "partial_os/ob", "normal"
pattern_name: str                   # именованный паттерн
avoid_reason: Optional[str]         # почему НЕ торговать сейчас
pattern_confidence: float           # 0.0-1.0
```

**DEV задачи (последовательно после верификации TRADER):**
1. DEV-58: Phase detector + cascade detector в `mtf_interpreter.py`
2. DEV-59: avoid_reason в MTFContext + phase-aware guard в `trading_intelligence.py`
3. DEV-60: Named pattern в Telegram формат (`intelligence_formatter.py`)
4. DEV-61: wt_spread → confidence multiplier

**Зависимость:** Сначала TRADER верифицирует паттерны → потом DEV реализует
**ARCH-45 ревью:** ≈06.04.2026 — включить анализ первых паттерн-данных

---

### ARCH-49 — Dynamic OS live comparison: shadow vs fixed на 15m 🟡
**Статус:** ✅ выполнено 24.03.2026 (shadow instrumentation)
**Источник:** TRADER бэктест 24.03.2026 (dyn k=1.2 → Avg R +0.51 на 15m vs fixed -0.18)

**Проблема:** Бэктест показывает значительное улучшение от dynamic OS на 15m (+0.51 vs -0.18), но методология бэктеста вызывает вопросы (расхождение +0.43 vs +0.06 в другом скрипте на 3m). Нельзя менять продакшн-порог без live верификации.

**Решение:** shadow comparison в продакшне 30 дней.

**DEV (без отдельного номера, часть ARCH-49):**
- В `dynamic_thresholds.py` или `analyze_symbol()`: логировать `[DYN-OS]` когда dynamic порог (k=1.2) был бы применён vs текущего fixed
- Формат: `[DYN-OS] symbol: fixed_os=-60 dyn_os=-47.3 triggered=True/False`
- Собирать в features_json для сравнения WR по подгруппам

**Критерии включения через 30 дней:**
- n ≥ 50 сделок где dynamic trigger != fixed trigger
- WR подгруппы `dyn=True, fixed=False` > 35%
- Delta Avg R ≥ +0.2R vs контрольная группа

**Сейчас:** оставить `dynamic_os: shadow` в config.yaml (без изменений)

---

### ARCH-46 — PIVOT_TOUCH staleness: score penalty для устаревших сигналов 🟡
**Статус:** ✅ решено 23.03.2026 — спек готов, передан DEV-55
**Источник:** TRADER 23.03.2026 — разбор GPS/USDT, PIVOT_TOUCH от 1.5ч назад

**Проблема:** `check_pivot_touch()` засчитывает касание пивота если ANY бар в окне коснулся уровня. Если касание было 10+ баров назад — setup устарел, но сигнал всё равно регистрируется.

**Решение: score penalty, не hard block.**

- `staleness_bars: 5` (конфиг) — на 15m = 75 минут TTL
- `score_penalty: -10` к `overall_strength`
- Свежий (≤ 5 баров) → без изменений
- Не hard block: сигнал может быть частью confluence

**Требует от DEV:**
1. В `signal_checkers.py` → `check_pivot_touch()`: добавить `"pivot_bar_index"` в `SignalData.data`
2. В `trading_intelligence.py` → `analyze_symbol()`: применить penalty если `bars_ago > staleness_bars`

**Конфиг:**
```yaml
trading:
  pivot_touch_staleness:
    enabled: true
    staleness_bars: 5
    score_penalty: -10
```

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

### ARCH-39 — DEV-44 guards: перенести ПОСЛЕ вычисления regime? 🟡
**Статус:** ✅ выполнено 24.03.2026 — решение принято, спек передан DEV-46
**Источник:** DEV DISCUSSION 23.03.2026

**Решение ARCH:** Вариант B — перенести DEV-44 guards ПОСЛЕ блока вычисления `regime`.

Обоснование: Проверил код — DEV-44 стоит на строке 498, до вычисления `regime` на строке 531. Для `analyze_symbol` пути `_regime_44 = None` → guards не срабатывают. Это недостаток реализации, не задуманное поведение. Спек ARCH-37 явно требовал "вставлять ПОСЛЕ блока определения `regime`". DEV-46 исправит это: guards переезжают перед `return self.register_trade(...)`, используют вычисленный `regime` напрямую.

---

### ARCH-43 — Решение по max_rr cap: 6.0 → 4.0? 🟡
**Статус:** ✅ решено 23.03.2026 — **max_rr остаётся 6.0, без изменений**
**Источник:** TR-008 TRADER наблюдение (23.03)

**Данные для решения:**
- 89% TP-сделок имеют теоретический RR ≤ 4.0 (медиана = 2.0) → cap=6 не мешает им
- TSL avg=5.54R, median=2.54R → TSL основной механизм профита, TP — страховочный уровень
- pivot_reversal с RR 5-7 реально отрабатывают (ALGO 5.7→R=5.67, FLUID 5.3→R=4.41) → снижение cap до 4.0 режет рабочие сетапы
- 50 SL-сделок из TR-008 — ВСЕ до DEV-35 (cap не был активен) → нерелевантны
- QNT +15.13R via TSL — легитимный moonshot, низкий cap убил бы его на 5-6R

**Решение: max_rr = 6.0, без изменений.**

Корневая причина SL-проблемы (контр-трендовые входы RR>10) уже устранена DEV-32/33.
Повторный анализ: TR-008 через 2 недели с чистыми данными после DEV-32/33.
Если тогда avg_RR у TP-сделок < 4.0 → рассматривать снижение до 5.0.

---

### ARCH-42 — Live Market Stress Gate 🟢
**Статус:** ✅ решено 23.03.2026 — спек передан DEV-48
**Источник:** TR-008 TRADER вопрос (market_event пауза)

**Решение: реализовать как rolling window gate в `register_trade_async()`.**

**Архитектура:**
- `_sl_timestamps` уже существует (DEV-39). Reuse без изменений.
- Проверять в `register_trade_async()` ПЕРЕД Correlation Guard (самый ранний выход).
- Rolling window (не fixed cooldown): gate активен пока в текущем 30-мин окне ≥ N SL.
  Как только старые SL "вышли" из окна — gate открывается автоматически. Никаких таймеров.
- `enabled: false` по умолчанию (shadow mode через log, аналогично DEV-37).

**Config (добавить в `config.yaml`):**
```yaml
trading:
  market_stress_gate:
    enabled: false       # true = блок, false = только лог
    sl_threshold: 5      # SL за window_minutes → активировать gate
    window_minutes: 30   # reuse из market_event_marker
```

**Код для DEV-48 (`core/trade_simulator.py`, `register_trade_async()`, ПЕРЕД DEV-38):**
```python
# ARCH-42: Market Stress Gate — блок входов при массовых SL
try:
    from core.config_loader import config as _cfg_msg
    _msg = (_cfg_msg.get("trading", {}) or {}).get("market_stress_gate", {}) if _cfg_msg else {}
    if _msg:
        _threshold = _msg.get("sl_threshold", 5)
        _window_min = _msg.get("window_minutes", 30)
        _now_msg = datetime.utcnow()
        _window_start_msg = _now_msg - timedelta(minutes=_window_min)
        _recent_sl = [t for t in self._sl_timestamps if t >= _window_start_msg]
        if len(_recent_sl) >= _threshold:
            _sym_msg = _get_recommendation_value(recommendation, "symbol") or ""
            if _msg.get("enabled"):
                logger.info("[ARCH-42] %s БЛОК market_stress: %d SL за %d мин",
                            _sym_msg, len(_recent_sl), _window_min)
                return None
            else:
                logger.info("[ARCH-42] shadow %s: %d SL за %d мин (gate disabled)",
                            _sym_msg, len(_recent_sl), _window_min)
except Exception as _e_msg:
    logger.debug("[ARCH-42] stress gate error: %s", _e_msg)
```

**Почему rolling window, не fixed cooldown:**
- Fixed cooldown (60 мин) → gate закрыт даже если рынок успокоился
- Rolling window → gate закрывается сам как только 5-й SL "протухает" (прошло 30 мин)
- Самовосстановление без доп. состояния

**Приоритет DEV-48:** 🟢 низкий. Запустить в shadow mode (enabled: false) — собрать данные.

---

### ARCH-41 — Финальное решение по DEV-37 (hard_block_mult + enabled) 🟡
**Статус:** ✅ решено 23.03.2026
**Источник:** DEV-42 shadow review 24.03.2026

**Решения:**

1. **hard_block_mult: 3.0 → 2.0** ✅ — 0 hard_block событий за всё время. При tier1≈3.3% медиана, порог 9.9% нереалистичен. Снизить до 6.6%. → DEV-47 (уже создана).

2. **enabled: true — оставить** ✅ — риск низкий (только -10 str penalty, не hard block). 46% penalty на сигналах приемлемо. Перепроверить через 2-3 дня после перезапуска бота с чистыми логами.

3. **Вопрос max_rr (от TRADER)** — не входит в ARCH-41. Создана ARCH-43.

---

### ARCH-40 — Shared pivot_calculator для scan_loop.py 🟢
**Статус:** ✅ выполнено 24.03.2026 — оценка сделана, передано в DEV-46
**Источник:** DEV DISCUSSION 23.03.2026

**Результат проверки масштаба:**
- `bot/loops/scan_loop.py` — уже использует `bot.pivot_calculator` везде. Новых инстансов не создаёт. ✅
- `core/wt_15m_reversal_scanner.py:68` — единственное место: `_pivot_calc = PivotCalculatorFixed()` без db_path. 1 файл, 1 место.

**Решение:** Масштаб < 3 мест. Включить в DEV-46 как минорный пункт: при вызове из `bot/` — передавать `bot.pivot_calculator` как параметр. Если изолированно — низкий приоритет.

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

### DEV-52 — Level 3 Фаза A: L3-lite shadow mode (условия 3+5+6) 🟢
**Статус:** ✅ выполнено 23.03.2026
**Источник:** TR-006 спек (TRADER 23.03.2026) + ARCH решение 23.03.2026

**Цель:** реализовать L3-checker Фаза A в shadow mode — логировать кандидатов без реального входа.

**Условия Фазы A:**
- **Условие 3** — 1h структура не противоположна направлению (BOS/CHoCH check)
- **Условие 5** — effective_score ≥ 85
- **Условие 6** — Портфельный лимит (< 2 LONG, < 2 SHORT, < 4 OPEN)

**Архитектура:**

1. **Портфельный gate** в `register_trade_async()` (~строка до return):
```python
# DEV-52: Портфельный лимит L3
open_trades = self.get_open_trades()
open_longs  = sum(1 for t in open_trades if t['direction'] == 'LONG')
open_shorts = sum(1 for t in open_trades if t['direction'] == 'SHORT')
direction_str = _direction_str(_get_recommendation_value(recommendation, 'direction'))
if direction_str == 'LONG' and open_longs >= 2:
    logger.info("[DEV-52] %s: портфельный лимит LONG (%d/2)", symbol, open_longs)
    return None
if direction_str == 'SHORT' and open_shorts >= 2:
    logger.info("[DEV-52] %s: портфельный лимит SHORT (%d/2)", symbol, open_shorts)
    return None
if len(open_trades) >= 4:
    logger.info("[DEV-52] %s: портфельный лимит TOTAL (%d/4)", symbol, len(open_trades))
    return None
```

2. **Условие 3 (структура 1h)** в `analyze_symbol()` — после DEV-36/37 блоков:
```python
# DEV-52: L3-условие 3 — 1h структура
from core.structure_detector import detect_structure
if data and data.get('1h'):
    df_1h = data['1h']
    struct_1h = detect_structure(df_1h)
    last_break = struct_1h.get('last_break')
    if last_break:
        bars_ago = len(df_1h) - 1 - last_break['break_index']
        is_stale = bars_ago > 48
        is_bearish_bos = last_break.get('type') == 'BOS' and last_break.get('direction') == 'BEARISH'
        is_bullish_bos = last_break.get('type') == 'BOS' and last_break.get('direction') == 'BULLISH'
        if not is_stale:
            if direction == 'LONG' and is_bearish_bos:
                # HARD BLOCK: BEARISH_BOS против LONG
                logger.info("[DEV-52-L3] %s БЛОК: BEARISH_BOS против LONG на 1h", symbol)
                # shadow: пока не блокируем, только логируем
            elif direction == 'SHORT' and is_bullish_bos:
                logger.info("[DEV-52-L3] %s БЛОК: BULLISH_BOS против SHORT на 1h", symbol)
```

3. **Условие 5 (effective_score ≥ 85)** — уже есть как `overall_strength`. Пока shadow mode → просто логируем кандидатов.

**Shadow mode:** `enabled: false` по умолчанию. При `enabled: false` — только INFO лог `[DEV-52-L3] candidate 5/6 conds`.

**Config:**
```yaml
trading:
  l3_checker:
    enabled: false   # shadow mode → true после накопления статистики
    min_score: 85
    max_open_long: 2
    max_open_short: 2
    max_open_total: 4
```

**Файлы:** `core/trade_simulator.py`, `core/trading_intelligence.py`, `config.yaml`

**Фаза B (DEV-53):** +условие 4 (WT кросс freshness + near_pivot) — после DEV-52
**Фаза C (DEV-54):** +условия 1+2 (FVG/OB 4h + Fibonacci OTE) — заблокировано (нет multi-TF SMC)

---

### DEV-53 — Level 3 Фаза B: +условие 4 (WT кросс freshness + near_pivot) 🟢
**Статус:** 🟢 в плане — после DEV-52 ✅
**Источник:** TR-006 спек (TRADER 23.03.2026)

**Цель:** расширить L3 shadow mode условием 4: WT кросс должен быть свежим (≤3 баров назад) И цена вблизи пивота.

**Условие 4 — 15m WT кросс в зоне + пивот:**
```python
# LONG: wt1 пересекает wt2 снизу вверх при wt1_prev < -60 (OS)
# SHORT: wt1 пересекает wt2 сверху вниз при wt1_prev > 60 (OB)
# Свежесть: кросс произошёл <= 3 баров 15m назад (45 мин)
tier1 = max(1.0%, min(ATR_15m * 1.5, 5.0%))  # TR-004 формула
cond4 = (wt_cross_bars_ago <= 3) and (dist_to_pivot < tier1_pct)
```

**Реализация:**
1. `core/signal_checkers.py` — добавить `wt_cross_bar_index` в `SignalData.data` для wt_signal
2. `core/trading_intelligence.py` → L3-checker блок — добавить cond4:
```python
wt_cross_bars_ago = len(df_15m) - 1 - wt_sig.data.get("wt_cross_bar_index", 0)
near_piv = recommendation.metadata.get("dist_pivot_pct", 999) < tier1_pct
cond4 = (wt_cross_bars_ago <= 3) and near_piv
```

**Файлы:** `core/signal_checkers.py`, `core/trading_intelligence.py`
**Зависит от:** DEV-52 ✅

**Дополнение ARCH 25.03 (TR-007 → ARCH):** При переходе к production (Фаза B) добавить CHoCH soft block:
```python
# В L3-checker блоке, после cond3 проверки:
elif _brk_type_52 == "CHOCH" and _brk_dir_52 != _dir_52ti:
    overall_strength -= 8  # CHoCH soft block (TR-006 спек)
    _cond3_note = f"CHOCH_soft_penalty {_bars_ago_52}bars"
```
Отличие от BOS: BOS → `cond3=False` (жёсткий блок), CHoCH → `-8 str` (мягкий, сделка проходит).

---

### DEV-58 — ARCH-48 Фаза B: Weekly Bias production gate ✅
**Статус:** ✅ реализовано 24.03.2026 — код готов, включить: `weekly_bias_filter.enabled: true` в config.yaml
**Источник:** ARCH-48 решение 24.03.2026

**Условие включения:** вручную через config.yaml (порог ≥100 сделок — рекомендация, не ограничение в коде)

**Что реализовать:**

В `core/trading_intelligence.py` → `analyze_symbol()`, внутри блока ARCH-48 (after shadow log), добавить production gate когда `enabled: true`:
```python
if _wcfg.get("enabled") and _gate_block_48:
    _penalty_48 = int(_wcfg.get("soft_penalty", 25))
    _near_pct_48 = float(_wcfg.get("near_level_pct", 1.5)) / 100
    _hard_ctx = int(_wcfg.get("hard_block_ctx_score", 3))
    _weekly_r1_48 = (_weekly_bias_meta.get("weekly_r1")) if "_weekly_bias_meta" in dir() else None
    _weekly_s1_48 = (_weekly_bias_meta.get("weekly_s1")) if "_weekly_bias_meta" in dir() else None
    _near_r = _weekly_r1_48 and abs(current_price - _weekly_r1_48) / current_price < _near_pct_48
    _near_s = _weekly_s1_48 and abs(current_price - _weekly_s1_48) / current_price < _near_pct_48

    if _dir_48 == "LONG" and _weekly_bias_48 == "BEARISH" and not _near_s:
        if _ctx_score_48 >= _hard_ctx:
            recommendation.action = "WATCH"
            logger.info("[ARCH-48] %s hard block ctx=%d LONG/BEARISH", symbol, _ctx_score_48)
        else:
            overall_strength -= _penalty_48
    elif _dir_48 == "SHORT" and _weekly_bias_48 == "BULLISH" and not _near_r:
        overall_strength -= _penalty_48
```

**Дополнительно (TRADER Q2):** добавить ctx_score проверку в `bot/loops/scan_loop.py::_handle_wl_breach_entry()` — WL breach НЕ проходит через `analyze_symbol()` → shadow mode DEV-56 его не видел:
```python
# В _handle_wl_breach_entry(), перед register_trade:
_wbcfg = cfg.get("trading", {}).get("weekly_bias_filter", {})
if _wbcfg.get("enabled"):
    # вычислить weekly_bias и ctx_score аналогично DEV-56
    # если ctx_score == hard_block_ctx_score и direction конфликтует → return
```

В `config.yaml` изменить: `weekly_bias_filter.enabled: true`

**Файлы:** `core/trading_intelligence.py`, `bot/loops/scan_loop.py`, `config.yaml`
**Зависит от:** DEV-56 ✅ + ≥3 дней данных Фазы A

---

### DEV-60 — use_be_after_tp1: BE только для MULTI_TP после TP1 hit ✅
**Статус:** ✅ реализовано 24.03.2026
**Источник:** TRADER 24.03.2026 решение + ARCH одобрение 24.03.2026

**Зачем:** `use_breakeven: false` отключает BE глобально. После TP1 hit у MULTI_TP — BE = доп. защита (floor у entry+0.1%) независимо от глобального флага.

**Что реализовать:**

1. `config.yaml`:
```yaml
trading:
  use_be_after_tp1: false  # default: off (TSL защищает остаток)
```

2. `core/trade_simulator.py` → `check_open_trades_with_tsl()`, около строк 900-910:
```python
_use_be_tp1 = (self.config.get("trading", {}) or {}).get("use_be_after_tp1", False)
_tp1_be_trigger = (tp1_hit_at is not None and _is_multi_tp_be and _use_be_tp1)
if (use_breakeven or _use_be_tp1) and not be_activated and sl is not None and (
    (use_breakeven and current_r is not None and current_r >= breakeven_activation_r)
    or _tp1_be_trigger
):
```

**Файлы:** `config.yaml`, `core/trade_simulator.py`
**Приоритет:** 🟢 — реализовать после DEV-59 и DEV-58

---

### DEV-59 — pivot_reversal R:R cap: применить max_rr к SL/TP вычислению ✅
**Статус:** ✅ реализовано 24.03.2026
**Источник:** TRADER TR-007 анализ 24.03.2026 — данные БД id>3100

**Проблема:** `max_rr=6.0` (DEV-35) реализован в `recommendation_generator.py::calculate_levels()`. pivot_reversal стратегия вычисляет SL/TP по отдельному code path — cap не проходит.

**Данные из БД** (pivot_reversal, id>3100):
- XMR LONG TREND_UP: R:R=17.7x (TP=19.1%, SL=1.08%)
- SQD LONG TREND_UP: R:R=23.6x (TP=30.7%)
- HUMA LONG TREND_UP: R:R=19.4x (TP=38.8%)
- Итог: WR=9.1% (1/11) — TP недостижимо, SL срабатывает на первом откате

**Фикс:** найти где pivot_reversal устанавливает `take_profit` и добавить ограничение:
```python
max_rr = cfg.get("trading", {}).get("sl_management", {}).get("max_rr", 6.0)
rr = abs(tp_price - entry_price) / abs(entry_price - sl_price)
if rr > max_rr:
    tp_price = entry_price + max_rr * abs(entry_price - sl_price) * (1 if is_long else -1)
```
Применить к обеим сторонам: LONG + SHORT.

**Файлы:** `core/pivot_reversal.py`, `core/trading_intelligence.py` (где формируется TP для pivot_reversal)
**Приоритет:** 🔴 — объясняет WR=9.1% у pivot_reversal за последнюю неделю

---

### DEV-57 — BE activation: tp1_hit_at как безусловный триггер breakeven 🔴
**Статус:** ✅ выполнено 24.03.2026
**Источник:** TRADER анализ UMA/USDT id=3163 (24.03.2026), ARCH одобрение (24.03.2026)

**Проблема:** `be_activated` остаётся 0 если трекер запустился ПОСЛЕ того как цена уже отошла от TP1. BE check смотрит на `current_r >= 0.5R`, а TP1 была взята в прошлом.

**Факты:**
- UMA id=3163: TP1 hit 15:00 UTC, be=0, закрылась по SL 20:37 UTC
- 3 открытые позиции сейчас в том же состоянии (KITE/TRB/KAVA, защищены TSL)

**Фикс (`core/trade_simulator.py` ~строка 886-891):**

Добавить вычисление `_is_multi_tp` ДО BE check (сейчас он стоит на строке 916):

```python
# ПЕРЕД строкой 889 (BE check):
_strategy_type_early = trade.get("strategy_type", "SINGLE")
_is_multi_tp_be = _strategy_type_early in ("DUAL_TP", "TRIPLE_TP_TSL")

# Строка 891 — изменить условие:
tp1_be_trigger = (tp1_hit_at is not None and _is_multi_tp_be)
if use_breakeven and not be_activated and (current_r >= breakeven_activation_r or tp1_be_trigger) and sl is not None:
```

**Где брать `tp1_hit_at` на этом этапе:** загружается из `trade.get("tp1_hit_at")` — значит из `get_open_trades()` query. Проверить что `tp1_hit_at` включён в SELECT в `get_open_trades()`.

**Размер изменения:** ~3 строки. Минимальный риск.

**Приоритет:** 🔴 — каждый цикл трекера теряет BE защиту для TP1-hit позиций

---

### DEV-56 — ARCH-48 Weekly Bias Filter Фаза A: shadow mode 🔴
**Статус:** ✅ выполнено 24.03.2026
**Источник:** ARCH-48 решение 24.03.2026 — TRADER запрос top-down контекста

**Цель:** добавить `weekly_bias` в pipeline как shadow-only наблюдатель. Никаких изменений в фильтрации сделок — только запись данных и логирование потенциальных блоков.

**Точка вставки:** `core/trading_intelligence.py` → `analyze_symbol()`, после `_calculate_adaptive_weighted_strength()`, перед `_generate_recommendation()`.

**Источник данных:** `mtf_context.weekly_pivots` и `mtf_context.monthly_pivots` / `mtf_context.daily_pivots` — уже загружены в `_build_mtf_context()`.

**Что реализовать:**

1. **`core/trading_intelligence.py`** → `analyze_symbol()`:
```python
# ARCH-48: Weekly Bias Filter — Фаза A shadow
try:
    from core.config_loader import config as _cfg_a48
    _wcfg = (_cfg_a48.get("trading", {}) or {}).get("weekly_bias_filter", {}) if _cfg_a48 else {}
    _weekly_pp = (mtf_context.weekly_pivots or {}).get("PP") if mtf_context else None
    if _weekly_pp and current_price:
        _weekly_bias = "BULLISH" if current_price > _weekly_pp else "BEARISH"
        _monthly_pp = (mtf_context.monthly_pivots or {}).get("PP") if mtf_context else None
        _daily_pp   = (mtf_context.daily_pivots or {}).get("PP") if mtf_context else None
        _ctx_score  = sum([
            bool(_monthly_pp and current_price < _monthly_pp),
            bool(_weekly_pp  and current_price < _weekly_pp),
            bool(_daily_pp   and current_price < _daily_pp),
        ])
        _dir_str = direction.value if hasattr(direction, "value") else str(direction)
        _gate_block = (
            (_dir_str in ("LONG", "long")  and _weekly_bias == "BEARISH") or
            (_dir_str in ("SHORT", "short") and _weekly_bias == "BULLISH")
        )
        # Shadow: только лог, не меняем фильтрацию
        if _gate_block:
            logger.info("[ARCH-48 shadow] %s: direction=%s would_block=True weekly_bias=%s ctx_score=%d",
                        symbol, _dir_str, _weekly_bias, _ctx_score)
        # Сохранить для features_json
        _weekly_bias_meta = {
            "weekly_bias": _weekly_bias,
            "weekly_context_score": _ctx_score,
            "weekly_gate_would_block": _gate_block,
        }
        # Добавить к metadata рекомендации если есть:
        if hasattr(recommendation, "metadata") and isinstance(recommendation.metadata, dict):
            recommendation.metadata.update(_weekly_bias_meta)
except Exception as _e48:
    logger.debug("[ARCH-48] weekly bias error: %s", _e48)
```

2. **`core/trade_simulator.py`** → `register_trade_async()`: убедиться что `metadata` из recommendation попадает в `features_json`. Если уже работает — ничего не менять. Если нет — добавить merge.

3. **`config.yaml`**:
```yaml
trading:
  weekly_bias_filter:
    enabled: false           # Фаза A: false (shadow). Фаза B: true
    soft_penalty: 25
    hard_block_ctx_score: 3
    near_level_pct: 1.5
```

**Проверка результата:** через 1-2 дня в `features_json` сделок должны появиться поля `weekly_bias`, `weekly_context_score`, `weekly_gate_would_block`. Проверить:
```sql
SELECT features_json FROM simulated_trades ORDER BY id DESC LIMIT 5;
```

**Файлы:** `core/trading_intelligence.py`, `config.yaml`, (опционально) `core/trade_simulator.py`
**Зависит от:** ARCH-38 (singleton pivot_calc, DEV-45 ✅)
**Следующий шаг:** DEV-58 (Фаза B production gate) — после анализа ≥ 3 дней данных (≈27-29.03)

---

### DEV-55 — PIVOT_TOUCH staleness: score penalty для устаревших касаний пивота 🟡
**Статус:** ✅ выполнено 25.03.2026
**Источник:** ARCH-46 решение 23.03.2026 + TRADER наблюдение GPS/USDT

**Проблема:** `check_pivot_touch()` засчитывает касание если ANY бар в окне коснулся пивота. Если касание было 10+ баров назад — setup устарел, сигнал фантомный.

**Что сделать:**

1. **`core/signal_checkers.py`** → `check_pivot_touch()`:
   Сохранить индекс бара касания:
   ```python
   signal_data["pivot_bar_index"] = bar_index  # индекс последнего касания
   ```

2. **`core/trading_intelligence.py`** → `analyze_symbol()`, после сбора сигналов:
   ```python
   # ARCH-46: PIVOT_TOUCH staleness penalty
   _pt_cfg = (config.get("trading", {}) or {}).get("pivot_touch_staleness", {})
   if _pt_cfg.get("enabled") and df is not None:
       _staleness = _pt_cfg.get("staleness_bars", 5)
       _penalty = _pt_cfg.get("score_penalty", -10)
       for sig in filtered_signals:
           if sig.signal_type == "pivot_touch":
               _bars_ago = len(df) - 1 - sig.data.get("pivot_bar_index", 0)
               if _bars_ago > _staleness:
                   overall_strength += _penalty
                   logger.warning("[ARCH-46] %s PIVOT_TOUCH stale: %d баров (penalty %d)",
                                  symbol, _bars_ago, _penalty)
   ```

3. **`config.yaml`**:
   ```yaml
   trading:
     pivot_touch_staleness:
       enabled: true
       staleness_bars: 5
       score_penalty: -10
   ```

**Файлы:** `core/signal_checkers.py`, `core/trading_intelligence.py`, `config.yaml`

---

### DEV-51 — Установить sklearn: ML pipeline полностью отключён 🟡
**Статус:** ✅ выполнено 23.03.2026 — `scikit-learn>=1.3.0` добавлен в requirements.txt
**Источник:** ARCH-45 baseline 23.03.2026 — обнаружено при запуске OutcomePredictor

**Проблема:** `sklearn` не установлен в окружении → весь ML pipeline (OutcomePredictor, RPredictor, MLPredictor) работает в dummy-режиме:
```
OutcomePredictor: sklearn не установлен — predict_win_prob вернёт None
```

**Что проверить:**
```bash
# Какое окружение использует бот?
which python3
python3 -c "import sklearn; print(sklearn.__version__)"
# Если не найден:
pip install scikit-learn
# или
pip3 install scikit-learn
```

**Файл:** `requirements.txt` → убедиться что `scikit-learn` есть (уже должен быть по CLAUDE.md).
**Примечание:** CLAUDE.md говорит `pip install scikit-learn` — значит в продакшн окружении должен быть. Проверить что бот запускается из правильного venv.

**Ожидаемый эффект после установки:**
- OutcomePredictor обучится и начнёт давать P(win)
- Adaptive confidence blending 0.7×orig + 0.3×P(win) заработает
- ARCH-45 финальный ревью станет возможным

**Приоритет:** 🟡 важно — без этого AUC-триггер для ARCH-21 никогда не сработает.

---

### DEV-49 — Timezone bug: created_at + trade_tracker fallback ✅
**Статус:** ✅ выполнено 25.03.2026
**Источник:** TRADER расследование 23.03.2026 — обнаружен при разборе GPS/USDT id=3155

**Масштаб:** 754 из 3059 закрытых сделок (24.6%) закрыты phantom-баром ДО входа.
WR искажён: отображается 31.5% → реальный 36.8% (+5.3pp скрыто).

**Два независимых бага:**

**Баг #1 — created_at сохраняется в LOCAL time (UTC+3) с суффиксом +00:00:**
```python
# БЫЛО (баг): datetime.now() — возвращает локальное время машины
created_at = datetime.now()  # UTC+3, но сохраняется как UTC

# НАДО:
from datetime import timezone
created_at = datetime.now(timezone.utc)
```
Искать в `core/trade_simulator.py` → `register_trade()` и `register_trade_async()`.
Также проверить `bot/` и любые места записи временны́х меток в simulated_trades.

**Баг #2 — fallback df.iloc[-5:] в trade_tracker захватывает pre-entry бары:**
```python
# БЫЛО (баг в core/trade_simulator.py ~строка 837):
df = df_filtered if len(df_filtered) > 0 else df.iloc[-5:].copy()
# При timezone-баге фильтр пустой → fallback → бары ДО входа → phantom SL/TP

# НАДО: если фильтр пустой — пропустить чек, не использовать fallback
if len(df_filtered) == 0:
    logger.warning("[trade %d] нет баров после created_at (%s) — пропуск чека", trade_id, created_at)
    continue
df = df_filtered
```

**Файлы:**
- `core/trade_simulator.py` — оба бага
- Проверить все места `datetime.now()` → заменить на `datetime.now(timezone.utc)`

**После фикса:**
- Пересчитать/пометить 754 баг-сделки в БД: добавить поле или пометить `data_quality=bug_timezone`
- id=3161 (SQD), id=3163 (UMA) — OPEN сделки с timezone-багом в created_at, исправить вручную или пересчитать при следующей проверке
- Исключить баг-сделки из ML обучения (OutcomePredictor, adaptive weights)

**Что сделано:**

**Фикс #1** — `core/trade_simulator.py` строка ~259:
```python
# БЫЛО (баг):
ts = ts.replace(tzinfo=timezone.utc)   # навешивает метку без конвертации

# СТАЛО (фикс):
ts = ts.astimezone(timezone.utc)       # конвертирует из LOCAL → UTC
```
Naive datetime 16:12 (UTC+3) → правильно сохраняется как 13:12 UTC.

**Фикс #2** — `core/trade_simulator.py` строка ~837:
```python
# БЫЛО (баг): fallback → pre-entry бары → phantom SL/TP
df = df_filtered if len(df_filtered) > 0 else df.iloc[-5:].copy()

# СТАЛО (фикс): при пустом фильтре — пропустить чек
if len(df_filtered) == 0:
    logger.warning("[trade %d] нет баров после created_at (%s) — пропуск чека SL/TP", ...)
    continue
df = df_filtered
```

**Оставшееся (отдельная задача):**
- Пометить 754 баг-сделки в БД (data_quality=bug_timezone) — исключить из ML
- id=3161 (SQD), id=3163 (UMA) — OPEN с bug created_at, закроются корректно после фикса

---

### DEV-48 — Market Stress Gate: реализация shadow mode ✅
**Статус:** ✅ выполнено 24.03.2026
**Источник:** ARCH-42 спек (23.03.2026)

**Что сделать:** добавить ARCH-42 gate в `register_trade_async()` ПЕРЕД DEV-38 Correlation Guard.

**Файлы:**
- `core/trade_simulator.py` — добавить блок в `register_trade_async()` (код в ARCH-42 спеке)
- `config.yaml` — добавить секцию:
```yaml
trading:
  market_stress_gate:
    enabled: false
    sl_threshold: 5
    window_minutes: 30
```

**Важно:** `_sl_timestamps` уже есть (DEV-39). Новый импорт `timedelta` добавить если нет.
Запустить в shadow mode (`enabled: false`) — только лог `[ARCH-42] shadow`.

---

### DEV-47 — Снизить hard_block_mult 3.0 → 2.0 ✅
**Статус:** ✅ выполнено 24.03.2026
**Источник:** ARCH-41 / DEV-42 shadow review

**Что:** `config.yaml` → `trading.pivot_proximity_filter.hard_block_mult: 2.0` (было 3.0).
За всё время наблюдения hard_block=0. При tier1≈3.3% медиана — текущий порог 9.9% нереалистичен. Снизить до 6.6%.

**Файл:** `config.yaml` → 1 строка.

---

### DEV-50 — OutcomePredictor: фильтрация data_quality=bug_timezone ✅
**Статус:** ✅ выполнено (25.03.2026)
**Источник:** ARCH ответ DEV-49 (25.03.2026)

**Зачем:** 948 сделок помечены `features_json["data_quality"]="bug_timezone"` (DEV-49). Признаки в OutcomePredictor не временные → текущего влияния нет. **Риск:** при активации ARCH-21 sliding window (training_window=500) эти 948 баг-сделок могут доминировать в обучающей выборке.

**Что сделать:** в `OutcomePredictor.fit()` в цикле (~строка 128), сразу после парсинга `fj`:

```python
# DEV-50: исключаем баг-данные timezone из обучения (948 сделок до 25.03)
if fj.get("data_quality") == "bug_timezone":
    continue
```

**Файл:** `core/outcome_predictor.py` строка ~130.

**Приоритет:** 🟢 низкий — реализовать до активации ARCH-21 sliding window (не блокер сейчас).

---

### DEV-46 — Перенести DEV-44 guards ПОСЛЕ вычисления `regime` ✅
**Статус:** ✅ выполнено 23.03.2026
**Источник:** ARCH-39 решение 24.03.2026

**Проблема:** DEV-44 guards в `register_trade_async()` вставлены ДО вычисления `regime` (строка 498 vs строка 531). Для `analyze_symbol` пути `_regime_44 = None` → guards по режиму не срабатывают. Для WL breach (SimpleNamespace с `regime`) — работают. Это недостаток реализации.

**Что сделать:**

1. Удалить текущий DEV-44 блок (`core/trade_simulator.py` строки ~498-529)

2. Вставить guards ПЕРЕД `return self.register_trade(...)` (~строка 543), используя вычисленный `regime`:

```python
# ARCH-37 второй рубеж — все code-paths (analyze_symbol + WL breach + будущие)
try:
    from core.config_loader import config as _cfg_a37
    if _cfg_a37 and regime:
        _sym_a37 = _get_recommendation_value(recommendation, "symbol") or ""
        _dir_a37 = str(_get_recommendation_value(recommendation, "direction") or "").upper()
        # DEV-33 fallback: blocked_regimes
        _br = _cfg_a37.get("trading.blocked_regimes", [])
        if regime in _br:
            logger.info("[ARCH-37] %s: второй рубеж — %s в blocked_regimes", _sym_a37, regime)
            return None
        # DEV-32 fallback: regime_direction_block
        _rdb = _cfg_a37.get("trading.regime_direction_block", {})
        if _rdb.get("enabled") and _dir_a37:
            _blocked = _rdb.get(regime)
            if _blocked and _dir_a37 == _blocked:
                logger.info("[ARCH-37] %s: второй рубеж — %s блокирует %s", _sym_a37, regime, _dir_a37)
                return None
except Exception as _e_a37:
    logger.debug("[ARCH-37] guard error: %s", _e_a37)

return self.register_trade(recommendation, regime=regime, extra_features=extra_features)
```

3. (Минор) `core/wt_15m_reversal_scanner.py:68` — `_pivot_calc = PivotCalculatorFixed()` без db_path. Проверить как вызывается; если из `bot/` — принять `pivot_calc` параметром снаружи. Если изолирован — пропустить.

**Файлы:** `core/trade_simulator.py`

**Проверка после:** убедиться что для теста `analyze_symbol` пути (HIGH_VOL) trade не регистрируется (guard срабатывает через MarketRegime).

---

### DEV-42 — DEV-37 shadow review → включить ✅
**Статус:** ✅ выполнено 23.03.2026
**Источник:** ARCH (DISCUSSION 23.03) + DEV наблюдение

**Результат анализа логов (crypto_bot.log, 23.03 + 24.03):**
- 23.03: 48 событий (near=26, penalty=22, hard_block=0) → enabled: true
- 24.03 (повторный замер): 83 события (near=46/55%, penalty=37/45%, hard_block=0/0%)
- hard_block стабильно = 0%. Фильтр работает корректно, жёсткой блокировки нет.
- **Статус: закрыт.** `pivot_proximity_filter.enabled: true` — оставить как есть.

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

### DEV-45 — Singleton PivotCalculatorFixed в TradingIntelligence ✅
**Статус:** ✅ выполнено 23.03.2026
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

### DEV-46 — Перенести DEV-44 guards ПОСЛЕ вычисления regime ✅
**Статус:** ✅ выполнено 23.03.2026
**Источник:** ARCH-39 решение (24.03.2026)

**Проблема:** DEV-44 guard читает `_regime_44` из `rec.regime` → всегда `None` → **guards мёртвые** для всех путей. Нужно перенести ПОСЛЕ `regime = MarketRegimeClassifier.classify_from_ohlcv(...)`.

**Что сделать в `core/trade_simulator.py`, `register_trade_async()`:**

1. Удалить текущий DEV-44 блок (строки ~498–529, до `regime: Optional[str] = None`)

2. Вставить ПОСЛЕ строки ~510 (после `except Exception as e: logger.debug("MarketRegime...")`):

```python
        # DEV-44 (ARCH-39 fix): Safety gate — второй рубеж, использует свежий regime
        if regime:
            try:
                from core.config_loader import config as _cfg_44
                if _cfg_44:
                    _sym_44 = _get_recommendation_value(recommendation, "symbol") or ""
                    _dir_44 = _direction_str(_get_recommendation_value(recommendation, "direction"))
                    # Guard 1: blocked_regimes (DEV-33 fallback)
                    if regime in (_cfg_44.get("trading.blocked_regimes") or []):
                        logger.info("[DEV-44] %s БЛОК blocked_regime: %s", _sym_44, regime)
                        return None
                    # Guard 2: regime_direction_block (DEV-32 fallback)
                    _rdb = _cfg_44.get("trading.regime_direction_block") or {}
                    if _rdb.get("enabled") and _rdb.get(regime) == _dir_44:
                        logger.info("[DEV-44] %s БЛОК regime_direction: %s/%s", _sym_44, regime, _dir_44)
                        return None
            except Exception as _e44:
                logger.debug("[DEV-44] Safety gate error: %s", _e44)
```

**Дополнительно (ARCH-40):** в `core/wt_15m_reversal_scanner.py:68` заменить `PivotCalculatorFixed()` на переданный экземпляр или `bot.pivot_calculator` при вызове из `bot/`.

**Файлы:** `core/trade_simulator.py`, `core/wt_15m_reversal_scanner.py`

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
