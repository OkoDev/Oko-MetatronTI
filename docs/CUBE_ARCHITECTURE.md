# Куб Метатрона — Полная архитектурная схема
> Oko MTF Bot · Актуально на 2026-04-18 · 427 пар · 3200+ сделок

---

## 1. Все сферы и рёбра — полносвязный граф

```mermaid
flowchart TD
    %% ════════════════════════════════════════
    %% ИНФРАСТРУКТУРА
    %% ════════════════════════════════════════
    subgraph INFRA["🌐 Инфраструктура"]
        EX["BingX<br/>ccxt 4.2.85"]
        AE["ApiEngine<br/>LRU·CB·Retry·Sem20"]
        DC["DataCollector<br/>OHLCV + Ticker"]
        DB[("SQLite<br/>subscriptions.db")]
    end

    %% ════════════════════════════════════════
    %% ДЕТЕКТОРЫ СИГНАЛОВ (9 типов)
    %% ════════════════════════════════════════
    subgraph DET["📡 Детекторы сигналов"]
        D1["WT Signal<br/>cross ±60"]
        D2["WT-B Signal<br/>★ WR=85%"]
        D3["MTF Signal<br/>7 TF alignment"]
        D4["Divergence<br/>reg/hidden cascade"]
        D5["Anomaly<br/>volume×3"]
        D6["Pivot Reversal<br/>S1/R1 + WT + FVG"]
        D7["Confluence<br/>ReversalScanner★"]
        D8["MTF Alert<br/>5 мин фоновый"]
        D9["Trend Signal<br/>4h+1h+15m+5m"]
    end

    %% ════════════════════════════════════════
    %% SMC СЛОЙ
    %% ════════════════════════════════════════
    subgraph SMC["🏗️ SMC Layer (core/smc/)"]
        SMC1["swing_points<br/>HH/HL/LH/LL"]
        SMC2["structure<br/>BOS / CHoCH"]
        SMC3["fvg<br/>Fair Value Gap"]
        SMC4["order_blocks<br/>OB последний"]
        SMC5["fibonacci<br/>OTE 0.618-0.786"]
        SMC6["liquidity<br/>swept/unswept"]
        SMCC["SMCContext<br/>агрегат"]
    end

    %% ════════════════════════════════════════
    %% ML СЛОЙ (3 модели)
    %% ════════════════════════════════════════
    subgraph ML["🤖 ML Layer"]
        ML1["OutcomePredictor<br/>RF P(win) AUC~0.56"]
        ML2["MLPredictor<br/>GB PRICE_DIR + STRENGTH"]
        ML3["RPredictor<br/>GBR expected_R → Kelly"]
        MR["MarketRegime<br/>ADX+ATR+EMA<br/>4 режима"]
    end

    %% ════════════════════════════════════════
    %% INTELLIGENCE LAYER
    %% ════════════════════════════════════════
    subgraph INT["🧠 Trading Intelligence"]
        IA["signal_aggregator<br/>adaptive_weighted_strength"]
        IB["confidence_calc<br/>signal×zone×regime"]
        IC["recommendation_gen<br/>SL/TP иерархия<br/>RR≥2.0 фильтр"]
        ID["ml_enhancer<br/>P(win) blend · Kelly"]
        TI["TradingIntelligence<br/>analyze_symbol<br/>⏱ HARD 20s · ML 5s"]
    end

    %% ════════════════════════════════════════
    %% СТРАТЕГИИ
    %% ════════════════════════════════════════
    subgraph STR["♟️ Стратегии"]
        S1["ReversalScanner ★<br/>TSL cross + WT cross<br/>+ pivot + div"]
        S2["PivotReversal<br/>S1/R1 + WT + FVG"]
        S3["MTFBias<br/>7 TF + senior gate"]
        S4["Conservative<br/>min 3 сигнала"]
        RS["regime_strategy<br/>TREND→TRIPLE_TP_TSL<br/>RANGE→DUAL_TP<br/>HIGH_VOL→×0.5"]
    end

    %% ════════════════════════════════════════
    %% ФИЛЬТРЫ (monitoring.py)
    %% ════════════════════════════════════════
    subgraph FILT["🔒 Фильтры (monitoring.py)"]
        F1["dedup<br/>30 мин / пара"]
        F2["SL cooldown<br/>4 ч после SL"]
        F3["BTC regime<br/>HIGH_VOL block"]
        F4["WATCH+NEUTRAL<br/>skip"]
        F5["is_actionable<br/>str≥50 · BUY/SELL"]
        F6["DEV-155/156<br/>min_str по режиму<br/>CircuitBreaker"]
    end

    %% ════════════════════════════════════════
    %% QUALITY GATES
    %% ════════════════════════════════════════
    subgraph QG["🛡️ Quality Gates (register_trade_async)"]
        G1["Market Stress<br/>5+ SL за 30 мин"]
        G2["Correlation Guard<br/>BTC/WBTC · PAXG/XAUT"]
        G3["Regime Block<br/>LONG в TREND_DOWN"]
        G4["Portfolio Limit<br/>2L+2S+4 total"]
        G5["max_rr cap<br/>RR>3 → обрезать"]
    end

    %% ════════════════════════════════════════
    %% СИМУЛЯТОР СДЕЛОК
    %% ════════════════════════════════════════
    subgraph SIM["💾 Trade Simulator"]
        TS["TradeSimulator<br/>register · track · close"]
        TT["TradeTracker<br/>⏱ каждые 5 мин"]
        MFE["MFE Tracker<br/>max/min price<br/>max_R · captured_R%"]
        TSL_NODE["Cascade TSL<br/>15m→1h→4h<br/>активация +1R"]
        BE["Breakeven<br/>+0.8R → SL=entry"]
    end

    %% ════════════════════════════════════════
    %% PERFORMANCE + ОБУЧЕНИЕ
    %% ════════════════════════════════════════
    subgraph PERF["📊 Performance + ML Retrain"]
        PE["PerformanceEngine<br/>stats · by_signal_type<br/>weekly_summary"]
        WU["update_weights<br/>base × clamp(1+avgR×0.4)"]
        FIT["OutcomePredictor.fit<br/>каждое закрытие"]
    end

    %% ════════════════════════════════════════
    %% BOT / UI
    %% ════════════════════════════════════════
    subgraph BOT["🤖 Bot / UI (aiogram 3.4.1)"]
        TG["Telegram<br/>broadcast"]
        CMD["/intelligence · /scan<br/>/pivots · /settings"]
        WL["SignalWatchList<br/>WATCH → escalate"]
        DASH["Dashboard :8000<br/>aiohttp (read-only)"]
    end

    %% ════════════════════════════════════════
    %% БУДУЩИЕ УЗЛЫ (Фазы 1-3)
    %% ════════════════════════════════════════
    subgraph FUTURE["🔮 Фаза 1-3 (Реактивный граф)"]
        PCB["PairContextBus<br/>Фаза 1 · DEV-93<br/>regime · cascade_count<br/>post_tsl_data"]
        PTA["PostTradeAnalyser<br/>Фаза 2 · DEV-94<br/>SL→reversal WL<br/>TSL→OTE queue"]
        TB["TriggerBus<br/>Фаза 3 · DEV-95<br/>event-driven scan"]
    end

    %% ════════════════════════════════════════
    %% РЁБРА — ПОТОК ДАННЫХ
    %% ════════════════════════════════════════

    EX -->|"ccxt fetch_ohlcv"| AE
    AE -->|"OHLCV DataFrame"| DC
    DC -->|"prefetch 15m+1h+3m"| D1 & D2 & D3 & D4 & D5 & D6 & D7
    DC -->|"фоновые / 5 мин"| D8 & D9

    %% SMC внутренние связи
    DC --> SMC1
    SMC1 --> SMC2
    SMC2 --> SMC3
    SMC3 --> SMC4
    SMC4 --> SMC5
    SMC5 --> SMC6
    SMC1 & SMC2 & SMC3 & SMC4 & SMC5 & SMC6 --> SMCC

    %% Детекторы → Фильтры
    D1 & D2 & D3 & D4 & D5 & D6 & D7 & D8 & D9 -->|"SignalData[]"| F1
    F1 --> F2 --> F3 --> F4

    %% SMC → Intelligence
    SMCC -->|"SMCContext"| TI

    %% Intelligence внутренние связи
    F4 -->|"pre_signals"| TI
    TI --> IA --> IB --> IC --> ID

    %% Стратегии → Intelligence
    S1 & S2 & S3 & S4 --> TI
    RS -->|"адаптация SL/TP"| IC

    %% ML ↔ Intelligence (двунаправленно)
    ML1 & ML2 & ML3 -->|"P(win) · Kelly · strength"| ID
    MR -->|"TREND/RANGE/HIGH_VOL"| TI
    MR -->|"режим"| RS

    %% Intelligence → Фильтры actionable
    TI -->|"TradingRecommendation"| F5
    F5 --> F6

    %% Фильтры → Quality Gates → Симулятор
    F6 -->|"should_register"| G1 --> G2 --> G3 --> G4 --> G5
    G5 --> TS

    %% Фильтры → TG (сообщение всегда)
    F6 -->|"broadcast"| TG

    %% Симулятор → DB
    TS -->|"INSERT simulated_trades"| DB
    DB -->|"SELECT OPEN"| TT

    %% Трекер внутри
    TT --> MFE
    TT --> BE
    TT --> TSL_NODE
    TSL_NODE -->|"Cascade 15m→1h→4h"| DC

    %% Закрытие → DB
    TT -->|"UPDATE status=TP/SL/TSL/EXPIRED"| DB

    %% DB → Performance + ML обратная связь
    DB -->|"закрытые сделки"| PE
    DB -->|"каждое закрытие"| FIT & WU
    FIT -->|"новые P(win)"| ML1
    WU -->|"новые веса"| IA
    ML2 & ML3 -->|"retrain ← features_json"| DB

    %% Bot UI
    CMD -->|"manual analyze_symbol"| TI
    DB -->|"read stats"| DASH
    DB -->|"read trades"| CMD
    WL -->|"WATCH→escalate"| F5

    %% Будущие рёбра (пунктир = планируемые)
    TS -.->|"Фаза 1"| PCB
    TT -.->|"post_tsl"| PCB
    PCB -.->|"Фаза 2"| PTA
    PTA -.->|"reversal WL"| WL
    PTA -.->|"OTE queue"| TI
    PCB -.->|"Фаза 3"| TB
    TB -.->|"event trigger"| TI
```

