# Whats-Next — Handoff Document
> Создан: 13.03.2026 | Агент: Claude Sonnet 4.6 Developer
> Сессия: Стратегии торговли STRAT-01 — STRAT-04

---

## original_task

Реализация системы торговых стратегий в отдельном блоке (strategies/) чтобы:
- Создавать новые стратегии как отдельные файлы
- Удобно тестировать их на исторических данных через CLI
- Легко переключаться между стратегиями через config.yaml

Конкретные задачи из плана stateful-hatching-waterfall.md:
- STRAT-01: ConfluenceScannerStrategy в strategies/built_in/
- STRAT-02: Параметр strategy в BacktestConfig + подключение движка
- STRAT-03: CLI runner run_backtest.py
- STRAT-04: active_strategy в config.yaml + trading_intelligence

---

## work_completed — ВСЕ ЗАДАЧИ ВЫПОЛНЕНЫ

### STRAT-01: ConfluenceScannerStrategy
**Файл:** [strategies/built_in/confluence_scanner_strategy.py](strategies/built_in/confluence_scanner_strategy.py) (новый, ~200 строк)
- `@register_strategy("confluence_scanner")` декоратор
- `analyze()` — ищет `SignalType.CONFLUENCE` с `strength >= min_strength`, выбирает лучший LONG/SHORT
- `calculate_sl_tp()` — TSL-линия из `market_context.tsl_trendup/trenddown` + буфер `sl_buffer_pct%`, fallback `ATR×1.5`
- Параметры: `min_strength=60, tp_rr=3.0, sl_buffer_pct=0.3, tsl_max_dist=3.0, tsl_min_dist=0.6`

### STRAT-02: BacktestConfig + движок
**Файл:** [backtesting_engine.py](backtesting_engine.py) строки 102-104:
```python
strategy: str = "default"
strategy_config: dict = None
```
- `_fetch_ohlcv_swap()` строки 147-153: retry на ошибку BingX 100410, max 3 retry, backoff 5/10/15 сек
- `detect_signals()`: блок для `confluence_scanner` — подтягивает пивоты из `weekly_pivots`, создаёт `_conf_cache = {f"{symbol}_1D": flat_dict}`, вызывает `scan_confluence()`

### STRAT-03: CLI runner
**Файл:** [run_backtest.py](run_backtest.py) (новый, ~215 строк)
```bash
python run_backtest.py --list-strategies
python run_backtest.py --strategy confluence_scanner --symbol BTC/USDT --days 30
python run_backtest.py --strategy default --symbol ETH/USDT --from 2026-01-01 --to 2026-03-01
```
- UTF-8 force на Windows (строки 3-7) — иначе emoji ломает cp1251
- Нормализация символа: `args.symbol.upper().replace(" ", "")`
- `finally: await engine._swap_exchange.close()` — закрытие всегда
- Вывод: Win Rate, Avg R, Profit Factor, Sharpe, Max DD, Total Return + разбивка по типам сигналов

### STRAT-04: active_strategy в config + trading_intelligence
**Файл:** [config.yaml](config.yaml) — добавлен блок:
```yaml
trading:
  active_strategy: confluence_scanner
  strategies:
    confluence_scanner:
      min_strength: 60
      tp_rr: 3.0
      sl_buffer_pct: 0.3
      tsl_max_dist: 3.0
      tsl_min_dist: 0.6
    confluence:
      min_signals: 2
      conflict_threshold: 0.3
    conservative:
      min_signals: 3
      min_confidence: 0.65
```

**Файл:** [core/trading_intelligence.py](core/trading_intelligence.py) — чтение стратегии из нового пути:
```python
strategy_name = (config.get("trading.active_strategy") or config.get("strategy.name") or "confluence")
strategy_config = config.get(f"trading.strategies.{strategy_name}") or {}
```

### Сопутствующие изменения

**[strategies/registry.py](strategies/registry.py)** — добавлен импорт ConfluenceScannerStrategy, MTFBiasStrategy в try/except

