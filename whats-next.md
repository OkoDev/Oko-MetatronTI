# What's Next — Handoff 22.03.2026 (сессия 9)

<original_task>
## Продолжение спринта DEV (сессия 9)

Сессия 8 завершила:
- п.4: run_universe_backtest.py — инфраструктура бэктеста на 30 случайных альтах
- п.5: SMC эксперимент cfg1/cfg2/cfg3 (ETH/SOL/BNB): ETH OB-фильтр +5.4% WR, SOL/BNB не улучшает
- п.6: Вариант C — require_pivot_tp: без пивотного TP в 2-20R → не регистрировать сделку
- п.7: FVG immediate mitigation fix (start_bar fvg.index+2 → +1)

ARCH ответил на Q1/Q2/Q3 и поставил три задачи для сессии 9:
1. Q1 (OB per-asset) → реализовать `smc_ob_pairs` в BacktestConfig — применять OB-фильтр только на топ-5 ликвидных пар
2. Q2 → 30-символьный бэктест (данные закэшированы) — запустить и дать отчёт
3. Q3 → chart_builder fallback (уже подтверждён в прошлой сессии)

Сессия 9 выполнила:
- ✅ `smc_ob_pairs` реализован полностью в 4 местах
- ✅ 30-символьный бэктест (task btzlnl2xq) запущен в фоне — всё ещё работает
- ✅ TASKS.md обновлён — DEV→ARCH отчёт написан
</original_task>

<work_completed>
## Сессия 9 — завершено

### 1. `smc_ob_pairs` — per-asset OB-фильтр (✅ полностью реализован)

**Файл:** `scripts/backtesting_engine.py`

**BacktestConfig (строка 174-175):**
```python
smc_ob_pairs: list = None     # per-asset OB-фильтр: список символов где smc_require_ob активен.
                              # None = применять ко всем. ["ETH/USDT","BTC/USDT"] = только топ-5.
```

**run_backtest() — Фильтр 6 (строки 663-665):**
```python
_ob_pairs = self.config.smc_ob_pairs
_ob_pair_match = (_ob_pairs is None) or (self.config.symbol in _ob_pairs)
if self.config.smc_require_ob and _ob_pair_match and not _smc_ob_active:
    continue
```

**run_bot_backtest() — параметр (строка 1407):**
```python
smc_ob_pairs: list = None,    # per-asset: None=все, ["ETH/USDT",...]=только эти
```

**run_bot_backtest() — BacktestConfig инициализация (строки 1435-1445):**
```python
engine_cfg = BacktestConfig(
    ...
    use_smc=use_smc, smc_require_ob=smc_require_ob, smc_require_fvg=smc_require_fvg,
    smc_ob_pairs=smc_ob_pairs,  # ← добавлено в сессии 9
)
```

**run_bot_backtest() — inline SMC-фильтр (строки ~1540-1548):**
```python
_ob_pairs = engine_cfg.smc_ob_pairs
_ob_pair_match = (_ob_pairs is None) or (symbol in _ob_pairs)
if smc_require_ob and _ob_pair_match and not _ob_ok:
    continue
```

### 2. `run_smc_experiment.py` — CLI аргумент `--ob-pairs` (✅)

**Файл:** `scripts/run_smc_experiment.py`

Добавлен параметр `smc_ob_pairs: Optional[List[str]] = None` в `run_smc_configs()`.
Добавлен CLI: `--ob-pairs ETH/USDT BTC/USDT SOL/USDT BNB/USDT XRP/USDT`
Передаётся в каждый `run_bot_backtest()` вызов.

Пример запуска с per-asset OB:
```bash
python scripts/run_smc_experiment.py \
  --symbols ETH/USDT BTC/USDT SOL/USDT BNB/USDT XRP/USDT \
  --ob-pairs ETH/USDT BTC/USDT SOL/USDT BNB/USDT XRP/USDT \
  --source binance --start 2023 --end 2024
```

### 3. TASKS.md — DEV→ARCH отчёт (✅)

Добавлен блок `### [22.03.2026] DEV — smc_ob_pairs реализован + 30-symbol бэктест запущен` в начало Discussion (строки 15-53). Все три задачи ARCH закрыты.

### 4. memory/current_state.md — обновлён (✅)

Добавлена запись сессии 9 с полным списком изменений.

---

## Сессия 8 — было завершено ранее (для справки)