---

## 2. Внутренности Intelligence Layer — детальная схема

```mermaid
flowchart LR
    subgraph INPUT["Входные сигналы"]
        PS["pre_signals<br/>List[SignalData]"]
        SMC_IN["SMCContext<br/>FVG · OB · BOS"]
        MTF_IN["MTFContext<br/>bias · aligned%"]
    end

    subgraph TI_CORE["TradingIntelligence.analyze_symbol()"]
        direction TB
        SNAP["snapshot_time = now()<br/>дедупликация по времени"]
        COL["_collect_all_signals()<br/>⏱ HARD 20 сек<br/>wt·anomaly·mtf·smc·div·pivot"]
        AGG["signal_aggregator<br/>_analyze_signals_advanced<br/>adaptive_weighted_strength<br/>FAVOR = direction × weight"]
        CONF["confidence_calculator<br/>signal_count_factor<br/>× zone_factor<br/>× regime_factor"]
        SL_TP["recommendation_generator<br/>SL: swing→pivot→FVG→TSL→ATR<br/>TP: следующий пивот ≥ min_R<br/>RR ≥ 2.0 фильтр"]
        ML_E["ml_enhancer ⏱ 5 сек<br/>P(win) → blend confidence<br/>Kelly → position_size<br/>RPredictor → expected_R"]
        REC["_generate_recommendation<br/>BUY/SELL/WATCH/HOLD<br/>strategy_type<br/>risk_level"]
        SNAP --> COL --> AGG --> CONF --> SL_TP --> ML_E --> REC
    end

    subgraph WEIGHTS["Адаптивные веса"]
        W1["MTF_BIAS 0.50 ★"]
        W2["PIVOT_REVERSAL 0.24"]
        W3["WT_B 0.15 ★"]
        W4["CONFLUENCE 0.15"]
        W5["SMC_STRUCT 0.12"]
        W6["DIVERGENCE 0.10"]
        W7["WT 0.133"]
        W8["TREND 0.04"]
        W9["ANOMALY 0.03"]
    end

    PS --> COL
    SMC_IN --> ML_E
    MTF_IN --> CONF

    W1 & W2 & W3 & W4 & W5 & W6 & W7 & W8 & W9 --> AGG
```

