# Trader Vision — Predictive Setup Engine

> **Версия:** 1.0 · **Дата:** 2026-04-28 · **Автор:** TRADER (Claude)
> **Цель:** превратить 65 триггеров (карта [SIGNAL_BUS_CUBE_MAP.md § Слой 1.5](SIGNAL_BUS_CUBE_MAP.md)) из инвентаря в **настоящую предсказательную торговую систему** с лимитными ордерами, заранее построенными сетапами и полным набором инвалидаций.
> Документ — стратегическое видение, не текущий план реализации. Конкретные задачи вынесены в [TASKS.md](../TASKS.md) (ARCH-105…ARCH-110).

---

## Краткое резюме (TL;DR)

1. Сейчас бот работает в одном режиме: **Reactive** (триггер сработал → market entry → надеемся на хорошую цену). Это даёт slippage и упускает оптимальные точки.
2. Нужны три режима: **Reactive** + **Predictive** (лимит на ожидаемой цене) + **Cascade** (composite-сетап из 2–4 триггеров).
3. Ключевая абстракция, которой не хватает — **Setup** (план сделки): композиция триггеров + предсказанная entry-зона + лимитные ордера + invalidation + TTL + linked exit plan.
4. Чтобы это работало — нужен **Trigger Bus** (отдельный от EventBus поток атомарных событий) и **Setup Engine** (Сфера 18, новая).
5. Самое важное чего сейчас нет для прогнозирования: **order flow / open interest / volume profile / funding history / session edge**. Без этого предсказание цены — гадание.
6. Конкретные торговые гипотезы — раздел «Гипотезы прогнозирования» (10 шт., все проверяемы на истории).

---

## 1. Три режима использования триггеров

### Режим A — Reactive (сейчас)

```
[Trigger fires] → [Detector aggregates] → [analyze_symbol] → [market BUY/SELL]
```

**Плюсы:** простота, гарантированный фил.
**Минусы:** slippage 1–3% (DEV-185), вход в пиках, психология FOMO встроена в код.

### Режим B — Predictive (нужен)

```
[Trigger fires]
   → [Setup Builder]
   → [предсказывает entry-зону: например "0.5–0.8% ниже текущей"]
   → [ставит ladder limit orders в зоне]
   → [ждёт фил | отменяет по TTL | инвалидирует если другой триггер]
   → [при филле → выставляет linked SL/TP]
```

**Плюсы:** нет slippage, лучшая R:R, ловим reversal в момент wick'а.
**Минусы:** часть лимитов не филлится (надо мерить fill_rate), требует TTL и invalidation logic.

### Режим C — Cascade (composite setup)

```
[Trigger 1: HTF WT cross 4h в OB] → SETUP CREATED (TTL 4 часа)
   ↓
[Trigger 2: 1h CHoCH bearish в течение 4h]   → SETUP UPGRADED (P2)
   ↓
[Trigger 3: 15m FVG fill в OTE 0.705-0.786] → SETUP READY (P1, лимит на 0.705)
   ↓
[Trigger 4: 5m volume spike + WT cross]      → SETUP TRIGGERED (фил лимита)
```

**Плюсы:** WR значительно выше (4 события подтверждают друг друга), DD ниже.
**Минусы:** редкие сигналы (5–15 сетапов/день вместо 50–80 сделок).

**Текущая система** — это плохо реализованный Cascade: `analyze_symbol` собирает все детекторы в один тик и считает strength. Это **не каскад во времени**, а **снапшот в моменте**. Настоящий каскад собирается по событиям с TTL, а не по запросу.

---

## 2. Setup — недостающая абстракция

### Что такое Setup

