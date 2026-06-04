---
name: Архитектурное решение — таймфреймы
description: Правила работы с ТФ в коде — никогда не хардкодить, всегда из данных
type: project
---

## Правило: ТФ всегда идёт из данных, никогда не хардкодится

**Причина:** В будущем планируется запуск стратегий на нескольких ТФ одновременно (интрадей 5m/15m и свинг 1h/4h). Если ТФ захардкожен — рефакторинг будет болезненным.

## Текущее состояние (15.03.2026)

Сейчас "15m" хардкожен в нескольких местах — это технический долг:
- `signal_checkers.py` — `SignalData(timeframe="15m")`
- `confluence_scanner.py` — `SignalData(timeframe="15m")`
- `message_builder.py` — `tv_link(symbol, interval=15)` дефолт
- `dashboard_server.py` — `&interval=15` в JS

## Правильный подход

1. `SignalData.timeframe` — заполняется детектором из аргумента, не хардкодится
2. `TradingRecommendation` — получает `timeframe` из главного сигнала
3. TV-ссылки — берут ТФ из `recommendation.timeframe` или `simulated_trades.timeframe`
4. Дашборд — берёт ТФ из БД (поле `timeframe` уже есть в `simulated_trades`)

## Будущее видение

Интрадей (5m/15m) и свинг (1h/4h) — разные профили:
- разный `limit` OHLCV
- разный интервал скана
- разный "старший ТФ" для TREND_1H бонуса
- разные параметры SL/TP

Конфиг будущего:
```yaml
timeframes:
  "15m":
    limit: 160
    scan_interval_sec: 900
    senior_tf: "1h"
  "1h":
    limit: 100
    scan_interval_sec: 3600
    senior_tf: "4h"

trading:
  entry_timeframe: "15m"   # активный ТФ
```
