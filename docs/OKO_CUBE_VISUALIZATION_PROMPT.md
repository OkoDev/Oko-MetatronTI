# OKO MTF Bot — Полная схема Куба Метатрона для AI-визуализации

> Для генерации через Midjourney / DALL-E 3 / Stable Diffusion XL / Ideogram

---

## Соответствие нашей картины изображению

На полученном изображении уже правильно:
- Центральная сфера = Shared Context Bus ✅
- Зелёные левые сферы = ML/Intelligence слой ✅
- Оранжевые правые сферы = Data/Signal слой ✅
- Sub-кубы как кластеры малых сфер ≈ есть
- Таблицы-аннотации ✅
- Петли обратной связи (Regime → Weight) ✅

**Что нужно добавить в следующую версию:**
- 3 явных Sub-куба (SMC, Elliott-Pivot, WT) как вложенные мини-Кубы
- Новые сферы 14 (WaveService), 15 (WTService/RSIService)
- Цветовое разделение Sub-кубов
- Слой "5 Платоновых тел" как фоновые геометрии

---

## Полная карта сфер для промпта

```
ЦЕНТР: Shared Context Bus (ярко-белый/золотой пульсирующий кристалл)
       core/context/pair_context.py — PairFullState

СЛОЙ 1 — ДАННЫЕ (синие сферы, левый и нижний кластер):
  S1: DataCollector       — OHLCV polling, BingX API
  S2: WSFeed              — WebSocket real-time ticks (частично подключён)

СЛОЙ 2 — СИГНАЛЫ (оранжевые сферы, правый кластер):
  S7: Signal Detectors    — confluence, divergence, atr_change, pivot, liquidity_sweep
  S8: Pivot Levels        — PP/S1-S3/R1-R3, Fibonacci-proxy

СЛОЙ 3 — КОНТЕКСТ (фиолетовые сферы, верхний кластер):
  S5: Cross-Market Node   — BTC regime, USDT.D, BTC Dominance
  S6: Market Regime       — TREND_UP/DOWN/RANGE/HIGH_VOL + mode=REVERSAL/TREND

СЛОЙ 4 — ML/INTELLIGENCE (зелёные сферы, левый верхний кластер):
  S3: MTF WT Specialist   — 35 WT-признаков × 7 TF → TREND/REVERSAL/EXHAUSTION
  S4: MTF SMC Specialist  — 40 SMC-признаков × 4 TF → STRONG_BEAR/BULL/NEUTRAL
  S10: ML Outcome Pred    — RandomForest P(win), Kelly sizing
  S9: Narrative Builder   — human-readable narrative → TG

СЛОЙ 5 — ИСПОЛНЕНИЕ (красные сферы, нижний правый):
  S11: Trade Simulator    — SL/TP/TSL tracking, VST
  S13: Execution Layer    — BingX API orders
  S7: Exit Manager        — cascade TSL 15m→1h→4h

СЛОЙ 6 — ОБРАТНАЯ СВЯЗЬ (бирюзовые сферы):
  S11: Post-Trade Analyser — MFE, captured_R, feedback loop
  S12: Self-Diagnostics    — validation all 12 spheres

НОВЫЕ СФЕРЫ (золотые, особое выделение):
  S14: WaveService (ARCH-121) — Elliott n_down/n_up/phase, волновой прокси
  S15: WTService (ARCH-117)   — единая формула WT для всех потребителей

SUB-КУБЫ (светящиеся кластеры внутри большой сферы):
  SMC Sub-куб  (внутри S4): OB + FVG + Structure + Liquidity + OTE → SMCContext
  Elliott-Pivot Sub-куб (S8+S14): WaveService + PivotSphere + FibClusters → PricePositionContext
  WT Sub-куб   (внутри S3, vision): WT×5TF → MTF_WT_Verdict
```

---

## Промпт для Midjourney / DALL-E 3

### Короткий (для DALL-E):

```
A dark cyberpunk visualization of "Metatron's Cube" as a neural trading AI architecture.
Central glowing golden sphere labeled "Shared Context Bus" connected to 14 outer spheres
arranged in sacred geometry. Color layers: blue=data, orange=signals, purple=context,
green=ML intelligence, red=execution, teal=feedback. Three nested "sub-cubes" glow inside
specific spheres showing fractal structure. Neural connection lines pulse with data flow.
Dark space background with holographic grid. Technical annotations floating near each sphere.
Style: futuristic HUD, neon bioluminescence, quantum computing aesthetic.
```

