# OKO MTF Bot — Концепция и Архитектура

> *«Рынок — это живой организм. Понять его поведение можно только если видеть все его уровни одновременно.»*

---

## Что это

**Oko MTF Bot** — самообучающаяся торговая система для криптовалютного рынка, построенная на принципе **конфлюенции**: сигнал считается качественным только тогда, когда несколько независимых концепций указывают в одном направлении одновременно.

Бот работает на бирже **BingX**, мониторит **~250 торговых пар** в реальном времени, симулирует сделки без реальных денег (VST — Virtual Spot Trading), накапливает данные об исходах и использует их для самообучения.

**Текущий статус (28.05.2026):**
- `3 597` закрытых сделок в базе данных
- Работает в режиме симуляции — идёт сбор данных и калибровка
- Цель: переход в реальную торговлю при достижении устойчивого edge

---

## Проблема с классическими подходами

Большинство торговых алгоритмов построены как **линейный конвейер**:

```
данные → индикатор → сигнал → вход → выход → забыто
```

Это порождает фундаментальные проблемы:

| Проблема | Проявление |
|----------|-----------|
| **Stateless** | Система не помнит что 2 часа назад TSL закрыл позицию на этой паре |
| **Слепые зоны** | Получили сигнал → не проверили контекст на старших TF |
| **Изоляция модулей** | MTF данные есть, но Exit Manager их не видит |
| **Нет переключения** | Рынок разворачивается, система продолжает торговать тренд |
| **Один индикатор** | RSI перепродан → вход → а рынок в свободном падении |

**Ответ**: не конвейер, а **mesh** — полносвязная сеть где каждый модуль видит состояние всех остальных.

---

## Архитектурная концепция: Куб Метатрона

### Геометрия как принцип

**Куб Метатрона** — фигура сакральной геометрии: **13 сфер**, где одна центральная соединена с каждой из 12 внешних, а внешние между собой. Внутри вписаны все 5 Платоновых тел.

Ключевые свойства, которые мы переносим в архитектуру:
- **Полная связность (mesh)** — любая сфера может общаться с любой другой напрямую
- **Централизованное ядро** — центральная сфера как Shared Context Bus
- **Самодостаточность каждого узла** — при единстве системы
- **Иерархия абстракций** — данные → детекторы → ML → решение → исполнение

### Схема

```
                    ┌─────────────────────────────────────────────────┐
                    │                                                 │
         ┌──────┐   │  ┌──────┐    ┌──────┐    ┌──────┐             │
         │  S1  │   │  │  S3  │    │  S4  │    │  S5  │             │
         │Data  │◄──┼──│WT ML │    │SMC ML│    │Regime│             │
         │Coll. │   │  │Spec. │    │Spec. │    │Class.│             │
         └──┬───┘   │  └──┬───┘    └──┬───┘    └──┬───┘             │
            │       │     │           │            │                 │
            ▼       │     ▼           ▼            ▼                 │
         ┌──────┐   │  ┌──────────────────────────────────────────┐  │
         │  S2  │──►├─►│                                          │◄─┤
         │ WS   │   │  │       SHARED CONTEXT BUS (Центр)         │  │
         │ Feed │   │  │          PairFullState per symbol         │  │
         └──────┘   │  │                                          │  │
                    │  └──────────────────────────────────────────┘  │
         ┌──────┐   │     │           │            │         │        │
         │  S6  │◄──┼─────┘           │            │         │        │
         │Trade │   │  ┌──────┐    ┌──────┐    ┌──────┐  ┌──────┐   │
         │Intel.│   │  │  S7  │    │  S8  │    │  S9  │  │  S10 │   │
         └──┬───┘   │  │Risk/ │    │Pivot │    │Post  │  │ML    │   │
            │       │  │Pos.  │    │Calc. │    │Trade │  │Out.  │   │
            ▼       │  │Mgr.  │    │      │    │Anal. │  │Pred. │   │
         ┌──────┐   │  └──────┘    └──────┘    └──────┘  └──────┘   │
         │  S11 │   │                                                 │
         │Trade │   │  ┌──────┐    ┌──────┐                          │
         │Simul.│   │  │  S12 │    │  S13 │                          │
         └──────┘   │  │Narr. │    │Exec. │                          │
                    │  │Build.│    │Layer │                          │
                    │  └──────┘    └──────┘                          │
                    │                                                 │
                    └─────────────────────────────────────────────────┘
```

