# 🏛️ EXECUTION SPHERE — дизайн Ф2 (контракт единого слоя исполнения)

> **Это Ф2 эпика [EXECUTION_REBUILD_EPIC.md](EXECUTION_REBUILD_EPIC.md).** Ф0 (карта хаоса) и Ф1 (API-меню) закрыты.
> Здесь — ЦЕЛЕВОЙ контракт: интерфейсы, доменная модель, правило-истина, карта поглощения 8 узлов, порядок миграции.
> Код Ф3/Ф4 пишется ПО этому документу. Close-path не кодить без теста на копии БД (инцидент ложного закрытия 2026-04-07).
>
> Заземление: все имена методов/строк ниже проверены grep'ом по коду 19.06.2026. Поглощает ARCH-96-HUB, ARCH-96-EXEC, EXEC-SIM-SPLIT (#21).

---

## 0. Принципы (из эпика §3, здесь — операционализированы)

1. **ОДИН слой исполнения.** Любой open/close/track/state идёт через `ExecutionSphere`. Прямых вызовов `order_manager`/`position_sync`/`close_trade` из бизнес-кода больше нет.
2. **WS = ЕДИНСТВЕННЫЙ источник истины состояния позиции.** REST = (а) команды (place/cancel/leverage/margin), (б) cold-start снимок при запуске, (в) read-only сверка-сторож, которая **только алертит** о рассинхроне, но **никогда не метит closed по цене**.
3. **`account` + `exchange` = ПАРАМЕТРЫ.** Sphere не знает слова «BingX». Биржевая специфика — за `ExchangeAdapter`. Account берётся **из позиции** (positionId/raw), не из предположения main.
4. **Один калькулятор** ([[principle_reuse_not_duplication]]). sizing/SL/TP/R-математика — общие для SIM и VST. Различие SIM↔VST = ОДНА ветка «трогаем ли биржу», а не два пайплайна.

---

## 1. Слои (целевая структура `core/execution/`)

```
ExecutionSphere            ← оркестратор, exchange/account-агностичный (бизнес зовёт ТОЛЬКО его)
  ├─ ExchangeAdapter (ABC) ── BingXAdapter  (ccxt + bingx-специфика: positionId, one_click, 109400)
  │                        └─ (future) другой Adapter — Sphere не меняется
  ├─ AccountRouter         ← СУЩЕСТВУЕТ (core/exchange/account_router.py), reuse как есть (sticky symbol→account)
  ├─ PositionStore         ← НОВОЕ: единственный владелец состояния позиций (WS-истина + cold-start)
  └─ ExecutionLedger       ← НОВОЕ: realized PnL / fee / funding из WS (o.rp / o.n / a.m=FUNDING_FEE)
```

**Почему PositionStore отдельно:** сейчас состояние «жива ли позиция» собирается тремя путями (WS `pa=0`, REST polling `open_pairs`, SIM close-by-price свечой). PositionStore делает его ОДНИМ: WS пишет истину, REST только инициализирует/сверяет. Это и есть удаление корня призраков.

---

## 2. Доменная модель (dataclasses, биржа-агностичные)

```python
@dataclass(frozen=True)
class OrderRequest:
    symbol: str            # 'XLM/USDT:USDT' (наш формат)
    direction: str         # LONG | SHORT
    entry_price: float
    sl: float
    tp: float
    qty: float
    leverage: int | None   # None → глобал-fallback внутри adapter
    mode: str              # 'sim' | 'vst' | 'live'  ← единственный переключатель песочницы
    account: int | None    # None → AccountRouter.route(symbol)
    source: str            # ote_nested / ... (для policy/метрик)
    meta: dict             # extra_features, regime и т.д.

@dataclass(frozen=True)
class OrderResult:
    success: bool
    symbol: str
    direction: str
    qty: float
    entry_price: float     # фактический avgPrice fill (o.ap), не запрошенный
    sl: float
    tp: float
    order_id: str | None
    sl_order_id: str | None
    tp_order_id: str | None
    position_id: str | None  # якорь жизни позиции (вход+SL+TP+перевыставления = один pid)
    leverage: int            # ФАКТ после клампа
    account: int
    notional_usdt: float
    error: str | None

@dataclass
class Position:             # «что реально на бирже СЕЙЧАС» — из WS, не REST polling
    symbol: str
    side: str               # LONG | SHORT
    qty: float              # pa; 0 == флэт == удалить
    entry: float            # ep
    mark: float | None
    upnl: float | None
    leverage: int | None
    margin_mode: str | None # mt: cross | isolated
    position_id: str | None
    account: int
    updated_ts: float

@dataclass(frozen=True)
class Fill:                 # из ORDER_TRADE_UPDATE
    symbol: str; side: str; pos_side: str
    order_id: str; position_id: str | None
    order_type: str         # MARKET/STOP/TAKE_PROFIT/LIQUIDATION/...
    status: str             # FILLED/PARTIALLY_FILLED/...
    is_reduce_only: bool
    avg_price: float        # o.ap — реальный exit (анти-fakeR)
    last_qty: float; total_qty: float
    realized_pnl: float     # o.rp — $-истина
    fee: float              # o.n
    fee_asset: str

@dataclass(frozen=True)
class CloseResult:
    success: bool; symbol: str; position_id: str | None
    exit_price: float | None; realized_pnl: float | None
    status: str             # SL | TP | TSL | LIQUIDATION | MANUAL
    error: str | None

@dataclass(frozen=True)
class LedgerEntry:
    account: int; ts: float
    kind: str               # REALIZED_PNL | COMMISSION | FUNDING_FEE | LIQUIDATION
    symbol: str | None; amount: float; asset: str
```