---

## 3. Жизненный цикл сделки — конечный автомат

```mermaid
stateDiagram-v2
    [*] --> OPEN : register_trade_async, Quality Gates OK, RR ge 2.0

    state OPEN {
        [*] --> Tracking
        Tracking --> BE_SET : current_R ge 0.8, SL = entry
        Tracking --> TSL_ON : current_R ge 1.0, Cascade TSL
        TSL_ON --> TSL_WIDE : тренд 4h совпадает
        TSL_ON --> TSL_MED : тренд 1h совпадает
        TSL_ON --> TSL_TIGHT : тренд 15m совпадает
        Tracking --> TP1 : price ge tp1, BE обязателен
        TP1 --> TP2 : price ge tp2
    }

    OPEN --> TP : price ge take_profit
    OPEN --> SL : price le stop_loss
    OPEN --> TSL_CLOSE : trailing stop пробит
    OPEN --> EXPIRED : duration gt 48h

    TP --> RETRAIN : update_weights + OutcomePredictor.fit
    SL --> RETRAIN
    TSL_CLOSE --> RETRAIN
    RETRAIN --> [*]
    EXPIRED --> [*]

    note right of TSL_CLOSE
        TSL пишет post_tsl_data
        в PairContextBus (Фаза 1)
    end note
    note right of SL
        SL cooldown 4h
        на эту пару
    end note
```

