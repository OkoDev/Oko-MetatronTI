"""
RADAR-ARMED loop — бот исполняет сетапы радара (RADAR-ARMED-VST, docs/RADAR_ARMED_PLAN.md).

Архитектура (утверждена 03.07): радар (oi_fast_poller, pm2 oi-fast) = автономный алертер,
пишет ПОЛНЫЕ сетапы в oko_feed/external_data.db → radar_orders (status='NEW'). Этот лёгкий
loop поллит порт (локальный SQLite, без REST) и регистрирует через trade_router +
source_policy 'radar' (LIMIT-вход, risk 0.5%/20x, лимит 5 позиций — ответы Егора 03.07).
Reuse всей обвязки: positionId-захват, SL-синк, TSL, l3-гейты, position_sync.

Статусы порта (меняет ТОЛЬКО бот, радар пишет NEW и забывает):
  NEW → TAKEN (#trade_id) / SKIPPED (гейт, причина в note) / STALE (протух entry_ttl_min).

Gated: config trading.radar_armed.enabled (default false) — выключено → loop не стартует.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import time

logger = logging.getLogger(__name__)

DEFAULT_POLL_SEC = 15


def _cfg(bot) -> dict:
    try:
        return bot.config.get("trading.radar_armed", {}) or {}
    except Exception:
        return {}


def _fetch_new_orders(db_path) -> list[dict]:
    """NEW-сетапы из порта radar_orders. Таблицу создаёт радар — до первого сетапа её нет."""
    try:
        with sqlite3.connect(db_path, timeout=5) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(
                "SELECT ts, symbol, sig_type, side, entry, sl, tp1, tp2, tp3, grade, starred "
                "FROM radar_orders WHERE status='NEW' ORDER BY ts").fetchall()
            return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []   # no such table — радар ещё не писал сетапов
    except Exception as e:
        logger.debug("[RADAR-ARMED] fetch: %s", e)
        return []


def _set_status(db_path, symbol: str, ts: int, status: str, note: str = "") -> None:
    try:
        with sqlite3.connect(db_path, timeout=5) as c:
            c.execute("UPDATE radar_orders SET status=?, taken_ts=?, note=? "
                      "WHERE symbol=? AND ts=? AND status='NEW'",
                      (status, int(time.time()), note[:200], symbol, ts))
            c.commit()
    except Exception as e:
        logger.debug("[RADAR-ARMED] set_status %s: %s", symbol, e)


def _radar_open_count(db_path) -> int:
    """Открытые radar-сделки (лимит max_positions). PENDING_ENTRY = лимитка ждёт fill (шаг 4)."""
    try:
        with sqlite3.connect(db_path, timeout=5) as c:
            return c.execute(
                "SELECT COUNT(*) FROM simulated_trades WHERE status IN ('OPEN', 'PENDING_ENTRY') "
                "AND features_json LIKE '%\"trade_mode\": \"radar\"%'").fetchone()[0]
    except Exception:
        return 10**9   # БД недоступна → fail-closed (не открываем новое)


def _radar_symbol_busy(db_path, symbol: str) -> bool:
    """Уже есть живая radar-сделка/лимитка по символу — новый сетап не дублируем."""
    try:
        with sqlite3.connect(db_path, timeout=5) as c:
            return c.execute(
                "SELECT 1 FROM simulated_trades WHERE symbol=? AND status IN ('OPEN', 'PENDING_ENTRY') "
                "AND features_json LIKE '%\"trade_mode\": \"radar\"%' LIMIT 1",
                (symbol,)).fetchone() is not None
    except Exception:
        return True   # fail-closed


def _mark_pending(db_path, trade_id: int) -> bool:
    """OPEN → PENDING_ENTRY: LIMIT поставлен, fill не подтверждён (actual_entry_price пуст).

    PENDING-строка невидима для get_open_trades → TSL/BE/close-by-price/live-guard её не
    трогают; орфан-детект видит её отдельной выборкой (position_sync._detect_orphans).
    """
    try:
        with sqlite3.connect(db_path, timeout=5) as c:
            cur = c.execute(
                "UPDATE simulated_trades SET status='PENDING_ENTRY' WHERE id=? AND status='OPEN' "
                "AND (actual_entry_price IS NULL OR actual_entry_price <= 0) "
                "AND exchange_order_id IS NOT NULL AND exchange_order_id != ''",
                (trade_id,))
            c.commit()
            return cur.rowcount > 0
    except Exception as e:
        logger.warning("[RADAR-ARMED] mark_pending #%d: %s", trade_id, e)
        return False


async def _check_pending(bot, ttl_sec: float) -> None:
    """PENDING_ENTRY-чекер: fill → OPEN (+actual_entry, захваты, post-fill хук);
    TTL истёк → cancel лимитки → CANCELLED. SL/финальный TP привязаны к самому
    LIMIT-ордеру (place_bracket_order) — до fill на бирже нечего защищать."""
    import datetime as _dt
    db_path = bot.trade_simulator.db_path
    try:
        with sqlite3.connect(db_path, timeout=5) as c:
            c.row_factory = sqlite3.Row
            rows = [dict(r) for r in c.execute(
                "SELECT id, symbol, direction, exchange_order_id, created_at FROM simulated_trades "
                "WHERE status='PENDING_ENTRY' AND features_json LIKE '%\"trade_mode\": \"radar\"%'")]
    except Exception:
        return
    if not rows:
        return
    om = getattr(bot, "order_executor", None)
    if om is None or not om.is_live():
        return
    now = _dt.datetime.now(_dt.timezone.utc)
    for t in rows:
        tid, symbol = t["id"], t["symbol"]
        direction = (t["direction"] or "").upper()
        oid = str(t["exchange_order_id"] or "")
        try:
            client = await om._get_client_synced(symbol)
            fill_price = 0.0
            for o in await client.get_filled_orders(symbol, limit=10):
                if str(o.get("orderId")) == oid:
                    fill_price = float(o.get("avgPrice") or o.get("price") or 0)
                    break
            if fill_price > 0:
                with sqlite3.connect(db_path, timeout=5) as c:
                    c.execute("UPDATE simulated_trades SET status='OPEN', actual_entry_price=? "
                              "WHERE id=? AND status='PENDING_ENTRY'", (fill_price, tid))
                    c.commit()
                logger.info("[RADAR-ARMED] #%d %s %s LIMIT FILLED @ %.6g → OPEN", tid, symbol, direction, fill_price)
                # Захваты как в trade_router после open_bracket (positionId = якорь exit'а).
                # ⚠️ fetch_and_save_tp_order_id НЕ спавним: om.get_tp_order_id при нескольких TP
                # «оставляет один, остальные отменяет» — каннибализирует наши частичные TP1/TP2.
                try:
                    from core.exchange.tsl_updater import (
                        fetch_and_save_sl_order_id, fetch_and_save_position_id,
                    )
                    asyncio.create_task(fetch_and_save_sl_order_id(bot, tid, symbol, direction))
                    asyncio.create_task(fetch_and_save_position_id(bot, tid, symbol, direction))
                except Exception as _ce:
                    logger.debug("[RADAR-ARMED] captures #%d: %s", tid, _ce)
                await _on_entry_filled(bot, tid, symbol, direction, fill_price)
                continue
            # не зафиллен — TTL?
            age_s = None
            try:
                ca = _dt.datetime.fromisoformat(str(t["created_at"]).replace("Z", "+00:00"))
                if ca.tzinfo is None:
                    ca = ca.replace(tzinfo=_dt.timezone.utc)
                age_s = (now - ca).total_seconds()
            except Exception:
                pass
            if age_s is not None and age_s > ttl_sec:
                resp = await client.cancel_order(symbol, oid)
                code = resp.get("code", -1) if isinstance(resp, dict) else -1
                if code == 0:
                    with sqlite3.connect(db_path, timeout=5) as c:
                        c.execute("UPDATE simulated_trades SET status='CANCELLED', closed_at=? "
                                  "WHERE id=? AND status='PENDING_ENTRY'", (now.isoformat(), tid))
                        c.commit()
                    logger.info("[RADAR-ARMED] #%d %s LIMIT TTL %.0fмин — отменён → CANCELLED",
                                tid, symbol, age_s / 60)
                else:
                    # cancel не прошёл (возможно гонка с fill) — НЕ помечаем, перепроверим циклом
                    logger.warning("[RADAR-ARMED] #%d %s cancel code=%s — перепроверка след. циклом",
                                   tid, symbol, code)
        except Exception as e:
            logger.debug("[RADAR-ARMED] pending #%d %s: %s", tid, symbol, e)


def _read_features(db_path, trade_id: int) -> dict:
    try:
        import json as _json
        with sqlite3.connect(db_path, timeout=5) as c:
            r = c.execute("SELECT features_json FROM simulated_trades WHERE id=?", (trade_id,)).fetchone()
        return _json.loads(r[0]) if (r and r[0]) else {}
    except Exception:
        return {}


def _patch_features(db_path, trade_id: int, updates: dict) -> None:
    """Дописать ключи в features_json (read-modify-write; для OPEN-строк конкурентов нет)."""
    try:
        import json as _json
        with sqlite3.connect(db_path, timeout=5) as c:
            r = c.execute("SELECT features_json FROM simulated_trades WHERE id=?", (trade_id,)).fetchone()
            feats = _json.loads(r[0]) if (r and r[0]) else {}
            feats.update(updates)
            c.execute("UPDATE simulated_trades SET features_json=? WHERE id=?",
                      (_json.dumps(feats), trade_id))
            c.commit()
    except Exception as e:
        logger.warning("[RADAR-ARMED] patch_features #%d: %s", trade_id, e)


async def _on_entry_filled(bot, trade_id: int, symbol: str, direction: str, fill_price: float) -> None:
    """Multi-TP (шаг 5): частичные reduce-only TP по долям tp_shares на все цели КРОМЕ
    финальной — финальная уже стоит attached-TP полного объёма с самого LIMIT-ордера
    (place_bracket_order) и на остатке сработает как последний тейк.

    client.place_tp_order НАПРЯМУЮ (не om.place_tp_order): обёртка om и om.get_tp_order_id
    считают >1 TP дубликатами и отменяют «лишние» — для multi-TP это каннибализация.
    """
    om = getattr(bot, "order_executor", None)
    if om is None or not om.is_live():
        return
    cfg = _cfg(bot)
    shares = [float(s) for s in (cfg.get("tp_shares") or [40, 30, 30])]
    feats = _read_features(bot.trade_simulator.db_path, trade_id)
    tps = [float(t) for t in (feats.get("radar_tps") or [])]
    if len(tps) < 2:
        logger.info("[RADAR-ARMED] #%d %s: одна цель — attached TP уже держит её (без частичных)",
                    trade_id, symbol)
        return
    try:
        om._invalidate_positions()                       # LIMIT-fill не инвалидирует кэш позиций
        qty_pos = await om.get_position_qty(symbol, direction)
        if qty_pos <= 0:
            with sqlite3.connect(bot.trade_simulator.db_path, timeout=5) as c:
                r = c.execute("SELECT qty FROM simulated_trades WHERE id=?", (trade_id,)).fetchone()
            qty_pos = float(r[0]) if (r and r[0]) else 0.0
        if qty_pos <= 0:
            logger.warning("[RADAR-ARMED] #%d %s: qty неизвестен — частичные TP не ставлю", trade_id, symbol)
            return
        client = await om._get_client_synced(symbol)
        side_close = "SELL" if direction == "LONG" else "BUY"
        # Separate Isolated: TP = close-ордер → positionId ОБЯЗАТЕЛЕН (109400, HBAR #41530).
        # К моменту fill pid уже в БД (fetch_and_save_position_id при постановке LIMIT);
        # fallback — с биржи через om.
        pid = None
        try:
            with sqlite3.connect(bot.trade_simulator.db_path, timeout=5) as c:
                r = c.execute("SELECT position_id FROM simulated_trades WHERE id=?", (trade_id,)).fetchone()
            pid = str(r[0]) if (r and r[0]) else None
        except Exception:
            pass
        if not pid:
            pid = await om._get_position_id(symbol, direction)
        if not pid:
            logger.warning("[RADAR-ARMED] #%d %s: positionId не найден — частичные TP отложены "
                           "(позиция защищена attached SL/TP)", trade_id, symbol)
            return
        tp_oids = []                                     # [[oid, price, qty], ...] для BE-чекера
        for i, tp in enumerate(tps[:-1]):                # все цели кроме финальной (она attached)
            share = shares[i] / 100.0 if i < len(shares) else 0.0
            q = await client.quantize_qty(symbol, qty_pos * share)
            if share <= 0 or q <= 0:
                tp_oids.append(None)
                continue
            resp = await client.place_tp_order(symbol=symbol, side=side_close,
                                               pos_side=direction, stop_price=tp, qty=q,
                                               position_id=pid)
            code = resp.get("code", -1) if isinstance(resp, dict) else -1
            if code == 0:
                oid = str(resp.get("data", {}).get("order", {}).get("orderId", ""))
                tp_oids.append([oid, tp, q])
                logger.info("[RADAR-ARMED] #%d %s TP%d @ %.6g qty=%s (%.0f%%) oid=%s",
                            trade_id, symbol, i + 1, tp, q, share * 100, oid)
            else:
                tp_oids.append(None)
                logger.warning("[RADAR-ARMED] #%d %s TP%d @ %.6g FAILED: %s",
                               trade_id, symbol, i + 1, tp, resp)
        om._invalidate_open_orders(symbol)
        _patch_features(bot.trade_simulator.db_path, trade_id,
                        {"radar_tp_oids": tp_oids, "radar_tp_final": tps[-1]})
    except Exception as e:
        logger.exception("[RADAR-ARMED] #%d %s multi-TP error: %s", trade_id, symbol, e)


async def _check_be_after_tp1(bot) -> None:
    """Авто-БУ (шаг 6, Егор: «БУ после TP1 + наш TSL на остатке»): fill TP1 → SL → BE.

    Детект fill TP1 = REST-поллинг orderId в filled (тот же путь что pending-чекер, без
    правок exec_ws). BE = actual_entry ± 0.1% (комиссия) тугим STOP-LIMIT 0.15%
    (be_limit_buffer_pct, путь e762449). Дальше остаток ведёт штатный TSL-движок
    (radar-сделка OPEN — TSL работает по tsl_activation_r как у всех).
    """
    if not bool(_cfg(bot).get("be_after_tp1", True)):
        return
    om = getattr(bot, "order_executor", None)
    if om is None or not om.is_live():
        return
    db_path = bot.trade_simulator.db_path
    try:
        with sqlite3.connect(db_path, timeout=5) as c:
            c.row_factory = sqlite3.Row
            rows = [dict(r) for r in c.execute(
                "SELECT id, symbol, direction, actual_entry_price, entry_price, stop_loss, "
                "exchange_sl_order_id, features_json FROM simulated_trades "
                "WHERE status='OPEN' AND (be_activated IS NULL OR be_activated=0) "
                "AND features_json LIKE '%\"trade_mode\": \"radar\"%' "
                "AND features_json LIKE '%\"radar_tp_oids\"%'")]
    except Exception:
        return
    import json as _json
    for t in rows:
        try:
            feats = _json.loads(t["features_json"] or "{}")
            oids = feats.get("radar_tp_oids") or []
            tp1 = oids[0] if oids else None
            if not tp1 or not tp1[0]:
                continue
            symbol, direction = t["symbol"], (t["direction"] or "").upper()
            client = await om._get_client_synced(symbol)
            tp1_filled = any(str(o.get("orderId")) == str(tp1[0])
                             for o in await client.get_filled_orders(symbol, limit=20))
            if not tp1_filled:
                continue
            ae = float(t["actual_entry_price"] or 0) or float(t["entry_price"] or 0)
            if ae <= 0:
                continue
            be = ae * (1.001 if direction == "LONG" else 0.999)   # +комиссия round-trip
            qty_rest = await om.get_position_qty(symbol, direction)
            new_id = await om.update_sl(
                symbol, direction,
                old_sl_order_id=str(t["exchange_sl_order_id"] or ""),
                new_sl_price=be, qty=qty_rest or 0.0,
                old_sl_price=float(t["stop_loss"] or 0),
                limit_buffer_pct=0.15,                            # тугой BE-лимит (77fd649)
            )
            if new_id:
                with sqlite3.connect(db_path, timeout=5) as c:
                    c.execute("UPDATE simulated_trades SET be_activated=1, stop_loss=?, "
                              "exchange_sl_order_id=? WHERE id=? AND status='OPEN'",
                              (be, new_id, t["id"]))
                    c.commit()
                logger.info("[RADAR-ARMED] #%d %s TP1 FILLED → BE @ %.6g (oid=%s), остаток ведёт TSL",
                            t["id"], symbol, be, new_id)
        except Exception as e:
            logger.debug("[RADAR-ARMED] BE-чекер #%s: %s", t.get("id"), e)


async def radar_armed_loop(bot) -> None:
    """Поллинг порта radar_orders → фильтры v1 → регистрация через trade_router (source='radar')."""
    cfg = _cfg(bot)
    if not cfg.get("enabled", False):
        logger.info("[RADAR-ARMED] disabled (trading.radar_armed.enabled=false) — loop не стартует")
        return
    from oko_feed.store import DB_PATH as RADAR_DB
    poll_sec = float(cfg.get("poll_sec", DEFAULT_POLL_SEC) or DEFAULT_POLL_SEC)
    ttl_sec = float(cfg.get("entry_ttl_min", 45)) * 60
    sig_types = [str(s).lower() for s in (cfg.get("signal_types") or ["build", "pump", "spring"])]
    pump_grades = [str(g).upper() for g in (cfg.get("pump_grades") or ["A", "B"])]
    max_pos = int(cfg.get("max_positions", 5))
    logger.info("[RADAR-ARMED] started: poll=%ds ttl=%dмин types=%s pump_grades=%s max_pos=%d",
                poll_sec, ttl_sec / 60, sig_types, pump_grades, max_pos)

    while True:
        try:
            await asyncio.sleep(poll_sec)
            # pending-lifecycle: fill→OPEN / TTL→cancel (до чтения новых — освобождает слоты)
            await _check_pending(bot, ttl_sec)
            # авто-БУ по fill TP1 (шаг 6): SL→BE тугим STOP-LIMIT, остаток ведёт TSL
            await _check_be_after_tp1(bot)
            orders = _fetch_new_orders(RADAR_DB)
            if not orders:
                continue
            now = time.time()
            for o in orders:
                sym_feed, ts = str(o["symbol"]), int(o["ts"])
                # свежесть: сетап живёт entry_ttl_min (тот же TTL, что и лимитка после постановки)
                if now - ts > ttl_sec:
                    _set_status(RADAR_DB, sym_feed, ts, "STALE", f"age={int((now - ts) / 60)}min")
                    continue
                st = str(o["sig_type"]).lower()
                if st not in sig_types:
                    _set_status(RADAR_DB, sym_feed, ts, "SKIPPED", f"sig_type {st} off")
                    continue
                if st == "pump" and str(o["grade"] or "").upper() not in pump_grades:
                    _set_status(RADAR_DB, sym_feed, ts, "SKIPPED", f"grade {o['grade']} off")
                    continue
                if _radar_open_count(bot.trade_simulator.db_path) >= max_pos:
                    _set_status(RADAR_DB, sym_feed, ts, "SKIPPED", f"max_positions {max_pos}")
                    continue
                if _radar_symbol_busy(bot.trade_simulator.db_path, f"{sym_feed}/USDT:USDT"):
                    _set_status(RADAR_DB, sym_feed, ts, "SKIPPED", "symbol busy (radar OPEN/PENDING)")
                    continue
                await _try_register(bot, o, RADAR_DB)
        except asyncio.CancelledError:
            logger.info("[RADAR-ARMED] loop cancelled")
            raise
        except Exception as e:
            logger.exception("[RADAR-ARMED] loop error: %s", e)
            await asyncio.sleep(poll_sec)


async def _try_register(bot, o: dict, radar_db) -> None:
    """Один сетап порта → TradingRecommendation → trade_router.submit(source='radar')."""
    try:
        from core.signals.signal_models import TradingRecommendation, SignalDirection, MarketContext
    except ImportError as e:
        logger.warning("[RADAR-ARMED] import failed: %s", e)
        return
    sym_feed, ts = str(o["symbol"]), int(o["ts"])
    side = str(o["side"]).upper()
    is_long = side == "LONG"
    symbol = f"{sym_feed}/USDT:USDT"                     # формат БД/бота (как _ws_to_db_symbol)
    entry, sl = float(o["entry"]), float(o["sl"])
    tps = [float(t) for t in (o["tp1"], o["tp2"], o["tp3"]) if t]
    if not tps:
        _set_status(radar_db, sym_feed, ts, "SKIPPED", "no targets")
        return
    # take_profit = ДАЛЬНЯЯ цель: ближние TP1/TP2 — частичные (multi-TP, шаг 5); финальная в БД,
    # чтобы симуляторный TP-детект/repair_missing_tp не закрыли позицию на первой цели (разведка §1-2).
    tp_final = tps[-1]

    # TP-inversion / протух по цене: цена уже за первой целью → сетап отработал без нас
    px_now = 0.0
    try:
        px_now = float(await bot.data_collector.get_current_price(symbol) or 0)
    except Exception:
        pass
    if px_now > 0:
        if (tps[0] <= px_now) if is_long else (tps[0] >= px_now):
            _set_status(radar_db, sym_feed, ts, "SKIPPED", f"tp1 passed px={px_now:.6g}")
            return
        if (px_now <= sl) if is_long else (px_now >= sl):
            _set_status(radar_db, sym_feed, ts, "SKIPPED", f"sl passed px={px_now:.6g}")
            return

    rec = TradingRecommendation(
        symbol=symbol,
        action="BUY" if is_long else "SELL",
        direction=SignalDirection.LONG if is_long else SignalDirection.SHORT,
        overall_strength=70, confidence=0.7, risk_level="MEDIUM", signals_count=1,
        supporting_signals=[], conflicting_signals=[],
        market_context=MarketContext(
            symbol=symbol, current_price=entry,
            volume_24h=0.0, volume_change_24h=0.0, price_change_24h=0.0,
        ),
        entry_price=entry, stop_loss=sl, take_profit=tp_final,
        sl_source=f"radar:{o['sig_type']}", tp_source="radar:targets2.0",
    )
    extra = {
        "signal_type_override": f"radar_{o['sig_type']}",
        "trade_mode": "radar",
        "trigger_source": f"radar:{o['sig_type']}",
        "radar_ts": ts, "radar_grade": o.get("grade"),
        "radar_starred": int(o.get("starred") or 0),
        "radar_tps": tps,                                # все цели — план multi-TP (шаг 5)
    }
    try:
        if bool(bot.config.get("signal_router.enabled", False)) and hasattr(bot, "trade_router"):
            res = await bot.trade_router.submit(rec, source="radar", extra_features=extra)
            tid = getattr(res, "trade_id", None)
            if tid:
                _set_status(radar_db, sym_feed, ts, "TAKEN", f"#{tid}")
                # LIMIT поставлен, fill не подтверждён → PENDING_ENTRY (лайфцикл шага 4).
                # Ордер не встал (exchange_order_id пуст) → строка остаётся OPEN SIM-тенью.
                if getattr(res, "exchange_order_id", None):
                    if _mark_pending(bot.trade_simulator.db_path, tid):
                        logger.info("[RADAR-ARMED] #%d → PENDING_ENTRY (LIMIT ждёт fill, TTL %d мин)",
                                    tid, int(_cfg(bot).get("entry_ttl_min", 45)))
                logger.info("[RADAR-ARMED] %s %s %s → TAKEN #%s (entry=%.6g sl=%.6g tps=%s)",
                            sym_feed, side, o["sig_type"], tid, entry, sl, tps)
            else:
                drops = "; ".join(f"{g}:{d}" for g, d in getattr(res, "hard_drops", [])) or "none"
                _set_status(radar_db, sym_feed, ts, "SKIPPED", f"router: {drops}")
                logger.info("[RADAR-ARMED] %s router dropped: %s", sym_feed, drops)
        else:
            _set_status(radar_db, sym_feed, ts, "SKIPPED", "signal_router off")
            logger.warning("[RADAR-ARMED] signal_router.enabled=false — не регистрирую (нужен router)")
    except Exception as e:
        logger.exception("[RADAR-ARMED] %s register error: %s", sym_feed, e)
