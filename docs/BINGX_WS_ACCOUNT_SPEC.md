# BingX Swap WebSocket Account Data — спецификация (reference для EXECUTION-REBUILD)

> Источник: **официальный** `BingX-API/api-ai-skills` → `skills/swap-ws-account/api-reference.md` (19.06.2026).
> Альт: `npx skills add BingX-API/api-ai-skills` (BingX-овский Claude Code skill-пакет с полной API-reference, НЕ SPA).
> Зачем: эпик [[exec_sim_split_epic]] / EXECUTION-REBUILD — WS = ЕДИНЫЙ источник истины состояния позиции.
> Корень класса багов (призраки/fake-R/funding/cross) = НЕ использовали эти поля, городили REST-обёртки.

## 1. ListenKey lifecycle
- **Create:** `POST /openApi/user/auth/userDataStream` → `listenKey`. Rate 2/s per UID.
- **Keepalive:** valid 1ч, продлевать каждые 30 мин: `PUT /openApi/user/auth/userDataStream` (param `listenKey`) → +60 мин.
- **Expiry:** event `listenKeyExpired` {e, E, listenKey} → реконнект с новым ключом.
- **Delete:** `DELETE /openApi/user/auth/userDataStream`.

## 2. ORDER_TRADE_UPDATE (order update push) — fill-события
| Поле | Значение |
|------|----------|
| `e` / `E` / `T` | event id / event time ms / order update ts |
| `o.s` | символ пары |
| `o.i` | **orderId** (numeric) |
| `o.c` | clientOrderId |
| `o.S` | направление ордера: BUY / SELL |
| `o.o` | тип: MARKET, LIMIT, STOP, STOP_MARKET, TAKE_PROFIT, TAKE_PROFIT_MARKET, TRIGGER_LIMIT, TRIGGER_MARKET, TRAILING_STOP_MARKET, TRAILING_TP_SL, **LIQUIDATION** |
| `o.X` | статус: NEW, PARTIALLY_FILLED, **FILLED**, CANCELED, EXPIRED |
| `o.x` | execution type: NEW, **TRADE**, CANCELED, EXPIRED, CALCULATED |
| `o.q` / `o.z` / `o.l` | orig qty / total filled qty / last fill qty |
| `o.p` / `o.ap` / `o.L` | order price / **avg fill price** / last fill price |
| `o.ps` | позиция: LONG / SHORT / BOTH |
| `o.n` / `o.N` | **комиссия (fee)** / валюта комиссии |
| `o.rp` | **realized PnL по закрытой позиции** |

## 3. ACCOUNT_UPDATE — состояние позиции/баланса
- `a.P[].pa` — **position amount (size); pa=0 ИЛИ отсутствие записи = ФЛЭТ (закрыта)**
- `a.P[].mt` — margin mode: **cross / isolated**
- `a.P[].ps` — LONG / SHORT / BOTH
- `a.B[].a / wb / cw / bc` — asset / wallet balance / cross wallet / balance change
- `a.m` — триггер: DEPOSIT, WITHDRAW, ORDER, **FUNDING_FEE**

## 4. Open / Close / SL-TP — нет прямого флага, нужна корреляция ORDER_TRADE_UPDATE × ACCOUNT_UPDATE
- **OPEN:** `o.x=TRADE`, `o.o=MARKET`, не reduceOnly, `pa>0`, `o.rp=0`.
- **CLOSE:** `o.x=TRADE` уменьшает позицию; `pa`→0; `o.rp` = realized PnL.
- **SL/TP fill:** `o.o ∈ {STOP, STOP_MARKET, TAKE_PROFIT, TAKE_PROFIT_MARKET}`, `o.x=TRADE`.
- **Ликвидация:** `o.o=LIQUIDATION`.

## 🎯 Что эти поля закрывают (проблемы 19.06)
| Проблема дня | WS-поле = решение |
|--------------|-------------------|
| fake-R (REST `_resolve_exit` врал) | `o.ap` (реальный avg fill) + `o.rp` (realized PnL) |
| $-метрика истины (profit_pct×notional) | `o.rp` напрямую |
| Комиссии (оценка таблицей −$169) | `o.n` (fee per fill) |
| Funding-разрыв (−$266 untracked) | `a.m=FUNDING_FEE` события |
| Призраки/orphan (close-by-price ложно) | `a.P[].pa=0` = надёжный флэт |
| Cross-дрейф (acc2) | `a.P[].mt` (cross/isolated) |
| SL-за-ликвидацией (POPCAT) | `o.o=LIQUIDATION` |

## Текущее использование в боте (что уже есть, `core/exchange/exec_ws_integration.py`)
- ЭТАП 2a: `ORDER_TRADE_UPDATE FILLED MARKET ro=false` → запись exchange_order_id (открытие). Использует `o.X/o.o/ro`.
- 2a': закрывающий FILLED → запоминает `ap` (реальный exit).
- ЭТАП 2b: `ACCOUNT_UPDATE pa=0` → `close_trade` по реальному флэту.
- **НЕ используются:** `o.rp` (realized PnL), `o.n` (fee), `a.m=FUNDING_FEE`, `o.o=LIQUIDATION`, `a.P[].mt`. ← дельта для EXECUTION-REBUILD.
- **Конкурент:** `position_sync:504` REST close-by-price опережает WS pa=0 по 15s-кэшу → ложные закрытия = призраки. УБРАТЬ при переходе на WS-истину.
