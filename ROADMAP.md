# ROADMAP — Oko MTF Bot

Документ прогресса: от текущего состояния к самообучающейся торговой системе с адаптацией весов и ML-позиционированием.

---

## ✅ Этап 1 — Trade Simulator (фундамент)
- TradeSimulator: регистрация сделок, SL/TP трекинг по OHLC
- R_multiple, profit_pct, duration_minutes
- Статусы: OPEN / TP / SL / EXPIRED (48ч)
- Правило при одновременном hit SL+TP в одной свече — ближе к open

## ✅ Этап 2 — TTL кеш OHLCV
- Timeframe-dependent TTL в `data_collector.py`
- Снижение API-запросов с ~1150 до ~300 в цикл
- TTL: 1m=15с, 3m=30с, 5m=45с, 15m=60с, 45m=120с, 1h=180с, 4h=300с, 1d=600с

## ✅ Этап 3 — Веб-дашборд
- `web/dashboard_server.py`, порт 8000
- `/` HTML-сводка, `/api/stats` JSON endpoint
- `core/performance_engine.py` — агрегирует статистику из simulated_trades
- Автозапуск вместе с ботом через `asyncio.create_task`

## ✅ Этап 4 — Market Regime + ML + Пивоты

### 4.1 — Market Regime
- `core/market_regime.py`: MarketRegimeClassifier (ADX + ATR + EMA)
- Режимы: TREND_UP / TREND_DOWN / RANGE / HIGH_VOL
- Запись `regime` в `simulated_trades` через `register_trade_async()`

### 4.2 — ML OutcomePredictor + Адаптивные веса
- `core/outcome_predictor.py`: RandomForest(200 деревьев), CV AUC ≈ 0.56
- 12 признаков: strength, confidence, direction, signal_type(3), volatility, price_change, regime(4)
- Блендинг confidence = 0.7×orig + 0.3×P(win) в TradingIntelligence
- Адаптивные веса: `new_weight = base × clamp(1 + avg_R × 0.4, 0.5, 2.0)`
- Реальные веса на ~163 сделках: pivot_reversal=0.24, wt_signal=0.133, trend_signal=0.08

### 4.3 — Фиксированные пивоты
- `core/pivot_calculator_fixed.py`: замена скользящего окна на UTC-периоды
- Месячные (1M), недельные (1W), дневные (1D) пивоты фиксируются на весь период
- Кеш по `period_start`, а не TTL
- Конфлюэнции: 1M-1W, 1M-1D, 1W-1D

### 4.4 — MFE трекинг (05.03.2026)
- `max_price`, `min_price` — накапливаются при каждой проверке открытых сделок
- `max_R_possible` — лучший достижимый R за время жизни
- `captured_R_pct` — процент захваченного потенциала (R_multiple / max_R_possible × 100%)
- `user_settings` — персональная таблица (депозит, плечо, риск% на каждого пользователя)

---

## 🔲 Этап 5 — Веб-настройки стратегии
**Цель:** редактировать параметры без перезапуска бота через браузер

- Страница `/settings` (aiohttp): HTML-форма с текущими значениями из `config.yaml`
- `GET /settings` → форма, `POST /settings` → сохранение + hot-reload
- Блоки настроек:
  - **Anomaly detector**: `volume_multiplier`, `price_threshold`
  - **Веса сигналов**: слайдеры для `signal_weights` (pivot_reversal, wt_signal, trend_signal...)
  - **MTF**: набор таймфреймов (чекбоксы), минимальный count OS/OB для алерта
  - **Управление капиталом**: депозит, плечо, риск%, SL/TP%, авто-расчёт позиции
- Персональные настройки читаются из `user_settings` по `user_id`
- Расчёт позиции (авто): `Position = (Deposit × Risk%) / SL% × Leverage`

## 🔲 Этап 6 — Динамический TP (pivot-based)
**Цель:** заменить фиксированный TP% на ближайший уровень пивота

- TP = ближайший уровень пивота выше/ниже цены входа
- R варьируется от 1.5 до 10+ в зависимости от структуры рынка
- Трейлинг SL: после достижения +1R подтягивать стоп в безубыток
- Данные MFE (Этап 4.4) покажут сколько потенциала теряется при фиксированном TP

## 🔲 Этап 7 — R-регрессор (Kelly-sizing)
**Цель:** ML-предсказание ожидаемого R → адаптивный размер позиции

- `GradientBoostingRegressor`: предсказывает `max_R_possible` по признакам
- Признаки: 12 из OutcomePredictor + расстояние до ближайшего пивота + ATR
- Обучение после накопления 300+ сделок с заполненным MFE (Этап 4.4)
- Kelly: `kelly_f = (win% × avg_R_win − loss% × 1) / avg_R_win`
- `Position = Deposit × kelly_f × confidence`

## 🔲 Этап 8 — Рефакторинг монолитов + PostgreSQL
**Цель:** масштабируемость при росте пользователей (>100)

- Разбить `bot_with_subscriptions.py` (1540+ строк) → `bot/handlers/`
- Разбить `trading_intelligence.py` (1850+ строк) → `core/signals/`, `core/ml/`
- SQLAlchemy ORM-прослойка → переход на PostgreSQL займёт 1 день
- Redis для кеша OHLCV (замена in-memory `_ohlcv_cache`)

---

## Метрики прогресса

| Метрика | Сейчас | Цель (Этап 7) |
|---------|--------|----------------|
| Сделок в БД | 163 | 500+ |
| Win rate | 43.3% | > 50% |
| avg_R (win) | 2.0 | > 3.0 (dynamic TP) |
| CV AUC (OutcomePredictor) | 0.56 | > 0.65 |
| avg captured_R_pct | — | > 60% |

---

## История обновлений

| Дата | Изменение |
|------|-----------|
| 2025-03-01 | Этап 1: simulated_trades, trade_simulator, интеграция в бота |
| 2026-03-04 | Этапы 2-4.3: кеш OHLCV, дашборд, Market Regime, ML, пивоты |
| 2026-03-05 | Этап 4.4: MFE трекинг, user_settings |
