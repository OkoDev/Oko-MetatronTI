# Oko MTF — Энциклопедия проекта

> Живой справочник. Пополняется по мере работы над проектом.
> Формат: идея → реализация → где используется → подводные камни.

---

## 🔴 ОБЯЗАТЕЛЬНО К ПРОЧТЕНИЮ ВСЕМ РОЛЯМ

> **Раздел "Архитектурная концепция: Куб Метатрона"** — фундаментальная концепция проекта.
> Все архитектурные решения, задачи и рефакторинги должны соответствовать этой концепции.
> Без понимания Куба нельзя принимать архитектурные решения.

---

## Навигация

- [🔷 Архитектурная концепция: Куб Метатрона](#архитектурная-концепция-куб-метатрона) ← ЧИТАТЬ ПЕРВЫМ
- [Типы сигналов (SignalType)](#типы-сигналов-signaltype)
- [Стратегии](#стратегии)
- [Ключевые концепции](#ключевые-концепции)
- [Ключевые модули](#ключевые-модули)
- [Параметры конфига](#параметры-конфига)

---

## Архитектурная концепция: Куб Метатрона

> **Принята:** 02.04.2026 | **Автор:** TRADER + ARCH | **Статус:** Основная концепция проекта
> **ARCH-67** — задача реализации полного Куба
> **Обязательно к прочтению:** DEV, ARCH, TRADER перед любой архитектурной задачей

---

### Откуда концепция

Куб Метатрона — фигура сакральной геометрии: **13 сфер**, соединённых линиями так, что каждая сфера связана с каждой другой напрямую. Внутри куба вписаны все 5 Платоновых тел. Ключевые свойства: полная связность (mesh), централизованное ядро, иерархия уровней абстракции, самодостаточность каждого модуля при единстве системы.

Мы применяем эту геометрию как **архитектурный принцип** торгового бота.

---

### Почему не конвейер

Текущая архитектура (и большинство торговых систем) — **линейный конвейер**:

```
данные → детекторы → агрегация → решение → исполнение → забыто
```

Проблемы конвейера которые мы наблюдаем на данных:
- **Stateless**: каждый проход по паре начинается с нуля, система не помнит что 2 часа назад TSL закрыл позицию
- **Слепые зоны**: получили аномалию объёма → не проверили дивергенции, пивоты, структуру
- **Нет переключения режимов**: рынок разворачивается (31.03 данные), система продолжает торговать тренд → confluence WR падает с 29% до 17% за один день
- **Изолированные узлы**: MTF WT данные есть, но Exit Manager их не видит; PostTradeAnalyser есть, но не кормит ML

**Куб решает это через mesh-связность:** любое событие достигает всех узлов одновременно через Shared Context Bus.

---

### Центральная сфера — Shared Context Bus

```python
# core/context/pair_context.py → НУЖНО РАСШИРИТЬ до pub/sub шины
# Сейчас: простое хранилище cascade_count, last_direction
# Цель: полная pub/sub шина

class SharedContextBus:
    """
    Центральная сфера Куба.
    Каждый модуль публикует свои выводы.
    Каждый модуль подписан на события других.
    Per-pair живое состояние всей системы.
    """
    def publish(self, symbol: str, event_type: str, data: dict) → None
    def subscribe(self, event_type: str, handler: Callable) → None
    def get_state(self, symbol: str) → PairFullState
```

**Что хранится в шине (per pair):**
```python
@dataclass
class PairFullState:
    symbol: str
    # Layer 0 — данные
    last_ohlcv_snap: dict          # последний снапшот OHLCV по TF
    last_tick_price: float         # цена из WS
    # Layer 1 — детекторы (последние результаты)
    wt_snap: dict                  # wt1/wt2/zone/cross/atr_trend по всем TF
    smc_snap: dict                 # OB/FVG/CHoCH/BOS/OTE/EQH/EQL по TF
    divergence_snap: dict          # активные дивергенции
    anomaly_snap: dict             # аномалия объёма last check
    pivot_snap: dict               # уровни 1W/1D/1M
    structure_snap: dict           # CHoCH/BOS статус
    # Layer 2 — контекст
    regime: str                    # TREND_UP/DOWN/RANGE/HIGH_VOL
    regime_mode: str               # TREND/REVERSAL (новый)
    cross_market: dict             # BTC 4h, USDT.D, Dominance
    # ML специалисты
    mtf_wt_verdict: str            # TREND/REVERSAL/EXHAUSTION
    mtf_wt_confidence: float
    mtf_smc_verdict: str           # STRONG_BULL/WEAK/BEAR_ZONE
    mtf_smc_confidence: float
    # История пары
    cascade_count: int
    avg_r_cascade: float
    last_direction: str
    last_close_status: str         # TSL/SL/TP
    post_tsl_data: dict            # OTE зона после TSL
    # Нарратив
    last_narrative: str            # последний нарратив Narrative Builder
    last_signal_time: datetime
```

---

### 12 сфер — модули системы

Вокруг центральной шины — 12 самодостаточных модулей. Каждый читает из шины и публикует обратно.

#### Сфера 1 — DataCollector
```
Файл:    core/infra/data_collector.py
Статус:  ✅ активен
Функция: OHLCV + ticker с BingX через ccxt
Публикует в шину: ohlcv_snap per TF
Читает из шины:  ничего (источник данных)
Проблема: polling каждые 60 сек → Сфера 2 (WS) исправит
```

#### Сфера 2 — WSFeed (Real-time)
```
Файл:    core/infra/ws_feed.py
Статус:  ⚠️ файл есть, НЕ ПОДКЛЮЧЁН
Функция: WebSocket тики в реальном времени
Публикует в шину: tick_price, volume_spike (немедленно)
Читает из шины:  список пар для подписки
Важность: триггер для немедленного Full CALL при аномалии объёма
```

#### Сфера 3 — MTF WT Specialist (ML)
```
Файл:    core/ml/mtf_wt_specialist.py  ← ОТСУТСТВУЕТ
Статус:  ❌ нужно создать
Функция: ML модель обученная исключительно на MTF WT данных
Входные признаки (35): 7 TF × {wt1, wt2, zone, wt_cross, atr_trend}
  TF: 1d, 4h, 1h, 45m, 15m, 5m, 3m
  wt1 (float)       — значение WaveTrend 1
  wt2 (float)       — значение WaveTrend 2
  zone (-1/0/1)     — OS / Normal / OB
  wt_cross (-1/0/1) — медвежий / нет / бычий кросс
  atr_trend (1/-1)  — направление ATR-тренда из calculate_trend()
                      это TSL линия — ключевой контекст для WT сигнала!
Выход: TREND_CONTINUATION / REVERSAL_SETUP / EXHAUSTION / UNCLEAR
       + confidence 0.0-1.0
Обучение: labeled примеры из simulated_trades
  X = mtf_wt_snap из features_json
  y = TP(1) / SL(0) / исход
Публикует в шину: mtf_wt_verdict, mtf_wt_confidence
Читает из шины:  wt_snap (обновлённый DataCollector-ом)
Почему отдельная модель: текущий mtf_interpreter.py даёт одну цифру
  "76% медвежий" — это потеря 27 из 28 признаков
```

#### Сфера 4 — MTF SMC Specialist (ML)
```
Файл:    core/ml/mtf_smc_specialist.py  ← ОТСУТСТВУЕТ
Статус:  ❌ нужно создать
Функция: ML модель на структурном контексте по всем TF
Входные признаки (36): 4 TF × 9 признаков
  TF: 1d, 4h, 1h, 15m
  Признаки per TF:
    ob_bull (bool)          — бычий Order Block активен
    ob_distance_pct (float) — расстояние до OB в %
    fvg_open (bool)         — незакрытый Fair Value Gap
    choch (bool)            — Change of Character (последние N баров)
    bos (bool)              — Break of Structure
    ote_zone (bool)         — цена в OTE зоне Фибоначчи [0.705-0.786]
    eqh_near (bool)         — Equal Highs в радиусе 1% (ликвидность сверху)
    eql_near (bool)         — Equal Lows в радиусе 1% (ликвидность снизу)
    liquidity_above (bool)  — пул ликвидности выше цены
Выход: STRONG_BULL_ZONE / WEAK_ZONE / STRONG_BEAR_ZONE / NEUTRAL
       + confidence 0.0-1.0
Обучение: аналогично MTF WT Specialist
Публикует в шину: mtf_smc_verdict, mtf_smc_confidence
Читает из шины:  smc_snap

Примечание про EQH/EQL:
  Equal Highs = несколько максимумов на одном уровне = ликвидность
  Маркетмейкер БУДЕТ sweep этот уровень прежде чем развернуться
  EQH на 1h + OTE на 15m = классический stop hunt setup → SHORT setup
  EQL на 1h + OTE на 15m = liquidity grab → LONG setup
  Детектор: нет в проекте, нужно добавить в core/smc/liquidity.py
```

#### Сфера 5 — Cross-Market Node
```
Файл:    core/indicators/cross_market.py  ← ОТСУТСТВУЕТ
Статус:  ⚠️ DEV-111 partial (только BTC 4h shadow)
Функция: макроконтекст который применяется ко ВСЕМ парам
Источники данных:
  BTC/USDT 4h regime    — TREND_UP/DOWN/RANGE (основной фильтр)
  USDT.D (доминанс USDT) — рост = бегство в кэш = медвежий рынок
  BTC Dominance          — рост = альты слабеют
Логика:
  BTC 4h TREND_DOWN + USDT.D растёт → блокируем LONG для всех
  BTC 4h TREND_UP + Dominance падает → усиливаем LONG
  Зависимость альт/BTC часто слабая — фильтр мягкий, не жёсткий
Публикует в шину: cross_market {btc_regime, usdt_d_trend, btc_dom}
Читает из шины:  ничего (независимый источник)
```

#### Сфера 6 — Market Regime + Reversal Mode Detector
```
Файл:    core/indicators/market_regime.py  ← РАСШИРИТЬ
Статус:  ✅ v1 active, ⚠️ v2 shadow, ❌ Reversal Mode нет
Текущий выход: TREND_UP / TREND_DOWN / RANGE / HIGH_VOL
Новый выход (нужно):
  regime: TREND_UP / TREND_DOWN / RANGE / HIGH_VOL  (как сейчас)
  mode:   TREND / REVERSAL  ← новое поле

Reversal Mode условия (все три):
  1. WT 4h в OS (< -60) или OB (> 60) — истощение
  2. ADX на 1h снижается последние 3 бара (тренд слабеет)
  3. CHoCH на 1h или 15m — структура сломана

Влияние mode на Decision Core:
  mode=TREND     → confluence главный, pivot_reversal подавлен (-20 strength)
  mode=REVERSAL  → pivot_reversal главный, confluence подавлен (-20 strength)

Данные подтверждают:
  27-29.03: confluence avg_R=+0.49R (тренд активен)
  01.04:    pivot_reversal WR=41.7%, +0.81R (разворот начался)
  Система не знала о смене → теряла деньги в переходный период

Публикует в шину: regime, mode
Читает из шины:  wt_snap (4h WT для exhaustion проверки)
```

#### Сфера 7 — Signal Detectors (пакет)
```
Файлы:   core/signals/, core/indicators/, core/smc/, core/pivots/
Статус:  ✅ все активны или в shadow
Детекторы:
  wt_15m_reversal_scanner.py  — CONFLUENCE (WT cross + TSL + pivot)
  divergence_detector.py      — DIVERGENCE (Regular/Hidden + cascade)
  structure_detector.py       — CHoCH/BOS
  anomaly_model.py            — аномалия объёма
  pivot_reversal.py           — разворот от пивота
  signal_watch_list.py        — WL breach
  ote_detector.py             — OTE zone [0.705-0.786]  (shadow)
  funding_detector.py         — FUNDING_EXTREME
  liquidity_sweep_detector.py — LIQUIDITY_SWEEP
  bounce_detector.py          — bounce от уровня  (shadow)
  trend_signals.py            — EMA cross + ADX

Каждый детектор:
  Читает из шины:  ohlcv_snap, wt_snap (уже вычисленный)
  Публикует в шину: свой сигнал если найден
  НЕ запускает Full CALL самостоятельно — это делает шина

Проблема текущей реализации:
  Детекторы не читают из шины — каждый сам вызывает data_collector
  Нет pre-compute: WT пересчитывается в каждом детекторе независимо
  Решение: ARCH Memory (pre-compute в scan_one, все читают df["wt1"])
```

#### Сфера 8 — Pivot Levels
```
Файлы:   core/pivots/
Статус:  ✅ активен
Уровни:  1M / 1W / 1D (Woodie + Standard + Camarilla)
         Period-based (UTC): 1M = с 1го числа, 1W = с понедельника
Публикует в шину: pivot_snap {PP, S1, S2, S3, R1, R2, R3 по TF}
Использование:
  - Детекторы: proximity check (≤0.15%)
  - Narrative Builder: "цена у 1W S1 = сильная поддержка"
  - Exit Manager: TP targets
  - MTF SMC Specialist: признаки входной модели
Важно: S1 = pp*2.003 - high, R1 = pp*1.997 - low (проверено, НЕ МЕНЯТЬ)
```

#### Сфера 9 — Narrative Builder (Decision Core)
```
Файл:    core/intelligence/narrative_builder.py  ← ОТСУТСТВУЕТ
Статус:  ❌ главный отсутствующий узел
Функция: читает ВСЁ из шины → строит единый нарратив → принимает решение

Входные данные (из шины):
  mtf_wt_verdict + confidence     (Сфера 3)
  mtf_smc_verdict + confidence    (Сфера 4)
  cross_market                    (Сфера 5)
  regime + mode                   (Сфера 6)
  все активные сигналы            (Сфера 7)
  pivot_snap                      (Сфера 8)
  cascade_count, avg_r_cascade    (PairContextBus)
  post_tsl_data                   (PostTradeAnalyser)

Выход — TradingNarrative:
  text: str          — человекочитаемый нарратив для TG
  action: str        — BUY/SELL/HOLD/WATCH
  strategy: str      — SINGLE/DUAL_TP/DUAL_TSL
  confidence: float  — итоговая уверенность
  p_win: float       — P(win) от всех ML моделей взвешенно
  key_factors: list  — топ-3 фактора которые решили

Пример нарратива (цель):
  "BTC/USDT 4h TREND_DOWN. WT 4h истощён (-71, OS).
   CHoCH подтверждён на 1h. Цена вошла в 4h OB зону.
   EQL на 1h — ликвидность снята. OTE [0.705-0.786] активна.
   Cascade по паре: 3 TSL подряд avg +4.2R.
   MTF WT: REVERSAL_SETUP (0.81). MTF SMC: STRONG_BULL_ZONE (0.74).
   → LONG setup. P(win)=0.73. Стратегия: DUAL_TSL."

Сейчас вместо этого: _analyze_signals_advanced() в trading_intelligence.py
  → суммирует веса → выдаёт число overall_strength
  → нет нарратива, нет режима, нет связного контекста
```

#### Сфера 10 — Exit Manager
```
Файл:    core/trading/exit_manager.py  ← ОТСУТСТВУЕТ (ARCH-62)
Статус:  ❌ сейчас в монолите trade_simulator.py (1500 строк)
Функция: управление всеми выходами из позиции
Читает из шины: wt_snap (для cascade TSL), pivot_snap, regime
Логика:
  check_open_trades() — главный цикл трекинга
  cascade_tsl.py      — эскалация/де-эскалация TSL (отдельный файл)
  levels_calculator.py — расчёт SL/TP уровней
  cap_tf при tp1_hit  — ограничение cascade до 1h после TP1
  bounce TSL-only     — сделки без take_profit (NULL TP)
Проблемы текущей реализации:
  tsl_tf DEFAULT '15m' — TSL стартует тесным для 15m сделок
  После tp1_hit нет cap_tf → 4h TSL слишком широкий → 33% cap
  bounce trades виснут → Dead Trades
```

#### Сфера 11 — Post-Trade Analyser + Feedback Loop
```
Файл:    core/trading/post_trade_analyser.py
Статус:  ✅ shadow
Функция: реакция на исход сделки → обновление всех узлов шины
События:
  on_tp()  → PairContextBus.add_win() + cascade_count++
  on_sl()  → проверить дивергенции, есть ли re-entry
  on_tsl() → вычислить OTE зону, добавить в post_tsl_queue
             → TriggerBus.add_ote_trigger(symbol, ote_zone)
Feedback loop (СЕЙЧАС ОТСУТСТВУЕТ):
  isход + features_json → MTF WT Specialist.add_labeled_sample()
  исход + smc_snap      → MTF SMC Specialist.add_labeled_sample()
  исход + нарратив      → Narrative Builder.update_weights()
Это превращает систему из статичной в самообучающуюся
```

#### Сфера 12 — Self-Diagnostics
```
Файл:    scripts/run_diagnostics.py  ← ОТСУТСТВУЕТ (DEV-121)
Статус:  ❌ нужно создать
Функция: периодическая проверка всех 12 сфер эталонными кейсами
Что проверяет:
  SL/TP/TSL логика   — эталонные кейсы с известным исходом
  Market Regime      — синтетические OHLCV с известным ADX
  Cascade TSL        — эскалация 15m→1h→4h, де-эскалация по WT
  Pivot Levels       — S1/R1/S2/R2 против эталона
  WT Scanner         — dynamic_os=false не пробрасывает RANGE сигналы
  R_multiple calc    — DUAL_TP tp1_fix_pct=20 → правильный взвешенный R
  features_json      — все ключи присутствуют
Выход: "✅ Куб OK" или "❌ Сфера N: описание проблемы"
Запуск: автоматически в ml_loop + по запросу /diagnostics
```

---

### 5 Платоновых тел — уровни абстракции

```
╔══════════════════════════════════════════════════════════════════╗
║  🟫 ГЕКСАЭДР (Земля) — ХРАНЕНИЕ                                ║
║  SQLite: simulated_trades, pair_context, pivot_cache            ║
║  Файлы: core/db/, subscriptions.db                              ║
║  Принцип: единый источник правды, всё персистируется            ║
║  Статус: ✅                                                      ║
╠══════════════════════════════════════════════════════════════════╣
║  🔵 ОКТАЭДР (Воздух) — СЕТЬ И API                              ║
║  BingX ccxt, ApiEngine, CircuitBreaker, WSFeed                  ║
║  Файлы: core/infra/api_engine.py, ws_feed.py, data_collector.py ║
║  Принцип: надёжный транспорт, retry, dedup, rate limit          ║
║  Статус: ✅ stable, ⚠️ WS не активирован                       ║
╠══════════════════════════════════════════════════════════════════╣
║  🔴 ТЕТРАЭДР (Огонь) — БИЗНЕС-ЛОГИКА                          ║
║  12 сфер-модулей, Shared Context Bus                            ║
║  Принцип: mesh-связность, pub/sub, не конвейер                  ║
║  Файлы: core/signals/, core/smc/, core/indicators/, core/ml/    ║
║  Статус: ⚠️ работает как конвейер, нужен переход на mesh        ║
╠══════════════════════════════════════════════════════════════════╣
║  🌊 ИКОСАЭДР (Вода) — ПОТОК К ПОЛЬЗОВАТЕЛЮ                    ║
║  TG алерты, Dashboard, intelligence_formatter                   ║
║  Нарратив приходит сюда ГОТОВЫМ от Narrative Builder            ║
║  Файлы: bot/monitoring.py, web/, core/ui/                       ║
║  Статус: ✅ работает, ⚠️ нарратив примитивный (нет Сферы 9)    ║
╠══════════════════════════════════════════════════════════════════╣
║  🌌 ДОДЕКАЭДР (Эфир) — AI И АНАЛИТИКА                         ║
║  MTF WT Specialist, MTF SMC Specialist, OutcomePredictor        ║
║  Narrative Builder, Self-Diagnostics, R-predictor               ║
║  Принцип: обучение на реальных исходах, feedback loop           ║
║  Файлы: core/ml/, core/intelligence/                            ║
║  Статус: ⚠️ ML базовый (AUC~0.5), ❌ специалисты отсутствуют   ║
╚══════════════════════════════════════════════════════════════════╝
```

---

### Mesh-связность — правило проектирования

**Куб Метатрона требует:** каждая сфера МОЖЕТ общаться с каждой другой напрямую через шину. Не через монолит, не через цепочку вызовов.

**Практическое правило для DEV:**
> Если модуль A нужно передать данные в модуль B — публикуй в шину, не передавай напрямую.
> Если модуль нуждается в данных — читай из шины, не вызывай другой модуль.
> Исключение: DataCollector (Сфера 1) — единственный кто работает с биржей напрямую.

**Anti-pattern (что делать НЕ надо):**
```python
# ❌ КОНВЕЙЕР — нарушает Куб
result_a = detector_a(ohlcv)
result_b = detector_b(result_a)
result_c = aggregator(result_a, result_b)

# ✅ КУБ — правильно
bus.publish(symbol, "ohlcv_updated", ohlcv_snap)
# detector_a, detector_b, aggregator подписаны на "ohlcv_updated"
# и реагируют независимо, публикуя в шину свои результаты
```

---

### Full CALL — центральный принцип

**При получении ЛЮБОГО сигнала** — триггер для Full CALL:
```
WT cross / аномалия объёма / CHoCH / пивот touch / дивергенция / EQH sweep / OTE
    │
    ▼  публикует в шину event("signal_detected", symbol, signal_data)
    │
    ▼  Narrative Builder подписан → читает ВСЁ из шины → строит нарратив
    │
    ├── TG Alert (нарратив + уровни)
    ├── simulated_trades (features_json = снапшот всей шины)
    ├── PairContextBus.update()
    └── Exit Manager (если позиция открыта — пересчитать уровни)
```

Сейчас `analyze_symbol()` в `trading_intelligence.py` выполняет Full CALL частично — вызывает все детекторы, но результат не идёт в шину, нет нарратива, нет Reversal Mode.

---

### Текущий статус Куба (21.05.2026)

> Подробнее: `docs/CURRENT_ARCHITECTURE.md` — два потока (Reactive Bot + ARCH-104), рёбра Куба, roadmap.

```
Сфера  1  DataCollector          ✅ активен → bus: OHLCV_UPDATED
Сфера  2  WSFeed                 ✅ real-time тикеры → TICK_PRICE (throttled)
Сфера  3  MTF WT Specialist      ✅ активен → bus: WT_VERDICT, WT_SNAP_UPDATED
Сфера  4  MTF SMC Specialist     ⚠️ shadow (ждёт 200+ SMC сделок)
Сфера  5  Cross-Market Node      ✅ BTC 4h режим → bus: CROSS_MARKET
Сфера  6  Market Regime          ✅ режим+mode+verdict_gate (ARCH-84) → REGIME_UPDATED
Сфера  7  Signal Detectors       ✅ 6 детекторов (wt_sideways отключён DEV-213)
                                  + HTF: trend_change_1h/4h/15m, wt_cross, zone_entry
Сфера  8  Pivot Levels           ✅ swing SL (DEV-214) + FVG confluence → PIVOT_SNAP_UPDATED
Сфера  9  Narrative Builder      ✅ TradeRouter (DEV-199) = единый узел регистрации
                                  + ARCH-104 Decision Adapter (новое ребро, 21.05)
Сфера 10  Exit Manager           ✅ TSL + emergency watchdog (DEV-185.2) → POSITION_CLOSED
Сфера 11  Post-Trade Analyser    ✅ feedback + signal weights + PatternLifecycle (ARCH-104)
Сфера 12  Self-Diagnostics       ✅ SphereRegistry + DecisionTrace/signal_drops (DEV-203)
─────────────────────────────────────────────────────────────────────
Центр     Shared Context Bus     ✅ pub/sub 22 события, 38 полей PairState

Mesh-связность (оригинальные + новые рёбра ARCH-104):
  Сфера 3  ← REGIME_UPDATED
  Сфера 6  ← WT_SNAP_UPDATED
  Сфера 9  ← SIGNAL_DETECTED
  Сфера 10 ← DIVERGENCE_FOUND, PIVOT_TOUCH
  Сфера 11 ← POSITION_CLOSED
  Сфера 5  → all pairs (CROSS_MARKET при BTC shock)
  Сфера 12 ← ВСЕ события
  [ARCH-104] Сфера 7 → ARCH-104 Adapter → Pattern Matcher   🆕
  [ARCH-104] Pattern Matcher → RiskIntelligence              🆕
  [ARCH-104] RiskIntelligence → DecisionFusion → Сфера 9    🆕
  [ARCH-104] PatternLifecycle → Сфера 11 (auto_retire)       🆕

Итог: 12 из 12 сфер подключены к шине ✅
      4 новых ребра от ARCH-104 (Pattern Mining + Risk Intelligence)
      EventBus: 14 типов Full CALL триггеров
      ARCH-104 Stage 1 запущен: 241 пара, 15 паттернов, 10% capital (21.05.2026)
```

---

### Дорожная карта Куба

```
Фаза 0 (апрель 2026) — Фундамент              ✅ ЗАВЕРШЕНА
  ✅ PostTradeAnalyser + feedback loop
  ✅ Market Regime + verdict_gate production
  ✅ BTC 4h Cross-Market Node (Сфера 5)
  ✅ Self-Diagnostics / SphereRegistry (Сфера 12)

Фаза 1 (апрель-май 2026) — Рёбра Куба         ✅ ЗАВЕРШЕНА
  ✅ TradeRouter — Сфера 9 как единый узел (DEV-199)
  ✅ Exit Manager watchdog (DEV-185.2)
  ✅ DecisionTrace / signal_drops (DEV-203)
  ✅ Swing SL + FVG confluence для pivot (DEV-214)

Фаза 2 (май 2026) — ARCH-104 Pattern Mining    ✅ ЗАВЕРШЕНА
  ✅ 12 002 паттернов → 15 production (BH-FDR-валидация)
  ✅ RiskIntelligenceV1 + leverage formula
  ✅ DecisionFusion v1+v2 (LightGBM Phase 1.5)
  ✅ VST observer Stage 1: 241 пара, 10% capital (21.05.2026)

Фаза 3 (май-июнь 2026) — Стабилизация         🔄 АКТИВНА
  🔄 ARCH-104 capital ramp: Stage 2→5 (10→100%)
  🔴 Confirmation-Driven Sprint (DEV-200/201/202)
  🔴 ARCH-95-EXEC: расследование H1-H5 убытков
  ⚠️ Сфера 4 (SMC Specialist) — ждёт 200+ SMC сделок

Фаза 4 (~июнь-июль 2026) — Полный Куб         ⏸ FROZEN
  ARCH-74-EXT, ARCH-96..99, ARCH-101..111
  Разморозка при: 7 дней без регрессии avgR + ARCH-104 Stage 3+
```

---

### Правило: не отступать от концепции

> Любая новая задача DEV/ARCH должна соответствовать одному из вопросов:
> 1. Это строит/улучшает одну из 12 сфер?
> 2. Это усиливает Shared Context Bus?
> 3. Это добавляет связь между сферами (новое ребро Куба)?
> 4. Это feedback loop (сфера узнаёт от другой сферы)?
>
> Если ответ "нет" — задача либо технический долг, либо не нужна.

---

---

## Типы сигналов (SignalType)

> Enum в `core/signals/signal_models.py`. Каждый тип — отдельный детектор.
> Хранится строкой в `simulated_trades.signal_type`.

---

### SignalType.CONFLUENCE

**Другое название:** WT Reversal Signal (неофициально)
**Детектор:** `core/signals/wt_15m_reversal_scanner.py` → `scan_wt_15m_reversal()`
**Старый детектор:** `core/confluence/confluence_scanner.py` → `scan_confluence()` (оба живы)

#### Идея

Искать точки входа где несколько факторов совпали одновременно в коротком окне:
WaveTrend в перепроданности/перекупленности, тренд развернулся, цена у пивота.
Один индикатор ненадёжен. Совпадение трёх-четырёх = сетап с высокой вероятностью.
Название "confluence" = схождение факторов в одной точке.

#### Условия и очки (текущий детектор, `wt_15m_reversal_scanner`)

Lookback: **8 баров × 15m = 2 часа**. Порог: **strength ≥ 60**.

| Условие | Очки | Обязателен? |
|---|---|---|
| WT кросс прямо в зоне OS/OB | +25 | gate (один из двух) |
| WT кросс вне зоны (но WT ранее был в OS/OB) | +15 | gate (один из двух) |
| TSL пересечение + close confirmation | +25 | gate (обязателен) |
| Касание пивота (≤ 0.15%) | +25 | бонус |
| Дивергенция WT (регулярная) | +20 | бонус |
| Скрытая дивергенция WT | +15 | бонус |
| Пивот конфлюэнция 1W+1D | +15 | бонус |
| Пивот конфлюэнция 1M | +20 | бонус |

Минимальный сигнал: TSL(25) + WT_CROSS(15) = 40 → не хватает, нужен ещё один фактор.

#### Условия (старый детектор, `confluence_scanner`)

Lookback: **20 баров × 15m = 5 часов**. Те же базовые факторы, другие веса.
Активен в `confluence_state_machine` как параллельный источник.

#### Как создаётся (pipeline)

```
scan_loop.py → scan_one(sym)
  └─ если есть confluence_sm → bot.confluence_sm.update()
  │    └─ вызывает оба сканера + state machine логику
  └─ иначе → scan_wt_15m_reversal() напрямую
        └─ возвращает List[SignalData(signal_type=CONFLUENCE)]
              └─ добавляется в all_scan_signals
                    └─ trading_intelligence → WtEntryStrategy или MultiSignalStrategy
```

#### Где используется

- `WtEntryStrategy.analyze()` — берёт ТОЛЬКО CONFLUENCE сигналы (фильтр по типу)
- `MultiSignalStrategy.analyze()` — получает вместе с другими, вес = **0.35** (самый высокий)
- `confidence_calculator.py` — если CONFLUENCE сигнал имеет 2+ факторов → бонус к confidence
- `trading_intelligence.py` — вес в adaptive weights: **0.15**

#### Подводные камни

1. **Имя совпадает со стратегией.** Бывшая стратегия `confluence` (теперь `multi_signal`)
   работает с ВСЕМИ типами сигналов, не только CONFLUENCE. Путаница была системной.

2. **`SignalType.CONFLUENCE` ≠ "конфлюэнция стратегий".** Это один конкретный детектор
   (WT-based reversal), который внутри себя проверяет несколько условий.

3. **Имя в БД не менялось.** В `simulated_trades.signal_type` хранится строка `"confluence"`.
   Переименование потребует миграции ~2400 записей.

4. **Два детектора одновременно.** Старый (`confluence_scanner`) и новый
   (`wt_15m_reversal_scanner`) могут оба сгенерировать сигнал. State machine управляет приоритетом.

---

### SignalType.MTF_BIAS

**Детектор:** `core/mtf/mtf_checker.py`
**Вес в системе:** 0.50 (самый высокий)

> TODO: добавить полное описание

---

### SignalType.PIVOT_REVERSAL

**Детектор:** `core/pivots/pivot_reversal.py`
**Вес в системе:** 0.20

> TODO: добавить полное описание

---

### SignalType.DIVERGENCE

**Детектор:** `core/indicators/divergence_detector.py`
**Вес в системе:** 0.10

> TODO: добавить полное описание

---

### SignalType.WT_SIGNAL

**Детектор:** `core/signals/signal_checkers.py`
**Вес в системе:** 0.10

> TODO: добавить полное описание

---

### SignalType.TREND_SIGNAL

**Детектор:** `core/indicators/trend_signals.py`
**Вес в системе:** 0.10

> TODO: добавить полное описание

---

### SignalType.ANOMALY

**Детектор:** `core/signals/signal_checkers.py` (был отдельный `anomaly_detector.py`, удалён)
**Вес в системе:** 0.05

> TODO: добавить полное описание

---

## Стратегии

> Стратегия = правила отбора и агрегации сигналов + расчёт SL/TP.
> Регистр: `strategies/registry.py`. Активные: `config.yaml → trading.active_strategies`.
> Результат хранится в `simulated_trades.strategy_name`.

---

### WtEntryStrategy ("wt_entry")

**Файл:** `strategies/built_in/reversal_scanner_strategy.py`
**Бывшее имя:** `reversal_scanner` (переименовано 28.03.2026)
**Данные в БД:** 729 сделок

#### Что делает

Берёт из входящих сигналов только `SignalType.CONFLUENCE`. Выбирает сильнейший LONG или SHORT.
Если конфликт равной силы — возвращает None.

SL: TSL-линия × (1 - 0.3%). Если TSL слишком близко (< `tsl_min_dist`) — fallback ATR×1.5.
TP: entry ± sl_dist × `tp_rr` (3.0 по умолчанию).

#### Данные

avg_R = **−0.377**, WR = **4.5%** (729 сделок).

Плохой результат объясняется не буфером SL, а тем что стратегия входит по CONFLUENCE сигналу
вне зависимости от общего тренда. CONFLUENCE в тренде (+3.84R для `tsl_line:trendup`)
принципиально лучше чем CONFLUENCE против тренда.

#### Приоритет в оркестровке

Priority-1 в `_pick_best_recommendation()`. Если есть — берётся сразу, другие стратегии игнорируются.

---

### MultiSignalStrategy ("multi_signal")

**Файл:** `strategies/built_in/confluence.py`
**Бывшее имя:** `confluence` (переименовано 28.03.2026)
**Данные в БД:** 511 сделок

#### Что делает

Принимает ВСЕ типы сигналов. Требует 2+ от разных источников.
Считает взвешенный score, проверяет конфликты. Генерирует рекомендацию с адаптивным SL/TP.

Веса сигналов:
- MTF_ALERT: 0.30 | MTF_BIAS: 0.30 | CONFLUENCE: 0.35 | PIVOT_REVERSAL: 0.20
- DIVERGENCE: 0.15 | WT_SIGNAL: 0.10 | TREND_SIGNAL: 0.10 | ANOMALY: 0.05

#### Данные

avg_R = **+3.486**, WR = **2.0%** (511 сделок).
Высокий avg_R при низком WR означает редкие но крупные победители.

---

### PivotReversalStrategy ("pivot_reversal")

**Файл:** `strategies/built_in/pivot_reversal_strategy.py`
**Данные в БД:** 52 сделки

SL: ATR(14)×1.5, зажат [1%, 4%]. TP: entry ± sl_dist × tp_rr (3.0).
avg_R = −0.315, WR = 10%.

> TODO: расширить описание

---

## Ключевые концепции

---

### TSL — Trailing Stop Loss

**Реализация:** `core/trading/trade_simulator.py` → `check_open_trades_with_tsl()`
**Индикатор:** `calculate_trend()` из `core/indicators/indicators.py` (Supertrend)
**Параметры:** `analysis.indicators.trend.atr_period: 43`, `factor: 1.25`

#### Как работает

TSL = линия Supertrend (`trendup`/`trenddown`). Следует за ценой, не уходит назад.

1. **Активация:** только после достижения `+tsl_activation_r` (= 1.0R) прибыли
2. **Проверка:** по `CLOSE` свечи (не по LOW/HIGH — фитили не вышибают)
3. **Срабатывание:** LONG → `close <= tsl_trenddown` → STATUS=TSL, exit=close
4. **Хранение:** `tsl_tf` в БД — таймфрейм активного TSL

#### Cascade TSL (DEV-29)

Иерархия TF: 15m → 1h → 4h. Поднимается когда тренд подтверждён на старшем TF.
De-escalation: если `current_r >= cascade_tsl_deescalation_r (2.5)` и нижний TF даёт тighter стоп.

#### DEV-87 (28.03.2026)

До фикса: 11 мест в коде использовали `factor=1.0` (дефолт), хотя в конфиге `factor=1.25`.
TSL-линия с factor=1.0 шире (дальше от цены), с factor=1.25 — ещё шире.
Все вызовы `calculate_trend()` теперь читают factor из конфига.

---

### WL Breach — Watch List Breach Entry

**Реализация:** `bot/loops/scan_loop.py` → `_handle_wl_breach_entry()`
**Config:** `signal_quality.wl_sl_buffer_pct: 0.5`

#### Идея

Пара добавляется в Watch List когда приближается к ключевому уровню (пивоту).
При пробое уровня на `watch_list_breach_pct` (0.8%) — авто-вход без `analyze_symbol`.

#### SL logic

```python
sl = pivot_level * (1.0 - wl_sl_buffer_pct/100)  # LONG: 0.5% ниже пробитого уровня
```

#### Проблема (кейс SHAPE/USDT)

Когда `wl_pivot_key = "tsl_line"` (а не реальный pivot), `pivot_level` = значение TSL-линии,
которая в RANGE режиме может быть 5%+ от цены. SL получается катастрофически широкий.

Нужен gate: если нет реального пивота в разумной близости (≤8%) → не входить.

---

### SL проверка: CLOSE vs LOW

**Реализация:** `core/trading/trade_simulator.py` → строки ~1175

#### Логика

По умолчанию SL проверяется по LOW свечи (для LONG) или HIGH (для SHORT).
Это реалистично для ценовых уровней (swing_low, pivot, FVG) — фитиль дошёл = вышло.

Для TSL-линии (индикаторный уровень) — другая логика.
Фитиль через TSL-линию ≠ разворот тренда. Подтверждение = закрытие за линией.

**DEV-88 (28.03.2026):** для `sl_source` начинающихся с `tsl_line` или `wl_pivot_tsl` —
проверка по CLOSE:

```python
_sl_check_close = sl_source.startswith("tsl_line") or sl_source.startswith("wl_pivot_tsl")
hit_sl = close <= sl if _sl_check_close else low <= sl  # LONG
```

---

## Ключевые модули

> TODO: добавить описания по мере работы с модулями

| Модуль | Назначение | Строк |
|---|---|---|
| `oko_mtf.py` | точка входа, TradingAlertBot (бывш. `bot_with_subscriptions.py`, 15.05) | ~105 |
| `core/trading_intelligence.py` | агрегация сигналов → рекомендация | ~1850 |
| `core/trading/trade_simulator.py` | SL/TP/TSL трекинг, запись сделок | ~1300 |
| `bot/loops/scan_loop.py` | основной цикл сканирования | ~700 |
| `bot/monitoring.py` | мониторинг, WL breach, broadcast | ~600 |
| `core/signals/wt_15m_reversal_scanner.py` | детектор CONFLUENCE (WT reversal) | ~450 |
| `core/confluence/confluence_scanner.py` | старый CONFLUENCE детектор (lookback) | ~350 |

---

## Параметры конфига

> TODO: добавить по мере работы с конфигом

| Параметр | Значение | Описание |
|---|---|---|
| `analysis.indicators.trend.factor` | 1.25 | Ширина TSL-полосы Supertrend |
| `analysis.indicators.trend.atr_period` | 43 | Период ATR для Supertrend |
| `trading.tsl_activation_r` | 1.0 | R-кратность для активации TSL |
| `trading.cascade_tsl_deescalation_r` | 2.5 | R для de-escalation TSL на нижний TF |
| `signal_quality.wl_sl_buffer_pct` | 0.5 | Буфер SL от пробитого пивота при WL breach (%) |
| `trading.sl_tp.struct_sl_buffer_pct` | 0.3 | Буфер SL от swing_low/high (%) |
| `trading.strategies.wt_entry.sl_buffer_pct` | 0.3 | Буфер SL от TSL-линии для wt_entry (%) |
