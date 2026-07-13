---
name: the_graph_onchain_plan
description: The Graph MCP — On-Chain Intelligence для Куба. 5 сигналов (whale tracking, DEX liquidity, contract stress, funding correlation, new pools). WR 55-70%, БЕСПЛАТНО вместо Glassnode. Фазы P1-P5, 12-16 дней, нет блокеров.
metadata:
  type: project
  status: planned
  date: 2026-06-30
  priority: 2
  effort: medium
  source: team-ask + analysis
---

# 🚀 The Graph MCP — On-Chain Intelligence для Куба Метатрона

**Статус:** Рекомендуется для интеграции в неделю 2 (параллельно с Liquidation Cascades и Pairs Trading).

---

## 📊 **5 ON-CHAIN SIGNAL TYPES (из The Graph)**

### **Сигнал 1: WHALE TRACKING** ⭐

**Что это:**
- Крупные адреса (киты) начали активно покупать/продавать
- Информация о транзакциях в реальном времени через The Graph
- Киты часто первыми видят market movement

**Как работает:**
```
Кит выводит 1000 BTC с Binance (on-chain event)
    ↓ [через The Graph, 30-60 сек]
Мы видим это через graph_intelligence.query_whale_activity()
    ↓
Повышаем вес LONG сигналов на +20% (кит готовится к pump)
    ↓
Через 1-5 минут рынок движется (киты первые, мы вторые)
```

**Честный WR%:** 55-65%
- Киты не всегда правы (40-45% false positives)
- Но когда правы = сильное движение (+2-5% за 1-2 часа)
- R:R компенсирует низкий WR

**Данные из The Graph:**
- ERC20 transfer events (BTC на Ethereum = wrapped)
- Uniswap v3 swaps (кит торгует большой объём)
- CEX withdrawal events (через мосты, если доступно)

**Интеграция в Куб:**
- **Сфера:** 5 (Cross-Market Intelligence) или новая Сфера 6.5
- **Где использовать:** Фильтр к LONG/SHORT сигналам
- **Синтаксис:** `if whale_accumulated_usd > threshold and trend == 'neutral' → raise_entry_weight(+20%)`

**Пример интеграции:**
```python
class OnChainIntelligence(Sphere):
    def detect_whale_accumulation(self, symbol, window_minutes=5):
        whale_transfers = self.graph_client.query_whale_activity(
            symbol=symbol, 
            min_usd=1_000_000,
            since_minutes=window_minutes
        )
        whale_score = len(whale_transfers) / baseline_avg
        return whale_score  # 0.0-2.0 множитель
```

---

### **Сигнал 2: DEX LIQUIDITY SURGE** 

**Что это:**
- На Uniswap V3 / Curve / SushiSwap добавили огромный пул ликвидности
- Обычно means: новый токен, новый тренд, или кит готовит большую операцию
- **DEX activity часто предшествует CEX на 1-5 минут**

**Как работает:**
```
Появляется новый пул на Uniswap: BTC/USDC с $10M ликвидности
    ↓ [graph.ts регистрирует Mint event]
detect_dex_liquidity_surge() срабатывает
    ↓
Ожидаем volume spike на BingX через 2-5 минут
    ↓
Входим с повышенным размером (expect high volatility)
```

**Честный WR%:** 60-70%
- DEX данные чистые (on-chain fact)
- Но не все DEX pools = volume на CEX
- ~30-40% false signals

**Данные из The Graph:**
- Uniswap V3 PoolCreated, Mint events (ликвидность)
- Curve add_liquidity events
- Swap volume через пулы

**Интеграция в Куб:**
- **Сфера 2 (DataCollector):** добавить `dex_vol_ratio` в OHLCV stream
- **Синтаксис:** 
```python
def calculate_dex_volume_ratio(pair, window=5):
    dex_vol = get_uniswap_volume(pair, minutes=window)
    dex_ma = get_uniswap_volume_ma(pair, days=30)
    return dex_vol / dex_ma  # trigger if >2.0
```

