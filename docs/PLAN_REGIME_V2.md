# 📋 PLAN REGIME-V2 — унификация regime-классификации (D-10) + активация v2

> **Статус:** запланировано 11.06.2026 · **Тип:** унификация дубля (D-10) + активация classify_v2
> **Реестр:** `docs/DUPLICATES_REGISTRY.md` → D-10 · **Память:** [[regime_v2_validated]], [[arch124_regime_audit]]

## 🎯 Цель
Сделать `pair_context.regime` (Bus) ЕДИНЫМ источником режима, публикуемым через `classify_v2`
(HTF-доминанта), и заставить `use_v2` флаг переключать **весь** поток (не только запись в БД).
Результат: гейты входа перестают мислейблить RANGE, перестают резать прибыльные RANGE-сделки.

## 🔴 Проблема (D-10, замерено 11.06)
regime классифицируется в **6+ местах, 3 методами**:
- `classify_from_ohlcv` (СТАРЫЙ ADX+EMA) — `scan_loop:234` **HIGH_VOL-gate!**, `:848`, `monitoring:703/721`
- `classify_from_dataframes` (v1 MTF, мислейбл-синхронность) — `scan_loop:1369`, `scan_handlers`
- `classify_v2` (HTF-доминанта, shadow за `use_v2`) — `trade_simulator:1033`
- `classify_mode` (REVERSAL) — `scan_loop:1390` (отдельная функция, НЕ трогаем)

**Bus-источник ЕСТЬ** (`pair_context.regime`, publish `scan_loop:1394`), `monitoring` его читает ✅.
Но `scan_loop` гейты классифицируют САМИ (старым ADX). `use_v2` → только `trade_simulator`.

**Данные (6992 сделок):** v2 разделяет edge лучше (разброс avgR **0.798 vs 0.552**); v1 валит 47% в RANGE; **RANGE-сделки ПРИБЫЛЬНЫ (0.971) → RANGE-гейты резали прибыль**.

## ⚠️ Главные риски
1. **Гейты сменят поведение:** HIGH_VOL-gate сейчас на старом ADX → станет v2-ATR (другой trigger). RANGE-гейты на v1 → v2 (RANGE реже).
2. **classify_v2 нужен 4h** (60 баров > atr_period). Bus pair_context должен иметь 4h на момент классификации.
3. **Меньше блокировок RANGE** = больше входов (RANGE прибыльна, но проверить что не шум).

---

## Этапы (каждый — gate-проверка + откат)

### Этап 0 — Baseline
- [ ] Зафиксировать текущие метрики гейтов: сколько входов блокирует HIGH_VOL-gate (scan_loop:235), RANGE-gate (375), sideways (1401) — за период
- [ ] Shadow `regime_v2` уже пишется с 02.06 (6992 сделок) → baseline сравнения есть
- **Gate:** baseline в `data/research/`

### Этап 1 — Унификация ЧТЕНИЯ (все точки → Bus)
- [x] ✅ (11.06) `scan_loop:234` (HIGH_VOL-gate) + `:848` (atr_change SHORT) → читают `bot.pair_context.get(symbol).regime` + fallback. `:1369` неверно — v1 classify в `trading_intelligence:2054/2142` (Этап 2).
- [x] ✅ Fallback на `classify_from_ohlcv` если Bus None (первый скан) — реализован
- [ ] ⚠️ `monitoring:703/721` = BTC-global режим (1h+4h, ARCH-63 market gate), НЕ per-pair → нельзя унифицировать на `pair_context.get(symbol)`. Вариант: BTC публикует MTF regime в Bus (отдельная под-задача). `scan_handlers` (UI) — низкий приоритет.
- [ ] `scan_handlers` (UI/чат) — оставить как есть ИЛИ Bus (низкий приоритет, не торговля)
- **Откат:** вернуть локальный classify
- **Gate:** все торговые гейты читают Bus; поведение идентично (Bus публикует тот же v1 пока)

### Этап 2 — Унификация ИСТОЧНИКА (Bus публикует classify_v2 за флагом)
- [x] ✅ (11.06) `scan_loop:1384` (источник publish): `use_v2=true` → `classify_v2(df_entry, df_1h, df_4h)`, иначе `classify_from_dataframes` (v1). df_4h собран 60 баров (`:1313`) = под atr_period v2. py_compile ✅.
- [x] ✅ Один вызов classify на пару за скан (DEV-108 точка, _pair_regime → publish REGIME_UPDATED)
- [ ] `trade_simulator:1023` shadow-логика — оставить (отдельный shadow regime_v2 для БД); унификация её чтения на Bus — Этап 5 (опционально)
- **Откат:** `use_v2=false` → Bus публикует v1 (текущее поведение, в бою с 11.06)
- **Gate:** `use_v2=true` → Bus.regime = v2 → Этап-1 гейты (`scan_loop:234/848`) видят v2 АВТОМАТИЧЕСКИ (корень D-10 решён: флаг теперь меняет весь поток, не только trade_simulator)

### Этап 3 — Shadow-замер (v1-gate vs v2-gate)
- [ ] При `use_v2=false`: логировать «что бы заблокировал v2-gate» vs «что блокирует v1-gate» (shadow-diff)
- [ ] Метрика: сколько RANGE-сделок v1 пропускал в гейт, а v2 бы пустил (и их avgR)
- **Gate:** оценить эффект ДО активации

### Этап 4 — A/B активация
- [ ] `use_v2=true` на части символов / периоде → сравнить win-rate/avgR входов v1-gate vs v2-gate
- [ ] Особо: RANGE-сделки (должны перестать ложно блокироваться), HIGH_VOL (v2-ATR vs старый-ADX)
- **Acceptance:** v2-gate не хуже v1-gate по avgR входов И раннеры целы → катим

### Этап 5 — Решение
- [ ] v2 ≥ v1 → `use_v2=true` постоянно, старые `classify_from_ohlcv`/`classify_from_dataframes` в торговых гейтах → архив (D-10 ✅ устранён)
- [ ] Записать в реестр D-10 результат

---

## Критерии успеха
1. Один источник regime (Bus `pair_context.regime`), все торговые гейты читают его
2. `use_v2` переключает реально весь поток
3. v2-гейты не хуже v1 по avgR входов, RANGE-сделки не теряются ложно
4. Дубль 3-метода-6-мест устранён (D-10)

## Граница зон (предлагаю)
- **DS (реализация):** Этапы 1-2 (унификация чтения на Bus + Bus публикует classify_v2 за флагом), Этап 3 shadow-diff лог, А/B прогон.
- **Даат/Claude:** план, валидация shadow/A/B, решение кат, держу реестр D-10.

## Связи / зависимости
- **Связано с HIGH-VOL-VOLUME:** v2 определяет HIGH_VOL по ATR (1.8×median); объёмное обогащение (рой) — поверх, ПОСЛЕ унификации.
- **НЕ трогать:** `classify_mode` (REVERSAL detection, отдельная функция, не regime-метка).
- Параллельно: C-01 (CHoCH length) — независимо.
- Инструмент A/B: shadow `regime_v2` уже в БД (9 дней данных).