**[core/confluence_scanner.py](core/confluence_scanner.py)** — крупное обновление:
- Добавлен SHORT сетап (симметричный LONG)
- `_SCORE_WT_CROSS = 15` — фактор WT crossover (wt1/wt2)
- `last_tsl_cross` и `last_wt_cross` — поиск ПОСЛЕДНЕГО пересечения в `cross_fresh_bars=10` барах (не any() по всему lookback)
- `WT_CROSS_UP` обязателен для LONG, `WT_CROSS_DOWN` — для SHORT (без него сигнал не выдаётся)
- `window = df.iloc[-lookback_bars - 1:-1]` — исключает открытую свечу (lookahead bias fix)
- `confluence_message()` — TF метка `⏱ {tf}`, иконка направления
- `_check_near_resistance()` для SHORT (проверяет R1/R2/PP)
- `_check_bearish_divergence_wt()` — price HH, wt1 LH

**[core/signal_models.py](core/signal_models.py)** — добавлен `MTF_BIAS = "mtf_bias"` в `SignalType` enum

### Верификация
- `python run_backtest.py --list-strategies` — 4 стратегии: confluence, confluence_scanner, conservative, mtf_bias
- `python run_backtest.py --strategy confluence_scanner --symbol GRT/USDT --days 60` — успешно завершился
- Rate limit retry 100410 работает

---

## work_remaining

### 1. Закоммитить изменения (ВЫСОКИЙ ПРИОРИТЕТ)
Большой объём незакоммиченных изменений — риск потери.

Файлы для коммита:
```
strategies/built_in/confluence_scanner_strategy.py  (НОВЫЙ)
run_backtest.py                                      (НОВЫЙ)
backtesting_engine.py                               (strategy поля + rate limit retry)
strategies/registry.py                              (импорт ConfluenceScannerStrategy)
core/confluence_scanner.py                          (SHORT + WT_CROSS + anti-lookahead)
core/signal_models.py                               (MTF_BIAS enum)
core/trading_intelligence.py                        (active_strategy config path)
config.yaml                                         (active_strategy + strategies block)
```

### 2. Мониторинг WR+EV через 1-2 недели
После накопления данных проверить avg_R confluence сделок:
```bash
python -c "
from core.performance_engine import PerformanceEngine
pe = PerformanceEngine('subscriptions.db')
for r in pe.by_signal_type(): print(r)
"
```

### 3. Этап 8.4.3: hard/soft timeouts разделение
Разделить `timeout=10.0` в `_collect_all_signals` на hard (API) и soft (вычисления).

### 4. Этап 8.4.7: decision trace dashboard
Показывать в дашборде "почему" для каждой сделки.

### 5. Каскадные дивергенции 1D+4h
Добавить в `monitor_market()` цикл раз в 6 часов.
Метод `detect_cascade_divergence()` уже готов в `divergence_detector.py`.

### 6. Этап 9: core/structure_detector.py
Swing H/L, CHoCH/BOS (Break of Structure) для Smart Money Concepts.

---

## attempted_approaches — Ошибки и решения

### BingX rate limit 100410
- Проблема: При загрузке >60 дней данных 1h — код 100410 "endpoint trigger frequency limit"
- Решение: Retry loop в `_fetch_ohlcv_swap()` — max 3 попытки, backoff 5/10/15 сек
- Ограничение: 60 дней на 1h норм, 80-120 дней иногда вызывает

### Lowercase символ
- Проблема: `btc/USDT` → "bingx does not have market symbol btc/USDT:USDT"
- Решение: `symbol = args.symbol.upper().replace(" ", "")` в run_backtest.py

### Unclosed client session
- Проблема: После ошибки — asyncio WARNING об unclosed aiohttp session
- Решение: `finally: await engine._swap_exchange.close()`

### Windows encoding UnicodeEncodeError
- Проблема: "charmap codec can't encode emoji" при stdout cp1251
- Решение: Force UTF-8 redirect строки 3-7 run_backtest.py

### Duplicate LONG+SHORT confluence сигналы
- Проблема: `any()` по всему lookback → LONG и SHORT одновременно
- Решение: Поиск ПОСЛЕДНЕГО кросса — `last_tsl_cross`, `last_wt_cross` — взаимоисключают

### WT_OS слишком старый в lookback
- Проблема: WT был в OS 7-9 часов назад, сейчас уже в OB — фактор засчитывался
- Решение: Проверка `wt_current < wt_ob_thr` для LONG

### Confluence → action=WATCH вместо BUY/SELL
- Проблема: `signal_count_factor = min(1/5.0, 1.5) = 0.2` → `confidence = 0.17 < 0.55`
- Решение: В `_calculate_advanced_confidence` CONFLUENCE с N факторами считается как N сигналов:
  `effective_count += n_factors - 1` для каждого CONFLUENCE сигнала

