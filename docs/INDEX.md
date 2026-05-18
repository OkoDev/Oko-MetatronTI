# Oko MTF Bot — Индекс документации

> Актуально на: 2026-03-27

---

## 🚀 Быстрый старт

| Файл | Содержание |
|------|-----------|
| [README.md](../README.md) | Быстрый старт, команды, архитектура, параметры |
| [config.yaml](../config.yaml) | Конфигурация бота (или `http://localhost:8000/settings`) |

---

## 📋 Управление проектом (для агентов)

| Файл | Содержание |
|------|-----------|
| [TASKS.md](../TASKS.md) | Активные задачи DEV/ARCH/TRADER — приоритеты, статусы |
| [TASKS-ARCHIVE.md](../TASKS-ARCHIVE.md) | Архив 55 завершённых задач (22–25.03.2026) |
| [DISCUSSION.md](../DISCUSSION.md) | Живой диалог агентов (23–27.03.2026) |
| [DISCUSSION-ARCHIVE-MAR2026.md](../DISCUSSION-ARCHIVE-MAR2026.md) | Архив диалогов (19–22.03.2026) |
| [whats-next.md](../whats-next.md) | Handoff от предыдущей сессии |
| [memory/MEMORY.md](../memory/MEMORY.md) | Архитектурные решения, паттерны, известные баги |
| [memory/current_state.md](../memory/current_state.md) | Текущее состояние системы (последние 3 сессии) |

---

## 📖 История и прогресс

| Файл | Содержание |
|------|-----------|
| [PROJECT-LOG.md](../PROJECT-LOG.md) | История изменений проекта — от первого запуска (03.03) |
| [ROADMAP.md](../ROADMAP.md) | Этапы разработки, метрики прогресса |

---

## 🏗️ Архитектура

| Файл | Содержание |
|------|-----------|
| [docs/ARCHITECTURE.md](ARCHITECTURE.md) | Схема системы, потоки данных, БД, quality gates |
| [BOT_SIGNAL_MAP.md](../BOT_SIGNAL_MAP.md) | Сигнальный пайплайн: от OHLCV до регистрации сделки |
| [docs/INDICATORS_GUIDE.md](INDICATORS_GUIDE.md) | Индикаторы: WT, TSL, ATR, Swing, Divergence |
| [docs/SMC_GUIDE.md](SMC_GUIDE.md) | Smart Money Concepts: теория и реализация |
| [docs/SMC_LAYER.md](SMC_LAYER.md) | SMC слой в коде: core/smc/ пакет |

---

## 🗄️ Архив (устаревшие, но полезные)

| Файл | Содержание |
|------|-----------|
| [docs/archive/ARCHITECTURE_ANALYSIS.md](archive/ARCHITECTURE_ANALYSIS.md) | Диагностика архитектуры 19.03.2026 |
| [docs/archive/AUDIT_INDICATORS_REPORT.md](archive/AUDIT_INDICATORS_REPORT.md) | Аудит индикаторов (разовый отчёт) |

---

## 🗺️ Карта кода (ключевые файлы)

```
oko_mtf.py                     ← точка входа (бывш. bot_with_subscriptions.py)
config.yaml                    ← вся конфигурация
subscriptions.db               ← SQLite (сделки, пользователи)

core/trading_intelligence.py   ← главный оркестратор сигналов
core/trade_simulator.py        ← регистрация, Cascade TSL, MFE
core/signal_checkers.py        ← все детекторы сигналов
core/indicators.py             ← WaveTrend, ATR, TSL-line
core/market_regime.py          ← TREND_UP/DOWN/RANGE/HIGH_VOL
core/pivot_calculator_fixed.py ← пивоты (singleton, UTC)
core/smc/                      ← SMC пакет (swing, BOS, FVG, OB)
core/outcome_predictor.py      ← ML P(win)

bot/loops/scan_loop.py         ← цикл скана + WL breach входы
bot/loops/trade_tracker.py     ← трекинг открытых сделок
web/dashboard_server.py        ← дашборд :8000
```