---

## 3. `ExchangeAdapter` — граница multi-exchange (ABC)

Тест чистоты (ARCH-96-HUB): этот интерфейс описывается БЕЗ слова «BingX». Методы заземлены в том, что `BingXClient`/`order_manager` уже умеют.

```python
class ExchangeAdapter(ABC):
    # ── КОМАНДЫ (REST) ──────────────────────────────────────────────
    async def place_bracket(self, req: OrderRequest) -> OrderResult: ...
        # market entry + SL + TP одним вызовом. Внутри: set_leverage, кламп к max пары,
        # SL-safety кап, min_notional/min_sl_dist guard (сейчас order_manager.open_bracket:383-541).
    async def place_sl(self, symbol, side, sl, qty, account, position_id=None) -> str | None: ...
    async def place_tp(self, symbol, side, tp, qty, account, position_id=None) -> str | None: ...
    async def cancel(self, symbol, order_id, account) -> bool: ...
    async def close_reduce_only(self, symbol, side, qty, account, position_id=None) -> CloseResult: ...
        # reduceOnly market; fallback one_click. КОРЕНЬ hedge-close 101205 = account+positionId ИЗ позиции.
    async def set_leverage(self, symbol, side, lev, account) -> int: ...   # → факт
    async def get_max_leverage(self, symbol, side, account) -> int | None: ...
    async def set_margin_mode(self, symbol, mode, account) -> bool: ...    # ENFORCE isolated (кирпич бэклога)

    # ── ХОЛОДНЫЙ СНИМОК / СВЕРКА (REST, read-only) ─────────────────
    async def get_positions(self, account) -> list[Position]: ...
    async def get_filled(self, symbol, account, limit=50) -> list[dict]: ...  # резерв для cold-start статуса
    async def balances(self, account) -> dict: ...   # equity/available/used_margin/upnl

    # ── ИСТИНА СОСТОЯНИЯ (WS) ──────────────────────────────────────
    async def open_user_stream(self, account, on_event: Callable) -> Task: ...
        # listenKey lifecycle + reconnect (user_data_ws.UserDataStream уже это делает)
    def normalize_event(self, raw: dict) -> list[ExecEvent]: ...
        # сырой ORDER_TRADE_UPDATE/ACCOUNT_UPDATE → доменные ExecEvent (Fill / PositionUpdate /
        # LedgerEntry / MarginMode / EquityUpdate / ListenKeyExpired). ВСЯ парсинг-специфика биржи — ЗДЕСЬ.
```

`ExecEvent` — sealed union: `FillEvent(Fill)`, `PositionEvent(Position)`, `LedgerEvent(LedgerEntry)`, `LiquidationEvent`, `MarginModeEvent`, `EquityEvent`, `ListenKeyExpiredEvent`. Sphere работает только с ними — не с `o.`/`a.` сырьём.

---

## 4. `ExecutionSphere` — контракт (open / close / track / state)

