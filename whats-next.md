# What's Next — Handoff

## 🆕🔴 Новая сессия (Даат) — #21 EXEC-SIM-SPLIT (+ ПЕРВЫМ проверить SL-reconcile live)

> Думать/писать по-русски · grep before claim · числа из config/кода · TTS Microsoft Irina после задач.
> Ветка `arch-128-oko-sm` (запушена, ahead 0). Бот рестартнут 18.06 ~22:30 UTC (PID 31536, sl_reconcile=live).

### 🔴 ПЕРВЫЙ ШАГ (validation pending — активировано биржевое действие `0e96325`)
**Проверить `[SL-RECONCILE][live]`:** `grep -a "SL-RECONCILE\]\[live\]" logs/crypto_bot.log | tail`
- Ожидание: REAL/USDT SHORT (sl≈0.061912) + KAT/USDT SHORT (sl≈0.005315) получают SL (oid=…) в 1-м цикле reconcile (~5мин после старта).
- ⚠️ Если ошибки place (account / qty / precision / «No position») → ОТКАТ: `config.yaml trading.sl_reconcile: live → shadow` + рестарт. Loop account-aware (`arch96.multiaccount=true`, роутер по symbol), но live на бою ВПЕРВЫЕ — подтвердить.
- Чисто выставлены → #1 закрыт окончательно. Loop: `position_sync.sync_positions:386-420` (throttle 5мин).

### ЗАДАЧА: #21 EXEC-SIM-SPLIT (🔴 `docs/BACKLOG_CONSOLIDATED.md` #21)
**Первый шаг — сводка DEV-52 shadow-логов** (копятся с 18.06):
`grep -aE "\[DEV-52\]\[(RISK|MARGIN)\]" logs/crypto_bot.log` → частота would_block + распределение risk%/available per-account (acc1/acc2).
Далее: калибровка порогов (`trading.l3_checker.max_total_risk_pct=10`, `min_available_usdt=5`) → активация (`risk_gate_shadow:false`/`margin_gate_shadow:false` + рестарт, откат мгновенный). Память [[exec_sim_split_epic]]. Полный контекст эпика — в handoff EXEC-SIM-SPLIT ниже.

### ✅ Сделано сессию 18.06 вечер (Даат) — 6 коммитов, ЗАПУШЕНО (arch-128-oko-sm)
- `bce5d47` **классификатор BE** — безубыток вне win_rate (`effective_status` +be_activated → BE_area нейтрал; `performance_engine` closed−=be_neutral) + фикс `/api/kpi` 500 (datetime naive/aware смешан). WR VST 48.5→51.0 (копия). ВЕСА НЕ затронуты (update_signal_weights по avg_r). [[be_exit_classification_findings]].
- `0e96325` **#1 SL-reconcile LIVE** (loop был shadow, account-aware) — ↑проверить первым шагом.
- `ceb1380` NOTIF-TIER2 уведомления, `1edd2cf` роль-инфра, `a6eb622` gitignore `*.bak*`, `ef186d1` доки.
- Расследование «кривого SL» ЗАКРЫТО = штатный безубыток (НЕ баг) [[bug_stop_loss_inverted]]. BE-буфер 0.1% НЕ трогать (стенд `e:/tmp/be_buffer_stand.py`: режет раннеры). Git чист (research-зона DS 93 untracked не трогал).
**Бэклог:** runner-флаг + magnet-TP shadow→exit (ARCH-122 P3); ARCH-104 перемайн на честном R; свежая parquet-история (>17.05) под стенды; atr_change→4h.

───────────── ниже: handoff DS-326 (DEV, другой вектор) ─────────────

## 🆕 Сессия 18.06.2026 (DEV / Opus 4.8) — DS-326 ЗАКРЫТА (research)
> Коммиты: `6b2cda1` → `1108201` → `60c06d6` (ветка `arch-128-oko-sm`, НЕ запушено). Боевой код НЕ тронут (чистое исследование, бот не запускался).