### 12 сфер — модули системы

| # | Сфера | Модуль | Статус | Функция |
|---|-------|--------|--------|---------|
| **C** | Shared Context Bus | `core/context/pair_context.py` | ✅ Активен | Центральная шина. Хранит полное состояние каждой пары |
| **1** | DataCollector | `core/infra/data_collector.py` | ✅ Активен | OHLCV + ticker с BingX через ccxt |
| **2** | WSFeed | `core/infra/ws_feed.py` | ⚠️ Частично | WebSocket тики. Real-time цены |
| **3** | MTF WT Specialist | `core/ml/mtf_wt_specialist.py` | ✅ Активен | ML на 35 WT-признаках по 7 TF. Вердикт: TREND/REVERSAL/EXHAUSTION |
| **4** | MTF SMC Specialist | `core/ml/mtf_smc_specialist.py` | 🔄 Shadow | ML на 40 SMC-признаках (OB/FVG/CHoCH + Elliott + Pivot) |
| **5** | Market Regime | `core/indicators/market_regime.py` | ✅ Активен | ADX+ATR+EMA → TREND_UP/DOWN/RANGE/HIGH_VOL |
| **6** | Trading Intelligence | `core/trading_intelligence.py` | ✅ Активен | Агрегация сигналов. Принятие решения о входе |
| **7** | Risk/Position Mgr | `core/trading/risk_manager.py` | ✅ Активен | Kelly sizing, max drawdown, correlation guard |
| **8** | Pivot Calculator | `core/pivots/pivot_calculator.py` | ✅ Активен | 1M/1W/1D пивоты. Fibonacci уровни |
| **9** | Post-Trade Analyser | `core/trading/trade_simulator.py` | ✅ Активен | MFE tracking, captured R%, SL/TSL управление |
| **10** | ML OutcomePredictor | `core/ml/outcome_predictor.py` | 🔄 Тренируется | RandomForest. P(win) для каждого сигнала |
| **11** | Trade Simulator | `core/trading/trade_simulator.py` | ✅ Активен | Виртуальные сделки. Статусы TP/SL/TSL/EXPIRED |
| **12** | Narrative Builder | `core/intelligence/` | ✅ Активен | Генерация текстового описания сетапа |
| **13** | Execution Layer | `core/exchange/` | ✅ Активен | VST + будущий LIVE (BingX API) |

---

## Торговая философия: Конфлюенция концепций

Система объединяет **5 концептуальных слоёв**, каждый из которых смотрит на рынок под своим углом:

```
        РЫНОК
          │
          │  Волновая фаза?          → Elliott Wave (n_down/n_up прокси)
          │  Структура сломана?      → SMC: BOS / CHoCH / Order Block / FVG
          │  Где цена в пространстве? → Pivot Points (PP/S1/R1/S2/R2)
          │  Истощение тренда?       → WaveTrend (WT1/WT2, OS/OB зоны)
          │  Расхождение импульса?   → Divergence (Regular / Hidden)
          │
          ▼
     СИГНАЛ (только при конфлюенции ≥2-3 концепций)
```

### Elliott Wave как контекст фазы

```
Нисходящий импульс (5 волн):

    Peak ──────┐
               │ Волна 1 ↓  (первый пробой структуры = BearishBOS)
               └────┐
                    │
               ┌────┘ Волна 2 ↑  ← OTE зона [61.8%-78.6%] = SHORT entry
               │             (коррекция к Order Block волны 1)
               └──────────────┐
                              │ Волна 3 ↓  ← САМАЯ СИЛЬНАЯ
                              │              Ликвидационный каскад
                              │              Серия BOS + FVG
                         ┌────┘
                         │
                    ┌────┘ Волна 4 ↑  ← OTE зона = консервативный SHORT
                    │
                    └────────────┐
                                 │ Волна 5 ↓  ← WT/RSI ДИВЕРГЕНЦИЯ
                                 │              n_down=4+ = ЛОВУШКА
                                 │              STOPшортить без divergence!
                            ABC коррекция вверх ↑
```

