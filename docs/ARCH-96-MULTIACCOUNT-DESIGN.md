# ARCH-96: Мульти-аккаунт (субаккаунты BingX) — дизайн-док

> Инициатор: пользователь, 08.06.2026. Цель: обойти потолок ордеров BingX для масштабирования
> веера (OTE + новый WAVE-FLAGMAN). Это разморозка **Execution Sphere (ARCH-96, DS-приоритет#1)**.

## 1. Проблема — лимиты BingX

| лимит | значение | где укусит |
|---|---|---|
| ордеров на аккаунт (perpetual) | **100** (вкл. SL/TP) | расширение веера + частичные TP |
| ордеров на одну пару | **10–20** (анти-спам) | REPAIR-SL throttle плодит replace |
| rate-limit | **по IP + по UID** | субаккаунты с 1 сервера делят IP → 100410 |

Сейчас: OTE-observer торгует 18 пар × ~2-3 ордера (вход/SL/TSL) → запас до 100 есть. Но WAVE-FLAGMAN + расширение веера + частичные TP упрут в потолок. Субаккаунты = способ масштабировать (каждый = свой кошелёк/позиции/лимиты).

## 2. Текущая архитектура (verified grep, 08.06)

```
make_client(mode, config)                          bingx_client.py:536
  vst:  BINGX_VST_API_KEY / BINGX_VST_SECRET_KEY
  live: BINGX_API_KEY / BINGX_SECRET_KEY
  → ОДИН BingXClient(api_key, secret, base)

OrderManager                                        order_manager.py:43,71
  self._client (один, lazy _get_client)
  self._mode (один)
  _get_client_synced() = ЕДИНАЯ ДВЕРЬ + timestamp-sync (DEV-145)
    → 13+ вызовов: order_manager, position_sync, position_manager

⚠️ торговые ордера НЕ через GlobalRateLimiter (тот покрывает только OHLCV в api_engine).
   rate-limit на ордера НЕ централизован → 100410-боль (timestamp/IP).
```

**Плюс:** единая дверь = одна точка изменения. **Минус:** она же узкое место.

## 3. Предлагаемый дизайн

```
① Ключи субаккаунтов:
   BINGX_VST_API_KEY_1/2/3 + secrets (ИЛИ config exchanges.subaccounts[])
   make_client(mode, account_id) → клиент конкретного субаккаунта

② AccountRouter (новый core/exchange/account_router.py):
   • держит N клиентов (по субаккаунту)
   • route(symbol) → account_id (детерминированный, sticky)
   • счётчик ордеров per-account + per-symbol (position_sync + локальный pending)

③ OrderManager: _client → _clients{account_id: client}
   _get_client_synced(symbol) → router.route(symbol) → синканный клиент субаккаунта
   (дверь УЖЕ единая — добавляем symbol-параметр, минимальная инвазивность)
```

## 4. Критичные нюансы (риски)

1. **STICKY symbol→account (ОБЯЗАТЕЛЬНО):** одна пара ВСЕГДА на одном субаккаунте (вход+SL+TSL вместе). Иначе позиция разорвётся (SL на sub2, вход на sub1). Детерминированный маппинг (БД-таблица symbol→account для стабильности, не hash%N который сдвинется при добавлении субаккаунта).
2. **IP rate-limit:** субаккаунты с одного сервера делят IP-лимит → централизованный троттлинг ВСЕХ ордерных запросов (расширить GlobalRateLimiter на торговые). Лечит 100410 заодно.
3. **position_sync ВСЕХ субаккаунтов:** сейчас один аккаунт. Позиции размазаны по N → синкать все, агрегировать в общий portfolio-view (БД/дашборд).
4. **Order-counting:** route-решение нужен реальный счёт ордеров/аккаунт+пара (position_sync открытые + pending).
5. **Transfer main↔sub:** отдельный API для авто-баланса капитала (фаза 4).

## 5. Этапность

| фаза | содержание | риск |
|---|---|---|
| 1 ядро | AccountRouter + sticky symbol→account(БД) + make_client(mode,acc) + _clients + дверь(symbol). 2 субаккаунта тест VST. | средний |
| 2 IP | централизованный троттлинг ордеров (GlobalRateLimiter торговый) → лечит 100410 | низкий |
| 3 route | динамический выбор по нагрузке (order-count) вместо чистого sticky | средний |
| 4 capital | transfer API main↔sub (авто-баланс) | высокий (деньги) |

## 6. 🔴 ОТКРЫТЫЕ ВОПРОСЫ для роя

1. **Sticky-стратегия:** БД-таблица symbol→account (стабильно, но ручной ребаланс) ИЛИ consistent-hashing (авто, но сдвиг при добавлении субаккаунта)? Как ребалансить при добавлении субаккаунта БЕЗ разрыва открытых позиций?
2. **IP-троттлинг:** один GlobalRateLimiter на все субаккаунты (общий IP-бюджет) ИЛИ per-UID лимиты с общим IP-cap? Как разделить бюджет между N субаккаунтами справедливо?
3. **Фаза 1 vs Фаза 2 порядок:** строить router сначала (масштаб) ИЛИ IP-троттлинг сначала (лечит текущую 100410-боль без субаккаунтов)?
4. **Order-counting источник:** доверять position_sync (REST, лаг) ИЛИ локальный счётчик pending (точнее, но рассинхрон при рестарте)? Гибрид?
5. **Sticky гранулярность:** symbol→account (одна пара=один суб) ИЛИ strategy→account (OTE на sub1, WAVE-FLAGMAN на sub2)? Второе проще изолирует, но пара может быть на обоих движках.
6. **Failure mode:** субаккаунт упал (ключ отозван/rate-limit) — как роутить его пары? Failover на другой суб (но позиции там)? Или freeze?
7. **Архитектурно (Куб):** AccountRouter = часть Execution Sphere. Как он соотносится с OrderManager — поглощает его ИЛИ слой над ним?
