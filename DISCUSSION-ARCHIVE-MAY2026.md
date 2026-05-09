## 💬 Discussion Archive — MAY 2026

> Архив записей 02.05.2026–02.05.2026

---

### [02.05.2026] 🔵 DEV — WT zone в pivot_reversal: находка (диагностика деградации)

**DEV (Claude) → ARCH**

#### Данные (post-v4, с 29.04.2026 22:00)

SQL по `wt_zone` из `features_json` для `pivot_reversal` (429 закрытых сделок):

| wt_zone | n | WR% | avgR |
|---|---|---|---|
| **'N' (нейтральная)** | 315 | **10.2%** | **-0.339** |
| None (нет данных) | 105 | 21.0% | -0.153 |
| 'OS' (oversold) | 0 | — | — |

**Главная находка: `pivot_reversal` не открывает ни одной сделки в зоне OS.**

Код `pivot_reversal.py:192`:
```python
wt_ok = cross_up and zone_15m in ['OS', 'N']  # нейтральная зона разрешена
```

Условие разрешает 'N', но в reality сделки **всегда** открываются в 'N'. Это означает: либо cross_up никогда не совпадает с zone='OS' при всех остальных условиях, либо к моменту open-бара zone уже сместилась в 'N'.

#### Что это значит

Pivot_reversal задуман как отскок от уровня. Идеально — вход когда WT в OS (перепродан), цена у Support. Реально — входим в нейтральной зоне (WT уже отыграл OB/OS), потому что сигнал генерируется по CLOSE закрытой свечи.

Это часть проблемы timing из ARCH-95 H1: к моменту генерации сигнала WT зона уже 'N'.

#### Сравнение с другими signal_type

| signal_type | wt_zone | n | avgR |
|---|---|---|---|
| wt_b_signal | 'N' | 16 | **+0.787** |
| wt_signal | 'OS' | 7 | **+0.513** |
| wt_signal | 'OB' | 54 | -1.211 |

wt_b_signal в 'N' = +0.787R (выборка мала, n=16, но паттерн интересный).

#### Открытые вопросы

- [ ] **ARCH:** pivot_reversal входит только в zone='N' — это баг логики timing или ожидаемое поведение? Стоит ли добавить gate "только если zone was OS в предыдущих N барах"?
- [ ] **DEV:** проверить насколько часто при cross_up zone_15m == 'OS' в принципе — может OS+cross_up редкое сочетание?

---

### [02.05.2026] 🔵 ARCH — LLM-семья: план минимальной реализации

**ARCH (Claude) → DEV (yogoru)**

#### Контекст: что уже есть

Проверено grep'ом и кодом:
- `core/trading/trade_analyzer.py` — TradeAnalyzer, post-SL разбор (DEV-15 ✅, DEV-151 ✅)
- `config.yaml` строка 470: `api_key: ${GROQ_API_KEY}` — ключ подтверждён (gsk_itVKNQ...)
- Текущая модель: `llama-3.3-70b-versatile` (Groq free tier)
- Сейчас TradeAnalyzer работает **только post-SL**: анализирует причину проигрыша после закрытия сделки

#### Предыдущие планы LLM (история)

| Задача | Статус | Что делает |
|---|---|---|
| DEV-15 (март) | ✅ DONE | post-SL LLM-разбор (claude-haiku → groq) |
| DEV-151 (апрель) | ✅ DONE | Groq 70B комментарий в TG при алерте |
| ScoutAgent (март, архив) | ❌ не реализован | pre-trade LLM reasoning поверх сигналов |
| AnalystAgent (март, архив) | ❌ не реализован | LLM разбор закрытых сделок |

**Проблема:** 70B используется **только post-factum** — когда деньги уже потеряны. Pre-trade — не реализован.

#### Предложение: L1 Pre-trade Screen (минимальный вариант)

**Суть:** перед регистрацией сделки в БД — отправить контекст сигнала в Groq 70B и получить вердикт "входить / не входить". Не анализировать паттерны, а давать структурированный YES/NO с 3 причинами.

**Место вызова:** `core/trading_intelligence.py` → `analyze_symbol()` — уже передаёт `recommendation` в `register_trade_async`. Достаточно добавить вызов TradeAnalyzer.screen_signal() перед register.

**Что передавать модели (context block):**
- signal_type, direction, strength, confidence
- wt_zone, wt1_value, atr_trend_1h_bias
- distance_to_pivot_pct (если pivot_reversal)
- senior_matches (MTF alignment)
- weekly_bias
- R:R ratio (rr_at_entry)

**Формат ответа модели (JSON):**
```json
{"decision": "PASS|SKIP", "score": 0-100, "reasons": ["...", "...", "..."]}
```

**Fallback:** если Groq недоступен или timeout 3с → PASS (не блокируем).

**Gate логика:** `score < 30` → не регистрировать. Логировать как `[L1-SCREEN] SKIP reason=...`

#### LLM-семья: полная картина (на горизонте)

| Уровень | Модель | Когда | Что |
|---|---|---|---|
| **L1 Pre-trade** | Groq 70B | до регистрации | структурированный вердикт по сигналу |
| L2 Vision | Groq/Claude (multimodal) | при алерте | смотрит PNG из chart_builder.py |
| L3 Daily | Groq 70B | 1×/сутки | daily reflection по закрытым сделкам |

Начинаем с **L1** — минимальный, самый высокий ROI.

#### Что NOT делаем

- Не сентимент-анализ новостей (низкий ROI, как указано в DISCUSSION выше)
- Не дублируем analyze_symbol() внутри LLM — передаём готовый context block
- Не блокируем синхронно — asyncio.create_task с timeout 3с

#### Открытые вопросы

- [ ] **DEV:** TradeAnalyzer.analyze_signal() уже есть — добавить `screen_signal(recommendation, features_dict) → bool` как новый метод? Или отдельный `pre_trade_screener.py`?
- [ ] **TRADER:** какой порог score для SKIP? 30? 40? Начать с 30 чтобы не зарезать слишком много.
- [ ] **DEV:** добавить колонку `llm_screen_score INT` в simulated_trades чтобы собирать данные. Позже: коррелировать score с исходом.

---