---

## 4. Детекторы — типы и параметры

```mermaid
flowchart TD
    subgraph SCAN_LOOP["scan_one() — каждые 60 сек · Sem(20)"]
        D_WT["WT Signal<br/>wt1 cross wt2<br/>±60 zone · gap≥3<br/>str=70 · conf=0.8"]
        D_WTB["WT-B Signal ★<br/>1h · adaptive p10/p90<br/>div_strength 3-20<br/>str=70-90 · WR=85%"]
        D_MTF["MTF Signal<br/>1h trend + 15m WT<br/>+ 3m OB/OS<br/>str=85 · conf=0.9"]
        D_DIV["Divergence<br/>reg_bull/bear · hidden<br/>cascade 1h→15m<br/>bonус иерархии +25"]
        D_ANO["Anomaly<br/>volume > 3× MA20<br/>str=min(vol×10,100)"]
        D_CONF["Confluence ★<br/>ReversalScanner<br/>TSL cross + WT cross<br/>+ pivot 0.15% + div"]
    end

    subgraph BG_5MIN["Фоновые задачи — каждые 5 мин · Sem(10)"]
        D_MTF_A["MTF Alert<br/>7 TF alignment<br/>Classic/Aggr/Cons"]
        D_TREND["Trend Signal<br/>4h+1h+15m+5m<br/>Классик/Агрессив/Конс"]
        D_PIV["Pivot Reversal<br/>S1/R1 ±0.5% + WT<br/>+ FVG бонус +10"]
    end

    subgraph BG_1H["Фоновые — каждый час"]
        D_CASCADE["Cascade Divergence<br/>4h→1h hidden+regular<br/>бонус +15"]
    end

    D_WT & D_WTB & D_MTF & D_DIV & D_ANO & D_CONF --> FILT_OUT["→ Фильтры monitoring.py"]
    D_MTF_A & D_TREND & D_PIV --> FILT_OUT
    D_CASCADE --> FILT_OUT
```

---

## 5. SMC Layer — внутренности

```mermaid
flowchart LR
    OHLCV["OHLCV<br/>DataFrame"] --> SP

    subgraph SMC_PKG["core/smc/ (ARCH-17)"]
        SP["swing_points.py<br/>HH/HL/LH/LL<br/>(lookback=5)"]
        ST["structure.py<br/>BOS — пробой структуры<br/>CHoCH — смена характера<br/>Breaker Blocks"]
        FV["fvg.py<br/>Fair Value Gap<br/>mitigation check"]
        OB["order_blocks.py<br/>Последняя свеча перед BOS<br/>33-бар OB критерий"]
        LQ["liquidity.py<br/>swept / unswept<br/>кластеры"]
        FB["fibonacci.py<br/>OTE: 0.618–0.786<br/>от last swing"]
        CTX["context.py<br/>SMCContext агрегат<br/>→ TradingIntelligence"]
    end

    SP --> ST
    SP --> FV
    SP --> FB
    ST --> OB
    ST --> LQ
    SP & ST & FV & OB & LQ & FB --> CTX

    CTX -->|"ARCH-28: FVG+Pivot<br/>Confluence бонус"| BONUS["strength bonus<br/>if price in FVG zone"]
```