```python
@dataclass
class TradingSetup:
    setup_id: str
    symbol: str
    direction: SignalDirection  # LONG/SHORT

    # Композиция триггеров
    triggers: List[TriggerEvent]      # упорядочено по времени
    setup_type: str                   # OTE_REVERSAL / LIQ_SWEEP_BOUNCE / WT_DIVERGENCE_TSL_CROSS / ...
    confluence_score: int             # 0-100, аналог strength

    # Предсказание точки входа
    entry_zone_low: float             # нижняя граница зоны лимита
    entry_zone_high: float            # верхняя граница
    entry_orders: List[LimitOrder]    # ladder из 1–3 лимитов
    expected_entry_price: float       # mid зоны

    # Жёсткие планы
    stop_loss: float                  # обоснованный (за свингом / OB / pivot)
    take_profit: List[float]          # ladder TP
    invalidation_conditions: List[InvalidationRule]
    ttl: timedelta                    # сколько setup живёт без фила
    created_at: datetime

    # Прогнозы
    p_win_estimate: float             # из ML / гипотезы
    rr_estimate: float
    expected_time_to_trigger: timedelta  # сколько ждать фил по истории похожих
    expected_time_to_resolve: timedelta  # сколько живёт сделка после фила

    # Контекст
    htf_bias: str                     # сторона старшего TF на момент создания
    regime_at_creation: str
    btc_regime_at_creation: str
    pair_state_snapshot: dict         # фотография PairState
```

### Жизненный цикл Setup

```
DRAFT → ARMED → TRIGGERED → ACTIVE → CLOSED (TP/SL/TSL/EXPIRED)
         ↓
         INVALIDATED (другое событие сломало сетап до фила)
         ↓
         EXPIRED (TTL вышел без фила)
```

- **DRAFT** — собирается из 1–2 триггеров, ещё не поставили лимиты
- **ARMED** — лимиты выставлены на бирже, ждём фил
- **TRIGGERED** — лимит частично/полностью заполнен
- **ACTIVE** — открытая позиция, мониторим SL/TSL/TP
- **CLOSED** — позиция закрыта (терминал)
- **INVALIDATED / EXPIRED** — terminal без позиции

### Что это даёт

1. **Slippage → 0** на limit fills (отдельный KPI: limit_fill_rate %).
2. **R:R улучшение**: вход на ретесте уровня, а не на пробое — типично +20–40% к R:R.
3. **WR улучшение** через каскадную фильтрацию: только сетапы с ≥2 триггерами + HTF bias.
4. **Объяснимость**: каждый сетап имеет нарратив («HTF 4h CHoCH + 1h liquidity sweep + OTE entry» → понятно зачем взяли).
5. **Бэктестируемость**: вместо «эта стратегия в среднем …» можно сказать «сетап SETUP_TYPE_X имеет WR=42% n=180, средний time-to-fill 47 мин, expired_rate 23%».
6. **Унификация добавления стратегий**: новая стратегия = новая комбинация триггеров + предикат (см. § Strategy DSL).

---

## 3. Trigger Bus — поток атомарных событий

EventBus сейчас — это **очередь Full CALL**. Это правильно для событий уровня «нужно срочно проанализировать пару». Но для Setup Engine нужен другой поток: **поток атомарных триггеров с минимальной фильтрацией**.

### Архитектура

```
┌──────────────┐
│  Detectors   │ ← публикуют все 65 триггеров с метаданными
│  (RAW level) │
└──────┬───────┘
       │
       ▼
┌──────────────────────────────────────────┐
│  TriggerBus  (новый поток событий)       │
│  - все 65 триггеров                      │
│  - per-symbol stream + global stream     │
│  - НИКАКОГО cooldown / dedup на уровне   │
│    шины — фильтрация в подписчиках       │
│  - hot-storage (последние N=200/symbol)  │
└────────┬───────────────┬─────────────────┘
         │               │
         ▼               ▼
┌────────────────┐  ┌────────────────────┐
│  Setup Engine  │  │  EventBus (как     │
│  (новая S18)   │  │   сейчас, агрегат) │
│  собирает      │  │  для Full CALL     │
│  каскады       │  │  при критичных     │
│                │  │  одиночных         │
└────────────────┘  └────────────────────┘
```

**Принцип:** EventBus = «очередь для analyze_symbol», TriggerBus = «лента всех событий для построения сетапов и обучения ML».

### Что хранить в TriggerEvent

