---
name: last-sessions-2026-05-27-30
description: "Сводка по сессиям 27-30 мая 2026 — WS Phase A/B fix, ARCH-117/120/122/123, DEV-233-236 div+wt_cross fixes, ретробэктест golden просел"
metadata: 
  node_type: memory
  type: project
  originSessionId: fbe5c409-c90c-478e-b237-4c14ab7b0867
---

# Сессии 27-30 мая 2026 — что сделано

Источник: git log + TASKS.md. Хронологически.

## 🔧 27.05 вечер — WS Phase A/B fix (D-073-FOLLOWUP)

**Контекст:** BingX DEGRADED/DOWN, бот ловил каскады:
- 142 `sync_time failed` за 50 мин (force=True без throttle при свежем фейле)
- 463 WS errors за один scan-цикл
- WsFeed restart events периодически

**Правки (сессия 27.05 ~22:00):**

→ `core/exchange/bingx_client.py:120-131` — `sync_time` throttle для `force=True` при СВЕЖЕМ ФЕЙЛЕ (`_time_synced=False, <30с`). Разрывает каскад "109400 → force sync → 15с timeout → retry → force → ...".

→ `core/infra/ws_feed.py:30-81` + `config.yaml:performance.ws_*` — все хардкоды (batch_size, start_delay, reconnect_base, ohlcv_error_pause) выведены в config. **Новые дефолты (снижены под deg BingX):** `ws_ticker_batch_size: 75` (было 100, 4 батча вместо 3), `ws_ohlcv_batch_size: 80` (было 120), `ws_batch_start_delay_sec: 5.0` (было 2).

**Результаты 1ч наблюдения (DEGRADED-DOWN-DEGRADED биржа):**

| Метрика | До | После |
|---|---|---|
| WS errors за цикл | 463 | **0 за час** |
| sync_time failed | ~170/час | 11/час (−94%) |
| WsFeed restart | периодически | **0 за час** |
| force throttled | — | 12/час (правка работает) |
| Recovery из DOWN | блокировал | **6 мин без вмешательства** |

**НЕ лечено (известные проблемы):**
- `/api/stats` 4.98s сейчас, может зависать под нагрузкой → **DEV-231** (см. ниже)
- `update_priority_pairs` no-op (D-073 rollback) → ждёт D-072 data_service

## ⚠️ 27.05 — независимый коммит aab2e68 (НЕ конфликтует с моим)

`aab2e68 fix(time-sync): чаще ресинк + force=True bypass throttle` — добавил параметр `force=True` в `sync_time()`, mотивация Windows clock drift 1с/мин, recvWindow=5000ms.

**Моя последующая правка ДОПОЛНИЛА:** force обходит throttle на здоровом BingX (`_time_synced=True`), но НЕ обходит при свежем failed sync (моя защита от каскада). Логика комплементарна.

## 🚀 28-30.05 — крупный ARCH-рефакторинг

### ARCH-117 ✅ Phase 1+2 готовы (30.05)

**Корень:** WT-формула в 7+ файлах, производные (cross/div/zone) считаются каждым потребителем по-своему.

→ `core/intelligence/wt_service.py` — **WTService** единый источник: `wt_cross` (сырой, обр.совместимость), `cross_in_zone` (строгий combinator-стиль), `zone` (±60). 17 тестов ✅, в бою healthy. scan_loop → `build_wt_snap()`.
→ `core/intelligence/rsi_service.py` — **RSIService** на каноне `compute_rsi` (Wilder RMA). 9 тестов ✅.
→ Удалён `extended_indicators.py` (коммит ffd88c8) → wt2 EWM≠SMA фикс **moot**.
→ `ml_predictor._calculate_rsi` (SMA-дубль) удалён.
→ `chart_builder._calculate_wt` → `indicators.calculate_wt`.

### ARCH-118 🟡 Standartisation features_json — Вариант B принят (30.05)

**Корень самоподтверждения golden:** бэктест и live считали признаки разными источниками.
**Решение B:** `combinator.compute_flags(df)` вызывается ОДНИМ кодом в live (при входе сделки) и в бэктесте → live=backtest parity по определению.
План: `snapshot_features(df_by_tf, entry_idx) → dict` + вызов в register_trade + бэктест-движках + запись ~211 флагов в features_json.

### ARCH-120 SMC Sub-куб Phase 1 (2fd6cef, 30.05)
Единый вход + liquidity в snapshot. Первый фрактальный куб.

### ARCH-122 TPSelector магниты из Bus (47b712e+4bdaaa3, 30.05)
tp2 из TPSelector магнитов (не из pivot). Часть 1a + Часть 2.

### ARCH-123 PivotSphere Сфера 8 Phase 1 (f7ce4fe, 30.05)
Singleton-обёртка + fibonacci_equiv. **Переименован из ARCH-118** (коллизия с features_json).

## 🐛 28-30.05 — критичные багфиксы

### DEV-233 ✅ RSI-дивергенции pivot-based (cb5c5b1, 30.05)
Был **lookahead в дивергенциях.** Переписано на LonesomeTheBlue (pivot-к-пивоту + dontconfirm для live-ветки). bull_div/bear_div=regular, rsi_div_*_hidden.

