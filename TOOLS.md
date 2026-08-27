# 🧰 КАРТА ИНСТРУМЕНТОВ

> Читать при старте сессии — **до того**, как писать новый скрипт.
> Половина инструментов ниже уже умеет то, что хочется написать заново.
> Создано 21.08.2026 после замечания Егора: «наличие модуля неочевидно, приходится
> указывать; хочется чтобы инструменты были интуитивно понятны и легко находились».

---

## 🔬 ИССЛЕДОВАНИЕ — начинать ОТСЮДА

### `scripts/research_harness.py` ⭐ ЕДИНАЯ ТОЧКА ВХОДА
Прогон механики + **вся матрица признаков** + слепой отбор + обязательные срезы.

```python
from scripts.research_harness import collect, report, blind_select, mtf_flags
R = collect(mechanic, tf="15m", n_symbols=25)   # механика + 435 MTF-признаков
report(R)                                        # срезы: сторона/год/стоп/хрупкость/охват
blind_select(R)                                  # IS → OOS, открывается ОДИН раз
```

**Что подтягивается САМО** (забыть семью технически невозможно):

| семья | 15m | +1h/4h (MTF) |
|---|---|---|
| пивоты | 76 | 216 |
| SMC (BOS/CHoCH/FVG/OB/OTE/EQH) | 22 | 66 |
| дивергенции (WT + RSI) | 8 | 24 |
| WT | 10 | 18 |
| ATR-тренд | 4 | 12 |
| **всего** | **150** | **435** |

**Зашитые законы** (не опции): % net с костами · хрупкость и охват в каждой строке ·
порог выбирается только на IS · признак обязан быть известен в момент входа ·
не-причинные в чёрном списке · старший ТФ берётся с ЗАКРЫТОГО бара (`shift(1)`).

### `core/calculators/combinator_core.py` — сама матрица
`compute_flags(df, tf, include_pivots=True)` → DataFrame из 151 признака.
Харнесс вызывает её сам; напрямую нужна редко.

### Прочее исследовательское
| скрипт | зачем |
|---|---|
| `scripts/golden_search.py` | старый харнесс; 🔴 дублирует свои WT/ATR вместо комбинатора — схлопнуть |
| `scripts/ds_mining_features.py` | майнинг новых признаков |
| `scripts/pattern_sets_claimed_vs_live.py` | заявленные паттерны против боевых |
| `scripts/universe_drift.py` | дрейф вселенной (30/90/180д) → таблицы `universe_daily`/`universe_drift` |

---

## 🛡️ ПРОВЕРКА ПЕРЕД БОЕМ

### `scripts/strategy_preflight.py` ⭐ ОБЯЗАТЕЛЕН при добавлении стратегии
Гонит синтетический сигнал через 6 живых HARD-гейтов и печатает, **кто именно убил**.

```bash
python scripts/strategy_preflight.py                       # сводка по 32 источникам
python scripts/strategy_preflight.py impulse_fib --gates --stop 2.0 --rr 3.0
```

Ловит молчаливые отказы ДО боя. Уже поймал: расхождение `trade_mode` при копировании
политики, порог `min_sl_dist` в трёх местах с разными дефолтами.
🔑 К свойствам стратегии код ходит по **четырём** ключам — preflight показывает все.

---

## ⚙️ БОЕВЫЕ (pm2, не трогать без причины)

| процесс | скрипт | расписание |
|---|---|---|
| `oko-bot` | `bot_pm2.js` → `oko_mtf.py` | постоянно |
| `universe-drift` | `scripts/universe_drift.py` | `12 * * * *` |
| `regime-now` | `scripts/regime_now.py` | `5 * * * *` |
| `phase-watch` | `scripts/phase_watch.py` | `*/30 * * * *` |
| `shadow-resolve` | `scripts/shadow_resolve.py` | `*/30 * * * *` |
| `weekly-pivot` | `scripts/weekly_pivot_watch.py` | `*/15 * * * *` |
| `hb-watchdog` | `scripts/heartbeat_watchdog.py` | `*/3 * * * *` |
| `forward-machine` | `scripts/forward_machine.py` | `0 8 * * 0` |
| `backup-dbs` | `scripts/backup_dbs.py` | `10 4 * * 0` |
| ещё 8 | `pm2 list` | — |

**Правило:** правка конфига или боевого кода = рестарт + проверка `SelfTest N/N`.
Пропуск этого шага 21.08 положил бота на 25 минут.

---

## 🤖 РОЙ И АГЕНТЫ

| инструмент | зачем |
|---|---|
| `tools/team_ask.py` | опрос 11-12 LLM + peer-ranking + мета-синтез |
| `tools/llm_ask.py` | одиночный запрос |
| `tools/swarm_orchestrator.py` | оркестрация роя |