```python
@dataclass
class TriggerEvent:
    trigger_id: str               # уникальный ID для дедупа
    trigger_type: str             # из 65 — "wt_cross_15m_os", "tsl_cross_up_15m", ...
    event_kind: str               # один из 8 — "CROSS"/"TOUCH"/"BREAK"/...
    symbol: str
    tf: str                       # 15m, 1h, 4h ...
    timestamp: datetime           # время свечи (closed bar)
    price_at_trigger: float
    strength_score: int           # 0-100, специфично для триггера
    direction_hint: str           # LONG / SHORT / NEUTRAL
    raw_data: dict                # (например wt1, wt2 значения, pivot_level)
    setup_relevance: float        # 0-1: насколько этот триггер обычно ведёт к сетапу
```

### Это даст для ML

Trigger Bus = **полная история всех атомарных событий**. Для ML это:
- Обучающая выборка не из 3000 закрытых сделок, а из **сотен тысяч триггеров с известным «исходом окна»** (что произошло с ценой через 1h/4h/24h после триггера).
- Marginal effect каждого триггера: «WT cross в OS на 15m в TREND_DOWN режим даёт E[1h_return] = +0.3%, p=0.001».
- Feature engineering для S17 Meta-Learning (ARCH-99) становится тривиальным: фичи = последние N триггеров за окно K часов.

---

## 4. Strategy DSL — унификация для добавления стратегий

Сейчас новая стратегия = новый Python-класс с императивной логикой. Каждая стратегия дублирует чтение OHLCV, расчёт WT, проверку режима, выставление SL/TP. Это анти-паттерн Куба.

### Декларативное описание стратегии

```yaml
# strategies/declarative/htf_choch_ote.yaml

name: HTF_CHoCH_OTE
description: "4h CHoCH + 1h OTE retrace в направлении сломанной структуры"
direction: any  # LONG/SHORT определяется триггером

# Триггерная цепочка (порядок важен)
trigger_chain:
  - id: t1_choch
    trigger: choch_bullish OR choch_bearish
    tf: 4h
    window: 24h         # должен сработать в последние 24ч
    sets_direction: true

  - id: t2_ote_enter
    trigger: ote_zone_enter
    tf: 1h
    direction_match: t1_choch.direction
    window: 24h         # после t1, в пределах 24ч
    required: true

  - id: t3_ltf_trigger
    trigger_any:
      - wt_cross_in_zone
      - liq_sweep_reclaim
      - bull_or_bear_div
    tf: 15m
    direction_match: t1_choch.direction
    window: 4h          # после t2, в пределах 4ч

# Контекстные фильтры
context_filters:
  - regime: [TREND_UP, TREND_DOWN]    # не в RANGE
  - btc_regime_against: false          # не в противоход BTC при extreme
  - hour_utc: [4, 18]
  - sl_streak: <= 2

# Предсказание точки входа
entry_prediction:
  type: ladder_limit
  zone_anchor: t3_ltf_trigger.price
  zone_low: -0.3%       # на 0.3% ниже триггерной цены
  zone_high: +0.0%
  orders: 2             # 2 лимита: один на верхней границе, один на нижней
  size_split: [0.4, 0.6]

# План SL/TP
exit_plan:
  stop_loss:
    anchor: t1_choch.swing_level   # SL за свингом, сломанным CHoCH
    buffer_pct: 0.3
  take_profit:
    type: ladder
    levels:
      - {target: htf_pivot_R1, size: 0.5}
      - {target: htf_pivot_R2, size: 0.3}
      - {target: 3R, size: 0.2}

# Инвалидации
invalidations:
  - condition: "close < t1_choch.swing_level"
    action: cancel_setup
  - condition: "regime_change to RANGE"
    action: cancel_setup
  - condition: "ttl expired"
    ttl: 4h
    action: cancel_setup
```

**Что это даёт:**
- TRADER может **создавать новую стратегию без программирования** — yaml-файл.
- Все стратегии используют одни и те же триггеры, RAW и шину → нет дублирования.
- Backtester читает yaml, симулирует на истории Trigger Bus → быстрая валидация.
- Сравнение стратегий — структурное (одинаковая схема), не «у каждого своё».

### Минимальная имплементация Strategy DSL (Фаза 1)