**Прокси в коде:** `n_down` = число consecutive снижающихся swing highs = приближение к номеру нисходящей волны.

**Ключевой инсайт из бэктеста n=3597 (28.05.2026):**

| Signal Type | n_down=3 avgR | n_down=4 avgR | Вывод |
|-------------|--------------|--------------|-------|
| `atr_change` SHORT | -0.396 | **-0.904** | n=4 = ловушка |
| **`divergence`** SHORT | +0.709 | **+3.372 WR=79%** | n=4 = GOLD! |
| `wt_b_signal` SHORT | +1.371 | +2.456 | Хорошо при n=3-4 |

**Золотой комбо SHORT:** `4h n_down=4 + 1h n_down=0` → avgR=+1.403, WR=51.6%, n=93.
*(HTF глубокий тренд + MTF отскок = оптимальный момент)*

---

## Как работает система: полный поток

```
┌────────────────────────────────────────────────────────────────────┐
│                         SCAN LOOP (~30 сек)                        │
│                                                                    │
│  ① DataCollector           ② Pre-compute                          │
│    BingX API: OHLCV          4h: Market Regime                     │
│    250 пар × 4 TF            Elliott n_down/n_up (HTF+MTF+LTF)     │
│    25-32 сек                 Pivot Points 1M/1W/1D                 │
│                              SMC snap (OB/FVG/CHoCH/BOS)           │
│                                                                    │
│  ③ Signal Detection (параллельно для каждой пары)                 │
│    ├─ WaveTrend cross (OS/OB zone)                                 │
│    ├─ Divergence (Regular + Hidden, MTF cascade)                   │
│    ├─ ATR Change (trend flip на 15m/1h/4h)                         │
│    ├─ Pivot Reversal (касание уровня + volume)                     │
│    ├─ Liquidity Sweep (stop hunt + reversal)                       │
│    └─ ARCH-104 patterns (15 validated patterns)                    │
│                                                                    │
│  ④ Confirmation-Driven Aggregation                                 │
│    strength = Σ (weight × confidence) по всем подтверждениям       │
│    Confirmations: BOS, FVG, OTE zone, Volume spike, CHoCH, ...     │
│                                                                    │
│  ⑤ Quality Gates (последовательно)                                 │
│    ├─ min_strength ≥ 40 (регистрация) / ≥ 50 (Telegram)           │
│    ├─ AbovePP / BelowPP фильтр (direction-specific)               │
│    ├─ Elliott phase check (n_down × htf_direction)                 │
│    ├─ CHoCH gate (n_down≥3 + BullCHoCH → STOP SHORT)              │
│    ├─ Regime gate, SL cooldown, dedup                              │
│    └─ Fibonacci confluence score                                   │
│                                                                    │
│  ⑥ Trade Simulator                                                 │
│    Регистрация в simulated_trades                                   │
│    SL = swing low/high → pivot ± buffer → ATR fallback             │
│    TP = TPSelector (gravity/dist^1.5 из FVG/PDH/психо уровней)    │
│    TSL = активируется после +1R, следит за ATR trend               │
│                                                                    │
│  ⑦ Shared Context Bus                                              │
│    Публикация результатов → все сферы обновляются                  │
│    ML накапливает features_json для обучения                        │
└────────────────────────────────────────────────────────────────────┘
```

---

## Принцип конфлюенции: математика

**Золотой паттерн** (исследование ARCH-104, 19.05.2026):

```
bull_div_1d + bull_fvg_4h + wt_os_4h
  → n=29, avgR=+1.89, WR=100%  ← лучший паттерн в базе
```

**Формула силы сигнала:**

```python
strength = Σ (confirmation.weight × confirmation.confidence)

# Примеры весов:
OTE zone          → weight=7
CHoCH на HTF      → weight=6-8
BOS               → weight=5
FVG fill          → weight=5
WT cross OS/OB    → weight=3
Volume spike      → weight=4
EQH/EQL sweep     → weight=3
```