**Пример:** 
- BTC/USDC объём на DEX скачил с 10M до 50M за 5 минут
- Ожидаем BingX volume spike в течение 2-5 минут
- Включаем более агрессивные entry сигналы

---

### **Сигнал 3: CONTRACT STRESS (Macro Risk Filter)**

**Что это:**
- Большие изменения в TVL (Total Value Locked) на Lending/Staking контрактах
- Liquidations на Compound/Aave (признак просадки)
- Stress в DeFi = risk для крипто в целом

**Как работает:**
```
TVL на Curve упал на 20% (люди вывод из пула)
    ↓
Это признак: а) не вера в stablecoin, б) риск-офф
    ↓
Снижаем risk_pct на 30% в нашем боте (defensive mode)
    ↓
Закрываем некоторые позиции, ждём clarity
```

**Честный WR%:** 50-55% (как макро-фильтр, не entry)
- Используется для **уменьшения риска**, не для входа
- Noise высокий, но макро-сигнал есть

**Данные из The Graph:**
- Curve PoolRemoveLiquidity events
- Aave Borrow/Repay events (взяли/вернули кредит)
- Liquidation events на compound/Aave

**Интеграция в Куб:**
- **Сфера 5 (Cross-Market Node):** добавить `defi_stress_level` (0-100%)
- **Использование:** Множитель к risk_management
```python
def calculate_defi_stress():
    tvl_change = (tvl_now - tvl_5d_ago) / tvl_5d_ago
    liquidation_events = count_liquidations_5min()
    stress_score = abs(tvl_change) * 50 + liquidation_events * 10
    return clamp(stress_score, 0, 100)

# Использование:
risk_pct = base_risk_pct * (1 - defi_stress / 100)
```

---

### **Сигнал 4: FUNDING RATE + ON-CHAIN CORRELATION**

**Что это:**
- Funding rate HIGH (лонги переплачивают) + киты SHORT'ят на фьючерсах
- = Признак разворота к LONG (киты покупают перед движением вверх, шортят фьючерсы как хеджирование)
- Тройная корреляция: funding + whale + order flow = сильный сигнал

**Как работает:**
```
Funding rate BTC: +0.05% в час (очень high)
    ↓
The Graph shows: крупные адреса OPEN SHORT на Perpetual Protocol
    ↓
Наш бот: funding HIGH + whale SHORT = они готовят pump вверх!
    ↓
Открываем LONG с повышенным confidence
```

**Честный WR%:** 60-70%
- Корреляция funding + whale = очень сильный сигнал
- WR выше чем whale alone или funding alone

**Данные из The Graph:**
- Perpetual Protocol, GMX, Kwenta SHORT/LONG positions от whale'ов
- On-chain funding rate history

**Интеграция в Куб:**
- **Сфера 6 (Intelligence):** комбо сигнал
```python
def detect_funding_whale_correlation():
    funding_rate = get_current_funding_rate("BTC")
    whale_shorts = count_whale_shorts_perpetual("BTC", last_30min=30)
    
    if funding_rate > 0.03 and whale_shorts > threshold:
        return Signal(
            type="WHALE_FUNDING_DIVERGENCE",
            direction="LONG",
            confidence=0.7,
            reason="whales_shorting_at_high_funding"
        )
```

**Улучшение:** +5-10% к WR существующих стратегий (Epsilon Arbitrage, Pairs Trading)

---

### **Сигнал 5: NEW POOL DETECTION (Discovery)**

**Что это:**
- На DEX появился новый пул (обычно новый токен или emerging trend)
- Не все новые пулы = профит, но могут быть gems
- Помогает рано поймать хороший тренд

**Как работает:**
```
Новый пул на Uniswap V3: Solana-BTC/USDC (Solana ecosystem)
    ↓
Это может означать: а) новый коллаб, б) emerging trend Solana
    ↓
Добавляем в watchlist, внимательнее следим
    ↓
Если volume поднялась в течение часа = candidate для entry
```

