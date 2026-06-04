---
name: feedback-no-fabricated-apis
description: "Никогда не вызывать методы/атрибуты которые \"должны логически существовать\" — только то что подтверждено grep'ом в коде"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 7eb11094-8711-4e7a-9c69-bf18fb7e5f76
triggers:
  - 'obj.method() где obj незнакомый'
  - 'новый адаптер/интеграция'
  - 'вызов из bot/exchange/data_collector/registry'
  - '''должен существовать'' / ''логически'''
---

# Не выдумывать API объектов

При написании нового кода **запрещено** вызывать методы/атрибуты предполагая что они существуют по аналогии или логически.

**Why:** 20.05.2026 написал в `bot/loops/arch104_observer_loop.py::_get_active_pairs` вызов `subscription_manager.get_active_subscriptions()` — такого метода нет, `SubscriptionManager` это про TG-подписчиков а не про универс пар. Observer 4.5ч молча работал на fallback-10 пар вместо реальных 241. Пользователь увидел `scanned=10` и спросил "10 пар?" — пришлось откатывать и переписывать.

**Реальный источник универса в этом проекте:**
- Универс торгуемых пар = `bot.monitored_pairs` (что и сканит `scan_all_pairs`)
- `SubscriptionManager` ≠ универс. Это таблица TG-подписчиков на алерты пар.

**How to apply:**
- Перед `obj.method()` где `obj` мне не знаком в этой сессии — `Grep "def method_name" path/to/obj.py`
- Особенно строго при интеграции нового модуля в существующий объект (bot, exchange, data_collector, registry)
- Если "логически должно быть" но grep пуст — НЕ писать предполагаемый вызов, спросить или прочитать класс целиком
- Связанные правила: [[feedback-grep-before-claim]] из CLAUDE.md