```python
class ExecutionSphere:
    def __init__(self, adapter: ExchangeAdapter, account_router: AccountRouter,
                 store: PositionStore, ledger: ExecutionLedger, calc: ExecutionCalc): ...

    # ── OPEN ───────────────────────────────────────────────────────
    async def open(self, req: OrderRequest) -> OrderResult:
        # 1. account = req.account or router.route(symbol)
        # 2. guards (min_sl_dist/sl_direction/min_notional) — общий ExecutionCalc, ОДИН раз
        # 3. mode=='sim' → НЕ трогаем биржу, OrderResult(order_id=None) → research-БД
        # 4. mode in (vst,live) → adapter.place_bracket(req)
        # 5. store.bind_pending(...)  (positionId дозахватится WS-fill'ом, не REST-ретраями)
        # возврат OrderResult — вызывающий пишет в БД через единый ExecutionRepo

    # ── CLOSE (единственная авторитетная команда закрытия) ─────────
    async def close(self, position_id: str, reason: str) -> CloseResult:
        # account + side + qty ИЗ store.position(position_id) — не из предположения
        # adapter.close_reduce_only(...); фактический флэт подтвердит WS pa=0 (не метим closed тут оптимистично)

    # ── WS-ИСТИНА (единственный вход для on_event всех аккаунтов) ──
    async def on_event(self, account: int, ev: ExecEvent) -> None:
        # FillEvent open  → store.bind(order_id, position_id, real entry o.ap, exec_mode)
        # FillEvent close → store.record_exit(position_id, o.ap, o.rp, o.n) + ledger
        # PositionEvent pa=0 → store.mark_flat → ЕДИНСТВЕННЫЙ путь close в БД (status/exit из record_exit)
        # PositionEvent pa>0 → store.upsert (qty/entry/upnl/mt/leverage) → шина
        # LiquidationEvent → close как LIQUIDATION + alert
        # LedgerEvent(FUNDING/COMMISSION/REALIZED) → ledger (закрывает untracked −$266/−$169)
        # MarginModeEvent cross → alert (дрейф) ; EquityEvent → шина

    # ── TRACK (TSL — через Sphere, не отдельный REST-цикл) ─────────
    async def adjust_sl(self, position_id: str, new_sl: float) -> bool: ...

    # ── STATE (для дашборда/сайзинга — из WS-снимка, НЕ REST polling) ─
    def state(self, account: int | None = None) -> list[Position]:
        return self._store.positions(account)
```

**ExecutionCalc** = чистые функции (sizing `calc_qty`, R-math, SL/TP guards, leverage clamps SL-safety). Один и тот же код для sim и vst → метрики сравнимы. Сейчас это размазано: `position_sizer.calc_qty`, `order_manager` guards, `trade_simulator` R-math, `_resolve_exit` классификация. Собрать в один модуль без поведенческого дрейфа.

---

## 5. WS = истина: таблица «событие → действие» (ядро Ф4)

| WS-сигнал (поле) | ExecEvent | Действие Sphere | Закрывает дыру |
|---|---|---|---|
| `o.X=FILLED o.o=MARKET !ro` | FillEvent(open) | bind order_id+positionId+**o.ap**(реал.вход)+exec_mode | exch_id=None семья (2a уже есть) |
| `o.X=FILLED` reduceOnly/STOP/TP | FillEvent(close) | record_exit: **o.ap** exit, **o.rp** realized, **o.n** fee | fake-R, profit_pct×notional, комиссии |
| `o.o=LIQUIDATION` | LiquidationEvent | close LIQUIDATION + alert | SL-за-ликвидацией невидим |
| `a.P[].pa=0` | PositionEvent(flat) | **ЕДИНСТВЕННЫЙ** close в БД | призраки (REST close-by-price убран) |
| `a.P[].pa>0` | PositionEvent | store.upsert + шина | дашборд-оперативка из шины |
| `a.P[].mt=cross` | MarginModeEvent | alert/ENFORCE isolated | cross-дрейф acc2 (−$322) |
| `a.m=FUNDING_FEE` | LedgerEvent | funding-леджер | untracked funding −$266 |
| `a.B[].wb` (USDT) | EquityEvent | шина equity (push) | equity без REST-poll |
| `listenKeyExpired` | ListenKeyExpired | reconnect новый ключ | разрыв WS-истины |

**Сейчас НЕ используются** (`BINGX_WS_ACCOUNT_SPEC.md:59`): `o.rp`, `o.n`, `a.m=FUNDING_FEE`, `o.o=LIQUIDATION`, `a.P[].mt`. Это вся дельта Ф4 поверх существующего 2a/2b.

---

## 6. Правило-истина закрытия (КОРЕНЬ, ради которого всё)

**Сейчас три конкурирующих закрытия:**
1. WS `pa=0` → `_sync_close_async` (надёжно) — `exec_ws_integration.py:129,234-274`
2. REST polling `(sym,dir) not in open_pairs` → close-by-price — `position_sync.py:501-654` ← **ложно метит closed по 15s-кэшу → призраки**
3. SIM close-by-price свечой — `trade_simulator.check_open_trades`