```bash
python tools/team_ask.py --file бриф.md --no-context "вопрос"
```
Результат → `memory/last_team_discussion.md` + `obsidian/Team-Discussions/`.
🔑 Рой ошибался в главном дважды за сессию (знак дрейфа, разворотность). Ценен
отдельными репликами, не консенсусом: полезные гипотезы приносила ОДНА модель.

---

## 🗂️ ГДЕ ЧТО ЛЕЖИТ

```
core/           бизнес-логика   (smc/ pivots/ indicators/ calculators/ trading/ exchange/)
bot/            UI + лупы       (loops/ handlers/ menus/)
scripts/        442 файла       ⚠️ свалка: 17 боевых, остальное — разовые исследования
tools/          рой и LLM
memory/         handoff         (current_state.md ← читать при старте)
docs/           ENCYCLOPEDIA.md (Куб Метатрона), ARCHITECTURE.md
obsidian/       граф знаний     (Project-MOC.md ← главный хаб)
```

**Данные:** `ohlcv_cache.db` (15m 2022-2026, 5m 2025-2026, 1h/4h, 450+ монет) ·
`subscriptions.db` (боевые сделки, `universe_drift`).

---

## 🔴 ЛОВУШКИ ФОРМАТОВ (три тихих нуля за один день)

Все три дают **пустой результат, а не ошибку** — самый опасный вид отказа.

| что | требует |
|---|---|
| `compute_flags` | **DatetimeIndex** (ресемплит пивоты) |
| SMC-детекторы (`detect_structure_breaks`, `detect_order_blocks`, `detect_fvg`) | **RangeIndex + колонка `time`** |
| символы в `ohlcv_cache.db` | **без суффикса**: `0G/USDT`, не `0G/USDT:USDT` |
| матрица признаков | есть **текстовые** колонки (`'PP'`, `'R1'`) → `select_dtypes(["number","bool"])` |
| `created_at` в боевой БД | **два формата** → `pd.to_datetime(x, format="mixed", utc=True)` |

🔑 **Перед любым замером — санитарная проверка на одной монете:** сколько строк,
сколько объектов вернул детектор, пример первого. Ноль объектов = стоп, а не вывод.

---

## 📋 ЧЕГО НЕ ХВАТАЕТ (бэклог инструментов)

- `golden_search.py` схлопнуть на комбинатор (сейчас дублирует WT/ATR);
- в харнесс добавить срезы «режим года» и «кластер» — сейчас на совести механики;
- `scripts/` разложить по подпапкам: `research/` `ops/` `audit/` `archive/`;
- корень: 54 МБ `scratch_*.pkl` и 18 файлов `*.bak.*` — вынести.

## 📊 АВТОИНВЕНТАРЬ

<!-- АВТОИНВЕНТАРЬ: обновляется `python scripts/project_map.py --write`. Не править руками. -->

Собрано автоматически 21.08.2026 18:16. 🔴 = не менялось >60 дней · 💾 = тяжелее 100 МБ · ⚙️ = в pm2

### Директории

| путь | файлов | размер | назначение |
|---|---|---|---|
| `backups/` | 7 | 7482 МБ | 💾 _назначение не описано — дополнить в PURPOSE_ |
| `logs/` | 19 | 2177 МБ | 💾 логи (растут — чистить) |
| `data/` | 322 | 445 МБ | 💾 исторические данные |
| `cache/` | 2 | 103 МБ | 💾 кэш расчётов |
| `oko_feed/` | 26 | 55 МБ | фид рыночных данных |
| `web/` | 893 | 43 МБ | aiohttp дашборд |
| `graphify-out/` | 618 | 40 МБ | ГРАФ КОДА: graph.json, GRAPH_REPORT.md — связность модулей |
| `scripts/` | 657 | 26 МБ | скрипты: боевые в pm2 + разовые исследования |
| `obsidian/` | 1664 | 26 МБ | граф знаний: задачи, обсуждения, концепции (Project-MOC.md — хаб) |
| `.obsidian/` | 33 | 19 МБ | 🔴 _назначение не описано — дополнить в PURPOSE_ |
| `models/` | 11 | 18 МБ | обученные ML-модели |
| `core/` | 784 | 9 МБ | бизнес-логика (smc/ pivots/ indicators/ calculators/ trading/ exchange/) |
| `docs/` | 151 | 6 МБ | ENCYCLOPEDIA.md (Куб Метатрона), ARCHITECTURE.md |
| `tests/` | 291 | 5 МБ | тесты |
| `memory/` | 50 | 5 МБ | handoff между сессиями (current_state.md) |
| `bot/` | 164 | 3 МБ | UI aiogram + лупы стратегий (loops/) |
| `tmp_charts/` | 22 | 1 МБ | 🔴 _назначение не описано — дополнить в PURPOSE_ |
| `tools/` | 100 | 1 МБ | рой LLM (team_ask), оркестрация |
| `.claude/` | 88 | 1 МБ | CLAUDE.md — правила проекта, читается автоматически |
| `.agents/` | 81 | 1 МБ | 🔴 скиллы агентов (bingx-*) |
| `.continue/` | 68 | 1 МБ | 🔴 _назначение не описано — дополнить в PURPOSE_ |
| `strategies/` | 50 | 0 МБ | 🔴 встроенные стратегии (registry) |
| `config/` | 8 | 0 МБ | конфигурации подсистем |
| `archive/` | 32 | 0 МБ | 🔴 _назначение не описано — дополнить в PURPOSE_ |
| `market_intel/` | 4 | 0 МБ | 🔴 _назначение не описано — дополнить в PURPOSE_ |
| `.vscode/` | 1 | 0 МБ | 🔴 _назначение не описано — дополнить в PURPOSE_ |
| `.claude-config/` | 1 | 0 МБ | 🔴 _назначение не описано — дополнить в PURPOSE_ |
| `docker/` | 2 | 0 МБ | 🔴 _назначение не описано — дополнить в PURPOSE_ |
| `utils/` | 2 | 0 МБ | 🔴 _назначение не описано — дополнить в PURPOSE_ |
| `.cursor/` | 0 | 0 МБ | 🔴 _назначение не описано — дополнить в PURPOSE_ |
| `.tmp/` | 0 | 0 МБ | 🔴 _назначение не описано — дополнить в PURPOSE_ |
| `_meta/` | 0 | 0 МБ | 🔴 _назначение не описано — дополнить в PURPOSE_ |

