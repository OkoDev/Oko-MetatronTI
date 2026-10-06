---
name: bot_autocloses_manual_positions_d070
description: "🔴 Бот закрывает ЛЮБУЮ позицию на своём счёте без OPEN-записи в БД (D-070 orphan_autoclose=live). Съел 4 ручные позиции с монитора. Защита — таблица manual_positions, читается в _detect_orphans"
metadata: 
  node_type: memory
  type: project
  originSessionId: 8a85002d-70e3-47a1-91f1-8bb41a7089c3
  modified: 2026-08-14T16:24:06.642Z
---

# 🔴 Бот закрывает ручные позиции как orphan (14.08.2026)

Егор спросил «бот не закроет мои позиции при проверке DRIFT?» — проверка показала, что **уже закрыл**:

```
05:14:29 [D-070][autoclose][live] RPL/USDT:USDT LONG ЗАКРЫТ market
05:39:02 [D-070][autoclose][live] YFI ЗАКРЫТ · 05:39:09 MELANIA · 05:39:15 RSR
```

**Механика:** `config.yaml:295 orphan_autoclose: live` + `execution_mode: vst` — бот торгует на ТОМ ЖЕ
счёте, где человек открывает руками. `_detect_orphans` считает orphan'ом любую позицию биржи, чьей
пары (symbol, side) нет в OPEN-записях `simulated_trades` → `close_position_market(one_click_on_fail=True)`.
Hedge-safety спасает только символы, где у бота есть своя OPEN по другой стороне; «чистый» ручной
символ закрывается без вопросов. Уйти на субаккаунт НЕ помогает: `AccountRouter` сканирует аккаунты 1–4.

**Защита (сделано):** таблица `manual_positions` в `subscriptions.db` + ~20 строк в
`core/exchange/position_sync.py::_detect_orphans` — активные ручные пары идут в `tracked_pairs`,
а пары, которых уже нет на бирже, помечаются `closed_at` там же. Монитор :8010 пишет туда каждую
сделку (`_register_manual` в `web/structure_terminal.py`).

🔑 **Намеренно НЕ в `simulated_trades`**: попади ручная сделка туда — TSL-updater переставил бы стоп
человеку, а форвард-табло посчитало бы чужую сделку своей статистикой ([[forward_machine_sphere11]]).

**How to apply:** любой новый путь, открывающий позиции мимо `trade_simulator` (скрипт, ручной вызов,
внешний терминал), ОБЯЗАН зарегистрироваться в `manual_positions` — иначе бот её закроет в течение
минуты. Связано: [[orphan_root_dbexch_desync]], [[adopt_manual_trades_vision]].