**Целевое правило:**
- VST/LIVE закрытие в БД метит **ТОЛЬКО** `on_event(PositionEvent pa=0)` + `record_exit`. Один автор.
- `position_sync.py:501-654` close-by-price → **УДАЛИТЬ.**
- `position_sync` остаётся ТОЛЬКО как read-only сторож (cold-start снимок + watchdog ниже).
- SIM close-by-price остаётся ТОЛЬКО для `mode=='sim'` (research-БД), к бирже отношения не имеет.

**Страховка от потерянного/дропнутого WS-события (рефинмент роя 19.06, консенсус 5/5 + спор groq/openrouter):**
WS может дропнуть событие (DEV-228/230: перегрузка event loop, ccxt.pro лимиты). Чтобы не зависнуть OPEN навсегда — **bounded-staleness watchdog**, НЕ возврат close-by-price:
1. **Метрика WS-staleness:** считаем «тиков без ACCOUNT_UPDATE по аккаунту» + время. На дашборд + алерт при превышении (рано видим дроп).
2. **Watchdog с таймаутом:** если БД OPEN, а REST-снимок (`get_positions` этого sym+account) показывает флэт **N циклов / T секунд подряд** → эскалация: `ExecutionSphere.close(position_id, reason="ws_drop_verify_flat")`. Это **тот же авторитетный канал** (verify-flat перед закрытием), а не параллельный close-by-price. Гонки/двойного закрытия нет (один автор close — Sphere; idempotent по position_id).
3. Так текущий `orphan_autoclose: shadow` становится правильным live-механизмом через единый канал.
**Отличие от удалённого close-by-price:** старый метил closed по 15s-кэшу цены **сразу** (ложно→призраки); watchdog закрывает **только** после подтверждённого флэта на бирже N циклов и **только** через Sphere.close. Цена в решении не участвует.

---

## 7. SIM / VST split внутри Sphere (поглощает #21)

- `OrderRequest.mode` — единственный переключатель. `open()`: `sim` → ранний возврат без adapter; `vst/live` → adapter.
- Разные БД: `live.db` (VST=истина) / `sim.db` (research). Сейчас всё в `subscriptions.db` с `execution_mode`-флагом → «у кого ID есть, у кого нет». Запись идёт через `ExecutionRepo`, который роутит по mode.
- Единый калькулятор гарантирует: SIM-сделка = «та же сделка, только не отправлена на биржу». Сравнение sim↔vst становится честным (сейчас APEX fake −15R от смешения).
- Обучение (`performance_engine`) читает live.db (VST) — SIM-фантомы физически в другой БД, не могут протечь в веса.

---

## 8. Карта поглощения: 8 узлов → новые роли

| Узел сейчас (файл) | Что с ним | Куда переезжает |
|---|---|---|
| `order_manager.open_bracket` :383 | → `BingXAdapter.place_bracket` | guards/клампы → ExecutionCalc; REST place → adapter |
| `order_manager.place_sl/tp/cancel/close_partial` | → методы BingXAdapter | как есть, под интерфейс |
| `trade_router._place_exchange_order` :232 | тоньше | зовёт `Sphere.open(req)`; БД-запись → ExecutionRepo |
| `trade_simulator.close_trade` :1601 | остаётся как БД-операция | вызывается ТОЛЬКО из Sphere.on_event (не из position_sync) |
| `trade_simulator.check_open_trades` | только SIM-режим | close-by-price → research-БД |
| `position_sync.sync_positions` :298 | **режется** | close-by-price (501-654) УДАЛИТЬ; остаётся cold-start + orphan-алерт |
| `position_sync._resolve_exit` :36 | резерв | только cold-start статус (когда WS-истории нет); в норме exit из WS o.ap |
| `position_sync._emergency_close_check` :127 | → `Sphere.close` | через единый канал |
| `position_sync._detect_orphans` :673 | остаётся | алерт + `Sphere.close` (verify-flat авторитетный) |
| `position_sync` `upsert_positions(1,...)` :364 | **фикс** | account из позиции (не хардкод acc1) → PositionStore |
| `exec_ws_integration` 2a/2b :187 | → `Sphere.on_event` | + добивает o.rp/o.n/FUNDING/LIQUIDATION/mt |
| `user_data_ws.UserDataStream` :45 | reuse | → `BingXAdapter.open_user_stream` |
| `tsl_updater` (sl/tp/positionId capture, TSL) | расщепить | positionId/exch_id capture → не нужен (WS-fill даёт нативно); TSL → `Sphere.adjust_sl` |
| `account_router.AccountRouter` | reuse как есть | внедряется в Sphere |

---

## 9. Порядок миграции (Ф3 → Ф4, безопасно)

> Правило: каждый шаг — аддитивен и за флагом; close-path — только после теста на копии БД.

