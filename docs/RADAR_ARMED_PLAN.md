# RADAR-ARMED-VST — план реализации (для свежей сессии)

> Добро Егора 03.07: «нужны лимитные ордера + частичное закрытие по нескольким TP на бирже;
> можно запускать в прод на VST» + «на BingX есть авто-БУ — включать при достижении одной из целей».
> Возможности API сверены со скиллами `bingx-swap-trade` / `bingx-dynamic-sl-tp` 03.07.

## Что даёт BingX API (проверено по скиллам)

| Нужно | API | Статус |
|---|---|---|
| Вход лимиткой | `type=LIMIT` | ✅ + наш `order_manager.entry_order_type='LIMIT'` готов (25.06) |
| Несколько частичных TP | `TAKE_PROFIT_MARKET` + `quantity` (доля) + `reduceOnly=true` — N ордеров | ✅ API позволяет; в боте НЕ реализовано |
| Batch-постановка | `POST /trade/batchOrders` до 5 ордеров | ✅ — SL+TP1+TP2+TP3 одним запросом |
| Авто-БУ | Нативного флага в API НЕТ (UI-фича). Два пути: (А) свой: WS-fill TP1 → `om.update_sl(BE)` — механика ГОТОВА (e762449 BE-синк); (Б) `TRAILING_STOP_MARKET` c `activationPrice`=цель + `priceRate` — нативный трейл, включается при достижении цели | ✅ обоими путями |
| TSL на остатке | `TRAILING_STOP_MARKET` (priceRate=коллбек%, activationPrice) или наш TSL-движок | ✅ |
| Гарантированный стоп | `stopGuaranteed=true` (за фи) | опция, не в v1 |

## Архитектура (утверждена в обсуждении 03.07)

**Радар = алертер (автономия продукта №2 не ломается). Исполняет БОТ через порт.**
```
радар (oi_fast_poller) → external_data.db: radar_orders (сетап: sym/side/entry/sl/tps/grade)
бот: radar_armed_loop (новый лёгкий луп) → читает radar_orders (poll 10-30с)
   → register через trade_router + source_policy 'radar' (execution_mode=vst, LIMIT)
   → reuse ВСЕЙ обвязки: positionId-захват, SL-синк, BE, TSL, l3-гейты, position_sync
```

## Шаги реализации (порядок строгий)

1. **🔬 Разведка PARTIAL (ДО кода!):** как текущий exit-пайплайн реагирует на «pa уменьшилась,
   но не 0» (частичный reduce-only fill). Прочитать `exec_ws_integration` 2a/2b + `position_sync`
   + reconcile-watchdog. Риск: частичный TP посчитают закрытием/орфаном. Выход v1 (lean):
   позиция OPEN до pa=0; частичные фиксации → `partial_fills` json в features_json;
   финальный exit = средневзвешенный; статусы НЕ переделывать.
2. **source_policy `radar`**: entry_order_type=LIMIT, risk_pct/leverage свои, execution_mode=vst.
3. **Порт radar_orders**: радар пишет сетап при BUILD-с-сетапом/PUMP (фильтр качества — см. вопросы);
   бот-луп подхватывает, дедуп по (symbol, ts).
4. **Pending-lifecycle LIMIT**: статус PENDING_ENTRY (или регистрация после fill), TTL-отмена
   (конфиг `radar_armed.entry_ttl_min`), fill-detection = существующий WS ORDER_TRADE_UPDATE.
5. **Multi-TP**: после fill входа → batchOrders: SL(STOP_MARKET, full) + TP1(40%)+TP2(30%)+TP3(30%)
   reduce-only по ценам карты целей (★-цели приоритетом). Precision qty — reuse округления
   order_manager. Санити: Σ долей ≤ позиции.
6. **Авто-БУ**: fill TP1 (WS, orderId известен из шага 5) → `om.update_sl(BE=actual_entry±fee)` —
   путь e762449. После TP2 — вариант: заменить SL на TRAILING_STOP_MARKET (нативный трейл остатка).
7. **Гейты v1**: только CORE-50, Grade A/B (или ★-цель), max N одновременных radar-позиций,
   l3-лимиты уже действуют.
8. **Тест-протокол**: (а) юнит-логика на копии БД; (б) ОДИН ручной VST-прогон на дешёвой монете
   (LIMIT→fill→3TP→частичный→BE→трейл) с грепом логов ДО включения авто; (в) флаг
   `radar_armed.enabled`, старт с 1-2 сигналов/день.

## 🔬 Результаты разведки PARTIAL (шаг 1 ВЫПОЛНЕН, 03.07)

**Вывод: v1-схема (позиция OPEN до pa=0, частичные фиксации → partial_fills, финальный exit
средневзвешенный) ЖИЗНЕСПОСОБНА.** Все авторитетные close-пути триггерятся только на pa=0/флэт —
частичный reduce-only fill сам по себе закрытие НЕ вызывает. Но найдены 4 узла, которые убьют
или испортят multi-TP позицию — гейтить ДО включения:

✅ **Безопасные узлы** (проверено чтением кода):
- exec_ws 2b `sync_close` (авторитет, в конфиге on): триггер строго `pa=0`
  (`exec_ws_integration.py:342` — `if pa_val != 0.0: continue`).
- ExecutionSphere/PositionStore (shadow): flat-триггер только `p.is_flat`
  (`position_store.py:81`); pa>0 → upsert.
- position_sync close-by-price: закрывает БД только если (sym,dir) НЕТ на бирже
  (`position_sync.py:559`); частичная позиция жива → не тронет.
- SL-RECONCILE live: ставит SL по qty С БИРЖИ (`abs(pp.qty)`) — остаток корректен.

🔴 **4 обязательных фикса ДО multi-TP:**
1. **LIVE-GUARD → emergency close всего остатка.** Симулятор детектит exit по свечам; для
   DUAL_TP `exit_status` ставится уже на tp2 (`trade_simulator.py:2918-2930`) → live-guard
   трекает (`trade_simulator.py:3050`) → через 7 мин `_emergency_close_check` закроет ВЕСЬ
   остаток market (`position_sync.py:239-241,297`). Для radar-сделок: симуляторный TP-детект
   отключить или детектить только ФИНАЛЬНУЮ цель (SL-детект оставить). Плюс: emergency qty
   берёт `trade.qty` из БД = полный, не остаток (`position_sync.py:271`).
2. **repair_missing_tp** (`tsl_updater.py:216`, каждые 60с): если на бирже нет живого
   TAKE_PROFIT-ордера (все TP исполнены, остаток на трейле), а БД take_profit>0 → поставит
   НОВЫЙ одиночный TP на ВЕСЬ остаток. Для radar: take_profit в БД = NULL/0 (цели живут в
   partial-плане) или гейт по trade_mode.
3. **orphan_autoclose: live × PENDING-lifecycle** (`position_sync.py:785-788`): tracked_pairs
   строится ТОЛЬКО из OPEN-строк, grace-периода нет → LIMIT зафиллился, строка ещё
   PENDING_ENTRY → в ближайший цикл (≤60с) позицию закроют как орфан. Зеркально: OPEN-строку
   ДО fill нельзя — close-by-price закроет её как «позиция исчезла». Итог: статус
   PENDING_ENTRY обязателен + расширить orphan-выборку на PENDING + перевод PENDING→OPEN по
   WS-fill (ORDER_TRADE_UPDATE).
4. **BE/TSL cancel+replace qty из БД** (`trade_simulator.py:2847`): после частичных TP SL
   перевыставляется на ПОЛНЫЙ qty. Closing-ордер биржа скорее всего clip'ает, но чисто —
   qty = get_position_qty (остаток) в момент replace.

**Прочие находки:**
- `_close_fills` (2b) и `_exit`-stash (Store) перезаписываются каждым закрывающим fill →
  при финальном pa=0 exit_price/realized = ПОСЛЕДНЕГО куска (`exec_ws_integration.py:265-275`,
  `position_store.py:110-116`). Честный результат = свой накопитель partial_fills на каждый
  закрывающий fill → weighted exit при close_trade.
- `close_trade` УЖЕ умеет weighted по частичному TP1: `tp1_hit_at`+`tp1_price` →
  R = fix×r_tp1 + (1−fix)×r_exit (`trade_simulator.py:1683-1702`, config
  `dual_tp.tp1_fix_pct`, сейчас 10). Паттерн расширяем на 3 TP.
- `_resolve_exit` positionID-якорь берёт последний close-fill по updateTime → финальный
  статус = тип последнего куска (TP3→TP; трейл/двинутый SL→TSL-коррекция). Для v1 ок.
- 2a `write_exch_id: false` (shadow) — actual_entry_price для LIMIT будет NULL до fill →
  захват entry на WS-fill обязателен (иначе fake-R класс).
- batchOrders в боте НЕ существует (grep пуст) — строить с нуля (bingx_client).
- `entry_order_type: LIMIT` откачен 25.06 именно из-за отсутствия pending-lifecycle
  (`config.yaml:722`) — LIMIT-код сохранён, переиспользуем.

## ✅ Ответы Егора (03.07, вопросы закрыты)

1. Доли TP1/TP2/TP3 = **40/30/30** (дефолт принят).
2. Армить в v1: **ВСЕ ТРИ** — BUILD-с-сетапом + PUMP Grade A/B + ПРУЖИНА.
3. Radar-политика: **risk 0.5% / плечо 20x**.
4. Лимит одновременных radar-позиций: **5**.
5. **Авто-БУ после fill TP1 + НАШ TSL-движок на остатке** (нативный TRAILING_STOP_MARKET — не в v1).

## 🏗️ СТАТУС РЕАЛИЗАЦИИ (03.07, вечерняя сессия — шаги 1-6 ПОСТРОЕНЫ, флаг OFF)