**DS-326 (WT-B дивергентный edge) — ЗАКРЫТА с честным негативным вердиктом:**
- ADX<25 (1h→15m) = единственный gross-фильтр +0.204R, OOS устойчив (2024 +0.302, 2025 +0.304; walk-forward IN +0.233/OUT +0.175). 4h-намёк отброшен (режим-зависим).
- TSL: crude(0.5R) чемпион; боевой hybrid/trend-based хуже для контртренда wt_b.
- 🔴 **РАЗВОРОТ:** +0.204 = артефакт узкого бэктест-SL 0.3%. R считается от SL → узкий SL раздувает R вчетверо. На прод-SL 0.5% gross→**+0.048**, net после комиссии BingX → **−0.145**. **Торгуемого edge НЕТ.**
- 🧭 **МЕТОД-УРОК (для всех бэктестов проекта):** R фантомен при узком SL — фиксировать прод-SL перед выводом. Память [[feedback-backtest-realistic-sl]]; проверка `python scripts/ds326_fees.py --min-sl 0.005 --max-sl 0.02`.
- Отчёт: `data/research/ds326_wtb_filters_result.md` (в `.gitignore`, локально). Скрипты: `scripts/ds326_{all_filters,edge_levers,tf_matrix,oos,fees}.py` (закоммичены).
- **Следующей сессии:** DS-326 НЕ открывать заново. Если копать wt_b — только прод-SL + maker-выход (TP лимиткой) + combo (SHORT+div5-12) + ликвидные пары, и то net тонкий.

───────────── ниже: предыдущий handoff EXEC-SIM-SPLIT (ДРУГОЙ живой вектор, 17-18.06, Даат) ─────────────

# What's Next — Handoff (EXEC-SIM-SPLIT, сессия 17-18.06.2026, Даат / Opus 4.8)

> Свежей сессии: прочитай этот файл + `memory/current_state.md` (тот же статус короче) + DISCUSSION.md (записи 21:23–21:50 UTC 17.06).
> Думать/писать по-русски · grep before claim · числа из config/кода · TTS Microsoft Irina после задач.
> Коммит сессии: **1a22f70** (ветка `arch-128-oko-sm`, НЕ запушен).

<original_task>
Юзер: «EXEC-SIM-SPLIT — что будем делать? опиши подробно». Эпик был «🔵 ВЕКТОР, не делать сейчас» (полный split на 2 процесса main/strip — дубль логики против reuse, strip протух, железо на пределе). Юзер выбрал путь **«80/5» в одном процессе** (НЕ полный split) и поручил ограничители риска. Порядок: (1) лимит позиций → мерка = риск-экспозиция %; (2) консенсус (рой+DS); (3) кирпич №1 shadow; (4) «починить config 710» → «balance_snapshots = единый источник»; (5) margin pre-check кирпичом №2; (6) рестарт+валидация; (7) коммит. Побочно: центровка «loading…» в дашборде CUBE; план Settings→Entry Gates.
</original_task>

<work_completed>
**Консенсус:** путь «80/5» принят тройным консенсусом юзер→DS→рой (team-ask 5/5: откладывать split + мерка риск-экспозиция %). Спор по потолку: cerebras 5-10% (нестабильность, 60% фантомов) vs остальные 20-30%; Mistral-meta признал cerebras сильнее. Разрешение: shadow-first → потолок по данным, старт активации 10%. Рой: `memory/last_team_discussion.md`.

**Кирпич №1 — риск-экспозиция gate (PER-ACCOUNT, shadow):** расширение DEV-52 l3_checker в `core/trading/trade_simulator.py` (~1252-1335, внутри `register_trade_async`). Мерка `Σ(qty×|entry−sl|) открытых VST acc / equity_account`. equity per-account из `balance_snapshots` (SELECT через `self._db_connect()`). Вклад новой = `risk_pct%` (qty ещё не посчитан). Лог `[DEV-52][RISK]`.

