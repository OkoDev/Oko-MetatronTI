# What's Next — Handoff Document

> Последнее обновление: **2026-05-30 ~07:30 UTC** (Агент: Developer/Opus 4.8).

---

## 🎯 ПРОДОЛЖЕНИЕ 30.05 (часть 2): ARCH-118 подготовка + нейминг

### ✅ Сделано (часть 2)
- **Коммиты в main** собраны (5 целевых + ARCH-118): TSL/stale, WS/observer, дивергенции, изоляция golden, аудит, нейминг. main ahead origin ~210 (push НЕ делал).
- **ARCH-118 аудит features_json** (`docs/FEATURES_JSON_AUDIT.md`): 170 ключей в БД, каждый signal_type пишет свой набор (36 vs 129) — нет единого снимка. Только 16 CORE-полей универсальны.
- **Удалён мёртвый `extended_indicators.py`** (429 строк: Bollinger/Ichimoku/MACD/Stoch/VWAP/MFI — никто не импортировал). ADX НЕ затронут (живёт в indicators.py, market_regime).
- **Реальный индикаторный каталог:** combinator (47 индикаторных + 35 pivot базовых) + indicators.py (15 числовых). Снимок ~770 признаков.
- **Стандартизация нейминга дивергенций** (вариант A): `bull_div→rsi_div_bull_regular`, `wt_div_*_reg→wt_div_*_regular`. Синхронно combinator + 64 паттерна YAML. End-to-end OK, рестарт применён.
- **Вердикт роя по ARCH-118** (5 моделей): вложенный JSON {meta, context:{wt,rsi,smc,trend,pivot}, signal}, сбор на входе, версионирование, свёртка pivot. **Решение: вариант B** — снимок = combinator.compute_flags() одним кодом в live+бэктест → parity ПО ОПРЕДЕЛЕНИЮ.

### ✅ Спор хранения ЗАКРЫТ (30.05, на реальных данных 15539 сделок) — ВЫСШИЙ УРОВЕНЬ
Вердикт: **отдельная таблица `trade_features`(FK) + вложенный JSON по доменам + sparse-булевы + generated-колонки**. Цифры: dense 770=207MB ❌→ sparse=22MB ✅. Pivot→свёртка. schema_version=2.
Ложится на Куб = persistence-проекция `PairFullState`, замыкает feedback loop Сферы 11.
🔴 **ИНВАРИАНТ «ОДИН КАЛЬКУЛЯТОР»** (combinator≡Bus, одна формула).
→ `memory/arch118_snapshot_decision.md` · `docs/FEATURES_JSON_AUDIT.md` РЕШЕНИЕ · `docs/ENCYCLOPEDIA.md` ИНВАРИАНТ.

### ⏭️ ARCH-118 реализация `snapshot_features` (вариант B) — В РАБОТЕ
1. **✅ ШАГ 1 ГОТОВ** — `core/intelligence/feature_snapshot.py`: чистая функция `snapshot_features(df_by_tf, entry_tf, signal) → dict` + декодер `snapshot_to_vector`. Импортирует ЕДИНЫЙ `combinator_v2.compute_flags` (инвариант). Проверено на реальных данных: **211 флагов**, sparse JSON **1160 B/сделка** (~18 MB на 15539), декодер консистентен. Фикс: `_import_compute_flags` делает `detach()` combinator-wrapper'а (combinator_v2 строка 21 переопределяет sys.stdout → закрывал buffer).
2. **✅ ШАГ 2 ГОТОВ** — live shadow. `feature_snapshot.build_df_by_tf(dc, symbol)` (тот же способ, что arch104 observer: fetch 1h/15m/4h + 1d=aggregate_tf(1h), parity). Shadow-блок в `register_trade_async` ПЕРЕД `register_trade` (строка ~1174, после гейтов) → пишет `features_json.arch118_snapshot`. Config `arch118.shadow_enabled: true`. Не влияет на входы. Проверено end-to-end (mock dc): 258 флагов, sparse 1358 B. **Требует рестарт бота.**
   - ⚠️ Parity-наблюдение: 1d=aggregate(df_1h@300)→~12 баров, ema200_1d неточна — но идентично live observer. Сверить в Шаге 3 (live vs бэктест с полной историей).
3. **✅ ШАГ 3 ГОТОВ** — бэктест-путь + СВЕРКА parity. `snapshot_from_flags_row(flags_row)` (снимок из готовой combinator all_flags, та же упаковка `_pack_context` что live → parity упаковки по определению). Скрипт `scripts/arch118_parity_check.py`. **НАХОДКА (12 пар): вариант B НЕ даёт parity автоматически — 2 источника расхождения, ОБА только на HTF (1d/4h/1W); LTF 1h/15m/5m идеальны:**
   - **(2) ГЛУБИНА [приоритет 1, системно]:** live `build_df_by_tf` грузит 1h@300→1d≈13 баров → `ema200_1d`/`wt_ob_1d` недостоверны. `ema50_above/below_ema200_1d` расходится **10/12**, `wt_ob_1d` 10/12. Фикс: грузить HTF (4h/1d) с достаточной глубиной (нативный fetch 1d@300/4h@300 ИЛИ 1h@1500+). Бэктест на полной истории корректен → live должен догнать глубину.
   - **(1) ВЫРАВНИВАНИЕ [приоритет 2]:** backtest reindex+shift HTF на 1h-сетку (анти-lookahead) vs live independent iloc[-1] → расхождение на 1 HTF-период (`bear_mom_1d` 8/12, `vol_spike_4h` 8/12). Нужно выбрать КАНОНИЧЕСКИЙ метод (обсудить): independent-last семантичнее для live-входа, shift нужен в историческом бэктесте.
   - **Вывод:** ~12-15/211 флагов (только HTF) расходятся до фикса. Чинить в Шаге 4 ДО обучения ML (иначе модель учится на неконсистентных HTF-фичах).
