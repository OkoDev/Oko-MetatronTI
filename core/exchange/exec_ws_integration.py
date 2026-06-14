"""
exec_ws_integration — интеграция UserDataStream в бот (EXEC-WS Этап 2).

on_event(WS) → действия БД:
  ЭТАП 2a (write_exch_id): ORDER_TRADE_UPDATE FILLED MARKET ro=false (открытие позиции)
     → найти свежую OPEN-сделку symbol+direction с exch_id=None → записать orderId.
     Лечит баг-семью exchange_order_id=None (orphan/фантомные SIM-only).
  ЭТАП 2b (sync_close): ACCOUNT_UPDATE P[].pa=0 (позиция закрыта на бирже)
     → найти OPEN биржевую сделку → _resolve_exit (REST filled orders) → close_trade.
     Лечит orphan/zombie/drift: позиция закрылась на бирже, БД узнаёт сразу (не через polling).

Всё за config-флагами trading.exec_ws.* (default false). SHADOW: если флаг off → лог «would …».
Per-account closure: start_exec_ws создаёт отдельный handler на каждый аккаунт (account_tag),
чтобы sync_close использовал правильный client (корень hedge_close_multiacct_root).
"""
from __future__ import annotations

import logging
import sqlite3
import time
from typing import Optional

logger = logging.getLogger(__name__)


def _ws_to_db_symbol(sym_ws: str) -> str:
    """'XLM-USDT' → 'XLM/USDT:USDT' (формат БД simulated_trades)."""
    parts = sym_ws.split("-")
    if len(parts) != 2:
        return sym_ws
    base, quote = parts[0], parts[1]
    return f"{base}/{quote}:{quote}"


_MATCH_WINDOW_MIN = 5     # сделка считается «свежей» (относится к открытию) если создана за N мин
_QTY_TOL = 0.02           # допуск совпадения qty (2%)


def _write_exch_id(bot, symbol: str, direction: str, order_id: str, qty: float, dry: bool) -> bool:
    """Записать exchange_order_id в СВЕЖУЮ OPEN-сделку, точно соответствующую открытию.

    Маппинг (точный, не «случайная старая»):
      1. ДЕДУП: orderId уже записан где-то → пропуск (дубль TRADE_UPDATE+ORDER_TRADE_UPDATE).
      2. Кандидаты: symbol+direction+status=OPEN+без exch_id+созданы за последние N мин (свежие).
      3. Выбор: по qty-match (WS qty ≈ БД qty ±2%); если qty нет — свежайшая в окне.
    Старые висящие сделки (created давно) НЕ берутся → не портим чужие данные.
    """
    import datetime
    db_path = bot.trade_simulator.db_path
    try:
        with sqlite3.connect(db_path, timeout=10) as conn:
            conn.execute("PRAGMA busy_timeout=10000")
            # 1. дедуп по orderId
            if conn.execute("SELECT 1 FROM simulated_trades WHERE exchange_order_id=? LIMIT 1",
                            (order_id,)).fetchone():
                return False
            # 2. свежие кандидаты
            cutoff = (datetime.datetime.now(datetime.timezone.utc)
                      - datetime.timedelta(minutes=_MATCH_WINDOW_MIN)).isoformat()
            rows = conn.execute(
                """SELECT id, qty FROM simulated_trades
                   WHERE symbol=? AND direction=? AND status='OPEN'
                     AND (exchange_order_id IS NULL OR exchange_order_id='')
                     AND created_at >= ?
                   ORDER BY id DESC LIMIT 5""",
                (symbol, direction, cutoff),
            ).fetchall()
            if not rows:
                logger.info("[EXEC-WS][2a] %s %s order=%s — нет СВЕЖЕЙ (<%dмин) OPEN без exch_id "
                            "(уже записан/др.аккаунт/старая)", symbol, direction, order_id, _MATCH_WINDOW_MIN)
                return False
            # 3. выбор по qty-match
            tid = None
            if qty and qty > 0:
                for rid, rqty in rows:
                    if rqty and abs(float(rqty) - qty) / qty < _QTY_TOL:
                        tid = rid
                        break
            if tid is None:
                tid = rows[0][0]   # fallback: свежайшая в окне (без qty-match)
            if dry:
                logger.info("[EXEC-WS][2a] would write exch_id=%s → #%d %s %s qty=%.4g (SHADOW)",
                            order_id, tid, symbol, direction, qty or 0)
                return True
            # ARCH-DB-V2 Ф1: order_id записан = реально на бирже → execution_mode по факту (VST/LIVE)
            from core.infra.config_loader import config as _cfg_dbv2
            _raw_em = str(_cfg_dbv2.get("trading.execution_mode", "vst")).upper()
            _em = {"VST": "VST", "LIVE": "LIVE"}.get(_raw_em, "VST")
            conn.execute(
                "UPDATE simulated_trades SET exchange_order_id=?, execution_mode=? WHERE id=? AND status='OPEN' "
                "AND (exchange_order_id IS NULL OR exchange_order_id='')",
                (order_id, _em, tid),
            )
            conn.commit()
            logger.info("[EXEC-WS][2a] exch_id=%s → #%d %s %s qty=%.4g (WS real-time)",
                        order_id, tid, symbol, direction, qty or 0)
            return True
    except Exception as e:
        logger.warning("[EXEC-WS][2a] write_exch_id error %s %s: %s", symbol, direction, e)
        return False