- **Ф3.1** Каркас: `core/execution/` — доменная модель (§2) + `ExchangeAdapter` ABC + `ExecutionCalc` (перенос чистых функций БЕЗ поведенческого дрейфа, parity-тест против старых).
- **Ф3.2** `BingXAdapter` — обёртка над существующими `BingXClient`/`order_manager`/`user_data_ws` (НЕ переписывать биржевые вызовы, только под интерфейс). `normalize_event` парсит то же, что `exec_ws_integration` сейчас.
- **Ф3.3** `PositionStore` + `ExecutionLedger` — наполняются из WS (o.rp/o.n/FUNDING/LIQUIDATION/mt), пока **в shadow** (пишут леджер, дашборд читает, но close-path ещё старый). Сверить леджер $ с balance_snapshots.
- **Ф3.4** SIM/VST split БД (`live.db`/`sim.db`) + `ExecutionRepo` — миграция данных, parity.
- **Ф4.1** Переключить close: `on_event(pa=0)` = единственный автор; **выключить** `position_sync` close-by-price (флаг `position_sync.close_by_price: off`). 🔴 ТЕСТ НА КОПИИ БД перед боем.
- **Ф4.2** orphan/emergency/dust → через `Sphere.close`; `orphan_autoclose: live` через единый канал (verify-flat).
- **Ф4.3** `open()`/`adjust_sl` через Sphere; trade_router тоньше.
- **Ф5** Дашборд: секция БИРЖА (Sphere.state из WS) / секция БД-история (live.db: open/close время, o.ap, o.rp, o.n, R) / секция SIM (sim.db). Эпик §5.

Метрика истины на каждом шаге = **$ из balance_snapshots / WS `o.rp`**, не R (эпик §9.4).

---

## 10. Развилки — РЕШЕНЫ (ревью роя 19.06, консенсус 5/5; обсуждение `memory/last_team_discussion.md`)

1. **REST-сторож:** ✅ **алерт-only + авто-close ТОЛЬКО через `Sphere.close` с verify-flat** (watchdog §6, таймаут-gated). close-by-price не возвращать ни в каком виде. (5/5)
2. **BingXAdapter Ф3.2:** ✅ **тонкая обёртка** над текущим `BingXClient`/`order_manager`/`user_data_ws`. ccxt-rewrite — отдельный бэклог, не блокирует корень. (4/4 высказавшихся)
3. **БД:** ✅ **физический `live.db`/`sim.db` split** (изоляция данных > простота). (4/4)
4. **TSL:** ✅ **команды через `Sphere.adjust_sl`** сейчас; reactive-TSL из on_event — позже. (4/4)

**Дополнительно из ревью (вносится в план):**
- **Cold-start reconcile** (уникальный аргумент openrouter): при старте PositionStore инициализируется снимком `get_positions`, а ExecutionLedger сверяется с `balance_snapshots` ($ из WS o.rp ↔ equity). Риск рассинхрона Store↔Ledger при холодном старте — закрыть явным шагом инициализации (Ф3.3).
- **WS-staleness метрика на дашборд** + алерт при пропуске >N ACCOUNT_UPDATE (раннее обнаружение дропа, §6).

## 10a. Открытые caveats (на проработку в Ф3.2-Ф4, поднял рой)
- **reconnect при `listenKeyExpired`** — устойчивость при длительных разрывах не покрыта тестами (sambanova). Нужен тест долгого разрыва.
- **downstream-потребители позиций** — миграция на PositionStore сломает аналитику/дашборд, если те читают БД/REST напрямую, не через шину. Составить карту потребителей ПЕРЕД Ф4 (sambanova).
- **производительность PositionStore cold-start** при многих аккаунтах/позициях (связь с таймаутами дашборда DEV-231 не ясна).

---

## 11. Соответствие Кубу Метатрона

- **Сфера 14 — Execution Sphere** (этот документ) = единый узел исполнения. Закрывает «11/12 сфер» → 12/12.
- **Shared Context Bus:** PositionStore/Ledger пушат в шину (equity/позиции/leverage/mt уже идут — `exec_ws_integration.py:223-254`). Дашборд-оперативка из шины ([[dashboard_oper_from_bus_analytics_sql]]).
- **Ребро:** `account → exchange → symbol → position` иерархия (ARCH-96-HUB) — Sphere её материализует.
- **Feedback loop:** честный realized PnL (o.rp) в `performance_engine` → веса сигналов учатся на $-истине, не на fake-R.

---

*Ф2 черновик. Со свежей головой → ревью ARCH/рой → Ф3.1 каркас. Даат, 19.06.2026.*