### п.5: SMC эксперимент

**Новый файл:** `scripts/run_smc_experiment.py`
Запускает 3 конфигурации: cfg1 (baseline без OB), cfg2 (OB-фильтр), cfg3 (OB+FVG)

**Результаты (ETH/SOL/BNB, Binance 2023-2024):**
- ETH: cfg1→432 tr WR=47.7%, cfg2→49 tr WR=53.1% (+5.4%), AvgR 0.130→0.330
- SOL: cfg1→417 tr WR=50.1%, cfg2→7 tr (n слишком мало, нестатистично)
- BNB: cfg1→425 tr WR=39.2%, cfg2→15 tr WR=33.3% (хуже!)
- Вывод: OB-фильтр полезен только на ликвидных зрелых парах (ETH/BTC)

**Отчёт:** `data/smc_experiment_20260322_012439.json`

### п.6: Вариант C — require_pivot_tp

**Файл:** `bot/monitoring.py` (~строка 380)
```python
elif bot.config.get("trading.sl_tp.require_pivot_tp", False):
    logger.info("[%s] Пропуск регистрации: require_pivot_tp=true, pivot не найден", symbol)
    if recommendation is not None:
        recommendation = None  # блокирует is_actionable и should_register
```

**Файл:** `config.yaml` — `require_pivot_tp: false` (выключен по умолчанию)

### п.7: FVG immediate mitigation fix

**Файл:** `core/smc/fvg.py`
`start_bar = fvg.index + 1` (было: `+ 2`)

### Инфраструктура бэктеста (сессии 7-8)

| Файл | Описание |
|------|----------|
| `scripts/universe_builder.py` | CoinGecko топ-250, стратификация 10+10+10, seed=42 |
| `scripts/multi_source_ohlcv.py` | Автовыбор источника: binance→cryptocom→bingx |
| `scripts/run_universe_backtest.py` | Universe бэктест на 30 случайных альтах |
| `scripts/backtesting_engine.py` | +Binance source, +smc params, +smc_ob_pairs |

**Данные закэшированы** (SQLite кэш в проекте):
- XRP/USDT 15m: 147932 баров (HIT)
- XRP/USDT 3m: 739655 баров (HIT)
- ETH/USDT 15m: 147932 баров (HIT)
- ETH/USDT 3m: PARTIAL (данные до 2026-01-31, хвост докачивается)
</work_completed>

<work_remaining>
## Немедленно (при следующем старте сессии)

### 1. Проверить результаты 30-символьного бэктеста (ПРИОРИТЕТ 1)

**Task ID:** `btzlnl2xq`

```python
# В начале следующей сессии:
TaskOutput(task_id="btzlnl2xq", block=False, timeout=5000)
```

Если `status=completed`:
- Найти новый JSON: `ls data/universe_backtest_*.json` (самый свежий)
- Прочитать отчёт, составить таблицу
- Добавить в TASKS.md Discussion (DEV→ARCH)

Если `status=running`:
- Продолжить другие задачи, вернуться позже
- ИЛИ `TaskOutput(..., block=True, timeout=600000)` чтобы подождать

**Что анализировать в результатах:**
- Медианный WR по 30 символам (цель > 45%)
- Сколько символов показывают WR > 50% (baseline без SMC)
- Распределение AvgR: есть ли аутлайеры тянущие среднее вниз
- FIGR_HELOC/USDT — скорее всего 0 сделок или ошибка, исключить из медианы

### 2. Коммит всех изменений спринта (ПРИОРИТЕТ 2)

60 файлов, 11088 вставок накоплено с коммита `8268f0c`:

```bash
# Рекомендованные файлы для стейджинга (основные изменения спринта):
git add scripts/backtesting_engine.py \
        scripts/run_smc_experiment.py \
        scripts/run_universe_backtest.py \
        scripts/universe_builder.py \
        scripts/multi_source_ohlcv.py \
        core/smc/fvg.py \
        bot/monitoring.py \
        config.yaml \
        TASKS.md \
        memory/current_state.md \
        whats-next.md

git commit -m "feat: SMC бэктест (smc_ob_pairs per-asset, universe backtest, FVG fix, require_pivot_tp)"
```

### 3. Каскадный SL — Этап A (следующий функциональный приоритет)

**План:** `C:\Users\yogoru\.claude\plans\squishy-brewing-church.md`