- `core/strategy/dsl_loader.py` — парсер yaml → `StrategySpec`
- `core/strategy/setup_builder.py` — для каждой `StrategySpec` подписывается на нужные триггеры в TriggerBus, держит state machine, эмитит `TradingSetup`
- `core/strategy/setup_executor.py` — `TradingSetup` → лимитные ордера, мониторинг fill, переход в ACTIVE

---

## 5. Новые фичи и данные, которые начнём получать

С введением Trigger Bus + Setup Engine у нас **в БД появятся новые таблицы**:

### `trigger_events` (hot-storage Trigger Bus)

| Поле | Тип | Что даёт |
|---|---|---|
| trigger_id | TEXT PK | уникальность |
| trigger_type | TEXT | для группировки в анализе |
| event_kind | TEXT | CROSS/TOUCH/... |
| symbol, tf, timestamp, price_at_trigger | стандарт | — |
| strength_score | INT 0-100 | self-strength |
| direction_hint | TEXT | LONG/SHORT/NEUTRAL |
| raw_data_json | JSON | wt1, pivot_level, fvg_size, ... |
| outcome_1h_pct | REAL | возврат через 1ч (NULL до закрытия окна) |
| outcome_4h_pct | REAL | возврат через 4ч |
| outcome_24h_pct | REAL | возврат через 24ч |

→ Это даёт **marginal value of each trigger** в любой момент.

### `trading_setups`

| Поле | Тип | Что даёт |
|---|---|---|
| setup_id | TEXT PK | — |
| setup_type | TEXT | "HTF_CHoCH_OTE" |
| status | TEXT | DRAFT/ARMED/TRIGGERED/ACTIVE/CLOSED/INVALIDATED/EXPIRED |
| triggers_json | JSON | список trigger_id |
| confluence_score | INT | — |
| entry_zone_low, entry_zone_high | REAL | предсказанная зона |
| expected_entry_price | REAL | mid зоны |
| actual_fill_price | REAL | реальный фил |
| slippage_pct | REAL | (fill − expected) / expected |
| time_to_fill_min | INT | сколько ждали |
| ttl_min | INT | дедлайн setup |
| invalidation_reason | TEXT | если cancelled до фила |
| linked_trade_id | INT | FK → simulated_trades |
| created_at, filled_at, closed_at | datetime | — |

→ Даёт **fill_rate%, slippage_pct, time_to_fill** — это новые KPI, которых сейчас нет.

### Новые фичи в `simulated_trades.features_json`

```json
{
  "setup_id": "...",
  "setup_type": "HTF_CHoCH_OTE",
  "trigger_chain": ["t1_choch_4h", "t2_ote_enter_1h", "t3_wt_cross_15m"],
  "trigger_count": 3,
  "time_t1_to_t3_min": 187,
  "entry_was_limit": true,
  "limit_fill_attempts": 1,
  "predicted_entry_price": 51234.5,
  "actual_entry_price": 51228.0,
  "predicted_p_win": 0.62,
  "predicted_rr": 2.7,
  "actual_rr": 3.1
}
```

→ Калибровка `predicted_p_win` vs реальная WR. Калибровка `predicted_rr` vs `actual_rr`. **Это даёт проверку, что наши прогнозы вообще работают.**

---

## 6. Чего не хватает для предсказания движения цены

Карта triggers перечисляет 65 событий, но они все из **одного источника — OHLCV**. Этого недостаточно для серьёзного прогноза. Нужно подключить новые источники.

### Группа A — Order Flow (критично, must-have)

| Источник | Что даёт | Сложность |
|---|---|---|
| **Open Interest** | дивергенция OI vs цена → squeeze prediction; рост OI на пробое = сила, падение OI = false break | Низкая (BingX `fetchOpenInterest`) |
| **Funding rate history** | сейчас только текущее. История 30 дней даёт: «funding extreme + время в зоне» = squeeze probability | Низкая (BingX `fapi/v1/fundingRate`) |
| **Aggressor delta / CVD** | кто покупает: бид-аггресс или офер-аггресс. Реверсивные дивергенции CVD vs цена — **сильнейший** trigger | Средняя (нужен trade stream WS) |
| **Liquidations** | каскады ликвидаций → реверсивные движения, особенно после wick'а | Средняя (BingX `fapi/v1/forceOrders`) |
| **Order book imbalance** | bid_volume / ask_volume в первых N уровнях; liquidity walls | Высокая (нужен L2 WS, тяжёлый поток) |

