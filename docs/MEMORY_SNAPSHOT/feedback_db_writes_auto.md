---
name: feedback_db_writes_auto
description: Правки боевой БД (UPDATE/закрытие сделок) выполнять БЕЗ подтверждения — юзер разрешил
metadata: 
  node_type: memory
  triggers: 
    - UPDATE
    - боевая БД
    - закрыть сделку
    - правка БД
  type: feedback
  originSessionId: 9d582948-c9be-42e6-8444-4165a225d1fa
---

Правки боевой БД `subscriptions.db` (UPDATE status, закрытие orphan-сделок, синхронизация БД↔биржа) выполнять СРАЗУ, без запроса подтверждения.

**Why:** юзер 08.06 явно сказал «в БД закрывай без подтверждения». Он в активной торговой работе, частые синки БД↔биржа — подтверждения тормозят.

**How to apply:** UPDATE/закрытие в `simulated_trades` (status, R, синхронизация) — выполнять напрямую + показать результат. ОСТОРОЖНО всё равно: INSERT/register_trade проверять runtime ([[feedback_ast_parse_no_scope]]); DROP/массовый DELETE — это другое, там подтверждение. Граница: рутинные UPDATE/sync = auto; деструктив схемы = спросить.
