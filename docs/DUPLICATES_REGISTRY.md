# 🧬 Реестр дублей (Duplicates Registry)

> **Принцип:** где КОПИЯ = дрейф = баг. Один канал/калькулятор, различия = параметры.
> (`principle_reuse_not_duplication`). Этот реестр — каталог известных дублирующих
> вычислений/кодовых баз. Цель: запоминать их и **выкидывать потихоньку** — стягивать
> множество копий в один источник истины (централизация → Куб → Сингулярность).

**Как вести:** при обнаружении дубля (одна формула/логика в 2+ местах) — внести строку.
При устранении — статус `✅ устранён` + дата + как. Перед новым модулем — свериться: не плодим ли копию?

**Статусы:** ✅ устранён · 🟡 активен-баг (выкинуть) · 🟢 намеренный (НЕ трогать) · ⚪ принцип
**Колонки:** 🟢 ЭТАЛОН = источник истины (правильный, на него унифицируем) · 🔴 ДУБЛЬ = копия (заменить вызовом эталона) · «Кормит» = кто потребляет (blast radius — проверяем «кто кого кормит»)

| # | Дубль | 🟢 ЭТАЛОН (истина) | 🔴 ДУБЛЬ (на унификацию) | Кормит (потребители) | Статус |
|---|---|---|---|---|---|
| D-01 | OTE-импульс | **`ote_retest_setups`** (zigzag 11/3, `smc_engine.py`, калиброван OKO-SM, ТОРГУЕТ) | `smc_snapshot.py` detect_structure period=5 | ML(outcome_predictor, mtf_smc_specialist) · narrative · trade_simulator(features) · дашборд | ✅ **устранён 11.06** — дубль теперь зовёт эталон. Замер 71.46%=эталон |
| D-02 | Два набора SMC-детекторов (FVG/OB/structure) | **TBD — определить!** (smc_engine «чарт/бэктест» ∥ core.smc «торгует через snapshot»). Замер: FVG 69% parity, regime 13% дрейф | TBD после определения эталона | бот торгует от `core.smc`→snapshot→магниты; чарт/бэктест от `smc_engine` | 🟡 **высокий** — сначала определить КТО эталон |
| D-03 | Combinator ∥ Bus-сферы (признаки) | **combinator** (заморожен, эталон паттернов/snapshot/ML) | сферы Bus — вариант B | ML train=stored ← combinator; live-сигналы ← сферы | 🟡 переходный мост до ARCH-117 |
| D-06 | WT-зона/cross/div (формула идентична 0.0) | **`indicators.py`** (canonical WT) + **combinator_v2** (cross-в-зоне, −60, ДО кросса = семантически верный) | scan_loop(сырой) · signal_checkers(adaptive) · htf_detectors · funding_detector(−40) — **4 порога** | детекторы читают wt_snap; arch104←combinator | 🟡 частично — WTService Сфера-14 ph1+2. Унифицировать порог + 1 div-алгоритм |
| D-07 | RSI-расчёт | **ДВА эталона (намеренно):** combinator-SMA = паттерны/ML; RSIService-Wilder = live | ~~ml_predictor-SMA~~ (был лишний 3-й) | combinator→паттерны/snapshot; RSIService→live | 🟢 раздельны ОСОЗНАННО; ml_predictor ✅ удалён |
| D-08 | trend-расчёт | **ДВА эталона (намеренно):** combinator-EWM = ML; calculate_trend-Pine = live (85% совпад.) | — | combinator↔ML; сферы↔live | 🟢 раздельны ОСОЗНАННО (ph3) |
| D-09 | extended_indicators.py (wt2 EWM≠SMA) | `indicators.py` (SMA-4) | удалённый extended_indicators (EWM) | никто (был мёртвый код) | ✅ **удалён** (ffd88c8) |
| D-04 | main ∥ sub аккаунты | единый канал (account=параметр) | клон main→sub | — | ⚪ принцип ARCH-96-HUB |
| D-05 | Документация ∥ код | config.yaml/код | числа в docs/DISCUSSION | агенты читают docs | ⚪ правило «config first» |

> **🔑 Различай баг vs намеренный:** D-07/D-08 — **два эталона для разных доменов** (combinator↔паттерны/ML заморожен ∥ сферы↔live), НЕ дубль-баг. Инвариант «один калькулятор» **релаксирован** (ph3, 31.05). **НЕ unify D-07/D-08** — сломает паттерны DEV-235-масштаба.

> **📌 Следующий шаг (юзер): «кто кого кормит»** — трассировать data flow для каждого активного дубля (D-02 первый): какой источник реально питает торговые решения vs отображение. Определить эталон D-02 → потом унифицировать.

| D-10 | **regime-классификация** | 🟢 **`classify_v2`** (HTF-доминанта, лучше разделяет edge 0.798 vs 0.552 — [[regime_v2_validated]]) → публиковать в `pair_context.regime` (Bus) как ЕДИНЫЙ источник | 🔴 **3 метода в 6+ местах:** `classify_from_ohlcv` (старый ADX — scan_loop:234 HIGH_VOL gate!, 848, monitoring:703/721) · `classify_from_dataframes` (v1 MTF мислейбл — scan_loop:1369) · `classify_mode` (REVERSAL) | гейты входа (HIGH_VOL/RANGE/sideways) ← scan_loop сам классифицирует (НЕ Bus); monitoring ✅ читает Bus; trade_simulator пишет (за `use_v2`) | 🟡 **НАЙДЕН 11.06.** `use_v2` флаг меняет ТОЛЬКО trade_simulator → активация неполна (гейты на старом ADX). Унифицировать: все точки → читают `pair_context.regime` из Bus, Bus публикует classify_v2. ЗАДАЧА REGIME-V2 |

