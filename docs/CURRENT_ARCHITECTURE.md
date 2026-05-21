# Текущая архитектура Oko MTF Bot

> Последнее обновление: 21.05.2026
> Документирует ДВА активных торговых потока и их взаимодействие.

---

## Два параллельных потока

```
┌──────────────────────────────────────────────────────────────────┐
│                    ПОТОК A: Reactive Bot                         │
│         (старый бот, живёт, улучшается, не умирает)              │
│                                                                  │
│  DataCollector → 6 детекторов → ConfirmationAggregator           │
│     → TradeRouter → TradeSimulator → SL/TP/TSL management        │
│                                                                  │
│  Стратегии: wt_b / pivot_reversal / divergence / atr_change      │
│  Capital: 100% (ARCH-104 Stage 1-2 → рост до 50%)                │
│  Статус: стабилизирован, avgR=-0.1 (неделя), цель ≥ +0.10        │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│                   ПОТОК B: ARCH-104 Pattern-Driven               │
│         (новый мозг, 15 паттернов, BH-FDR-валидированы)          │
│                                                                  │
│  DataCollector → arch104_signal_adapter → pattern matcher        │
│     → RiskIntelligenceV1 → DecisionFusion                        │
│     → TradeRouter → VST (биржевые ордера)                        │
│                                                                  │
│  Паттерны: L1_golden(avgR+6.0) + 10 LONG/SHORT (15 итого)        │
│  Capital: Stage 1 = 10% (21.05.2026, 241 пара)                   │
│  Цель: Stage 5 = 100% (через ~6 недель при подтверждении)        │
└──────────────────────────────────────────────────────────────────┘

                 ↓ Оба потока ↓
         ┌──────────────────────┐
         │      TradeRouter      │  ← единая точка регистрации
         │   (Сфера 9, DEV-199) │     field: source_router
         └──────────────────────┘
                     ↓
         ┌──────────────────────┐
         │   TradeSimulator +   │
         │   position_sync +    │
         │   watchdog DEV-185.2 │
         └──────────────────────┘
```

---

## Поток A — детально

### Сигнальный пайплайн

```
scan_loop.py (каждые 60с, 200+ пар)
  ↓
DataCollector.scan_one()
  → WT индикатор (wt1, wt2, trend)
  → ATR, RSI, объём
  → SMC snapshot (OTE zone, FVG, BOS/CHoCH)
  ↓
6 детекторов параллельно:
  wt_b            → wt1 < -53 + кросс + объём
  pivot_reversal  → swing SL + FVG confluence (DEV-214 ✅)
  divergence      → bull/bear div на RSI/WT
  atr_change      → ATR trend change 15m/1h/4h
  wt_sideways     → ОТКЛЮЧЁН (DEV-213, -131R/24ч)
  watch_list      → WL breach
  ↓
ConfirmationAggregator (DEV-199/209)
  → Σ weight × confidence per window
  → per-source window: 1800s для atr_change_15m, 600s для остальных
  ↓
soft_penalties + hard_drops (DEV-203 DecisionTrace)
  ↓
TradeRouter.submit() → register_trade_async() + open_bracket()
```

### Фильтры качества (config.yaml)

| Параметр | Значение | Эффект |
|---|---|---|
| min_strength_register | 40 | порог записи в БД |
| min_strength | 50 | порог TG-уведомления |
| min_volume_usd | 5 000 000 | DEV-185.3 whitelist |
| sl_cooldown_hours | 4 | нет повторных SL по паре |
| sl_limit_buffer_pct | 1.0% | DEV-185 slippage protection |
| dev186_wt_signal_regime_gate | true | SHORT блок в TREND_UP |

### Текущая производительность (17.05.2026)

| signal_type | n (неделя) | avgR |
|---|---|---|
| pivot_reversal | 83 | **+0.256** ✅ |
| watch_list_breach | 90 | +0.015 ✅ |
| wt_b / wt_sideways | 1625 | -0.089 ❌ |
| atr_change | 141 | -0.136 ❌ |
| divergence | 12 | -0.696 ❌ |

---

## Поток B — ARCH-104 детально

### Архитектура

