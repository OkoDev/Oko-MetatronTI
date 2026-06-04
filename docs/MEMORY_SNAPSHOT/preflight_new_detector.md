---
name: preflight-new-detector
description: Pre-flight чек-лист перед созданием нового detector / signal source в core/signals/ или core/smc/
metadata: 
  node_type: memory
  type: preflight
  triggers: 
    - новый detector
    - новый signal source
    - core/signals/*.py создать
    - core/smc/*.py создать
    - добавить confirmation в registry
    - новый event_type в EventBus
  originSessionId: 7eb11094-8711-4e7a-9c69-bf18fb7e5f76
---

# Pre-flight: новый detector / signal source

> Read **прежде чем** писать новый детектор. Поводы: новый файл в `core/signals/` или `core/smc/`, упоминание SignalType, новый event_type.

## 1. Решение: skill vs code

→ [[feedback_skill_vs_code]]

Прежде чем писать код:
- **Аналитика для меня в чате** — это SKILL.md, не код
- **Realtime детекция влияющая на сделки** — это код
- **Не уверен** — сначала прототип через skill, проверить на исторических данных, потом код

## 2. Источник истины: pattern mining

→ [[memory/pattern_*]] + `docs/PATTERN_MINING_2026-05-19.md`

ARCH-104 уже отобрал **15 production patterns** из 12 002 BH-FDR-валидных. Прежде чем добавлять новый "детектор" / "сигнал":
- Проверить, не покрывает ли его существующий pattern в `config/arch104_patterns.yaml`
- Проверить combinator-выходы в `data/research/2026-05-20--ph1/` — может, твоя идея уже отвергнута walk-forward'ом
- Если нет в combinator — добавить flag в `tools/pattern_mining/combinator_v2.py::compute_flags()`, прогнать walkforward, потом интегрировать

## 3. Архитектура

| Что | Где |
|---|---|
| Сам детектор | `core/signals/<name>_detector.py` или `core/smc/<name>.py` |
| Класс детектора | `class XDetector` с методом `detect(df, **ctx) → XEvent`/`None` |
| EventBus publish | `await bot.event_bus.publish(symbol, "<event_type>", priority, payload)` |
| Confirmation aggregator | если влияет на strength — добавить в `core/confirmations/registry.py` с весом |
| Trade simulator | если генерирует прямой сигнал — путь через `register_trade_async` |

## 4. Pre-compute правило (ARCH)

→ [[arch_indicator_precompute]]

- WT, ATR, EMA, trend — **уже посчитаны в scan_one** перед твоим детектором, не пересчитывай
- Читай колонки из df: `df["wt1"]`, `df["atr"]`, `df["trend"]` etc.
- Если детектору нужен новый индикатор → pre-compute в `scan_one`, не в детекторе

## 5. Lookahead safety (критично!)

→ [[backtest_lookahead_bug]]

- При MTF reindex (`df_4h` на индекс `df_1h`) — сдвинуть индекс ВПЕРЁД на длину свечи (`Timedelta(hours=4)`) ДО reindex
- Иначе 4h флаги "видны" на 1h за 3ч до закрытия → false positives в бэктесте
- WR>90% в backtest — почти всегда lookahead bug

## 6. Trading philosophy

→ [[feedback_trading_philosophy]]

- Нет fallback без подтверждения ("alignment хороший — войдём без кросса" — НЕТ)
- Рынок должен **показать** разворот, не угадывать
- WT кросс обязателен (не бонус) для reversal-сигналов

## 7. Тесты

- Unit-тест в `tests/test_<name>_detector.py`:
  - На синтетическом сценарии — детектор срабатывает
  - На anti-сценарии — НЕ срабатывает
  - Edge cases: пустой df, df меньше `min_bars`, NaN в колонках
- Бэктест на исторических данных (если детектор для сделки) — `tools/pattern_mining/walkforward.py`

## 8. Что НЕ забыть

- Добавить в EVENT_PRIORITY (`core/context/event_bus.py`) если новый event_type
- Логировать первое срабатывание на INFO, дальнейшие DEBUG (избежать спама)
- features_json — записать debug-поля детектора (для последующего анализа)
- TASKS.md — статус новой задачи

## Связано
- [[arch_indicator_precompute]] · [[arch_signal_types]] (в Obsidian/Architecture)
- [[feedback_trading_philosophy]] · [[feedback_no_blocking]] · [[feedback_skill_vs_code]]
- [[backtest_lookahead_bug]]
