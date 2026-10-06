---
name: hedge_close_multiacct_root
description: "КОРЕНЬ ошибок 101205/109400 при закрытии hedge-orphan — multiacct routing, позиция на суб-аккаунте"
metadata: 
  node_type: memory
  type: project
  originSessionId: 9d582948-c9be-42e6-8444-4165a225d1fa
---

# 🔑 Hedge-close: КОРЕНЬ 101205 = multiacct routing (12.06.2026)

**Симптом:** закрытие hedge-orphan давало `101205 "No position to close"` даже с «правильным» positionId. Точечный MARKET-close на одних символах (AT) → `code=0`, на других (TA/BNLIFE/ESPORTS) → `101205`. Казалось «то работает, то нет».

**КОРЕНЬ (не метод close, а ROUTING):** проект `multiacct=True` (`arch96.multiaccount.enabled`). `OrderManager._get_positions_cached()` агрегирует позиции **ВСЕХ суб-аккаунтов**, помечая `p["_account"]=acc` (order_manager.py:172-186). Но closer бил `POST /trade/order` через **основной** client (acc=1). Позиции TA/BNLIFE/ESPORTS жили на **acc=2** → основной аккаунт их не видит → биржа честно отвечает `101205`. AT случайно был на acc=1 → срабатывало.

**Доп. ловушка:** `_get_positions_cached` TTL=15с (order_manager.py:165) — отдаёт **stale** список. Прямой `GET /user/positions` (только основной acc) показывал TA/BNLIFE как «закрытые» (их нет на acc1), а кэш-агрегат — как живые на acc2. Выглядело как «фантом кэша», но позиции реальны — просто на другом аккаунте.

## ✅ РАБОЧИЙ hedge-close (универсальный, multiacct-aware)
1. `acc = p.raw.get("_account")` — на каком суб-аккаунте позиция (parse_positions хранит исходник в `Position.raw`).
2. `pid = p.raw.get("positionId")` — точный positionId есть прямо в raw (НЕ нужен отдельный запрос/parser).
3. `cli = router.client_for_account(acc)` (`om._get_router()`), `await cli.sync_time()` — client ЭТОГО аккаунта.
4. `POST /openApi/swap/v2/trade/order`: `{symbol, side(противоположный: SELL для LONG/BUY для SHORT), positionSide(=direction), type:MARKET, quantity, positionId}` **БЕЗ reduceOnly**.
→ `code=0`. Проверено: **10/10 hedge-orphan закрыты, 0 ошибок** (все были на acc=2).

**Реализация:** `scripts/close_hedge_orphans.py` (router + client_for_account + positionId из raw). One-click `closeAllPositions` оставлен fallback ТОЛЬКО когда биржевого брата нет (qty=0 → БД-брат SIM) — иначе one-click снёс бы брата.

**Вывод для терминала (user: «решить разом, не точечно»):** любой close-path при multiacct ОБЯЗАН роутить по `_account` позиции, иначе orphan на суб-аккаунтах неубиваем. Это надо вшить в `order_manager.close_position_market` / EXEC-WS sync-close. Связь: [[exec_ws_vst_userdata_proven]] (push position-close мгновенно sync), [[feedback_read_bingx_docs]].

## ✅ ДЕДУП master↔sub в шине (27.06.2026) — та же multiacct-природа
Симптом: дашборд sync-panel показывал 21 позицию = 11 уникальных + 10 дублей. Корень тот же:
мастер-ключ acc1 (`BINGX_VST_API_KEY`) тянет позиции ОБОИХ аккаунтов (своя 1 + 10 суба),
acc2-ключ тянет свои 10 → каждая суб-позиция в шину дважды (acc1-фантом + acc2-реал).
Пути: REST `position_sync:437` `set_account_positions(1, ...)` (мастер видит всё) + WS
`exec_ws_integration:337` `update_position(_ACC_TAG_TO_INT[tag], ...)` (acc1+acc2 стримы).
**ФИКС:** дедуп на ЧТЕНИИ в `pair_context.all_positions()` — суб (account_id>1) авторитетен
для своих позиций, его (symbol, side) вытесняет копию мастера (acc1). Дедуп на чтении т.к.
ACCOUNT_UPDATE P[] суб-id НЕ несёт (только pa/mt/ps/s/ep/up, см. BINGX_WS_ACCOUNT_SPEC) →
владельца на событии мастера знать нельзя; read-dedup устойчив к порядку стримов.
Тест `tests/unit/test_pair_context_dedup.py` (3 кейса: дедуп/single-acc/opposite-sides). 21→11.
