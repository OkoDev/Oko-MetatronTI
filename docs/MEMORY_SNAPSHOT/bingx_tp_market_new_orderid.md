---
name: bingx-tp-market-new-orderid
description: BingX исполняет сработавший TAKE_PROFIT_MARKET/STOP под НОВЫМ orderId — матчить fill по поставленному oid нельзя
metadata: 
  node_type: memory
  type: project
  originSessionId: 53ad2006-69eb-4389-9eb0-02df4e0d45ab
---

**Факт (доказан 10.07.2026, IOTA #45257):** на BingX Swap условный ордер (TAKE_PROFIT_MARKET, вероятно и STOP_MARKET) при срабатывании исполняется под **новым orderId**. Поставленный oid в WS показывает только `X=TRIGGERED` и в `allOrders` как FILLED **не появляется**. Пример: поставлен `2075554896845299712`, fill лёг под `2075563066579226624`.

**Why:** любой код, который детектит исполнение условного ордера через `orderId == поставленный` (поллинг allOrders/get_filled_orders), молча не срабатывает никогда. Так сломался БУ-после-TP1 радара: be_activated не ставился → пивот-этажи не включались.

**How to apply:** матчить fill по комбинации: тип ордера (TAKE_PROFIT_MARKET/TAKE_PROFIT) + сторона закрытия (BUY для SHORT) + executedQty ≈ qty поставленного (±2%) + updateTime ≥ времени сетапа. Обычные LIMIT/MARKET исполняются под тем же oid — их матчить по oid можно (вход радара так и работает). Фикс: `_check_be_after_tp1` в [[bot/loops/radar_armed_loop.py]]. См. также [[bug_phantom_exit_resolve]] — соседний класс гонок с fills.

**Альтернатива (проверено на BONK 11.07):** GET `/openApi/swap/v2/trade/order?orderId=<старый oid>` возвращает НОВЫЙ исполненный ордер (новый orderId, status=FILLED, реальные stopPrice/qty) — биржа хранит связь. Точечный запрос по старому oid = самый надёжный детект исполнения условного ордера.

**Вторая ловушка (BONK 11.07):** `allOrders?limit=N` BingX отдаёт N СТАРЕЙШИХ ордеров символа, не свежие — окно-матчинг свежих fills слеп при длинной истории ордеров. Итог: детект исполнения условников = ТОЛЬКО точечный GET order по старому oid (`BingXClient.get_order`).