---

## critical_context

### Python
- Python 3.12 строго: `C:\Users\yogoru\AppData\Local\Programs\Python\Python312\python.exe`
- `.venv` и Python 3.13 не имеют aiogram — не использовать

### BingX API
- `enableRateLimit: False` в ccxt живого бота — намеренно, управление через `Semaphore(20)` в ApiEngine
- Backtesting engine: отдельный ccxt с `enableRateLimit: True` (нет Semaphore)
- Rate limit 100410 — временный бан endpoint, не глобальный

### Confluence OB/OS пороги
- WT OS зона: `< -60` (параметр `wt_os_threshold`, дефолт -60)
- WT OB зона: `_DEFAULT_WT_OB = 53` в confluence_scanner.py (НЕ 60!)
- Смысл: "текущий WT не выше +53" для проверки свежести LONG сигнала OS

### Обязательные условия для сигналов confluence_scanner
- LONG: требует `WT_CROSS_UP` в последних `cross_fresh_bars=10` барах (2.5 часа на 15m)
- SHORT: требует `WT_CROSS_DOWN` в последних `cross_fresh_bars=10` барах
- Без свежего WT кросса сигнал НЕ выдаётся даже при score >= min_strength

### Что НЕ переносить в strategies/
- `core/` = чистые алгоритмы (индикаторы, детекторы) — не трогать
- `strategies/` = только классы решений (входить/не входить, SL/TP)
- `ConfluenceScannerStrategy` — обёртка над готовыми `SignalType.CONFLUENCE` от `scan_confluence()`

### Дивергенции — ЗАПРЕТ
- НЕ должны попадать в `all_scan_signals` / `pre_signals`
- Создают `conflict_ratio` → `action=WATCH` → 0 сделок

### Пивоты в backtesting движке
- Хранятся как `{week_start_ms: {PP, R1, S1...}}`
- Для confluence_scanner нужна flat-конвертация: `_conf_cache = {f"{symbol}_1D": flat_dict}`

---

## current_state

### Статус deliverables

| Deliverable | Статус | Файл |
|---|---|---|
| ConfluenceScannerStrategy | ГОТОВ | strategies/built_in/confluence_scanner_strategy.py |
| BacktestConfig.strategy | ГОТОВ | backtesting_engine.py:102-104 |
| Rate limit 100410 retry | ГОТОВ | backtesting_engine.py:147-153 |
| CLI runner run_backtest.py | ГОТОВ | run_backtest.py |
| active_strategy config.yaml | ГОТОВ | config.yaml |
| trading_intelligence стратегия | ГОТОВ | core/trading_intelligence.py |
| Confluence SHORT сетап | ГОТОВ | core/confluence_scanner.py |
| WT_CROSS обязательный | ГОТОВ | core/confluence_scanner.py |
| TF в TG-сообщениях | ГОТОВ | core/confluence_scanner.py |
| Git commit | НЕ СДЕЛАН | — |

### Что работает
- `python run_backtest.py --list-strategies` — 4 стратегии
- `python run_backtest.py --strategy confluence_scanner --symbol GRT/USDT --days 60` — успешно
- Живой бот использует `active_strategy: confluence_scanner` из config.yaml
- Confluence генерирует LONG и SHORT сигналы симметрично

### Что под вопросом
- Незакоммиченные изменения — риск потери при аварии
- `trading_intelligence.py` с новым путём `trading.active_strategy` не верифицирован в живом боте
- 6 открытых сделок в БД со strength 31-32 (ниже порога 40)

### Команды для быстрой проверки
```bash
cd "e:/MTF BOT/CURSOR/crypto_volume_bot"

# Стратегии
python run_backtest.py --list-strategies

# Бэктест 30 дней
python run_backtest.py --strategy confluence_scanner --symbol BTC/USDT --days 30

# Git статус
git status && git log --oneline -5

# Статистика из БД
python -c "
from core.performance_engine import PerformanceEngine
pe = PerformanceEngine('subscriptions.db')
print(pe.summary())
for r in pe.by_signal_type(): print(r)
"
```

### Где мы сейчас
План **stateful-hatching-waterfall.md** полностью выполнен (STRAT-01 — STRAT-04).
Следующий обязательный шаг: **git commit** всех незакоммиченных изменений.
После: мониторинг результатов `confluence_scanner` в production через 1-2 недели.