### Детальный (для Midjourney v6):

```
/imagine prompt: Metatron's Cube sacred geometry as an advanced cryptocurrency trading AI system visualization, dark background with deep space nebula, central sphere "SHARED CONTEXT BUS" radiating gold and white light, 14 outer spheres connected by glowing neural pathways, spheres color-coded by function: electric blue spheres for data collection (DataCollector, WSFeed), bright orange for signal detectors (divergence, confluence, pivot, WaveTrend), deep purple for market context (Cross-Market, MarketRegime), emerald green for ML intelligence (MTF WT Specialist, SMC Specialist, Narrative Builder), crimson for execution (Trade Simulator, Exit Manager, TSL cascade), teal for feedback loops (Post-Trade Analyser, Diagnostics), gold accent spheres for new Wave Service and WT Service, three smaller sub-cube clusters nested within larger spheres showing fractal architecture (SMC sub-cube with 5 inner spheres: OB, FVG, Structure, Liquidity, OTE; Elliott-Pivot sub-cube; WT sub-cube), holographic data flow lines between all nodes, floating text annotations with file paths and technical specs, "5 Platonic Solids" as geometric background shapes (cube, octahedron, tetrahedron, icosahedron, dodecahedron), regime-weight-adaptation feedback arrow loop, bottom data table "ANATOMY OF CENTRAL BUS" and right table "FIVE PLATONIC SOLIDS", cyberpunk aesthetic with neon bioluminescence, quantum computing hologram style, trading dashboard HUD overlay, photorealistic render, 8K, intricate detail --ar 16:9 --v 6 --q 2
```

### Вариант с русскими аннотациями:

```
/imagine prompt: Metatron's Cube as a living AI trading system, 15 spheres in sacred geometry formation, center: "SHARED CONTEXT BUS / PairFullState 38 fields 22 events", labeled spheres in Russian and English: "MTF WT Specialist / 35 признаков / 7 TF", "MTF SMC Specialist / 40 признаков / 4 TF", "Signal Detectors / confluence divergence atr_change", "Pivot Levels / PP S1-S3 R1-R3", "Market Regime / TREND REVERSAL", "WaveService / Elliott n_down phase" (glowing gold), "WTService / единая формула WT" (glowing gold), three fractal sub-cubes labeled "SMC Sub-куб / OB+FVG+Structure+Liquidity", "Elliott-Pivot Sub-куб / Wave+Pivot+Fib", "WT Sub-куб vision", cyberpunk dark space background, holographic HUD, neon connections, floating code annotations --ar 16:9 --v 6
```

---

## Промпт для Stable Diffusion XL (детальный negative):

```
Positive:
metatron cube sacred geometry, 15 glowing spheres, central golden crystal hub, 
neural network connections, dark holographic space, color-coded nodes (blue data, 
orange signals, green ML, red execution, teal feedback, gold new spheres),
three fractal sub-cube clusters nested inside spheres, floating technical annotations,
trading AI system architecture diagram, cyberpunk aesthetic, quantum hologram, 
neon bioluminescence, 8K detail, professional visualization

Negative:
cartoon, anime, low quality, blurry, text errors, distorted geometry, 
flat design, white background, simple diagram, watermark
```

---

## Цветовая схема (для точности воспроизведения)

| Слой | Цвет | Hex | Сферы |
|------|------|-----|-------|
| Центральная шина | Золото/Белый | #FFD700 / #FFFFFF | Shared Context Bus |
| Данные | Электрик синий | #00BFFF | S1 DataCollector, S2 WSFeed |
| Сигналы | Оранжевый | #FF8C00 | S7 Detectors, S8 Pivots |
| Контекст | Фиолетовый | #9B59B6 | S5 CrossMarket, S6 Regime |
| ML/AI | Изумрудный | #2ECC71 | S3 WT, S4 SMC, S10 ML, S9 Narrative |
| Исполнение | Красный/Рубин | #E74C3C | S11 Simulator, S13 Execution, Exit |
| Обратная связь | Бирюзовый | #1ABC9C | S11 PostTrade, S12 Diagnostics |
| **Новые сферы** | **Золото яркое** | **#FFD700** | S14 WaveService, S15 WTService |
| Sub-кубы | Белый + цвет родителя | — | SMC, Elliott-Pivot, WT |
| Соединения | Градиент синий→белый | — | Neural pathways |

