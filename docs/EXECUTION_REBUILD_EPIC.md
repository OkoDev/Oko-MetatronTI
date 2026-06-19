# 🏛️ EXECUTION-REBUILD — ТЗ полной перестройки исполнения (для новой сессии)

> **Манифест юзера (19.06.2026):** «Хватит латать дыры и ставить заплатки — деньги утекают всё равно.
> Нужно полностью перестроить узлы входа/выхода/мониторинга сделки на бирже. Скудное лоскутное
> одеяло → явно определённые узлы, где всё сконцентрировано. Это ДЕНЬГИ. SIM должен быть отделён —
> он изжил себя как информативная структура; VST = боевая песочница = истина. Дашборд должен
> ЧЁТКО разделять: что мы видим с биржи и что у нас в базе.»
>
> Этот документ = единая карта для перестройки. Читать ПЕРЕД кодом. Поглощает [[exec_sim_split_epic]] (#21),
> ARCH-96-HUB, Execution Sphere (Сфера 14 Куба). Pre-flight: `docs/BINGX_WS_ACCOUNT_SPEC.md` +
> skills `.agents/skills/bingx-swap-*` (api-reference.md) + [[bingx_ai_skills_installed]].

---

## 1. ДЫРЫ ДЕНЕГ (доказано данными 19.06) — почему заплатки не лечат

Просадка VST −48%/нед разложена: **бумага +$21 + стратегия(closed) +$2 + REST −$435**. Стратегия НЕ виновата.
REST −$435 = **издержки + утечки мимо tracked-потока**, все из ОДНОГО корня — лоскутное исполнение:

| Дыра | Цифра/факт | Корневой механизм |
|------|-----------|-------------------|
| **Призраки/orphan** | DOLPHIN/PARTI/Q exch-only, течь −$268/3.6ч | `position_sync:504` close-by-price метит БД closed по 15s-кэшу → позиция жива (конкурент WS pa=0) |
| **Комиссии** | −$169/нед (6835 сделок, оборот $187K) | гиперчастота входов в SL (3257 SL vs 424 TP) |
| **Funding** | часть −$266 untracked | НЕ учитываем `a.m=FUNDING_FEE` из WS |
| **fake-R** (история) | R=264 при MFE=1.3 | `_resolve_exit` REST матчил чужой ордер (фикс-заплатка есть, корень = REST а не WS) |
| **account-хардкод** | acc2 невидим | `position_sync:364` `upsert_positions(1,...)` |
| **hedge-close 101205** | close бил не тот акк | routing без account из позиции |
| **SL-за-ликвидацией** | POPCAT 50× SL 2.75%>liq 1.9% | плечо не клампится по sl_dist (кап-заплатка есть) |

**Вывод:** все дыры = симптомы того, что состояние позиции собирается REST-polling'ом по разным узлам, а не из WS-истины. Заплатки чинят симптом, корень остаётся.

---

## 2. ЛОСКУТНОЕ ОДЕЯЛО — 8+ узлов исполнения (что есть сейчас)

| Узел (файл) | Роль | Проблема |
|-------------|------|----------|
| `core/exchange/order_manager.py` `open_bracket` | place MARKET+SL+TP | leverage-кламп слоями (заплатки) |
| `core/trading/trade_router.py` | роутинг сигнал→ордер, per-source policy | account из routing, не из факта |
| `core/trading/trade_simulator.py` `close_trade`/`check_open_trades` | close-by-price (БД-метка) | НЕ шлёт биржевой close; метит по свече |
| `core/exchange/position_sync.py` `sync_positions`/`_resolve_exit`/`_emergency_close_check`/`_detect_orphans` | REST-сверка БД↔биржа | **конкурент WS**, ключ по symbol без account, close-by-кэш→призраки |
| `core/exchange/exec_ws_integration.py` (2a/2b) | WS fill→exch_id, pa=0→close | ✅ правильный путь, НО не юзает rp/n/FUNDING_FEE/LIQUIDATION/mt |
| `core/exchange/user_data_ws.py` | listenKey + raw WS | ловит ORDER/ACCOUNT, частично |
| `core/exchange/tsl_updater.py` | TSL + position_id захват | отдельный REST-цикл |
| `core/exchange/account_router.py` | sticky symbol→account | ок, но истина account не сверяется с позицией |

**Два конкурирующих источника закрытия** = корень призраков: WS `pa=0` (истина) ∥ REST `position_sync:504` close-by-price (по кэшу, ложно).

---

## 3. ЦЕЛЕВАЯ АРХИТЕКТУРА — Execution Sphere (один узел)

**Принципы:**
1. **ОДИН слой исполнения.** Все open/close/track/state — через него ([[principle_reuse_not_duplication]]).
2. **WS = ЕДИНЫЙ источник истины состояния позиции.** REST = только команды (place/cancel) + cold-start снимок. **Убрать REST close-by-price** (`position_sync:504`) — позиция закрывается в БД ТОЛЬКО по WS `ACCOUNT_UPDATE pa=0` + `ORDER_TRADE_UPDATE` fill.
3. **`account` + `exchange` = ПАРАМЕТРЫ**, не хардкод (main/BingX). Интерфейс `ExchangeAdapter` → multi-exchange. Account ИЗ позиции (raw/positionId), не из предположения.
4. **WS даёт нативно** (см. `BINGX_WS_ACCOUNT_SPEC.md`): `o.rp` (realized PnL=$-истина), `o.n` (комиссия), `o.ap` (реальный fill=анти-fakeR), `o.o=LIQUIDATION`, `a.m=FUNDING_FEE`, `a.P[].pa=0` (флэт), `a.P[].mt` (cross/isolated). → убирает profit_pct×notional, income-леджер, _resolve_exit REST.

**Контракт Execution Sphere (черновик):**
```
ExecutionSphere(adapter, account_router):
  open(signal, account?, exchange?) → OrderResult        # place, captures real account+orderId+positionId
  close(position_id, reason)        → CloseResult         # reduceOnly, account из позиции
  on_ws_event(ORDER_TRADE_UPDATE)   → update fills/fees/realized (o.ap/o.n/o.rp)
  on_ws_event(ACCOUNT_UPDATE)       → pa=0→close DB; mt→margin-mode; a.m=FUNDING_FEE→funding ledger
  state(account?) → live positions (из WS-снимка, не REST-polling)
```

---

## 4. SIM / VST РАЗДЕЛЕНИЕ (юзер: «SIM изжил себя»)

- **VST = боевая песочница = ИСТИНА.** Реальные ордера на бирже (бумажные деньги), полное исполнение, WS-подтверждение. Метрики/обучение/дашборд-оперативка — отсюда.
- **SIM = research-слой.** Снятие лимитов (полный охват mining), НЕ трогает биржу, отдельная БД (`sim.db`). Никогда не смешивается с VST в оперативных вью.
- **Разные БД:** `live.db` (VST=истина) ↔ `sim.db` (research). Сейчас всё в `subscriptions.db` смешано (execution_mode-флаг) → источник «у кого ID есть, у кого нет».
- **Единая логика входа/выхода** (один калькулятор), различие ТОЛЬКО режим-флаг sim/vst.

---

## 5. ДАШБОРД-РЕДИЗАЙН (юзер: «это табличка, не дашборд»)

Сейчас: одна таблица мешает open(live)/closed(БД)/SIM/VST, ID разные (symbol vs число), времени open/close нет, режимы вперемешку.

**Целевое разделение:**
1. **Секция БИРЖА (live):** что реально на бирже СЕЙЧАС (из WS-снимка) — позиции, account, mt, leverage, uPnL, ликвидация. Источник = Execution Sphere state.
2. **Секция БД/ИСТОРИЯ:** закрытые VST-сделки — время open/close, реальный exit (o.ap), realized $ (o.rp), комиссия (o.n), R. Источник = live.db.
3. **Секция SIM (research):** отдельно, помечено, не путать с боевым.
4. **Обязательные колонки истории:** время открытия, время закрытия, длительность (не только порядковый #), стабильный ID, account, mode (явно VST/SIM/exch).
5. **Оперативка из ШИНЫ** (мгновенно), история/аналитика из SQL ([[dashboard_oper_from_bus_analytics_sql]]).

---

## 6. API-КАРТА ГОТОВА (Ф1 закрыта)

- **Skills:** `.agents/skills/bingx-swap-trade` (place/cancel/leverage/margin), `bingx-swap-account` (positions/balance/**income=funding/commission/realized**), `bingx-swap-ws-account` (listenKey+order/account update). Каждый = `api-reference.md`.
- **WS-спека:** `docs/BINGX_WS_ACCOUNT_SPEC.md` (ORDER_TRADE_UPDATE/ACCOUNT_UPDATE поля).
- **Endpoints (из кода):** REST `trade/order`,`trade/leverage`,`trade/closeAllPositions`,`user/positions`,`trade/allOrders`,`user/balance`,**`user/income`**; WS `user/auth/userDataStream`+`ORDER_TRADE_UPDATE`+`ACCOUNT_UPDATE`.

---

## 7. ФАЗЫ ПЕРЕСТРОЙКИ

- **Ф0** Карта хаоса — ✅ (этот документ, раздел 2).
- **Ф1** Чтение docs / API-меню — ✅ (api-ai-skills + spec).
- **Ф2** Дизайн `ExecutionSphere` + `ExchangeAdapter` контракт (раздел 3) — **со свежей головой**.
- **Ф3** SIM/VST split (БД + единая логика) — раздел 4.
- **Ф4** Миграция узлов → ExecutionSphere: убрать REST close-by-price, перевести close на WS pa=0, account из факта. Тест на КОПИИ БД (close-path критичен, инцидент ложного закрытия 2026-04-07).
- **Ф5** Дашборд-редизайн (раздел 5).

---

## 8. ⚠️ СЕГОДНЯШНИЕ ЗАПЛАТКИ (НЕ путать с корнем — все ждут push)

Сделаны как симптом-фиксы, корень закроет перестройка:
- SL-safety кап плеча (`order_manager`), liq_safety config
- OTE-CASCADE shadow 1D-фильтр (+fix регистра) — снижает частоту плохих входов (косвенно издержки)
- balance_history кэш (sparkline), exchange_history+trades_filtered масштаб (lev/size/$) — дашборд-видимость
- fake-R positionID-якорь, leverage per-source/кламп, margin-mode acc2→isolated (ранее)

**Симптом призраков НЕ закрыт:** `orphan_autoclose` всё ещё `shadow` (не авто-закрывает). verify-flat НЕ внедрён. → корень в Ф4.

---

## 9. PRE-FLIGHT новой сессии
1. Прочитать ЭТОТ файл + `BINGX_WS_ACCOUNT_SPEC.md` + `current_state.md`.
2. Глянуть skills `bingx-swap-ws-account/api-reference.md` (WS-контракт).
3. Начать с Ф2 (дизайн ExecutionSphere) — НЕ кодить close-path без теста на копии БД.
4. Метрика истины = $ из balance_snapshots / WS `o.rp`, НЕ R.