### DEV-234 ✅ wt_cross в OS/OB (cb5c5b1, 30.05)
**combinator считал кросс НУЛЯ** (с создания!), а основной бот (confluence_scanner / mtf_checker / WT_X) — кросс wt1×wt2 в зоне OS/OB. Фикс: +wt2=SMA4, кросс в зоне ±60 (config). Частота упала с **50-80 (кросс нуля) до 4-8/пара (реальный entry).**
**Затрагивает D-051 gate + T8-паттерны.**

### DEV-235 ✅ Ретробэктест n=88 на исправленном combinator (420dc43, 30.05)
**Старые метрики LONG-golden были завышены ложными div.** Итоги:
- L1_golden просел **+1.89 → +0.46**
- L1_golden_scale_1h **+6.07 → +0.47**
- SHORT (S1-S8) устойчивы — без изменений
- Перевернулось в минус только 4 паттерна
- Осталось сильными 52

CSV: `tmp_charts/dev235_retrobacktest.csv`.

### DEV-236 ✅ Изоляция 28 паттернов (a6cfa39, 30.05)
Registry +поле `enabled`, фильтр в `find_matching` + `htf_gate_open`. YAML: 28 паттернов с div/cross-якорем и деградацией ≥0.5R изолированы. **215 → 187 активных** (golden×7, T4_L div×8, T2_L div×4, T2L_L_L1×6 и др.).
Рестарт PID 8340: decisions 21→6, **golden в decisions=0**.

## 📋 28-29.05 — задачи по WS/scan

### DEV-226 ✅ pre-filter мёртвая зона (c8974c8)
WS pre-filter в trade_simulator делал `continue` для сделок с `tsl_activated=0` далеко от SL/TP. Фикс: early-profit check (`R≥0.3` по _ws_price).

### DEV-227 ✅ TSL при R>1 + stale-кэш OHLCV (c8974c8)
TSL-активация по `R>1` (вместо TSL_act_R). Stale OHLCV кэш force REST когда df.close протух.

### DEV-228 🔍 Расследование stale OHLCV завершено
Первопричина = **нестабильность ccxt.pro watch_ohlcv на BingX** (1 instance×80 пар, `SLOW await 64-92s`×110, 560 errors, залипание batch'а). НЕ баг кода — ограничение WS. Вердикт: force REST (DEV-227) = изолятор; WS = best-effort. Долгосрочно D-072 (data_service).

### DEV-230 🔄 WS kill-switch (тест-откат)
**Диагноз:** 5 ccxt.pro WS на одном event loop забивают loop (`SLOW await 64-92s`, scan ohlcv 76-96s, 339×DEGRADED 0×recover). Сеть BingX ок (ccxt из отд. процесса быстр).
Фикс: `config performance.ws_enabled: false` + ранний return в `_start_ws_feed`. REST-only. Нужен рестарт.

### DEV-231 🟡 ИЗВЕСТНАЯ ПРОБЛЕМА — дашборд timeout >10с
`_handle_dashboard_api` → `full_stats()` тяжёлый (агрегаты + open_trades обогащение). Профилировать, кэшировать тяжёлые агрегаты (TTL 10-30с) или вынести в фоновый расчёт. **Это та проблема, которую мы видели в моей сессии 27.05** (JSONDecodeError на snapshots под DEGRADED). Текущее: `/api/stats` 4.98s в норме, под нагрузкой может зависать.

### DEV-232 ✅ HTF-gate + кэш HTF для 5m (7433f33, 30.05)
Observer фетчил 5m для всех 242 пар → цикл 1020-3168с. Реализовано: `registry.htf_gate_open()` + HTF first → gate → 5m только если все HTF-anchors активны + кэш HTF-флагов (TTL 1800с).
Лог: `[DEV-232 gate: ltf_fetched=N htf_only=M]`. Нужен рестарт.

### DEV-224 ✅ TPSelector ВКЛ + confluence ВЫКЛ (f489a98, 30.05)
По shadow A/B (n=610). Pivot SHORT уже HARD через DEV-188.

## 🗂️ Прочее

- `0c73f9e` ARCH-104 рестарт 27.05 19:27 UTC — D-073 patch активен
- `b5f3331` position_sync: убран статус EXPIRED — реклассификация по P&L
- `8b06008` стандартизация нейминга дивергенций
- `f7ce4fe` ARCH-123 = ARCH-118 (переименование из-за коллизии с features_json)

## ⚠️ Что НЕ сделано из обсуждённого 27.05

- ❌ Шаг C (exponential pause после OHLCV error) — не делали, мониторинг показал что не нужно
- ❌ /api/stats wait_for / адаптивный TTL — пользователь обосновано назвал пластырем, отдельная DEV-231

## 📌 Текущее состояние (30.05 12:00 UTC)

- BingX: latency 4-5с (DEGRADED-зона), но handler-чейн стабилен
- Dashboard `/api/stats`: HTTP 200, 478KB, 4.98s — работает но медленно
- Бот живёт, 117+ open trades
- WS errors стабильно низкие
- Активные эпики: ARCH-117 ph3 (RSI live-консьюмеры), ARCH-118 (features_json snapshot), ARCH-120/122/123 (sub-cubes)
- 187 активных паттернов (после DEV-236 изоляции 28 из 215)
