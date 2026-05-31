# ARCH-118 — Единый снимок признаков: РЕШЕНИЕ (зафиксировано 30.05.2026)

> 🔴🔴 Высший уровень важности. Читать ПЕРЕД любой работой с features_json / combinator / ML / re-mining.
> Полная история темы тянется с 02.04.2026 (TR-007 n=1401, DEV-126 — 53% сделок без полей).

## Корень проблемы
Бэктест (`combinator`) и live (детекторы) считали признаки РАЗНЫМИ источниками → метрики
паттернов самоподтверждались. Golden-паттерн (WR=100%) = иллюзия сломанной дивергенции
(DEV-235: L1_golden_LTF_5m 97%→44.7%). Аудит: 170 уникальных ключей, каждый signal_type
пишет свой набор (36 vs 129), только 16 CORE-полей универсальны.

## Решение хранения (на реальных данных, 15539 сделок, SQLite 3.45.3 JSON1)

**Отдельная таблица `trade_features` (FK) + вложенный JSON по доменам + sparse-булевы + generated-колонки.**

- Dense JSON 770 = 207 MB (×8) ❌ → **sparse (только true) = 22 MB** ✅. False восстанавливается из версионированной схемы.
- `json_extract` full-scan = ~130 ms на 15.5K (с generated columns + индексом → ~0). Спор «вложенный vs queryability» — ложный.
- Плоская таблица 770 колонок отвергнута (ALTER на индикатор, потолок 2000 колонок, не ложится на Куб).
- Pivot 490 булевых → свёртка `nearest_level + distance_pct + relation`.
- Схема: `{meta(16 CORE), context:{wt,rsi,smc,pivot,trend}, signal:{pattern_id,confirmations[]}}` + `schema_version=2`.

Детали и цифры: `docs/FEATURES_JSON_AUDIT.md` → «РЕШЕНИЕ (зафиксировано)».

## Связь с Кубом Метатрона
Снимок = **persistence-проекция центральной сферы** (`PairFullState`). Домены ⟷ `*_snap` шины 1:1.
`trade_features` = архивный слой Куба (НЕ сфера). Bus = runtime. Замыкает feedback loop Сферы 11.
Маппинг доменов: `docs/ENCYCLOPEDIA.md` → «ИНВАРИАНТ ВЫСШЕГО УРОВНЯ».

## 🔴 ИНВАРИАНТ «ОДИН КАЛЬКУЛЯТОР» (не нарушать)
`combinator.compute_flags()` и сферы, питающие Bus, используют ОДНУ формулу на признак.
- Вариант B (combinator одним кодом live+бэктест) = parity по определению, переходный мост.
- После ARCH-117: `compute_flags()` вызывает те же сферы, что Bus → снимок из combinator ≡ из Bus.
- **ЗАПРЕТ:** два независимых пути расчёта одного признака. Второй калькулятор ДОЛЖЕН вызывать
  первый, а не дублировать. Дублирование = возврат корня самоподтверждения.

## Реализация (Шаги 1-4 готовы, 30.05)
- **Шаг 1:** `core/intelligence/feature_snapshot.py` — `snapshot_features` + `snapshot_to_vector`.
- **Шаг 2:** live shadow — `build_df_by_tf` + блок в `register_trade_async`. config `arch118.shadow_enabled`.
- **Шаг 3:** сверка parity → вариант B НЕ даёт parity сам по себе. 2 источника (только HTF): глубина + выравнивание.
- **Шаг 4 — PARITY ДОСТИГНУТ (0 расхождений, рой 7/7):**
  - КАНОН выравнивания = **independent-last** (рой 5/7): `snapshot_features_at(df_by_tf, entry_ts, closed_only=True)` — последняя ЗАКРЫТАЯ свеча каждого TF (trade-time, без lookahead). Заменяет reindex+shift ДЛЯ СНИМКА. combinator-matching паттернов остаётся reindex+shift (отдельный слой!).
  - **HTFHistoryCache** (рой 7/7): кэш глубокого 1h ≥4320 баров (3×1440 пагинация, BingX max 1440, TTL 1800с). 4h/1d=resample(deep 1h). Замер: @300→48 расхождений, @4000→0.
  - bit-identity > freshness (рой 7/7): `closed_only` исключает формирующуюся свечу.

## Шаг 5 — ЗАВЕРШЁН (ARCH-118 закрыт, 31.05)
- **5a свёртка pivot (рой 6/7 вариант B):** combinator.add_pivot_flags + 3 числовых на TF
  (`pivot_nearest/dist_pct/relation_{1D|1W}`) ПАРАЛЛЕЛЬНО 70 булевым (один калькулятор).
  Снимок (`_pack_context`) пишет value-колонки значением. 187 паттернов целы (0 ссылок на числовые).
- **5b таблица trade_features:** `subscription_manager` CREATE TABLE (trade_id PK=FK,
  schema_version/source/entry_tf top-level+индекс, features_json вложенный). `_write_trade_features`
  после register_trade. config `arch118.write_table:true` (prod, features_json не дублируется).
  data-era граница (backfill невозможен).

## Статус: ARCH-118 ЗАВЕРШЁН (коммиты b1fe5d8→97918ce)
Единый parity-консистентный снимок (211 булевых + числовые pivot + глубокий HTF, live≡backtest)
в `trade_features`. Готов для ML/re-mining на чистых данных. Долг: вынести compute_flags в core/
без import-side-effects ([[arch117_wt_audit]] ph3).