4. ⏭️ ШАГ 4 — (a) ФИКС PARITY HTF: глубина + унификация выравнивания; (b) свёртка pivot 70→3 (nearest_level + distance_pct + relation).
5. ⏭️ ШАГ 5 — таблица `trade_features`(FK) + generated-колонки + переключение с shadow.
- **🔴 ДОЛГ:** вынести `compute_flags`+indicators в `core/` модуль БЕЗ import-side-effects (combinator_v2 = скрипт с sys.stdout hack + HISTORY_DIR). Нужно для чистого инварианта.
- Детали схемы: `docs/FEATURES_JSON_AUDIT.md`. ARCH-117 (сферы→Bus) = параллельный трек, слить позже.

### 🔧 Состояние бота (часть 2)
- PID 944 (рестарт 07:04), REST-only, registry 215 паттернов (187 enabled), нейминг применён, 0 ошибок.

---

## 🎯 Сессия 30.05 (часть 1): исправление дивергенций + ретробэктест + изоляция golden

### ✅ Закрыто за сессию
**Стабилизация потока данных:**
- **DEV-226/227** — TSL не активировался при R>1 (pre-filter мёртвая зона + stale-кэш). Фикс: early-profit check + force REST bypass.
- **DEV-230** — WS перегружал event loop (scan 76s→8s, health 339×DEGRADED→HEALTHY). Kill-switch `performance.ws_enabled: false` (REST-only).
- **DEV-232** — observer фетчил 5m для всех 242 пар (цикл 3168s→~350s). HTF-gate + кэш HTF (TTL 600).

**Дивергенции (корневой баг):**
- **DEV-233** — RSI-дивергенции → LonesomeTheBlue (пивоты по close + trendline + live-ветка).
- **DEV-233b** — WT-дивергенции → WT_X (фрактал на WT + low/high, БЕЗ trendline). RSI и WT = ДВА разных индикатора.
- **DEV-234** — wt_cross выровнен на wt1×wt2 в OS/OB (было: кросс нуля).
- Эталоны: `memory/reference_pine_divergence.md`. Чарты: `tmp_charts/trx_divergence.png`, `trx_wtx_div.png`.

**Ретробэктест + чистка:**
- **DEV-235** — 3 этапа (1h/5m/15m, 45-46 пар × 2.4г) на исправленном combinator. ВЕРДИКТ: re-mining НЕ нужен. Golden-семейство = иллюзия сломанной div (L1_golden_LTF_5m 97%→44.7%). Костяк (T2L/SHORT/pivot) — реальный edge. Скрипты: `retrobacktest_dev235.py`, `_ltf.py`. CSV в `tmp_charts/`.
- **DEV-236** — изолировано 28 паттернов (`enabled: false`). Registry: +поле enabled, фильтр в find_matching + htf_gate_open. 215→187 активных. Подтверждено в проде (decisions 21→6, golden=0).

### 📌 Следующие шаги (порядок роя, вариант A)
1. **Наблюдение** — дать боту неделю поторговать на чистом костяке (187 паттернов). Фаза 2 (доказать «+» на честных паттернах).
2. **ARCH-117** — WT/RSI как единые сферы Куба (устранить 7 копий формулы). `core/intelligence/wt_service.py` уже есть (заготовка).
3. **ARCH-118** — стандартизация features_json (единый снимок 211 флагов, live=бэктест). Устраняет самоподтверждение в корне.
4. **Потом** — ML/re-mining на чистых данных.

### ⚠️ Открытые задачи (TASKS)
- **DEV-231** 🟡 — дашборд `/api/dashboard` timeout >10с (full_stats тяжёлый к БД).
- **DEV-230-FU** ⏸ — постоянное решение по WS (REST-only / D-072 / урезанный).
- **TR-232a/b** — разбор T5_L_02 (+6.41R) и убытков (46% SL).

### 🔧 Состояние бота
- PID 14248 (рестарт 01:22), REST-only, observer на 242 парах, gate работает.
- health периодически DEGRADED 2.4-3.2s — фоновая деградация BingX REST (не event loop, известно).
- WS отключён (`ws_enabled: false`).

### 📂 Изменённые файлы (незакоммичено)
- `tools/pattern_mining/combinator_v2.py` (дивергенции + wt_cross)
- `core/confirmations/arch104_patterns.py` (enabled + htf_gate_open)
- `config/arch104_patterns.yaml` (28× enabled:false)
- `tools/pattern_mining/retrobacktest_dev235.py`, `_ltf.py` (новые)
- `bot/loops/arch104_observer_loop.py`, `bot/core/bot.py`, `config.yaml` (DEV-230/232)
- `core/trading/trade_simulator.py`, `core/infra/api_engine.py`, `core/infra/data_collector.py` (DEV-226/227)
- `memory/`: golden_pattern_invalidated.md, reference_pine_divergence.md, current_state.md