### Документы в корне

| файл | строк | возраст | 
|---|---|---|
| `AGENTS.md` | 59 | 🔴 67 дн |
| `BOT_SIGNAL_MAP.md` | 468 | 1 дн |
| `DISCUSSION-ARCHIVE-APR2026.md` | 14978 | 🔴 76 дн |
| `DISCUSSION-ARCHIVE-JUN2026.md` | 4573 | 27 дн |
| `DISCUSSION-ARCHIVE-MAR2026.md` | 16223 | 🔴 136 дн |
| `DISCUSSION-ARCHIVE-MAY2026.md` | 122 | 🔴 76 дн |
| `DISCUSSION.md` | 6580 | 7 дн |
| `PROJECT-LOG.md` | 1558 | 🔴 76 дн |
| `README.md` | 144 | 39 дн |
| `RESEARCH.md` | 188 | 🔴 129 дн |
| `ROADMAP.md` | 1141 | 🔴 78 дн |
| `START.md` | 108 | 8 дн |
| `STATUS.md` | 24 | 🔴 113 дн |
| `TASKS-ARCHIVE.md` | 555 | 🔴 64 дн |
| `TASKS.md` | 520 | 42 дн |
| `TOOLS.md` | 241 | 0 дн |
| `whats-next.md` | 295 | 0 дн |

### ⚙️ Боевые скрипты (pm2)

| скрипт | процесс |
|---|---|
| `accum_scanner.py` | accum-scan (40 7 * * *) |
| `app.js` | pm2-logrotate (постоянно) |
| `backup_dbs.py` | backup-dbs (10 4 * * *) |
| `bot_pm2.js` | oko-bot (постоянно) |
| `deadflag_audit.py` | deadflag-audit (30 6 * * 0) |
| `forward_machine.py` | forward-machine (0 8 * * 0) |
| `heartbeat_watchdog.py` | hb-watchdog (*/3 * * * *) |
| `news_sphere.py` | news-sphere (постоянно) |
| `next` | oko-dash (постоянно) |
| `ollama_pm2.js` | ollama (постоянно) |
| `ote_cell_shadow.py` | ote-cell (постоянно) |
| `phase_watch.py` | phase-watch (*/30 * * * *) |
| `pivot_sanity.py` | pivot-sanity (25 0 * * *) |
| `python.exe` | dc-agent (постоянно) |
| `regime_now.py` | regime-now (5 * * * *) |
| `shadow_resolve.py` | shadow-resolve (*/30 * * * *) |
| `tg_collector.py` | tg-collector (постоянно) |
| `universe_drift.py` | universe-drift (12 * * * *) |
| `weekly_hypothesis.py` | weekly-hypo (7 * * * *) |
| `weekly_pivot_watch.py` | weekly-pivot (*/15 * * * *) |

### 🧹 Кандидаты на уборку (корень)

| что | файлов | размер |
|---|---|---|
| временные данные исследований | 66 | 56 МБ |
| бэкапы правок | 6 | 0 МБ |
| логи в корне | 2 | 5 МБ |