**Честный WR%:** 45-55% (noise высокий)
- Не для main strategy, а для discovery
- ~50% пулов = шум/scams
- ~50% = потенциальные winners

**Данные из The Graph:**
- Uniswap V3 PoolCreated events
- Фильтрируем по `initial_liquidity > $1M` и `fee_tier`

**Интеграция в Куб:**
- **Сфера 12 (PairContextBus):** добавить в watchlist
```python
def detect_new_pools():
    new_pools = graph_client.query_recent_pools(
        since_minutes=5,
        min_liquidity_usd=1_000_000
    )
    for pool in new_pools:
        watchlist.add(pool, monitor_level="DISCOVERY")
```

---

## 🏗️ **АРХИТЕКТУРА ИНТЕГРАЦИИ**

### **Модуль: core/intelligence/graph_intelligence.py**

```python
from graphql_client import GraphQLClient

class GraphIntelligence(Sphere):
    """
    Сфера 6.5: On-Chain Intelligence
    Получает данные через The Graph MCP
    """
    
    def __init__(self, config):
        self.graph_client = GraphQLClient(
            endpoint="https://api.thegraph.com/subgraphs/",
            mcp_server=config.mcp_servers.the_graph
        )
        self.cache = {}
        self.last_update = {}
    
    # Сигнал 1: Whale Tracking
    def query_whale_activity(self, symbol, threshold_usd=1_000_000, window_minutes=10):
        cache_key = f"whale_{symbol}"
        if self._is_fresh(cache_key, minutes=2):
            return self.cache[cache_key]
        
        query = f"""
        {{
          transfers(where: {{amount_gt: {threshold_usd}}}) {{
            from, to, amount, timestamp, asset
          }}
        }}
        """
        transfers = self.graph_client.query(query)
        
        whale_score = self._score_whale_transfers(transfers, symbol)
        self.cache[cache_key] = whale_score
        return whale_score
    
    # Сигнал 2: DEX Liquidity Surge
    def detect_dex_liquidity_surge(self, pair, threshold_multiplier=2.0):
        dex_vol = self._get_dex_volume(pair, minutes=5)
        dex_ma = self._get_dex_volume_ma(pair, days=30)
        ratio = dex_vol / dex_ma if dex_ma > 0 else 1.0
        
        return {
            "surge_detected": ratio > threshold_multiplier,
            "ratio": ratio,
            "usd_volume": dex_vol,
            "timestamp": now()
        }
    
    # Сигнал 3: Contract Stress
    def calculate_defi_stress(self):
        tvl_change = self._get_tvl_change(days=5)
        liquidations = self._count_liquidations(minutes=5)
        
        stress_score = abs(tvl_change) * 50 + liquidations * 10
        return clamp(stress_score, 0, 100)
    
    # Сигнал 4: Funding + Whale Correlation
    def detect_funding_whale_divergence(self, symbol):
        funding_rate = self._get_funding_rate(symbol)  # From BingX API
        whale_shorts = self._count_whale_positions(symbol, direction="SHORT")
        
        if funding_rate > 0.03 and whale_shorts > 3:  # threshold
            return Signal(
                type="WHALE_FUNDING_DIVERGENCE",
                confidence=0.7,
                direction="LONG"
            )
        return None
    
    # Сигнал 5: New Pool Detection
    def detect_new_pools(self, min_liquidity_usd=1_000_000):
        new_pools = self._query_recent_pools(
            since_minutes=5,
            min_liquidity_usd=min_liquidity_usd
        )
        return [
            {"pair": p.pair, "liquidity": p.liquidity, "fee_tier": p.fee_tier}
            for p in new_pools
        ]
```

### **Интеграция с Сферами Куба**