### Группа B — Macro / Cross-market (важно)

| Источник | Что даёт | Сложность |
|---|---|---|
| **USDT.D** | глобальный риск-аппетит | Низкая (CoinGecko) |
| **BTC.D** | альты/BTC ротация | Низкая (CoinGecko) |
| **DXY** | макро-USD сила, обратная корреляция с крипто | Низкая (Yahoo Finance / FRED) |
| **VIX** | risk-off контекст | Низкая (Yahoo) |
| **Fear & Greed Index** | sentiment (alternative.me) | Низкая |
| **Total3 / Total2** | капитализация альтов | Низкая (CoinGecko) |

### Группа C — Microstructure (для точности входа)

| Источник | Что даёт | Сложность |
|---|---|---|
| **Volume Profile (VPVR)** | High Volume Nodes = магнит цены, Low Volume Nodes = быстрая цена | Средняя (агрегация trades по уровням) |
| **POC (Point of Control)** | уровень с максимальным объёмом за период — ключевой магнит | Средняя |
| **Time-based session edge** | Asia / London / NY edge — разные паттерны | Низкая (datetime + session map) |
| **Spread / liquidity depth** | в моменте: безопасно ли ставить лимит | Высокая (L2 WS) |

### Группа D — On-chain / Sentiment (опционально)

| Источник | Что даёт | Сложность |
|---|---|---|
| **Stablecoin flows (USDT/USDC mint/burn)** | приход денег в крипто | Средняя (Glassnode/CryptoQuant API) |
| **Exchange netflow** | приход/отток с бирж — давление продаж/buyback | Средняя |
| **Social sentiment (LunarCrush, Santiment)** | пик хайпа = local top | Средняя (платно) |

### Приоритеты добавления (на ARCH-105)

1. 🔴 **Funding history** — простое API, мгновенный value (squeeze prediction)
2. 🔴 **Open Interest** — простое API, тяжёлая ценность (squeeze + false break)
3. 🟡 **Liquidations** — для контртренд reversal triggers
4. 🟡 **USDT.D / BTC.D** — макро-фильтр (ARCH-67)
5. 🟢 **CVD / aggressor delta** — следующий уровень (требует WS trade stream)
6. 🟢 **Volume Profile** — для точных лимитных уровней

---

## 7. Гипотезы прогнозирования (10 проверяемых)

Эти гипотезы — основа Predictive Setup Engine. Все можно бэктестить на истории сразу после внедрения Trigger Bus и outcome_1h/4h/24h в `trigger_events`.

### H1 — Liquidity sweep at EQH/EQL → reversal

> При sweep + reclaim уровня EQH/EQL на 1h в течение 1–2 свечей цена возвращается в diapason swing'а с вероятностью ≥70%.

- **Триггеры:** #29 / #30 (sweep+reclaim) + #31 / #32 (EQH/EQL sweep) + #54 (WT extremum)
- **Сетап:** лимит на 0.382–0.5 retrace от sweep wick'а
- **SL:** за концом wick'а + buffer
- **TP:** swing-mid → opposite swing
- **Тест:** outcome_4h_pct средний по группе vs неотобранные дни
- **Acceptance:** WR ≥ 60% на n ≥ 100 за 90 дней

### H2 — HTF CHoCH + LTF OTE retrace = optimal entry

> После CHoCH на 4h цена ретрейсит в OTE 0.705–0.786 в 60–70% случаев в течение 24ч. Лимит на 0.705 даёт R:R ≥ 3 при SL за свингом.