**Кирпич №2 — margin pre-check (PER-ACCOUNT, shadow):** тот же блок (рефактор: общий lookup account+equity+available → 2 gate). Корень фантомов (аудит `core/trading/trade_router.py:167,203`): `register_trade_async` создаёт SIM-запись ДО `_place_exchange_order`; `open_bracket` margin-fail → order_id NULL → запись остаётся SIM = фантом. Мерка `available_per_account < min_available_usdt`. Лог `[DEV-52][MARGIN]`.

**Системный фикс депозита («balance_snapshots = единый источник»):** было 4 рассинхрона — `config.deposit_usdt=710` ∥ `user_settings` ПУСТ→дашборд 1000 ∥ реальный equity 316 (acc1~150+acc2~167) ∥ VST sizing от `availableMargin`~22. `web/dashboard_server.py` (~750-765): `risk_exposure` = реальный риск `Σ(qty×|entry−sl|)` VST / equity (`balance_repo.get_accounts()`), врало ~5×. `config.yaml deposit_usdt` помечен SIM-номиналом (710 не трогал).

**Config (`config.yaml`→`trading.l3_checker`, ~203-219):** `max_total_risk_pct: 10.0`, `risk_gate_shadow: true`, `min_available_usdt: 5.0`, `margin_gate_shadow: true`. Существующие: `enabled: true`, `max_open_long/short: 25`, `max_open_total: 50` (количественный — реально блокирует).

**Проверки:** py_compile OK. Runtime на КОПИИ `subscriptions.db` (→`e:/tmp/subs_risktest.db`): №1 acc2 9.7-10.2% would_block / acc1 0.8-2.4% pass; дашборд risk 5.8%/eq307.

**ВАЛИДАЦИЯ В ПРОДЕ (shadow, после 2 рестартов):** 18.06 00:42 MSK WHITEWHALE acc2 → ОБА would_block: `[DEV-52][RISK] 12% > 10%` + `[DEV-52][MARGIN] avail=2.8 < 5.0`. Ровно сценарий фантома. Количественный DEV-52 блокирует (`SHORT 31/25`). Ошибок DEV-52 нет.

**Коммит 1a22f70:** trade_simulator.py, dashboard_server.py, config.yaml, TASKS.md, DISCUSSION.md (+291). Документация: DISCUSSION (6 записей), `memory/exec_sim_split_epic.md`, `memory/current_state.md`, TASKS (якорь + новый backlog DASH-SETTINGS-GATES).

**Побочное:** `oko-dashboard/app/page.tsx` ScreenFallback → `fixed inset-0` (центровка «loading…»). ⚠️ oko-dashboard НЕ git — НЕ в коммите, зафиксировать отдельно.
</work_completed>

<work_remaining>
0. **ЗАПУСТИТЬ `bot-data-audit`** в свежей сессии с брифом `docs/AUDIT_DATA_INTEGRITY_BRIEF.md` (глубокий аудит матчей/семантики; юзер просил). Уже в этой сессии починены: R-баг `_handle_live` (коммит d51b26f, матч (symbol,direction)), `get_by_symbol` +side, `fetchLivePositions` regime из бэка.
1. Накопить shadow-данные (дни) в `logs/crypto_bot.log` (`[DEV-52][RISK]`/`[DEV-52][MARGIN]`).
2. **Сводка по логам** (первый шаг новой сессии по теме): частота would_block + распределение risk%/available per-account. `grep -aE "\[DEV-52\]\[(RISK|MARGIN)\]" logs/crypto_bot.log`.
3. Калибровка порогов: `max_total_risk_pct` (10), `min_available_usdt` (5, available колеблется 2.8↔70).
4. Активация: `risk_gate_shadow: false` / `margin_gate_shadow: false` → рестарт (откат мгновенный).
5. DASH-SETTINGS-GATES (TASKS): лимиты в дашборд→Settings→«Entry Gates & Protection» (реестр `dashboard_server.py:2142+` + POST + фронт `settings.tsx` GATE_TOGGLES/слайдеры; `*_shadow` как Shadow/Block). ПОСЛЕ активации.
6. Вопрос DS (DISCUSSION 21:35): margin-альтернатива — бить фантом в точке `open_bracket` margin-fail в trade_router.
7. Backlog глубже: VST sizing-base (`availableMargin`→equity?) — порочный круг при занятой марже.
8. Push 1a22f70 — по отмашке юзера.
</work_remaining>

