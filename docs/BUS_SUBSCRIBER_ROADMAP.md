# Bus Subscriber Roadmap — Рост проекта через шину

> 14.06.2026, DS. Потенциальный бэклог. Ничего не реализовано — фантазия о росте.

## Идея

Shared Context Bus — нервная система проекта. Сейчас scan_loop = мозг + руки + глаза. 
Цель: scan_loop = оркестратор, всё остальное — подписчики шины.

```
sub_cube.compute_and_publish() → BUS.publish(SMC_SNAP_UPDATED)
                                      │
          ┌───────────────────────────┼───────────────────────┐
          ▼                           ▼                       ▼
    scan_loop (ядро)          NotificationDispatcher    Dashboard (real-time)
    читает snap               слушает → TG              лента FVG/OB/OTE
```

## Слои роста

### Слой 2 — Ближайшее (уже напрашивается)

| Подписчик | Событие | Эффект |
|---|---|---|
| NotificationDispatcher | `SMC_SNAP_UPDATED` | FVG/OB/CHoCH → TG, 0 строк в scan_loop |
| Dashboard real-time | `SMC_SNAP_UPDATED` | Лента FVG/OB/OTE на дашборде |
| Dashboard real-time | `TRADE_OPENED`, `TRADE_CLOSED` | Живые сделки |
| TG Strategy fire | `TRADE_OPENED` | Уведомление о новом сетапе |

### Слой 3 — Рост (средний горизонт)

| Подписчик | Событие | Эффект |
|---|---|---|
| Risk Monitor | `TRADE_OPENED`, `POSITION_UPDATED` | Дроудаун > X% → alert |
| Health Monitor | `CYCLE_COMPLETED`, `API_ERROR` | Деградация → TG администратору |
| Circuit Breaker | `TRADE_CLOSED` | N убытков подряд → пауза стратегии |
| Balance Tracker | `BALANCE_UPDATED` | Equity-кривая, алерт |
| Webhook Relay | `TRADE_CLOSED` | Discord/TradingView webhook |
| Performance Engine | `TRADE_CLOSED` | Real-time PnL |

### Слой 4 — Масштаб (архитектурный скачок)

| Подписчик | Событие | Эффект |
|---|---|---|
| Strategy-as-Subscriber | `SMC_SNAP_UPDATED` + `OHLCV_UPDATED` | ote/arch104/atr_change = отдельные подписчики |
| Position Sync | `EXEC_WS_ORDER`, `EXEC_WS_BALANCE` | Синхронизация через шину |
| Account Router | `TRADE_OPENED` | Маршрутизация сделок по счетам |

### Слой 5 — AI / Автономность

| Подписчик | Событие | Эффект |
|---|---|---|
| AdvisorPort (рой) | `SMC_SNAP_UPDATED` | Ежеминутный анализ → совет |
| ML Retrain Trigger | `N_TRADES_CLOSED` | Авто-переобучение |
| Strategy Optimizer | `STRATEGY_METRICS` | A/B-тесты в реальном времени |
| Anomaly Detector | все события | «Паттерн X перестал работать» |
| Copy-trade Relay | `TRADE_OPENED` | Зеркалирование на другой счёт |

### Слой 6 — Внешние

| Подписчик | Событие | Эффект |
|---|---|---|
| TradingView | `SIGNAL_*` | Кастомные индикаторы |
| Discord/Telegram Channel | `TRADE_CLOSED` | Публичный канал |
| Google Sheets | `DAILY_SUMMARY` | Авто-отчётность |
| Mobile App | `NOTIF_FIRED` | Push-уведомления |

## Принцип

**Добавить подписчик = зарегистрировать в bus + 0 строк в scan_loop.**

scan_loop остаётся оркестратором ядра (индикаторы, SMC, регистрация сделок). 
Всё остальное — слушатели шины.


## Дополнение: Уровни куба над PairState

> 14.06.2026, DS + Даат. AccountState уже в коде (EXEC-WS ACCOUNT_UPDATE). TraderState — следующий горизонт.

### Трёхуровневая архитектура

```
Layer 3: TRADER STATE                    ← МОЗГ
         ┌──────────────────────────────┐
         │ Цели: +X%/мес, макс дроудаун │
         │ Ресурсы: капитал, пары, TFs   │
         │ Решения: КОМУ сколько дать   │
         └──────────┬───────────────────┘
                    │ управляет
Layer 2: ┌──────────┴──────────┐
         │   AccountState ×2    │            ← ПОРТФЕЛЬ
         │   equity, margin,    │
         │   drawdown, exposure │
         └──────────┬───────────┘
                    │ торгует
Layer 1: ┌──────────┴──────────┐
         │   PairState ×526     │            ← ИСПОЛНЕНИЕ
         │   snap, regime, OTE  │
         └──────────────────────┘
```

### Layer 2 — AccountState (фундамент уже есть)

```
EXEC-WS ACCOUNT_UPDATE (push) ─┐
position_sync snapshot (poll)  ─┴→ BUS.update_account(id, equity) → AccountState
                                           │
         ┌─────────────┬───────────────┬───┴──────┬──────────────┐
         ▼             ▼               ▼          ▼              ▼
   get_available_  position_sizer  Dashboard  Risk Monitor  Circuit Breaker
   balance (0 REST) (живой equity) (real-time) (drawdown)  (Слой 3)
```

**AccountState = portfolio-измерение шины.** Параллельно PairState. Куб получает уровень выше пары: счёт/портфель.