- **Триггеры:** #22 / #23 (CHoCH) + #34 (OTE enter) + #38 / #39 (regular div) опционально
- **Сетап:** ladder лимит 0.705 / 0.786, SL за свингом сломанной структуры
- **TP:** последний impulse high/low (1R обычно), затем 2R / 3R
- **Тест:** out-of-sample на 20 пар × 180 дней
- **Acceptance:** Sharpe ≥ 1.5, WR ≥ 40% (компенсирует RR≥3), n ≥ 150

### H3 — Volume divergence + WT extremum = exhaustion

> Серия 3+ свечей с растущим закрытием но падающим volume + WT в OB > 80 = exhaustion. Цена откатывает к midline (EMA-20) в 65–75% случаев в течение 8 свечей.

- **Триггеры:** #54 (WT extremum) + #47 (volume spike, инверсный — declining vs MA)
- **Доп.:** новый детектор «volume divergence» (нет в текущем коде ❌)
- **Сетап:** market entry сразу или лимит на ретесте последнего HH
- **SL:** за крайним High импульса
- **TP:** EMA-20 / EMA-50 / последний swing low
- **Acceptance:** WR ≥ 60%, время до резолюции ≤ 8 свечей

### H4 — HTF WT cross + LTF FVG fill = высокий R:R

> WT cross на 4h в OS/OB + FVG fill на 15m/1h в направлении HTF cross = 2-3R сетап с WR ~50%.

- **Триггеры:** #9 / #10 (HTF WT cross) + #21 (FVG fill) + #6 / #7 (TSL cross 15m) подтверждение
- **Сетап:** лимит у границы FVG, SL за FVG + buffer
- **TP:** ATR(14, 4h) × 2
- **Acceptance:** Sharpe ≥ 2.0

### H5 — Funding squeeze prediction

> Funding > 0.05% за последние 24ч + OI растёт + цена в OB на 1h = SHORT squeeze setup. Реверс в течение 8 часов с вероятностью ≥ 60%.

- **Триггеры:** #50 (funding extreme) + #54 (WT extremum) + новый «OI rising» (нет в коде ❌)
- **Требования:** funding history + OI (Группа A)
- **Сетап:** ladder лимит выше текущей в зоне OB
- **Acceptance:** на 30 пар × 90 дней WR ≥ 55%

### H6 — Liquidation cascade reversal

> Каскад ликвидаций > $10M в одну сторону за 5 мин + WT extremum + EQH/EQL sweep = разворот в течение 30 мин в 70%+ случаев.

- **Требования:** liquidations stream (Группа A)
- **Сетап:** лимит у POC последних 4 часов
- **SL:** за wick'ом ликвидаций
- **Acceptance:** WR ≥ 65%, RR ≥ 1.5

### H7 — Session edge (London open / NY open)

> Первые 60 минут после London open (07:00 UTC) и NY open (13:30 UTC) дают повышенную WR для trend-following сигналов на 15m.

- **Триггеры:** #61 (time gate) + любые тренд-следующие
- **Тест:** разбить выборку по часам, посмотреть avg_R по часам — может, нужно дополнить hour_utc к `entry_priority`
- **Acceptance:** один час с avg_R значительно выше остальных (p < 0.05)

### H8 — Multi-TF cascade divergence предшествует движению

> Hidden divergence на 1h + Regular divergence на 15m в одну сторону = вероятность движения ≥ 1R в течение 4ч ~ 70%.

- **Триггеры:** #44 (cascade divergence) — уже реализован
- **Сетап:** лимит на ретесте last_close ± 0.3%
- **Acceptance:** уже есть данные, просто пересчитать WR per setup_type

### H9 — Volume Profile POC / VAH / VAL как магниты

> После пробоя VAH (Value Area High) с откатом — цена возвращается к POC в 60% случаев в течение 8 часов.

- **Требования:** Volume Profile (Группа C)
- **Сетап:** лимит на VAH ± 0.2%, TP на POC
- **Acceptance:** WR ≥ 55%

### H10 — BTC dominance flip → альт-сектор движение

> При BTC.D смене направления (UP→DOWN или наоборот) на дневном TF — альтсектор движется в обратную сторону в течение 24–48ч в 65% случаев.

- **Требования:** BTC.D (Группа B)
- **Сетап:** биас всех альт-LONG/SHORT в одну сторону на 24ч
- **Acceptance:** добавить как **глобальный биас фактор**, а не как сетап.