**Принцип:**
- 1 подтверждение → наблюдение
- 2-3 подтверждения → сигнал
- 4+ подтверждений → высококонфлюентный вход

---

## Типы сигналов и их характеристики

*(на основе бэктеста n=3587, post-14.05.2026)*

| Signal Type | n | avgR | WR | Специфика |
|-------------|---|------|----|-----------|
| `liquidity_sweep` LONG | 17 | **+4.42** | 64.7% | SSL sweep → ABC коррекция A. AbovePP = +8.6R (инверсия!) |
| `pivot_reversal` SHORT | 30 | **+1.90** | 40.0% | Разворот от R1/R2. PP-нейтрален |
| `wt_b_signal` SHORT | 16 | **+1.40** | 50.0% | WT Type B + дивергенция. HTF критичен |
| `divergence` SHORT | 154 | **+0.92** | 56.5% | Самодостаточен. Лучший при n_down=3-4 |
| `atr_change` SHORT | 392 | -0.27 | 36.7% | PP position критичен. n_down≥4 = ловушка |
| `confluence` SHORT | 765 | -0.71 | 32.5% | Убыточен. Не использовать без фильтров |
| `wt_sideways` SHORT | 208 | -0.90 | 38.9% | Убыточен. Отключён 17.05 |

---

## SL/TP Интеллект

### TPSelector (ARCH-113)

Вместо фиксированного TP бот вычисляет **гравитационный центр** рыночных уровней:

```python
score = gravity / dist^1.5   # α=1.5 доказан на данных 156K уровней, 20 пар, 2.4 года

# Источники уровней:
FVG (молодые, 0-3 бара)   → weight: high, decay быстрый
PDH/PDL (prev day H/L)    → weight: medium, stable
Психологические уровни    → weight: medium
Pivot PP/S1/R1            → weight: high, universal

# TP1 = ближайший кластер (dist<0.5R) — LTF цель
# TP2 = дальний кластер (1-3R)       — HTF цель
```

**Данные:** FVG <0.3R от TP = 73-86% reach rate.

### TSL (Trailing Stop Loss)

```
Активация: после достижения +1R (порог per strategy_type)
Следит за: ATR Supertrend trend direction
De-escalation: при откате 75% от пика → TSL сжимается
Insight (ARCH-104): TSL ВРЕДИТ на validated паттернах
  → no_trail + 24h time exit показывает лучший результат
```

---

## Технологический стек

```
┌─────────────────────────────────────────────────────┐
│  Telegram Bot (aiogram 3.4.1)                       │
│  → Уведомления о сигналах                           │
│  → Статистика, команды, настройки                   │
├─────────────────────────────────────────────────────┤
│  Web Dashboard (aiohttp 3.9.3)                      │
│  → http://localhost:8000                             │
│  → Real-time статистика, дашборды, signal_drops     │
├─────────────────────────────────────────────────────┤
│  Core Engine (Python 3.12)                          │
│  → ccxt 4.2.85 (BingX API)                         │
│  → pandas + numpy (OHLCV анализ)                    │
│  → scikit-learn (ML модели)                         │
│  → asyncio (параллельный скан 250 пар)              │
├─────────────────────────────────────────────────────┤
│  Storage                                             │
│  → SQLite (subscriptions.db)                         │
│  → Таблица: simulated_trades (3597+ строк)           │
│  → features_json: 40+ полей per сделка               │
├─────────────────────────────────────────────────────┤
│  AI Layer (внешние LLM)                             │
│  → Gemini, Cerebras, Mistral, Groq, OpenRouter      │
│  → team_ask.py — коллективный аудит стратегий       │
│  → daily_pipeline.py — ежедневный дайджест          │
└─────────────────────────────────────────────────────┘
```

**Производительность скана:**
- 250 пар × 4 TF = ~1000 API запросов
- Время скана: **25-32 секунды** (CircuitBreaker + LRU cache + asyncio.Semaphore)
- Параллелизм: `Semaphore(20)` — 20 одновременных API запросов