| Потребитель | Что даёт |
|---|---|
| position_sizer | Размер позиции от живого equity, не хардкод |
| Risk Monitor | Дроудаун в real-time (сейчас постфактум из БД) |
| Circuit Breaker | "Equity −X% → стоп всем стратегиям" |
| Dashboard | Real-time баланс без REST |

### Layer 3 — TraderState (дирижёр)

```python
class TraderState:
    goals: dict          # {"monthly_roi": 30, "max_drawdown": 15}
    active_strategies: ["ote_nested", "arch104", "atr_change"]
    
    def allocate(self, opportunities: list[Signal]) -> list[Allocation]:
        """Кому сколько капитала и в каком приоритете."""
```

**Сейчас:** каждая стратегия сама за себя, не знает о других.
**Будет:** TraderState — дирижёр. Знает всё.

### Что даёт TraderState

#### 1. Capital Allocator — динамический капитал
```
Сейчас: стратегии торгуют независимо
Будет:  "ote_nested 60% (лучший Sharpe), arch104 30%, atr_change 10%"
        Меняется автоматически по скользящему окну метрик
```

#### 2. Correlation Shield — защита от кластеризации
```
Сейчас: 5 LONG на BTC, ETH, SOL, BNB, XLM → 1 новость = −5 стопов
Будет:  TraderState: "3 correlated LONG уже есть. SOL, BNB → пропуск"
```

#### 3. Regime Router — стратегия × рынок
```
Сейчас: arch104 gate "SHORT при BTC bear"
Будет:  TREND_UP   → ote_nested LONG ×2, arch104 пауза
        TREND_DOWN → arch104 SHORT ×2, ote только SHORT
        RANGE      → atr_change + ote pull
        CHAOS      → все пауза
```

#### 4. Strategy Evolution — A/B автопилот
```
Сейчас: DS бэктестит → Даат внедряет → недели
Будет:  TraderState сам: "v1 vs v2 на 10% капитала → v2 лучше → switch 100%"
```

#### 5. Market Memory — исторический контекст
```
Сейчас: каждая сделка — чистый лист
Будет:  "XLM: 3й ретест $0.187 за неделю. Предыдущие 2 = TP (67%).
        → увеличить размер позиции на 20%"
```

### Самый дальний горизонт

```
                 TraderState (дирижёр)
                      │
    ┌─────────────────┼─────────────────┐
    ▼                 ▼                 ▼
Strategy A        Strategy B        Strategy C
(ote_nested)      (arch104)         (auto-created)
    │                 │                 │
    └─────────────────┼─────────────────┘
                      ▼
              Pattern Mining
              "новый паттерн → Strategy D → тест 5% → production"
```

**Стратегии создают себя сами.** Pattern mining → авто-генерация → A/B → production. Человек подтверждает.

### Итог: дорога на год

```
Сегодня:       PairState (L1)            — работает
14.06:         AccountState (L2)         — фундамент в коде
Ближайшее:     AccountState подписчики    — Risk Monitor, Circuit Breaker
Среднее:       TraderState (L3)          — дирижёр стратегий
Дальнее:       Авто-стратегии            — сами себя создают
```

## Вердикт роя (14.06.2026, 2 раунда team-ask + Даат)

**Архитектура (консенсус):**
- **L2+L3 в ОДНОЙ шине** — расширить `PairContextBus` измерениями `account_id`/`trader_state`. Отдельный `PortfolioBus` ОТВЕРГНУТ: дублирует pub/sub (`subscribe`/`publish`/`event_log`) = дрейф, противоречит «Центральной Сфере Куба». sambanova: «оптимизация, а не дробление».
- **Producer:** EXEC-WS push (`ACCOUNT_UPDATE`) основной + REST/poll fallback (5/5).
- **Доступ:** синглтон-аксессор `get_bus()` (не проводить через 30 callsites; DI позже).
- **TraderState (L3):** async-подписчик (отдельный loop) на `ACCOUNT_UPDATED`+`TRADE_CLOSED`+таймер ~5мин.
- **Capital Allocator:** множитель `strategy_weight` 0.0–2.0 поверх sizing (не ломает deposit×risk×lev), только новые сделки.
- **Correlation Shield:** фон-расчёт корреляций /15мин → LRU-cache → O(1) в hot path, порог corr=0.75.

**Первый кирпич (BUS-L2-BRICK):** `BalanceTracker` — подписчик `EXEC_WS_BALANCE` → `AccountState` → убирает REST-polling баланса (event-driven) + живой deposit для SIM/dashboard. Связь OPS-06-ACCOUNT.

**⚠️ Спор по порядку L3 (Даат vs рой):** рой → Capital Allocator вторым. Даат держит → **Correlation Shield РАНЬШЕ**. Причина: Capital Allocator аллоцирует по Sharpe, Sharpe на частично фейковых метриках (фейк-R от SL≈entry) = усиление ошибки с плечом. **Сначала достоверность (DATA-AUDIT-2), потом дирижёр.** Correlation Shield не зависит от Sharpe, спасает капитал сразу.

**Финальный порядок:** L2 AccountState → Correlation Shield → Regime Router → Capital Allocator (после DATA-AUDIT-2) → Strategy Evolution → Market Memory.

Полные разборы: `obsidian/Team-Discussions/2026-06-14-accountstate*.md` + `2026-06-14-раунд-2-*.md`.