_ACC_TAG_TO_INT = {"acc1": 1, "acc2": 2, "live": 1}
_SYNC_CLOSE_COOLDOWN_SEC = 10   # дедупликация: повторный pa=0 по той же паре в N сек игнорируется


def _find_exchange_trade(db_path: str, sym: str, direction: str):
    """Найти OPEN биржевую сделку (не SIM-only) по символу+направлению.

    Возвращает id или None. Биржевая = execution_mode != 'SIM' OR exchange_order_id реальный.
    """
    import sqlite3
    try:
        with sqlite3.connect(db_path, timeout=5) as conn:
            row = conn.execute(
                """SELECT id FROM simulated_trades
                   WHERE symbol=? AND direction=? AND status='OPEN'
                     AND (execution_mode != 'SIM' OR
                          (exchange_order_id IS NOT NULL AND exchange_order_id != '' AND exchange_order_id != 'SIM'))
                   ORDER BY id DESC LIMIT 1""",
                (sym, direction),
            ).fetchone()
            return row[0] if row else None
    except Exception:
        return None


async def _sync_close_async(bot, sym: str, direction: str, account_tag: str) -> None:
    """EXEC-WS 2b: позиция закрыта на бирже (pa=0) → закрыть OPEN в БД.

    Алгоритм:
      1. Найти биржевую OPEN-сделку в БД (не SIM-only).
      2. _resolve_exit через filled orders → реальный статус + exit_price.
      3. close_trade в БД.
    Если _resolve_exit не нашёл ордер → EXPIRED (fallback из position_sync).
    Multiaccount-safe: client берётся для account_tag аккаунта (account_router).
    """
    trade_id = _find_exchange_trade(bot.trade_simulator.db_path, sym, direction)
    if not trade_id:
        logger.info("[EXEC-WS][2b] %s %s pa=0 — OPEN в БД не найдена (уже закрыта/SIM-only)", sym, direction)
        return

    status, exit_price = "EXPIRED", None
    try:
        acc_int = _ACC_TAG_TO_INT.get(account_tag, 1)
        router = bot.order_manager._get_router()
        client = router.client_for_account(acc_int)
        if client is not None:
            from core.exchange.position_sync import _resolve_exit
            status, exit_price = await _resolve_exit(client, sym, direction, None)
    except Exception as e:
        logger.warning("[EXEC-WS][2b] _resolve_exit %s %s tag=%s: %s", sym, direction, account_tag, e)

    try:
        ok = bot.trade_simulator.close_trade(trade_id, status, exit_price)
        logger.info("[EXEC-WS][2b] #%d %s %s → %s @ %s (WS pa=0 sync_close ok=%s)",
                    trade_id, sym, direction, status, exit_price, ok)
    except Exception as e:
        logger.warning("[EXEC-WS][2b] close_trade #%d error: %s", trade_id, e)