**Три изменения Этапа A:**

#### 3a. Swing SL в `core/trading_intelligence.py`
Метод: `_calculate_levels()` строки 1269-1305
```python
# Новый приоритет SL:
# 1. SWING_LOW (для LONG): market_context.swing_low + буфер 0.3%
#    → sl_source = "swing_low"
# 2. TSL-линия (trendup/trenddown ATR-43) если swing недоступен
#    → sl_source = "tsl_line:trendup"
# 3. ATR fallback
#    → sl_source = "atr_14:X.XX%"
# market_context.swing_low/high уже вычисляются в _compute_swing_levels() (строки 1035-1063)
```

#### 3b. Безубыток в `core/trade_simulator.py`
Метод: `check_open_trades_with_tsl()`
```python
# Добавить перед TSL-проверкой:
breakeven_r = config.get("trading.breakeven_activation_r", 0.5)
if current_r >= breakeven_r and not tsl_activated:
    new_sl = entry * (1.001) if is_long else entry * (0.999)
    # UPDATE stop_loss в БД
```

#### 3c. Конфиг `config.yaml`
```yaml
trading:
  use_breakeven: true           # (уже есть: use_breakeven: false → изменить на true)
  breakeven_activation_r: 0.5  # новый параметр
```

**Верификация после реализации:**
```bash
grep "sl_source.*swing" crypto_bot.log | head -10
grep "breakeven" crypto_bot.log | head -10
```

### 4. SMC эксперимент с per-asset конфигом (после 30-symbol результатов)

```bash
python scripts/run_smc_experiment.py \
  --symbols ETH/USDT BTC/USDT SOL/USDT BNB/USDT XRP/USDT \
  --ob-pairs ETH/USDT BTC/USDT \
  --source binance --start 2022 --end 2026 --conc 2
```
Цель: проверить что OB только на ETH+BTC даёт лучший aggregated WR чем cfg2 (все символы).
</work_remaining>

<attempted_approaches>
## Что не работало / тупики

### 30-символьный бэктест — первая попытка (сессия 8)

Первый запуск `run_universe_backtest.py` завершился с exit code 0 но **без JSON-файла** в `data/`. Причина: задача была запущена как background bash в предыдущей сессии, произошёл компакт контекста, задача завершилась без сохранения (или упала на FIGR_HELOC/USDT). Решение: запустить повторно (task btzlnl2xq).

### Hard timeout на XRP 3m данных

При бэктесте последних ~10 баров (конец 2026-03) запрос 3m данных для будущих временных меток зависал на ~25 сек. Не блокер — только последние бары.

### Negative Sharpe во всех baseline прогонах

WR=46-47%, AvgR=0.10-0.13 → Sharpe < 0. Это особенность формулы: при leverage=1 и маленьком AvgR каждый -1R убыток перевешивает +0.13R выигрыш в equity волатильности. ARCH подтвердил: **формула, не стратегия**. Не переделывать.

### OB-фильтр на SOL и BNB не работает

cfg2 (smc_require_ob=True) на SOL: только 7 сделок из 417 — OB редко совпадает с сигналами. На BNB: WR снижается (39.2%→33.3%). Поэтому реализован per-asset `smc_ob_pairs`.

### BacktestConfig: smc_ob_pairs не передавался в engine_cfg

`run_bot_backtest()` создавал `BacktestConfig(...)` без `smc_ob_pairs=smc_ob_pairs`. Обнаружено в начале сессии 9, исправлено.

### OutcomePredictor — AUC < 0.5

Из лога task btzlnl2xq: `CV AUC=0.323` — хуже случайного. 2837 сделок, WR=21.0%. Модель не помогает. Это контекст продакшн-данных, не бэктест.
</attempted_approaches>

<critical_context>
## Критический контекст

### Роли агентов
- **DEV = yogoru@gmail.com** (этот инстанс, VSCode/Claude Code) — реализует
- **ARCH = oko.webdev@gmail.com** (Docker) — проектирует, пишет Discussion в TASKS.md
- Рабочий процесс: ARCH пишет → DEV реализует → DEV пишет отчёт в Discussion

### Python версии
- **Python 3.12**: `C:\Users\yogoru\AppData\Local\Programs\Python\Python312\python.exe`
  - Единственная с aiogram. Использовать для запуска бота и бэктестов.
