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

### ⏭️ СЛЕДУЮЩИЙ ШАГ (ARCH-118 реализация, новая сессия)
**`snapshot_features` — прототип единого снимка (вариант B):**
1. `snapshot_features(df_by_tf, entry_idx) → dict` — обёртка над `compute_flags` для всех TF на момент входа.
2. Вызов в `register_trade` (live) + в бэктест-движках.
3. Запись ~211 флагов в features_json (вложенная схема {meta, context, signal} + schema_version=2).
4. Свёртка pivot → nearest_level + distance_pct + relation.
5. Сначала SHADOW (параллельно текущему features_json), потом переключение.
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