---

## 6. ML Layer — обратная связь

```mermaid
flowchart TD
    subgraph ML_MODELS["ML Models (core/)"]
        OP["OutcomePredictor<br/>RandomForest<br/>12 признаков<br/>Таргет: TP=1/SL=0<br/>AUC ~0.56"]
        MP["MLPredictor<br/>GradientBoosting<br/>OHLCV-based<br/>PRICE_DIRECTION<br/>SIGNAL_STRENGTH"]
        RP["RPredictor<br/>GBR<br/>expected_R<br/>→ Kelly fraction"]
        MRC["MarketRegime<br/>ADX+ATR+EMA<br/>TREND_UP<br/>TREND_DOWN<br/>RANGE<br/>HIGH_VOL"]
    end

    DB[("SQLite<br/>simulated_trades")] -->|"закрытые сделки<br/>+ features_json"| OP & MP & RP
    OP -->|"P(win)"| BLEND["confidence blend<br/>= 0.7×calc + 0.3×P(win)"]
    RP -->|"expected_R"| KELLY["Kelly f<br/>position_size"]
    MP -->|"strength adj"| STRENGTH["overall_strength<br/>± ML delta"]
    MRC -->|"режим 4 класса"| REGIME_GATE["Quality Gates<br/>+ adaptive SL/TP<br/>+ min_strength DEV-155"]

    BLEND & KELLY & STRENGTH --> TI_OUT["TradingRecommendation<br/>итог"]

    subgraph RETRAIN["Обновление при закрытии сделки"]
        FIT1["OutcomePredictor.fit()<br/>Определяет: TP ✅ или SL ❌"]
        WU["update_signal_weights()<br/>new = base × clamp(1 + avgR × 0.4)"]
    end

    DB -->|"каждое закрытие"| FIT1 & WU
    WU -->|"обновляет веса"| WEIGHTS_OUT["adaptive_weighted_strength<br/>в signal_aggregator"]
```

---

## 7. Фазы перехода к Куб-архитектуре

```mermaid
flowchart LR
    subgraph NOW["✅ СЕЙЧАС — Линейный пайплайн"]
        N1["DataCollector"]
        N2["6+ Детекторов"]
        N3["TradingIntelligence<br/>stateless"]
        N4["TradeSimulator<br/>stateless"]
        N5["DB — закрыто, забыто"]
        N1 --> N2 --> N3 --> N4 --> N5
    end

    subgraph F1["🔨 Фаза 1 (апрель)<br/>DEV-91·92·93"]
        P1_1["DEV-93<br/>PairContextBus<br/>core/context/pair_context.py<br/>singleton in-memory"]
        P1_2["DEV-92<br/>_post_tsl_queue<br/>в TradeSimulator<br/>TTL=8h"]
        P1_3["DEV-91<br/>R-gradient trigger<br/>shadow mode"]
    end

    subgraph F2["🔨 Фаза 2 (май)<br/>DEV-94"]
        P2["PostTradeAnalyser<br/>core/trading/post_trade_analyser.py<br/>SL → reversal WL<br/>TSL → OTE Re-entry<br/>TP → continuation scan"]
    end

    subgraph F3["📅 Фаза 3 (июнь+)<br/>DEV-95"]
        P3_1["TriggerBus<br/>core/context/trigger_bus.py"]
        P3_2["TriggerLoop<br/>bot/loops/trigger_loop.py<br/>event-driven scan<br/>(vs uniform polling)"]
    end

    subgraph VALIDATE["🔬 Фаза 0 — Валидация (апрель)<br/>без неё нельзя дальше"]
        V1["DEV-87<br/>OTE backtest v2"]
        V2["DEV-90<br/>Market Regime v2<br/>shadow"]
        V3["TR-011<br/>SMC shadow WR<br/>по логам"]
    end

    VALIDATE -->|"узлы доказали ценность"| F1
    F1 -->|"P_post_tsl_queue работает"| F2
    F2 -->|"PTA валидирован"| F3
    F3 -->|"полносвязная система"| CUBE["⬡ Куб Метатрона<br/>Emergent Intelligence<br/>сistema видит вещи<br/>которые stateless<br/>не может"]

    NOW -.->|"инкрементальный переход"| F1
```