> **⚠️ ADX НЕ архивируется (уточнение 11.06):** эталон `classify_v2` САМ использует ADX (+ATR); v1 (`classify_from_dataframes`) ADX выкинул, **v2 его ВЕРНУЛ**. `compute_adx` (`indicators.py:437`, единый источник) кормит v2 + `classify_mode` (REVERSAL). Архив-кандидат — **только обёртка** `classify_from_ohlcv` (метод ADX+EMA→метка), и то на Этапе 5. Потребители (11.06): `trade_router:469`, `trade_simulator:1023` shadow, `monitoring:703/721` (BTC-global, не per-pair), `scan_loop:243/863` (теперь fallback после Этапа 1). Паттерн D-07/D-08: индикатор остаётся, дублирующая обёртка уходит.

---

## ⚠️ Калибровочные рассогласования (параметр, не код-дубль — но та же нить дрейфа)

| # | Параметр | 🟢 ЭТАЛОН | 🔴 РАССОГЛАСОВАН | Кормит | Статус |
|---|---|---|---|---|---|
| **C-01** | **CHoCH/SMC `length`** в `detect_structure_breaks` | **length=5** (OKO-SM, в `chart_builder`/`ote_signal_generator`/scripts — визуально подтверждён) | **length=50** (DEFAULT в `swing_bridge` ×3 — `etl_order_blocks`, `etl_bos_choch`, `etl_ote_premium`) | **combinator → 187 DS-паттернов · ML feature_snapshot · arch104_observer (ТОРГУЕТ) · scan_loop** | 🔴 **НАЙДЕН 11.06** |

**Замер слепоты (XLM, `scripts/choch_length_check.py`):** length=50 → **5m/15m = 0 CHoCH** (полная слепота!), 1h = 1 CHoCH лаг **202 бара**, 4h лаг 82. length=5 → 12-15 свежих CHoCH (лаг 2-51). arch104 торгует на **15m → видит 0 сломов**.

**Что отравлено слепым length=50** (через `swing_bridge`): 🔴 Order Blocks · BOS · CHoCH · OTE-premium/discount (`find_choch_ote` от слепых breaks). **Чисто:** FVG, FVG-overlap, Elliott (своя логика/zigzag).

**Корень ОДИН:** `detect_structure_breaks(length: int = 50)` дефолт не переопределён в `swing_bridge`. Фикс = **1 строка** (`length=5`, config `choch_length_ltf:5`) чинит OB+BOS+CHoCH+premium разом.
**⚠️ НО:** DS-паттерны МАЙНИЛИСЬ на length=50 → факторы сдвинутся → **нужен ре-майнинг** (train↔live консистентность).

**📊 BLAST ЗАМЕРЕН (11.06):** **69 из 200 паттернов (34%)** имеют ≥1 слепой фактор (`ob`/`discount`/`premium`). **131 (65%) — ЧИСТЫЕ** (FVG-ядро/pivot/ema/atr/rsi/div). Факторный состав: FVG **257** (доминанта, чист), pivot 85, atr 36 (чист), **ob 36 + discount 40 = слепые**, rsi 28, **WT всего 1** (почти не майнили), choch/bos — **НЕ в факторах**. Гипотеза «слепой choch-гейт → частые входы» **СНЯТА** (arch104_observer не использует choch). Частота скорее от объёма (200 паттернов) + 34% на слепой структуре. Фикс length=5 чинит эти 34%, ре-майнинг только им.

**Связь:** [[calib_choch_length5]] (правило length=5 зафиксировано, но в swing_bridge НЕ применено) · [[bug_ote_impulse_period5]] (та же болезнь свингов) · [[arch124_regime_audit]] (RANGE-мислейбл — v2 подтвердил RANGE≈тренды).

## Метод устранения (по D-01, эталонный)
1. **Найти оба пути** (grep формулы/поля в проекте)
2. **Определить ЭТАЛОН** — какой источник «правильный» (откалиброван/торгует). У D-01: zigzag (метод пользователя, ARCH-128)
3. **Проверить кто кормит/читает дубль** (grep) — blast radius (D-01: ML/narrative/sim — но фича, не решение → безопасно)
4. **🗄️ Архивировать дубль** — старый код в `archive/duplicates/D-NN_*.py` (НЕ удалять безвозвратно, «пусть отдохнёт»)
5. **Унифицировать** — заменить дубль вызовом эталона (D-01: snapshot → `ote_retest_setups`)
6. **Сверить** замером (D-01: snapshot 71.46% = эталон 72%)
7. **Записать** в реестр `✅ устранён` + ссылка на архивный файл

**Архив дублей:** `archive/duplicates/` — выведенный код спит там (помечен, читаем, готов вернуться).
Реализация бережного отношения к проделанной работе: ничего ценного не теряем.
- D-01 → [`archive/duplicates/D-01_smc_snapshot_ote_period5.py`](../archive/duplicates/D-01_smc_snapshot_ote_period5.py)

## Связи
- Закон: `principle_reuse_not_duplication`
- Vision: `vision_cube_tesseract_singularity` (каждое стягивание копий → шаг к Сингулярности)
- Инструмент находки: дашборд-сверка (D-01 найден сверкой вотчлиста с живым OKO-SM)
