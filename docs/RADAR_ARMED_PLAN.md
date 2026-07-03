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

## Открытые вопросы Егору (спросить в начале сессии)

1. Доли TP1/TP2/TP3 — 40/30/30? (дефолт скилла dynamic-sl-tp)
2. Какие сигналы армить в v1: только BUILD-с-сетапом? + PUMP Grade A/B? ПРУЖИНА?
3. risk % и плечо для radar-политики (0.5% / 20x?)
4. Лимит одновременных radar-позиций (3-5?)
5. Авто-БУ после TP1 или после TP2? Нативный трейл vs наш TSL-движок на остатке?

## Критический контекст

- **PARTIAL-семантика = главный риск** — недавно чинили exit-утечки (BE-синк, EXPIRED,
  fake-R); не наступить снова. Шаг 1 обязателен ДО любого кода.
- WR-статистика радара копится (radar_wr.py) — к моменту сессии будет материал для порогов.
- Правила: preflight_exchange_task (BingX docs/скиллы сначала) · register-путь → копия БД ·
  рестарт бота = Егор · TSL обязателен для пампов (движение импульсное).