---

## 8. Чего ещё не хватает (несигнальные пробелы)

### Bracket order management

Сейчас ([core/exchange/order_manager.py](../core/exchange/order_manager.py)) бот ставит `place_stop_order` (SL) после market entry. Нет:
- ❌ **OCO (One-Cancels-Other)** для TP/SL пары → один из них висит после фила другого.
- ❌ **Bracket entry (limit + linked SL/TP в одном вызове)** → если бот падает между entry и SL, остаётся naked position.
- ❌ **Iceberg orders** для крупных сетапов.

→ Это ARCH-96 Execution Sphere должна закрыть.

### Setup persistence

Сейчас сделка персистится в момент входа. Setup, который **не довился до фила**, теряется без следа. Нужно:
- Каждый setup пишется в `trading_setups` сразу при создании DRAFT
- Через 24ч можно ответить: «сколько setup'ов мы создали, сколько филлось, какие чаще expired» — это новый KPI fill_rate.

### Setup-aware ML

Сейчас ML обучается на `simulated_trades` — это ~3000 строк. С Setup persistence у нас будет 10–30× больше данных (все DRAFT/ARMED/EXPIRED тоже учат модель чему НЕ входить).

---

## 9. Дорожная карта (привязка к Кубу)

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Фаза 0: Стабилизация (текущий спринт «Реальные убийцы»)                │
│   → доводим avg_R pivot_reversal до ≥ −0.10R                            │
└──────────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ Фаза 1: Mesh шины (ARCH-101..104)                                       │
│   → детекторы → EventBus, BTC → cross_market, reversal_mode prod        │
└──────────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ Фаза 1.5: TriggerBus + persistence (ARCH-105)                           │
│   → новый поток + таблица trigger_events с outcome_1h/4h/24h            │
│   → detectors начинают писать ВСЕ 65 триггеров, не только sl signal    │
└──────────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ Фаза 2: ML Specialists production (ARCH-45/99)                          │
│   → +фичи из Trigger Bus → AUC должен прыгнуть с 0.41 на ≥ 0.55         │
└──────────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ Фаза 2.5: Setup Engine v1 (ARCH-106)                                    │
│   → TradingSetup dataclass + state machine + trading_setups table       │
│   → пока сетап = market entry (как сейчас) + persistence                │
└──────────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ Фаза 3: Execution Sphere (ARCH-96) — КРИТИЧНО ПЕРЕД LIVE                │
│   → IdempotencyGuard, OCO, bracket orders, SlippagePredictor            │
└──────────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ Фаза 3.5: Predictive entries (ARCH-107)                                 │
│   → Setup Engine v2: entry_zone_low/high + ladder limit orders          │
│   → fill_rate, slippage, time_to_fill — новые KPI                       │
└──────────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ Фаза 4: Strategy DSL (ARCH-108)                                         │
│   → yaml-стратегии + decl loader + setup_builder                        │
│   → TRADER может писать стратегии без программирования                  │
└──────────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ Фаза 5: Order Flow data (ARCH-105 Группа A)                             │
│   → funding history, open interest, liquidations                        │
│   → проверка H5, H6                                                     │
└──────────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ Фаза 5.5: Macro / Sentiment (ARCH-67 расширение)                        │
│   → USDT.D / BTC.D / DXY / FGI                                          │
│   → проверка H10                                                        │
└──────────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ Фаза 6: Volume Profile / CVD (ARCH-109)                                 │
│   → VPVR, POC/VAH/VAL, aggressor delta                                  │
│   → проверка H9                                                         │
└──────────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ Фаза 7: Setup-aware ML (ARCH-110)                                       │
│   → ML на полной истории Trigger Bus + Setup outcome                   │
│   → S17 Meta-Learning XGBoost f(context, setup_type) → E[R]             │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 10. Влияние на существующие сферы Куба