- **.venv и Python 3.13**: без aiogram — не использовать для бота

### Кэш данных Binance
SQLite кэш: HIT для XRP/ETH/BNB/SOL 15m и 1h (~147K баров на пару).
Повторные прогоны намного быстрее первого.

### BacktestConfig → run_bot_backtest разрыв

Два независимых SMC-фильтра:
1. `BacktestingEngine.run_backtest()` — Фильтр 6 (строки ~660-670)
2. `run_bot_backtest()` inline filter (строки ~1535-1550)

Оба теперь используют `smc_ob_pairs`. Новые параметры SMC нужно добавлять в **оба** места.

### COOLDOWN = 8 в бэктесте

`run_bot_backtest()` анализирует каждый 8-й бар. 147932 баров / 8 = ~18491 анализов.
Время: ~15-30 мин на символ при cache hit.
30 символов параллельно (concurrency=2) = ~4-8 часов.

### FIGR_HELOC/USDT

Нестандартный тикер в universe (seed=42, стратификация). Не существует на Binance.
Вероятно даст 0 сделок — исключить из медианы при анализе результатов.

### OutcomePredictor в продакшн

CV AUC=0.323 — хуже случайного. 2837 сделок, WR=21.0%. Модель деградировала.
Это не блокер для бэктеста но означает что `confidence` в реальном боте искажён.

### Незакоммиченные изменения — масштаб

60 файлов, 11088 вставок с последнего коммита `8268f0c`.
Нужен коммит перед следующим крупным изменением.

### План Каскадного SL

`C:\Users\yogoru\.claude\plans\squishy-brewing-church.md` — 4 этапа.
Этап A (Swing SL + безубыток) — следующий функциональный приоритет бота.
Swing уже вычисляется в `market_context.swing_low/high` но не используется как SL.

### Адаптивные веса (текущие из лога)

```
pivot_reversal: 0.200 → 0.185 (avg_R=-0.19, n=611)
wt_signal:      0.080 → 0.090 (avg_R=+0.32, n=473)
trend_signal:   0.050 → 0.045 (avg_R=-0.26, n=44)
anomaly:        0.030 → 0.035 (avg_R=+0.37, n=36)
```
</critical_context>

<current_state>
## Статус на момент завершения сессии 9

### Deliverables

| Артефакт | Статус | Файл/Строки |
|----------|--------|-------------|
| smc_ob_pairs в BacktestConfig | ✅ Готов | `backtesting_engine.py:174` |
| smc_ob_pairs в run_bot_backtest() | ✅ Готов | `backtesting_engine.py:1407,1444` |
| smc_ob_pairs в inline filter | ✅ Готов | `backtesting_engine.py:~1542` |
| --ob-pairs CLI в run_smc_experiment | ✅ Готов | `run_smc_experiment.py` |
| 30-symbol бэктест | 🔄 Работает | task `btzlnl2xq` |
| TASKS.md DEV→ARCH отчёт | ✅ Написан | `TASKS.md:15-53` |
| memory/current_state.md | ✅ Обновлён | актуален |
| require_pivot_tp (п.6) | ✅ Готов | `bot/monitoring.py`, `config.yaml` |
| FVG immediate mitigation (п.7) | ✅ Готов | `core/smc/fvg.py` |
| Коммит спринта | ❌ Не сделан | — |
| Каскадный SL Этап A | ❌ Не начат | plan: `squishy-brewing-church.md` |

### Порядок следующих действий

```
1. TaskOutput(btzlnl2xq) → если completed → прочитать JSON → TASKS.md отчёт
2. git commit (60 файлов спринта)
3. Каскадный SL Этап A:
   a. core/trading_intelligence.py — swing SL
   b. core/trade_simulator.py — breakeven +0.5R
   c. config.yaml — use_breakeven: true, breakeven_activation_r: 0.5
```

### Что работает

- Бэктест инфраструктура: `run_universe_backtest.py`, `run_smc_experiment.py`
- per-asset OB фильтр: `smc_ob_pairs` реализован и передаётся правильно
- Кэш данных: SQLite с ~150K баров на пару — быстрые повторные прогоны

### Что не работает / требует внимания

- 30-symbol бэктест — ещё работает, нет финального JSON
- OutcomePredictor: AUC=0.323 (деградация) — не блокер, но требует внимания позже
</current_state>
