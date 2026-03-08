# 📋 TASKS — Координация агентов

Файл координации между Architect (yogoru) и Developer (oko.webdev).

**Workflow:** Architect создаёт задачу → Developer берёт в работу → Architect делает review

---

## 🔥 В РАБОТЕ (In Progress)

_пусто_

---

## 📥 ОЧЕРЕДЬ (Backlog)

### [ARCH-01] Этап 8: Рефакторинг bot_with_subscriptions.py
**Агент:** Architect
**Приоритет:** Высокий
**Описание:**
Разбить монолит 1540+ строк на модули:
- `bot/core/bot.py` — класс OkoBot (__init__, свойства)
- `bot/loops/scan_loop.py` — scan_all_pairs, scan_one
- `bot/loops/ml_loop.py` — _ml_training_loop
- `bot/loops/trade_tracker.py` — check_open_trades loop
Точка входа остаётся в `bot_with_subscriptions.py` (только запуск).

### [ARCH-02] Этап 8: Рефакторинг trading_intelligence.py
**Агент:** Architect
**Приоритет:** Высокий
**Описание:**
Разбить 1850+ строк:
- `core/intelligence/signal_aggregator.py` — _analyze_signals_advanced
- `core/intelligence/confidence_calculator.py` — _calculate_advanced_confidence
- `core/intelligence/recommendation_generator.py` — _generate_recommendation
- `core/intelligence/ml_enhancer.py` — _enhance_analysis_with_ml

### [DEV-01] Этап 9: core/structure_detector.py
**Агент:** Developer
**Приоритет:** Средний
**Зависимость:** После ARCH-01 завершён
**Описание:**
Создать детектор SMC структуры:
- `detect_swing_highs_lows(df)` → список пиков/впадин
- `detect_choch(highs, lows)` → Change of Character
- `detect_bos(highs, lows)` → Break of Structure
- Интеграция в signal_checkers.py как новый тип сигнала

### [DEV-02] Тесты для signal_checkers.py
**Агент:** Developer
**Приоритет:** Средний
**Описание:**
`tests/unit/test_signal_checkers.py` уже существует — дополнить тестами:
- check_wt_signals с мок данными OS/OB зон
- check_anomaly_signals при volume spike
- check_divergence_signals (bullish/bearish)

### [DEV-03] Тесты для divergence_detector.py
**Агент:** Developer
**Приоритет:** Низкий
**Описание:**
`tests/unit/test_divergence.py` уже есть — расширить:
- hidden bullish/bearish с zone фильтром
- cascade divergence bonus расчёт

---

## ✅ ГОТОВО (Done)

| ID | Описание | Коммит |
|----|----------|--------|
| — | Этап 7: RPredictor интеграция | 7c7310e |
| — | Разделение порогов min_strength | ff407d4 |
| — | /settings полный дашборд | 00b5ef1 |
| — | /settings сброс на defaults | 80572c0 |
| — | conflict_ratio баг-фикс (0.15→0.05) | bddb51b |
| — | Kelly sizing в TG-алертах | bddb51b |
| — | RPredictor MIN_SAMPLES 100→75 | bddb51b |

---

## 📏 Правила

1. **Не редактировать один файл одновременно** — договариваться через этот файл
2. Architect задаёт архитектуру → Developer реализует
3. Каждая задача = отдельный git commit с внятным сообщением
4. После реализации — Architect делает `git diff HEAD~1` и пишет review здесь