<attempted_approaches>
- №1 сначала делил на `config.deposit_usdt=710` суммарно → shadow вскрыл расхождение → переделано на per-account equity из balance_snapshots.
- Runtime на копии: Python не понимает git-bash `/e/tmp/...` → Windows-путь `r'e:/tmp/...'`. Не-ASCII в print падает под cp1251 → ASCII или `PYTHONIOENCODING=utf-8`.
- `grep -c` exit 1 при 0 → оборачивать `(grep ... || true)`.
- Рой завис на meta ~22 мин (sambanova timeout) — 6 ответов есть, meta дописался; читать `memory/last_team_discussion.md`.
- ПЕРВЫЙ рестарт был между кирпичами → нужен был ВТОРОЙ. Урок: рестарт ПОСЛЕ всех правок.
- Tracebacks в логе из `bot/monitoring.py:1919 send_photo` (Telegram) — НЕ DEV-52, игнор.
</attempted_approaches>

<critical_context>
- Цель ([[vision_bot_as_anchor_against_emotion]]): риск-экспозиция % = тормоз жадности; путь к $1M через компаундинг → выживание/ruin первично.
- [[principle_reuse_not_duplication]]: кирпичи = расширение DEV-52, НЕ новые gate. Полный split отложен из-за дубля.
- Мерка = риск %, НЕ количество/маржа: `notional=risk/sl_dist` взрывается до 20× при узком стопе (`position_sizer.py:72-89`, cap `max_notional_mult=20`).
- Per-account ОБЯЗАТЕЛЕН: acc1 VST-Main ~150, acc2 VST-Sub ~167. Суммарный прячет проблему.
- 🔴 ГЛАВНАЯ НАХОДКА: реальная боль = МАРЖА 87% used на обоих акк (avail~22), НЕ стопы (риск стопов 0.8-10% здоров). Фантомы+ликвидация от маржи → margin pre-check острее.
- execution_mode: SIM⟺order_id NULL, VST⟺order_id есть. Обучение (`performance_engine.by_signal_type_ema`) фильтрует VST → фантомы вне весов.
- Правила: прогон main не трогать (рестарт=юзер); register-путь → runtime на копии ([[feedback_ast_parse_no_scope]]); биржевое → docs/код сначала ([[preflight_exchange_task]]); русский; TTS Irina.
- oko-dashboard НЕ git — фронт осторожно, отдельно.
- Всё за shadow-флагами → реально не блокирует, только лог. Безопасно.
</critical_context>

<current_state>
- Кирпичи №1+№2: ✅ реализованы, ✅ протестированы (py_compile+runtime копия), ✅ ВАЛИДИРОВАНЫ В ПРОДЕ (shadow), ✅ закоммичены (1a22f70). Работают в боте, копят логи.
- Deposit-рассинхрон: ✅ починен.
- Активация: ⏳ ждёт накопления данных (shadow=true, реально не блокирует).
- Дашборд risk_exposure: ✅ реальные % (в коммите). loading-fix oko-dashboard НЕ закоммичен (др. репо).
- DASH-SETTINGS-GATES: 🔵 backlog, после активации.
- Push: 1a22f70 локальный, НЕ запушен.
- Точка остановки логическая. Следующий заход по теме = сводка логов → калибровка → активация. Крупные новые задачи — в СВЕЖЕЙ сессии (этот контекст тяжёлый).
</current_state>