**Код готов и протестирован (2 smoke ALL GREEN), `radar_armed.enabled: false` — включение
только после ручного VST-прогона (шаг 8б).**

| Шаг | Что построено | Где |
|---|---|---|
| 1 ✅ | Разведка PARTIAL (раздел выше) — 4 опасных узла найдены и загейчены | — |
| 2 ✅ | `source_policies.radar` (LIMIT, 0.5%/20x) + `trading.radar_armed` | config.yaml |
| 3 ✅ | Порт `radar_orders` (NEW→TAKEN/SKIPPED/STALE) + запись сетапов BUILD/PUMP/SPRING | `oi_fast_poller.py::_log_radar_order` |
| 3б ✅ | `radar_armed_loop`: poll 15с → фильтры (типы/grade/лимит 5/symbol-busy/TTL/цена-протухла) → `trade_router.submit(source='radar')` | `bot/loops/radar_armed_loop.py` (регистрация в `bot/core/bot.py`) |
| 4 ✅ | Pending-lifecycle: TAKEN→`PENDING_ENTRY` (строка невидима для TSL/close-by-price/live-guard) → REST-чекер fill→OPEN+actual / TTL→cancel→`CANCELLED`. SL+финальный TP **attached к самому LIMIT-ордеру** — позиция защищена с первой секунды, exec_ws не тронут | `radar_armed_loop::_check_pending` |
| 4-гейты ✅ | orphan-детект видит PENDING (`position_sync._detect_orphans`) · grace 120с в close-by-price (`position_sync`) · LIMIT без fill НЕ пишет сигнальную цену в actual (`order_manager.open_bracket`) | position_sync.py, order_manager.py |
| 5 ✅ | Multi-TP: частичные reduce-only TP по `tp_shares` на цели кроме финальной (финальная = attached full — биржа clip'нет остаток). Напрямую `client.place_tp_order` — обёртки om каннибализируют >1 TP. `repair_missing_tp` загейчен для radar | `radar_armed_loop::_on_entry_filled`, tsl_updater.py |
| 6 ✅ | Авто-БУ: REST-детект fill TP1 (orderId в filled) → `om.update_sl(BE=actual±0.1%, buffer 0.15%)` → `be_activated=1`. Остаток ведёт штатный TSL | `radar_armed_loop::_check_be_after_tp1` |

**Решения по ходу (отклонения от плана, все в сторону lean):**
- batchOrders НЕ понадобился: SL+TP-final привязаны к LIMIT-ордеру атомарно (place_bracket_order),
  частичных TP остаётся максимум 2 — два обычных POST.
- Авто-БУ и fill-detection = REST-поллинг в самом лупе (15с), НЕ врезка в exec_ws —
  ноль правок WS-ядра, задержка приемлема для сетапов масштаба часов.
- Нативный TRAILING_STOP_MARKET не в v1 (ответ Егора: наш TSL).
- `take_profit` в БД = ФИНАЛЬНАЯ цель → симуляторный TP-детект/live-guard не закроют рано.
- BE/TSL qty после частичного TP: `place_sl_order` уже сам ретраит с реальным остатком
  («must be less than the available amount» → get_position_qty) — фикс не понадобился.

**Известные некритичные хвосты (v1 принимает):**
- Частичный fill лимитки при TTL-cancel → возможен кусок позиции: закроет orphan_autoclose (live).
- Если ДРУГАЯ стратегия откроет same-symbol+side поверх radar-сделки, её repair_missing_tp
  может отменить наши частичные TP (редко: CORE-50 пересечение; наблюдать в прогоне).
- `_close_fills`/Sphere stash при финальном pa=0 отдают цену последнего куска — profit_pct
  считается от неё на весь объём; честный weighted-расчёт по partial_fills = шаг v1.1
  (после первого прогона; кирпич `close_trade` tp1_fix уже есть).

**Шаг 8 (осталось):** (а) ✅ smoke×2 на тест-БД (порт+лайфцикл); (б) ОДИН ручной VST-прогон
на дешёвой монете с грепом `[RADAR-ARMED]` ДО включения: `radar_armed.enabled: true` +
рестарт бота (Егор) → INSERT тестовой строки в radar_orders → LIMIT→fill→TP1→BE→TSL;
(в) включение на поток: старт с 1-2 сигналов/день (лимит 5 уже в конфиге).

## Критический контекст

- **PARTIAL-семантика = главный риск** — недавно чинили exit-утечки (BE-синк, EXPIRED,
  fake-R); не наступить снова. Шаг 1 обязателен ДО любого кода.
- WR-статистика радара копится (radar_wr.py) — к моменту сессии будет материал для порогов.
- Правила: preflight_exchange_task (BingX docs/скиллы сначала) · register-путь → копия БД ·
  рестарт бота = Егор · TSL обязателен для пампов (движение импульсное).