---

## Дорожная карта к LIVE

```
Текущий этап (май 2026):
  ├─ ✅ VST (Virtual Spot Trading) — симуляция на реальных ценах BingX
  ├─ ✅ 3597 закрытых сделок — база для ML обучения
  ├─ ✅ Pattern Mining (ARCH-104) — 15 validated паттернов
  ├─ ✅ TPSelector (ARCH-113) — интеллектуальный TP
  ├─ 🔄 Elliott Wave фильтры — shadow phase (DEV-225)
  └─ 🔄 A/B тест shadow gates (DEV-224)

Следующий этап (июнь 2026):
  ├─ Переход ARCH-104 в Stage 2 (20% капитала)
  ├─ TPSelector в production (A/B подтверждение)
  ├─ Elliott phase detector в features_json
  └─ OutcomePredictor retrain (цель AUC ≥ 0.55)

Переход в LIVE (август-сентябрь 2026):
  Критерии:
  ├─ WR ≥ 38% на новых данных (post-14.05)
  ├─ AUC OutcomePredictor ≥ 0.55
  ├─ 500+ DUAL_TSL сделок → аудит пройден
  └─ Dead-Man Timer реализован (emergency close all)

  Порядок:
  1. VST (сейчас) → LIVE micro-lot (0.01% риска) → LIVE normal (1%)
```

---

## Философия: Emergent Intelligence

Конечная цель системы — не набор жёстких правил, а **обучающийся организм**:

```
Гипотеза (Claude/Trader)
      │
      ▼
Быстрый бэктест (scripts/)
      │
      ▼
Shadow mode (накопление данных без блокировки)
      │
      ▼
Статистическая валидация (n≥30, avgR, WR, Sharpe)
      │
      ▼
Production gate (HARD блок / усилитель)
      │
      ▼
ML обучается на новых фичах
      │
      ▼
Новые гипотезы... ← петля обратной связи
```

Система сама генерирует знание о рынке через опыт сделок, а не через хардкод правил.

**Куб Метатрона** — не просто красивая метафора. Это принцип, который позволяет системе **видеть рынок целиком**: каждая сфера вносит свой угол зрения, и именно в точке пересечения всех взглядов рождается торговое решение высокого качества.

---

## Структура проекта

```
crypto_volume_bot/
├── oko_mtf.py              ← точка входа
├── config.yaml             ← конфигурация (hot-reload)
├── subscriptions.db        ← главная БД (SQLite)
│
├── core/                   ← бизнес-логика (чистый Python)
│   ├── infra/              ← DataCollector, WS, API engine
│   ├── indicators/         ← WT, RSI, ATR, EMA, Elliott, Pivots
│   ├── signals/            ← детекторы сигналов
│   ├── smc/                ← SMC библиотека (OB/FVG/BOS/CHoCH/OTE)
│   ├── trading/            ← TradeSimulator, TSL, MFE
│   ├── ml/                 ← OutcomePredictor, WT/SMC Specialists
│   ├── pivots/             ← PivotCalculator (1M/1W/1D)
│   └── intelligence/       ← SignalAggregator, TPSelector
│
├── bot/                    ← UI слой (aiogram)
│   ├── loops/              ← scan_loop, arch104_observer
│   └── handlers/           ← Telegram команды
│
├── web/                    ← Dashboard (aiohttp, port 8000)
│
├── docs/                   ← Документация
│   ├── ENCYCLOPEDIA.md     ← Куб Метатрона + архитектура
│   ├── STRATEGIES/         ← Описание торговых стратегий
│   ├── LONG_ENTRY_RULES.md ← Правила входа LONG
│   └── SHORT_ENTRY_RULES.md← Правила входа SHORT
│
├── obsidian/               ← База знаний (~700 файлов)
│   └── Concepts/           ← Elliott Wave, SMC, WT, Pivots, MTF
│
└── scripts/                ← Бэктесты и анализ
    └── elliott_n_down_backtest.py ← n=3597, последний анализ
```

---

*Документ создан: 28.05.2026 | Oko MTF Bot v2.x | BingX exchange*