---

## Компоненты для таблиц (как на изображении)

### Таблица 1: Анатомия центральной шины

| Tier | Fields | Содержимое |
|------|--------|-----------|
| 0 | DataCollector | OHLCV snaps per TF |
| 1 | PairFullState | 38 полей состояния |
| 2 | WSFeed | Real-time ticks |
| 3 | core/context/ | pair_context.py |
| 4 | Signals | 22 event types |
| 5 | Volume | anomaly + books |
| 6 | CI trigger | confidence loop |

### Таблица 2: Пять Платоновых тел

| Тело | Слой | Tech Stack |
|------|------|-----------|
| Гексаэдр | Storage | SQLite, persistence |
| Октаэдр | Network | ccxt, BingX API |
| Тетраэдр | Logic | 15 сфер, Bus |
| Икосаэдр | Flow | TG, Dashboard |
| Додекаэдр | AI | ML models |

### Таблица 3: Sub-кубы (НОВОЕ)

| Sub-куб | Статус | Сферы | Центр |
|---------|--------|-------|-------|
| SMC | ✅ В коде | OB+FVG+Struct+Liq+OTE | SMCContext |
| Elliott-Pivot | 🔄 Строится | Wave+Pivot+Fib | PricePositionContext |
| WT | 🔵 Vision | WT×15m/1h/4h/1d/1w | MTF_WT_Verdict |

---

## Петли обратной связи (стрелки на схеме)

```
1. Regime → Weight Adaptation
   MarketRegime.mode → SignalAggregator.weights → entry boost/block

2. Outcome → Model Retrain  
   TradeSimulator.R_multiple → PostTradeAnalyser → ML.retrain()

3. Critique Loop
   SelfDiagnostics → всем сферам (validation эталонами)

4. Wave → TP Modifier (НОВОЕ, ARCH-115)
   WaveService.phase → TPSelector.phase_modifier → TP targets

5. SMC → Entry Filter (НОВОЕ)
   SMCContext.verdict → execute_functions → boost/block
```

---

## Ключевые надписи для финального изображения

**Центр:** `SHARED CONTEXT BUS` / `PairFullState • 38 fields • 22 events`

**Левый верх (зелёный кластер):**
- `MTF WT Specialist` / `core/intelligence/wt_specialist.py` / `35 features: 7TF × {wt1,wt2,zone,cross,atr}`
- `MTF SMC Specialist` / `core/ml/mtf_smc_specialist.py` / `40 features: 4TF × {OB,FVG,CHoCH,BOS,OTE}`
- `Narrative Builder` / `Decision Core + TradeRouter`
- `Post-Trade Analyser` / `outcome → features_json + model retraining`

**Правый верх (оранжевый кластер):**
- `SignalDetectors` / `core/signals/` / `CONFLUENCE, DIVERGENCE, ATR_CHANGE, BOS`
- `Pivot Levels` / `core/pivots/` / `1M/1W/1D • PP S1-S3 R1-R3`
- `Market Regime` / `core/indicators/` / `regime+mode: TREND/REVERSAL` / `Trigger: WT 4h + ADX 1h`

**Золотые новые сферы:**
- `WaveService S14` / `Elliott n_down/n_up/phase` / `ARCH-121`
- `WTService S15` / `Single WT formula` / `ARCH-117`

**Sub-кубы (вложенные):**
- `SMC Sub-куб` / `OB • FVG • Structure • Liquidity • OTE` → `SMCContext`
- `Elliott-Pivot Sub-куб` / `Wave • Pivot • Fibonacci` → `PricePositionContext`
- `WT Sub-куб (vision)` / `WT×5TF` → `MTF_WT_Verdict`

**Нижние блоки:**
- `DATA INGESTION` / `core/infra/ • BingX REST+WS`
- `TRADE EXECUTION` / `core/exchange/ • VST→LIVE`
- `NARRATIVE BUILDER` / `TG alerts • Dashboard`