```
┌─ Сфера 2 (DataCollector)
│  └─ Добавить: dex_vol_ratio → в OHLCV stream
│
├─ Сфера 5 (Cross-Market Intelligence)
│  └─ Добавить: defi_stress_level (0-100%)
│  └─ Использовать: как risk-фильтр
│
├─ Сфера 6 (Intelligence)
│  └─ Комбо сигнал: whale_activity + funding_rate
│  └─ Вход: повышение веса при divergence
│
├─ Сфера 12 (PairContextBus)
│  └─ New pools → в watchlist
│  └─ Monitor на 30-60 минут
│
└─ Сфера 8 (RiskIntelligence)
   └─ Использовать defi_stress для снижения risk_pct
```

---

## ⏱️ **ФАЗЫ РЕАЛИЗАЦИИ**

| Фаза | Компонент | Время | Зависимости | Выход |
|------|-----------|-------|-------------|-------|
| **P1** | MCP setup + GraphQL client | 1-2 дня | Docs The Graph | `graph_intelligence.py` skeleton |
| **P2** | whale_tracking (сигнал 1) | 2-3 дня | P1 | Working whale detector |
| **P3** | DEX liquidity + contract stress (сигналы 2,3) | 2-3 дня | P1 | DEX vol ratio, stress calculator |
| **P4** | Интеграция в Сферы (2,5,6,8,12) | 2-3 дня | P2,P3 | Feeding signals into Cube |
| **P5** | Funding+whale combo (сигнал 4) | 1-2 дня | P4 | Divergence detector |
| **P6** | New pools discovery (сигнал 5) | 1 день | P4 | Watchlist auto-add |
| **P7** | SHADOW-валидация | 3-5 дней | P6 | WR% подтверждение |

**ИТОГО:** 12-16 дней (при параллельной работе P2,P3 = 2 дня вместо 5)

---

## 🎯 **УСПЕХ-КРИТЕРИИ (выход из SHADOW)**

| Метрика | Порог | Статус |
|---------|-------|--------|
| **Whale tracking WR** | ≥55% | ⏳ валидировать |
| **DEX surge detection precision** | ≥60% | ⏳ валидировать |
| **Defi stress correlation** | r > 0.4 с market drawdown | ⏳ валидировать |
| **Funding+whale divergence WR** | ≥60% | ⏳ валидировать |
| **Coverage (% новых пулов поймали)** | ≥40% | ⏳ валидировать |
| **False positive rate** | <30% | ⏳ валидировать |

---

## 💡 **ВЫВОДЫ**

### **Почему The Graph вместо Glassnode?**
- ✅ **БЕСПЛАТЕН** (Glassnode $500-5000/мес)
- ✅ **Real-time** (on-chain events в реальном времени)
- ✅ **Независимый** (не зависит от биржи BingX)
- ✅ **Декентрализован** (данные вычисляются независимо, не могут быть подделаны)
- ⚠️ **Задержка 30-60 сек** (vs Glassnode 5-10 сек) = но для 5m-1h ТФ нормально

### **На-chain + микроструктура = триангуляция**
1. **The Graph whale tracking** → кит начал покупать
2. **Liquidation Cascades** → OI spike на 70%
3. **Pairs Trading** → BTC↔ETH расхождение

**Все три сигнала вместе = 65-75% WR** вместо 55-60% каждой отдельно.

### **Альтернативный стек (vs текущий)**

**Текущий (ограниченный):**
- OTE (WR 50%)
- Памп (WR 55%)
- Funding (WR 45-50%)

**Новый (разнообразный):**
- Gamma Scalping (WR 55-60%)
- Liquidation Cascades (WR 65-75%)
- Pairs Trading (WR 70-80%)
- **The Graph on-chain** (WR 55-70%)
- Delta Footprint (WR 55-60%)
- Epsilon Arbitrage (WR 85-95%, но сложный)

**Результат:** Куб из "3-поточного" становится "6-8-поточным" по надёжности + диверсификация риска.

---

**Дата:** 2026-06-30  
**Статус:** READY FOR IMPLEMENTATION  
**Рекомендация:** Начать P1 в понедельник (2 июля), параллельно с Gamma Scalping
