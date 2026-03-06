# ROADMAP — Oko MTF Bot

Документ прогресса: от текущего состояния к самообучающейся торговой системе.

---

## ✅ Этап 1 — Trade Simulator (фундамент)
- TradeSimulator: регистрация сделок, SL/TP трекинг по OHLC
- R_multiple, profit_pct, duration_minutes
- Статусы: OPEN / TP / SL / EXPIRED (48ч)
- При одновременном hit SL+TP в одной свече — победа того, кто ближе к open

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

### 4.3 — Фиксированные пивоты (period-based кеш)
- `core/pivot_calculator_fixed.py`: замена скользящего окна на UTC-периоды
- Месячные (1M), недельные (1W), дневные (1D) — фиксируются на весь период
- Конфлюэнции: 1M-1W, 1M-1D, 1W-1D

### 4.4 — MFE трекинг + user_settings (05.03.2026)
- `max_price`, `min_price` — накапливаются при каждой проверке открытых сделок
- `max_R_possible` — лучший достижимый R за время жизни
- `captured_R_pct` — процент захваченного потенциала (R_multiple / max_R_possible × 100%)
- Таблица `user_settings`: персональный депозит/плечо/риск% для каждого пользователя

## ✅ Этап 4.5 — Разделение слоёв (core/ vs bot/)
- `core/` — только бизнес-логика без aiogram (28 файлов)
- `bot/keyboards.py` + `bot/menus/` — весь UI-слой
- `bot_with_subscriptions.py` импортирует UI только из `bot/`

---

## ✅ Этап 5 — Веб-настройки стратегии (05.03.2026)
**Цель:** редактировать параметры бота без перезапуска через браузер

- Страница `/settings` (aiohttp): форма с текущими значениями из `config.yaml`
- Параметры анализа: volume_multiplier, price_threshold, check_interval, history_size
- Адаптивные веса сигналов — отображение из PerformanceEngine (read-only)
- Формула расчёта позиции: `Position = (Deposit × Risk%) / SL% × Leverage`
- Персональные настройки (депозит/плечо/риск%) — `/settings` в боте (user_settings)
- Hot-reload: `ConfigLoader.save_analysis()` → перезапись `config.yaml` → `reload()` без остановки бота
- Эндпоинты: `GET /settings`, `GET /api/settings`, `POST /api/settings`

## ✅ Этап 5.1 — Качество сигналов (06.03.2026)
**Цель:** убрать шум и дублирование

- Фильтр объёма: `min_volume_usd` — пары < порога не мониторируются (config.yaml)
- Фильтр мусорных пар: base asset длиннее 10 символов → пропустить
- Cooldown после SL: `sl_cooldown_hours` — пауза N часов перед новым сигналом по паре
- Дедупликация: `dedup_minutes` — один и тот же тип сигнала по одной паре не дублируется
- `min_strength` — сделка не регистрируется если `overall_strength < 50`
- `is_actionable`: регистрация только BUY/SELL + non-NEUTRAL direction
- INFO-лог с причиной пропуска сделки (strength/action/direction)

## ✅ Этап 5.2 — BTC-корреляционный фильтр (06.03.2026)
**Цель:** учитывать рыночный контекст при выдаче сигналов

- `_get_btc_regime(bot)` — кешированный режим BTC/USDT (TTL 5 мин, таймфрейм 1h)
- BTC HIGH_VOL → сигнал полностью пропускается
- BTC TREND_UP + SHORT направление → пропускается
- BTC TREND_DOWN + LONG направление → пропускается
- Фильтр применяется после AI-анализа в `_broadcast_intelligence_alert()`

## ✅ Этап 5.3 — Еженедельный отчёт в Telegram (06.03.2026)
**Цель:** пользователь видит итоги недели без ручных запросов

- `PerformanceEngine.weekly_summary(days_back=7)` — статистика за N дней
- `send_weekly_report(bot)` + `format_weekly_report(stats)` в `bot/monitoring.py`
- `_weekly_report_loop()` — asyncio задача, отправляет каждое воскресенье в 20:00 UTC

## 🔲 Этап 6 — Динамический TP (pivot-based)
**Цель:** заменить фиксированный TP% на ближайший уровень пивота

- TP = ближайший уровень пивота выше/ниже цены входа
- R варьируется от 1.5 до 10+ в зависимости от структуры рынка
- Трейлинг SL: после достижения +1R подтягивать стоп в безубыток
- MFE-данные (Этап 4.4) покажут сколько потенциала теряем при фиксированном TP

## 🔲 Этап 7 — R-регрессор (Kelly-sizing)
**Цель:** ML-предсказание ожидаемого R → адаптивный размер позиции

- `GradientBoostingRegressor`: предсказывает `max_R_possible` по признакам
- Признаки: 12 из OutcomePredictor + расстояние до ближайшего пивота + ATR
- Обучение после 300+ сделок с заполненным MFE
- Kelly: `kelly_f = (win% × avg_R_win − loss% × 1) / avg_R_win`
- Итог: `Position = Deposit × kelly_f × confidence`

## 🔲 Этап 8 — Масштабирование
**Цель:** готовность к >100 пользователям

- Разбить `bot_with_subscriptions.py` (1540+ строк) на обработчики в `bot/handlers/`
- Разбить `trading_intelligence.py` (1850+ строк) на `core/signals/` + `core/ml/`
- SQLAlchemy ORM → переход на PostgreSQL займёт 1 день при наличии прослойки
- Redis для кеша OHLCV (замена in-memory `_ohlcv_cache`)

---

## Метрики прогресса

| Метрика | Сейчас | Цель (Этап 7) |
|---------|--------|----------------|
| Сделок в БД | 226+ | 500+ |
| Win rate | 43.3% | > 50% |
| avg_R (win) | 2.0 | > 3.0 (dynamic TP) |
| CV AUC (OutcomePredictor) | 0.56 | > 0.65 |
| avg captured_R_pct | — | > 60% |
| Пар в мониторинге | 600+ | — |

---

## История обновлений

| Дата | Изменение |
|------|-----------|
| 2025-03-01 | Этап 1: simulated_trades, trade_simulator, интеграция в бота |
| 2026-03-04 | Этапы 2–4.3: кеш OHLCV, дашборд, Market Regime, ML, пивоты |
| 2026-03-05 | Этап 4.4: MFE трекинг, user_settings |
| 2026-03-05 | Этап 4.5: подтверждено разделение core/ (бизнес) vs bot/ (UI) |
| 2026-03-05 | Этап 5: веб-настройки /settings, hot-reload config.yaml |
| 2026-03-06 | ML: исправлен cold-start (joblib вне try/except, stub MLPClassifier, 1-class guard) |
| 2026-03-06 | Этап 5.1: фильтры качества (cooldown, dedup, min_strength, volume, is_actionable) |
| 2026-03-06 | Унификация сообщений: tv_link во всех типах, символ без :USDT, strength целым числом |
| 2026-03-06 | Дашборд: tvUrl/symLink в таблицах, aiohttp.access → WARNING |
| 2026-03-06 | Прогрев кеша пивотов при старте (asyncio.gather + Semaphore=20, 600+ пар) |
| 2026-03-06 | Этап 5.2: BTC-корреляционный фильтр (HIGH_VOL + направление vs тренд) |
| 2026-03-06 | Этап 5.3: Еженедельный отчёт (weekly_summary + _weekly_report_loop каждое вс. 20:00) |
