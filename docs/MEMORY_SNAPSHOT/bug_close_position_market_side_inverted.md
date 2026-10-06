---
name: bug_close_position_market_side_inverted
description: "✅ ПОЧИНЕНО 14.08 · close_position_market(side) ждёт сторону ОТКРЫТИЯ (BUY=закрыть LONG), а position_sync/radar передают сторону закрытия → 101205 всегда, спасает лишь one-click fallback (закрывает ВСЮ позицию)"
metadata: 
  node_type: memory
  type: project
  originSessionId: 8a85002d-70e3-47a1-91f1-8bb41a7089c3
  modified: 2026-08-14T17:40:20.543Z
---

# 🔴 close_position_market: side = сторона ОТКРЫТИЯ, половина проекта зовёт наоборот (14.08.2026)

Найдено при реализации закрытия позиции с графика: частичное закрытие BTC вернуло
`101205 No position to close`, хотя позиция была на месте.

**Контракт функции** (`core/exchange/bingx_client.py`): внутри `close_side = "SELL" if side == "BUY"`,
`pos_side = "LONG" if side == "BUY"`. То есть **`side` — сторона ОТКРЫТИЯ**: `BUY` = закрыть LONG.
Так же это описано в `scripts/close_hedge_orphans.py`. Передашь сторону закрытия — биржа ищет
противоположную позицию и отвечает 101205.

| вызов | как зовёт | итог |
|---|---|---|
| `order_manager.close_partial` (TP1) | `"BUY" if direction=="LONG"` | ✅ верно |
| `position_sync:291` emergency close | `"SELL" if direction=="LONG"` | ❌ 101205, БЕЗ one-click |
| `position_sync:477`, `:1057` (D-070 autoclose) | `"SELL" if LONG` | ❌ спасает one-click fallback |
| `radar_armed_loop:586` | `"SELL" if LONG` | ❌ 101205, БЕЗ one-click |

**Доказательство из боевого лога (05:39):** MELANIA/RSR — `close_position_market code=101205 …
→ one-click fallback` → `✅ закрыт one-click`. Все четыре D-070 закрытия прошли НЕ market-ордером,
а one-click'ом, то есть маскировка бага работала.

**Цена:** где `one_click_on_fail=False` (emergency в position_sync, radar) закрытие просто НЕ
происходит — позиция остаётся. Где fallback есть, он закрывает **всю** позицию целиком, что для
частичного выхода было бы катастрофой.

**Как правильно:** `close_position_market(sym, "BUY" if pos_side=="LONG" else "SELL", qty, position_id=…)`.
В `web/structure_terminal.py::api_close` уже исправлено (там `open_side`), проверено на VST:
частичное закрытие 0.0003 → 0.0002 с перестановкой SL/TP на остаток, затем полное.

Связано: [[orphan_root_dbexch_desync]], [[hedge_close_multiacct_root]].

## ✅ ПОЧИНЕНО 14.08.2026

Исправлены все вызовы, передававшие сторону закрытия: `position_sync` (emergency :294, dust :477,
D-070 autoclose :1058), `radar_armed_loop:590` (фиксация у потолка), `bingx_adapter.close_reduce_only`,
`order_manager:981` (SL пробит → close market), `scripts/close_orphans.py:101`.
Верно и раньше были: `order_manager.close_partial`, `close_leaked_positions`, `close_orphan_positions`.
В докстринге `close_position_market` теперь явное предупреждение о контракте.

**Проверка контракта экспериментом (VST):** открыл SOL LONG 0.33 → `close_position_market(sym,"BUY",
qty, one_click_on_fail=False)` → позиция CLOSED. Без fallback'а, то есть market-close прошёл сам.
После рестарта бота: **0 записей 101205 и 0 one-click** за первые минуты (были постоянными).
⏳ Не наблюдалось ещё ни одного реального emergency/CEIL-события — подтвердить на первом случае.