| Сфера | Изменение |
|---|---|
| **S3 MTF WT Specialist** | получает ЛЕНТУ всех wt-related триггеров, а не агрегаты — больше данных для обучения |
| **S4 MTF SMC Specialist** | то же для structure triggers |
| **S5 Cross-Market** | расширяется до полноценной macro-сферы (USDT.D, DXY, FGI) |
| **S7 Detectors** | детекторы становятся **trigger publishers** (фокус смещается с агрегации на эмиссию) |
| **S9 Narrative Builder** | строит нарратив из последовательности триггеров, а не снапшота |
| **S10 Exit Manager** | поддерживает setup-aware exits (SL/TP заранее в `TradingSetup.exit_plan`) |
| **S11 Post-Trade Analyser** | анализирует не только closed_trades, но и invalidated_setups |
| **S14 Execution Sphere** | критично нужно: bracket orders, OCO для лимитных сетапов |
| **S17 Meta-Learning** | работает на triggers+setups, не на closed_trades — данных в 30× больше |
| **🆕 S18 Setup Engine** | новая сфера: композирует triggers → setups |
| **🆕 S19 Trigger Bus** | новая сфера: hot-storage и поток триггеров |
| **🆕 S20 Order Flow** | новая сфера: OI / funding / liquidations / CVD |

После этого Куб превращается из 17 сфер в **20 сфер**, и **большинство проблем slippage / WR / DD решаются архитектурно**, а не точечными фиксами.

---

## 11. Acceptance — что считать успехом

После полного внедрения:

```
[ ] TriggerBus содержит ≥ 100k событий за 30 дней (~3k/день)
[ ] trigger_type-marginal value посчитан для всех 65 триггеров
[ ] trading_setups: ≥ 500 setup'ов за 30 дней
[ ] limit_fill_rate ≥ 55% (остальное — invalidated/expired без потерь)
[ ] avg_slippage_pct ≤ 0.1% (vs текущие 1–3%)
[ ] WR на predictive setups ≥ +5% vs reactive baseline
[ ] Sharpe ≥ 1.5 на 30 дней
[ ] avg R ≥ +0.15 (vs текущий минус)
[ ] ≥ 3 yaml-стратегии из Strategy DSL в production
[ ] OutcomePredictor AUC ≥ 0.62 (с trigger features)
[ ] LIVE-режим стабилен 30 дней без ручного вмешательства
```

---

## 12. Риски и контр-аргументы

### «Лимиты часто не филлятся»

- **Митигация:** ladder из 2–3 лимитов вместо одного, TTL invalidation, fallback в market entry если рынок ушёл больше N% от зоны.
- **Reality check:** настоящий KPI = `expected_return_per_setup` (включая expired/invalidated с 0R). Если предсказательный режим даёт лучший risk-adjusted return даже при fill_rate=40% — он выигрывает.

### «Slippage и так лечится — DEV-185 уже снизил»

- DEV-185 = STOP-LIMIT для SL, не для entry. Entry slippage пока не решён нигде.
- Predictive entry — единственный системный фикс entry slippage.

### «Это переусложнение для команды из 1 разработчика»

- Setup Engine v1 (Фаза 2.5) можно сделать минимальным: persistence + state machine, без predictive entries. Это уже даёт ML огромный выигрыш в данных.
- DSL — Фаза 4. До этого можно императивно описывать сетапы в коде.
- Order Flow — отдельная сфера, инкрементально.

### «А вдруг гипотезы H1–H10 не работают»

- Они проверяемы на исторических данных Trigger Bus сразу после Фазы 1.5. Хорошие отбрасываются за 2 недели бэктеста.
- Главный value не в конкретных H1–H10, а в **инфраструктуре проверки гипотез** — Trigger Bus + outcome okno.

---

## Связанные документы

- [docs/SIGNAL_BUS_CUBE_MAP.md](SIGNAL_BUS_CUBE_MAP.md) — карта триггеров (источник этого видения)
- [docs/ENCYCLOPEDIA.md](ENCYCLOPEDIA.md) — теория Куба
- [docs/CUBE_ARCHITECTURE.md](CUBE_ARCHITECTURE.md) — Mermaid-диаграммы
- [TASKS.md](../TASKS.md) — конкретные задачи (ARCH-105…ARCH-110)