---

## 8. Цепочка фильтров — от детектора до Telegram

```mermaid
flowchart TD
    SIG["Сигнал обнаружен<br/>SignalData"] --> D1_CHK

    D1_CHK{{"DIV фильтр?<br/>только для<br/>дивергенций"}}
    D1_CHK -->|"WT zone<br/>+ pivot ±2%"| F_DEDUP
    D1_CHK -->|"другие<br/>сигналы"| F_DEDUP

    F_DEDUP{{"dedup_minutes=30<br/>ключ: symbol"}}
    F_DEDUP -->|"дубликат"| SKIP1["⛔ skip<br/>DEBUG лог"]
    F_DEDUP -->|"ок"| F_COOL

    F_COOL{{"SL cooldown<br/>4 ч после SL"}}
    F_COOL -->|"cooldown"| SKIP2["⛔ skip<br/>DEBUG лог"]
    F_COOL -->|"ок"| F_BTC

    F_BTC{{"BTC режим<br/>HIGH_VOL?"}}
    F_BTC -->|"HIGH_VOL<br/>block mode"| SKIP3["⛔ skip<br/>INFO лог"]
    F_BTC -->|"counter-trend<br/>shadow"| AI_WARN["⚠️ btc_warning<br/>+ btc_counter_trend<br/>в features_json"]
    F_BTC -->|"ок"| AI

    AI["analyze_symbol()<br/>⏱ HARD 20 сек<br/>TradingRecommendation"] --> F_NEUTRAL

    F_NEUTRAL{{"WATCH +<br/>NEUTRAL?"}}
    F_NEUTRAL -->|"да"| SKIP4["⛔ skip<br/>INFO лог"]
    F_NEUTRAL -->|"нет"| WL_CHK

    WL_CHK{{"action=WATCH +<br/>чёткое направление?"}}
    WL_CHK -->|"да"| WL_ADD["SignalWatchList<br/>может escalate<br/>→ BUY/SELL"]
    WL_CHK -->|"нет"| F_DEV155

    F_DEV155["DEV-155/156<br/>min_strength<br/>по режиму<br/>CircuitBreaker"] --> F_ACTION

    F_ACTION{{"is_actionable?<br/>str≥50 · BUY/SELL<br/>direction≠NEUTRAL"}}
    F_ACTION -->|"нет"| TG_WATCH["📱 TG: WATCH<br/>❌ Не зарегистрирован<br/>INFO лог причины"]
    F_ACTION -->|"да"| F_REG

    F_REG{{"should_register?<br/>str≥75"}}
    F_REG -->|"нет"| TG_ONLY["📱 TG: сигнал<br/>❌ Не зарегистрирован"]
    F_REG -->|"да"| GATES

    GATES["Quality Gates<br/>① Market Stress<br/>② Correlation<br/>③ Regime Block<br/>④ Portfolio Limit<br/>⑤ max_rr cap"] --> DB_INS

    DB_INS["💾 INSERT simulated_trades<br/>+ 📱 TG: ✅ Зарегистрировано"]

    AI_WARN --> F_NEUTRAL
    WL_ADD --> F_DEV155
```

---

## Примечания к схемам

| Обозначение | Смысл |
|---|---|
| ★ | Ключевой компонент с высоким WR |
| ⏱ | Операция с таймаутом |
| `→` | Прямой поток данных |
| `-.->` | Планируемая связь (Фазы 1-3) |
| DEV-NNN | Номер задачи в TASKS.md |
| ARCH-NN | Архитектурное решение |

**Философия «Куб Метатрона»:**
> Каждая из 13 точек соединена с каждой другой. Нет привилегированных путей, нет слепых зон.
> Система «знает» вещи которые ни один индикатор не может вычислить сам по себе.
> *Но: полносвязная система с непроверенными узлами = leverage на ошибки. Фундамент — сначала.*