def make_event_handler(bot, account_tag: str = "acc1"):
    """Создаёт on_event closure для одного аккаунта (account_tag).

    start_exec_ws вызывает per-account чтобы sync_close использовал правильный client.
    """
    cfg = bot.config
    # дедупликация pa=0: {(sym, direction): last_close_ts}
    _sync_close_seen: dict = {}

    async def on_event(etype: str, msg: dict) -> None:
        et = (etype or "").upper()
        # ── ЭТАП 2a: запись exch_id при FILLED MARKET открытии ──
        # ВАЖНО: открытие приходит как 'TRADE_UPDATE' (place_bracket type=MARKET), а статус-апдейт
        # как 'ORDER_TRADE_UPDATE'. Не фильтруем по etype-строке — проверяем наличие order-данных 'o'.
        o = msg.get("o")
        if isinstance(o, dict) and o:
            # MARKET FILLED без reduceOnly = ОТКРЫТИЕ позиции (ro=true → закрытие, пропускаем)
            if o.get("X") == "FILLED" and o.get("o") == "MARKET" and not o.get("ro", False):
                order_id = str(o.get("i", "") or "")
                symbol = _ws_to_db_symbol(str(o.get("s", "")))
                direction = str(o.get("ps", "")).upper()   # LONG/SHORT
                try:
                    qty = abs(float(o.get("z") or o.get("q") or 0))   # z=filled qty, q=order qty
                except Exception:
                    qty = 0.0
                if order_id and symbol and direction in ("LONG", "SHORT"):
                    dry = not bool(cfg.get("trading.exec_ws.write_exch_id", False))
                    _write_exch_id(bot, symbol, direction, order_id, qty, dry)
            return
        # ── ЭТАП 2b: позиция закрыта (pa=0) → sync_close БД ──
        if et == "ACCOUNT_UPDATE":
            a = msg.get("a") or {}
            for p in (a.get("P") or []):
                if not isinstance(p, dict):
                    continue
                # pa=0 = позиция закрыта (BingX шлёт "0" или "0.00000000")
                pa_str = str(p.get("pa", "")).strip()
                try:
                    pa_zero = float(pa_str) == 0.0
                except ValueError:
                    pa_zero = False
                if not pa_zero:
                    continue
                sym = _ws_to_db_symbol(str(p.get("s", "")))
                direction = str(p.get("ps", "")).upper()
                if not sym or direction not in ("LONG", "SHORT"):
                    continue
                sync_close_on = bool(cfg.get("trading.exec_ws.sync_close", False))
                if not sync_close_on:
                    logger.info("[EXEC-WS][2b] %s %s pa=0 (sync_close OFF — shadow лог)", sym, direction)
                    continue
                # дедупликация: не закрывать то же самое несколько раз за N сек
                import time as _t
                key = (sym, direction)
                now_ = _t.monotonic()
                if now_ - _sync_close_seen.get(key, 0) < _SYNC_CLOSE_COOLDOWN_SEC:
                    continue
                _sync_close_seen[key] = now_
                import asyncio as _aio
                _aio.create_task(_sync_close_async(bot, sym, direction, account_tag))

    return on_event


def start_exec_ws(bot) -> Optional[list]:
    """Запуск UserDataStream на КАЖДЫЙ аккаунт (multi-account) если trading.exec_ws.enabled.

    Корень: бот торгует на 2 VST-аккаунтах (arch96.multiaccount) → нужен отдельный WS
    (listenKey) на каждый, иначе сделки др. аккаунта не видны (как JUP/REDSTONE на acc2).
    Возвращает список asyncio.Task (по одному на аккаунт) или None.
    """
    import asyncio
    import os
    cfg = bot.config
    if not bool(cfg.get("trading.exec_ws.enabled", False)):
        return None
    is_vst = str(cfg.get("trading.execution_mode", "vst")).lower() == "vst"

    # Список (tag, api_key, secret) по доступным ключам
    accounts = []
    if is_vst:
        for tag, ke, se in (
            ("acc1", "BINGX_VST_API_KEY", "BINGX_VST_SECRET_KEY"),
            ("acc2", "BINGX_VST_API_KEY_2", "BINGX_VST_SECRET_KEY_2"),
        ):
            k = os.getenv(ke)
            if k:
                accounts.append((tag, k, os.getenv(se) or ""))
    else:
        # LIVE user-data WS: listenKey доступен ТОЛЬКО на ОСНОВНОМ (master) аккаунте.
        # Суб-ключ BINGX_API_KEY (2zDHkp) → listenKey HTTP404 (проверено 12.06).
        # Master listenKey обычно покрывает суб-аккаунты. Основной master-ключ
        # (5G6nUxnT) лежит в BINGX_VST_API_KEY и работает И для VST, И для LIVE
        # (open-api.bingx.com listenKey HTTP200). Приоритет: явный LIVE-master → VST-
        # master (он же основной) → суб (последний шанс).
        k = (os.getenv("BINGX_LIVE_MASTER_API_KEY")
             or os.getenv("BINGX_VST_API_KEY")
             or os.getenv("BINGX_API_KEY"))
        s = (os.getenv("BINGX_LIVE_MASTER_SECRET_KEY")
             or os.getenv("BINGX_VST_SECRET_KEY")
             or os.getenv("BINGX_SECRET_KEY") or "")
        if k:
            accounts.append(("live", k, s))

    if not accounts:
        logger.warning("[EXEC-WS] enabled, но нет ключей (is_vst=%s) — не запускаю", is_vst)
        return None

    from core.exchange.user_data_ws import UserDataStream
    bot._exec_ws_list = []
    tasks = []
    for tag, k, s in accounts:
        # per-account closure: sync_close использует правильный client (multiaccount-safe)
        handler = make_event_handler(bot, account_tag=tag)
        uds = UserDataStream(k, s, is_vst=is_vst, on_event=handler, account_tag=tag)
        bot._exec_ws_list.append(uds)
        tasks.append(asyncio.create_task(uds.run()))
    logger.info("[EXEC-WS] запущено %d аккаунтов %s (is_vst=%s, write_exch_id=%s)",
                len(accounts), [a[0] for a in accounts], is_vst,
                cfg.get("trading.exec_ws.write_exch_id", False))
    return tasks