```
arch104_signal_adapter.py
  ← EventBus events (atr_change_*, wt_os_*, fvg_*, div_*)
  ← DataCollector snapshots (SMC, WT, volume)
  ↓
Pattern Matcher (core/confirmations/arch104_patterns.py)
  → boolean AND по anchor_factors
  → 15 паттернов в config/arch104_patterns.yaml
  ↓
RiskIntelligenceV1 (core/intelligence/risk_intelligence.py)
  → risk_pct multiplier (EMA avg_R + Sharpe)
  → leverage = ceil(risk_pct / sl_distance_pct × safety_buffer)
  ↓
DecisionFusion (core/intelligence/decision_fusion.py)
  → v1 (формульный) + v2 (LightGBM, Phase 1.5)
  → final: trade / skip / reduce_size
  ↓
TradeRouter → open_bracket() VST
```

### 15 паттернов (Stage 1)

```
LONG (5):
  L1_golden        1h   avgR=+6.074  WR=86.9%  n=61  🟢 READY
  L2_wt_double_fvg 1h   avgR=+1.239           n=103  🟡
  L3_premium_long  1h   avgR=+1.527           n=37   🟡
  L4_wt_atr        1h   avgR=+2.299           n=88   🟢 READY
  L1_golden_LTF    15m  avgR=+1.979           n=73   🟡
  L1_golden_5m     5m   avgR=+1.762           n=268  🟡

SHORT (6):
  S1_bos_atr       1h   avgR=+1.326           n=331  🟢 READY
  S2_fvg_bos       1h   avgR=+1.271           n=281  🟡
  S3_full_short    1h   avgR=+1.398           n=286  🟢 READY
  S4_strong_short  1h   avgR=+1.456           n=130  🟡
  S8_ote_strong    1h   avgR=+1.339           n=164  🟡

Capital ramp: Stage1(10%)→Stage2(20%)→Stage3(30%)→Stage4(50%)→Stage5(100%)
Критерий перехода: 7 дней живых VST без деградации
```

### Полный план: `docs/MIGRATION_ARCH104.md`

---

## Куб Метатрона — актуальный статус (21.05.2026)

```
Сфера  1  DataCollector          ✅ активен → OHLCV_UPDATED
Сфера  2  WSFeed                 ✅ real-time тикеры → TICK_PRICE
Сфера  3  MTF WT Specialist      ✅ → WT_VERDICT, WT_SNAP_UPDATED
Сфера  4  MTF SMC Specialist     ⚠️ shadow (ждёт 200+ SMC сделок)
Сфера  5  Cross-Market Node      ✅ BTC 4h режим → CROSS_MARKET
Сфера  6  Market Regime          ✅ + verdict_gate production (ARCH-84)
Сфера  7  Signal Detectors       ✅ 6 детекторов + HTF triggers
Сфера  8  Pivot Levels           ✅ + swing SL (DEV-214) + FVG confluence
Сфера  9  Narrative Builder      ✅ = TradeRouter (DEV-199)
                                  + ARCH-104 adapter (новое ребро)
Сфера 10  Exit Manager           ✅ TSL + watchdog DEV-185.2
Сфера 11  Post-Trade Analyser    ✅ → feedback + signal weights update
Сфера 12  Self-Diagnostics       ✅ SphereRegistry + DecisionTrace (DEV-203)
─────────────────────────────────────────────────────────
Центр     Shared Context Bus     ✅ pub/sub 22 события, 38 полей

НОВЫЕ РЁБРА (ARCH-104):
  Сфера 7 → ARCH-104 Adapter → Pattern Matcher  (новое ребро)
  Pattern Matcher → RiskIntelligence             (новое ребро)
  RiskIntelligence → DecisionFusion → Сфера 9   (новое ребро)
  PatternLifecycle → Сфера 11 (auto_retire)      (новое ребро)
```

---

## Что ещё в работе

| Задача | Суть | Приоритет |
|---|---|---|
| DEV-200 | ConfirmationRegistry dataclass + publisher | 🔴 |
| DEV-201 | SignalAggregator v2 (только Поток A) | 🔴 |
| DEV-202 | confirmations[] в features_json | 🟡 |
| ARCH-94 | Orphan-детектор | 🟡 |
| ARCH-95-EXEC | H1-H5 расследование убытков (H6/H7 покрыты ARCH-104) | 🔴 |

---

## Что НЕ делаем (FROZEN до Phase 4 ARCH-104)

ARCH-74-EXT, ARCH-96..99, ARCH-101..111 — сложные архитектурные эпики.
Заморожены намеренно: сначала стабильность и ARCH-104 capital ramp.

---

*`docs/CURRENT_ARCHITECTURE.md` — живой документ. Обновлять при каждом архитектурном решении.*
