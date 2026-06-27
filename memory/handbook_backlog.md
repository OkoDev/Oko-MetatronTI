---
name: handbook-backlog-ideas
description: 5 handbook элементов для TG-сообщений + Pump detector (из graphify анализа 26.06)
type: project
---

# BACKLOG: Handbook Elements + Pump Detector

**Дата:** 26.06.2026 · **Инициатор:** Daath (graphify анализ) · **Контекст:** [DISCUSSION.md#26.06.2026-01:15](../DISCUSSION.md#handbook-elements--pump-moneta-detector)

---

## ИДЕЯ 1: Handbook Elements в TG (Priority 1 — Critical)

### Проблема
Handbook (PDF для торговца) требует 5 элементов для принятия решения:
1. **Grade A/B/C** — качество сигнала
2. **Confidence %** — уверенность
3. **TP1/TP2/TP3** — разбиение выхода на 3 уровня (50%/30%/20%)
4. **Shape паттерн** — Wick/Exhaustion тип свечи
5. **History пары** — % Pumps, Reversed, AvgDrop

**Текущее состояние:** в коде есть ALL инструменты (TPSelector, risk-determination, signal detection), но торговец видит только половину в TG.

### Решение

#### 1. Grade A/B/C (converter in intelligence_formatter.py)
```python
def strength_to_grade(strength: int) -> str:
    """strength 0-100 → Grade A/B/C"""
    if strength >= 80:
        return "A"  # 🔥🔥🔥
    elif strength >= 60:
        return "B"  # 🔥🔥
    else:
        return "C"  # 🔥
```

**Вывод в TG:**
```
🔥🔥 Grade B · 85/100 · Confidence 78% · Риск: Низкий
```

#### 2. Confidence % (уже в коде, не выводится)
- `recommendation.confidence` (0.0-1.0) → "78%"
- Одна строка в шапке сообщения

#### 3. TP1/TP2/TP3 разбиение
**Источник:** `TPSelector.select()` возвращает `(tp1, tp2)`, нужно добавить TP3.

**Логика:**
- TP1 = entry + 50% × risk_distance (50% позиции)
- TP2 = entry + 100% × risk_distance (30% позиции)
- TP3 = entry + 150% × risk_distance (20% позиции)

**Вывод в TG:**
```
💰 Сделка
  Вход:  25100.00 (в OTE)
  Стоп:  24950.00  (-0.60%, Swing Low)
  TP1:   25250.00  (+0.60%, 50%)
  TP2:   25350.00  (+1.00%, 30%)
  TP3:   25450.00  (+1.40%, 20%)
  R:R    🟢 1:2.3
```

#### 4. Shape паттерн (Wick/Exhaustion)
**Новый модуль:** `core/indicators/candlestick_patterns.py`

```python
def detect_shape(df: pd.DataFrame, lookback: int = 5) -> str:
    """Detect Wick / Exhaustion / Doji / Momentum patterns"""
    # Exhaustion = large range + small body (reversal sign)
    # Wick = long shadow vs body (rejection sign)
    # Doji = equal open/close (indecision)
    # Momentum = close at extreme (breakout sign)
```

**Вывод в TG:**
```
📋 Сигналы
  ✅ WaveTrend (oversold, divergence detected)
  ✅ OB+FVG (confluence confirmed)
  ✅ Shape: Exhaustion wick (⬆ reversal pattern)
```

**Интеграция:** в `signal_checkers.py` → добавить shape как supporting signal.

#### 5. History пары (Pumps%, Reversed%, AvgDrop)
**Новый модуль:** `core/analytics/pair_history.py`

```python
class PairHistory:
    def calc_metrics(self, symbol: str) -> dict:
        """
        Возвращает из simulated_trades:
        - pumps_pct: % выигрышных LONG (vs total LONG)
        - reversed_pct: % SL-закрытий (vs total)
        - avg_drop: средний % убытка на SL
        """
        # Кэш: обновление раз в час
        # Минимум: 10 сделок по символу для валидности
```

**Вывод в TG:**
```
📊 История BTC
  Pumps: 3.2% (норма) · Reversed: 12% · Avg drop: -2.1%
```

### Acceptance Criteria
- ✅ TG-сообщение включает ВСЕ 5 элементов
- ✅ Grade видна рядом со Strength
- ✅ Confidence % выводится
- ✅ TP1/TP2/TP3 с % разбиением
- ✅ Shape паттерна в сигналах
- ✅ History пары в компактной форме
- ✅ Пример сообщения в `memory/handbook_example_tg.txt`

### Files to Modify
1. `core/ui/intelligence_formatter.py` — добавить Grade, Confidence, TP123, Shape, History
2. `core/indicators/candlestick_patterns.py` — NEW
3. `core/analytics/pair_history.py` — NEW
4. `core/signals/signal_checkers.py` — интегрировать shape

### Estimated Time
- Grade + Confidence: 10 min
- TP123 разбиение: 15 min
- Shape детектор: 20 min
- History модуль: 20 min
- **Total: ~60-70 min**

---

## ИДЕЯ 2: Pump Moneta Detector (Priority 2 — Nice to Have)

### Проблема
Handbook рекомендует торговцу **быстро искать памп-монеты** для entry. Сейчас нет инструмента для:
- Текущего scan памп-кандидатов
- Рейтинга по intensity
- Фильтра по volume

### Решение

#### Метрика памп-счётности
```python
def pump_score(symbol: str) -> float:
    """
    score = volume_boost × price_change × rsi_signal
    
    volume_boost = vol_24h / vol_7d_avg  (target: >2.0)
    price_change = 24h_change_pct        (target: >5%)
    rsi_signal = max(0, (rsi - 50) / 50) (target: rsi > 75 = 0.5)
    """
```

#### `/pumps` команда в боте
```
🔥 PUMP RANKING (обновлено 30 сек назад)

1. BTC  +12.3% vol×3.2  RSI 78  score=15.2
2. ETH  +8.1%  vol×2.1  RSI 72  score=12.1
3. SOL  +6.5%  vol×2.8  RSI 69  score=10.3
4. XRP  +5.2%  vol×1.9  RSI 65  score= 7.8
5. ADA  +4.1%  vol×1.7  RSI 58  score= 5.2

📊 Фильтр: volume > $1M
⚡ Alert: монета перешла в top-5 за последние 5 мин
```

#### Дашборд: Pumps Ranking
- Graph: score timeline за 1h/24h
- Table: top-20 с сортировкой (score/volume/change/rsi)
- Hot alert: новые входы в top-5

#### Интеграция в scan_loop
```python
async def scan_pump_candidates(bot):
    """Сканирует все торгуемые пары, ранжирует по pump_score"""
    # Выполняется параллельно с основным сканированием
    # Кэш: обновление каждые 5 минут (не перегружать ccxt)
    # Уведомление: если монета вошла в top-5
```

### Files to Create/Modify
1. `core/analytics/pump_detector.py` — NEW
2. `bot/loops/scan_loop.py` — добавить `scan_pump_candidates()`
3. `bot/handlers/pump_handler.py` — `/pumps` команда
4. Dashboard: добавить Pumps screen (само будет если pump_detector.py готов)

### Estimated Time
- Pump detector core: 20 min
- Интеграция в scan_loop: 15 min
- Bot handler + TG: 15 min
- **Total: ~50 min**

### Why Not Priority 1
- Handbook elements = **ядро аналитики для ручной торговли** (критично)
- Pump detector = **bonus для快速 скнов** (nice to have)
- Можно внедрить ПОСЛЕ handbook элементов

---

## Roadmap

### Phase 1 (Now)
1. ✅ Записать в DISCUSSION.md + TASKS.md
2. ✅ Создать этот документ

### Phase 2 (Next Session — Dev Priority)
1. **Grade/Confidence/Shape**: 20 min
2. **TP123 разбиение**: 15 min
3. **History пары**: 20 min
4. **Test + Deploy**: 10 min

### Phase 3 (Optional — ARCH Decision)
1. **Pump Detector**: 50 min
2. **Dashboard integration**: 10 min

---

## Links
- DISCUSSION: [26.06.2026 01:15 UTC](../DISCUSSION.md#handbook-elements--pump-moneta-detector)
- TASKS: [HANDBOOK-UI](#handbook-ui), [PUMP-DETECTOR](#pump-detector)
- Graphify Analysis: [graphify-out/GRAPH_REPORT.md](../graphify-out/GRAPH_REPORT.md) (god_nodes, surprising_connections)
- Handbook PDF: ~/Downloads/Volume_Bot_Guide_2026.pdf (sections 1-3: Grade, Confidence, TP1-TP3, Shape, History)
