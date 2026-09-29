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

# Допуск между заявленной ценой лимитки и фактической ценой позиции (%). Лимитный ордер
# исполняется по своей цене или лучше, поэтому расхождение больше этого — признак того,
# что позицию открыл кто-то другой (см. защиту в _check_pending).
_FILL_PRICE_TOL_PCT = 1.0

DEFAULT_POLL_SEC = 15


async def _late_fill_verify_close(bot, tid: int, symbol: str, cli, open_o: dict) -> None:
    """🔴 SAND-класс (#47688, 14.07): LIMIT зафиллился, а позиция уже закрылась МЕЖДУ циклами.
    При CUTOVER position_sync close-by-price выключен — резолвим сами: позиция флэт →
    закрывающий fill того же positionID (REST-якорь) → боевой close_trade."""
    import asyncio as _aio
    try:
        await _aio.sleep(2)
        pid = str(open_o.get("positionID") or open_o.get("positionId") or "")
        base = symbol.split("/")[0]
        try:
            for p in (await cli.get_positions() or []):
                if base in str(p.get("symbol", "")) and abs(float(p.get("positionAmt") or 0)) > 0:
                    return   # позиция жива — штатно поведёт сфера
        except Exception:
            return           # не смогли проверить — не гадаем
        fills = await cli.get_filled_orders(symbol, limit=30)
        cand = [o for o in (fills or [])
                if str(o.get("positionID") or o.get("positionId") or "") == pid
                and str(o.get("orderId")) != str(open_o.get("orderId"))]
        if not cand or not pid:
            return
        o = max(cand, key=lambda x: int(x.get("updateTime") or 0))
        ap = float(o.get("avgPrice") or 0)
        if ap <= 0:
            return
        typ = str(o.get("type", "")).upper()
        st = {"STOP": "SL", "STOP_MARKET": "SL", "TAKE_PROFIT": "TP",
              "TAKE_PROFIT_MARKET": "TP", "TRAILING_STOP_MARKET": "TSL"}.get(
            typ, "SL" if float(o.get("profit") or 0) < 0 else "TP")
        ok = bot.trade_simulator.close_trade(tid, st, ap)
        logger.info("[RADAR-ARMED] #%d %s late-fill verify-flat → %s @ %s (ok=%s)",
                    tid, symbol, st, ap, ok)
    except Exception as _e:
        logger.debug("[RADAR-ARMED] verify-flat #%d: %s", tid, _e)


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
            # 🔴 26.09 wave_leg НЕ ВЫБИРАЛСЯ — и гейт «pump только после выдоха» (14.07) молчал
            # 2.5 месяца: o.get("wave_leg") всегда None → условие `_wl is not None` ложно → пропуск.
            # Цена: 0 отсеиваний по wave_leg из 41924 SKIPPED, 119 ранних пампов ушли в бой после
            # введения гейта. На реальных ценах leg<3 даёт −1.93%/сд против +2.20% у leg≥3.
            # Тот же класс, что молчаливый пропуск waves_long: фильтр есть, данные до него не доходят.
            try:      # phase_json добавлен 12.07 (фаза серии BUILD) — старые БД без колонки
                rows = c.execute(
                    "SELECT ts, symbol, sig_type, side, entry, sl, tp1, tp2, tp3, grade, starred, "
                    "tg_msg_id, phase_json, wave_leg FROM radar_orders WHERE status='NEW' ORDER BY ts").fetchall()
            except sqlite3.OperationalError:
                rows = c.execute(
                    "SELECT ts, symbol, sig_type, side, entry, sl, tp1, tp2, tp3, grade, starred, "
                    "tg_msg_id, NULL AS phase_json, NULL AS wave_leg FROM radar_orders "
                    "WHERE status='NEW' ORDER BY ts").fetchall()
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


def _radar_types() -> tuple[str, list]:
    """
    Условие «запись принадлежит radar-семейству» — из РЕЕСТРА, а не LIKE по JSON.

    🔴 22.08 (DEV-238): LIKE `'%"trade_mode": "radar"%'` ломается о суффиксы — ровно
    так шаблон `impulse_fib` не поймал `impulse_fib_15m`, и лимитки нового источника
    молча выпали из лайфцикла. Здесь ключ — колонка `signal_type` плюс объявленные
    подтипы (`radar_pump`/`radar_spring`/`radar_build`/`radar_build_flip`).
    Эквивалентность ключей проверена на всей боевой базе: 570 = 570, расхождений 0.
    """
    try:
        from core.trading.source_registry import types_sql
        return types_sql("radar")
    except Exception as e:                                   # noqa: BLE001
        logger.warning("[RADAR] реестр недоступен (%s) — запасной ключ по features_json", e)
        return ("features_json LIKE '%\"trade_mode\": \"radar\"%'", [])


def _radar_open_count(db_path) -> int:
    """Открытые radar-сделки (лимит max_positions). PENDING_ENTRY = лимитка ждёт fill (шаг 4)."""
    try:
        cond, params = _radar_types()
        with sqlite3.connect(db_path, timeout=5) as c:
            return c.execute(
                "SELECT COUNT(*) FROM simulated_trades WHERE status IN ('OPEN', 'PENDING_ENTRY') "
                f"AND {cond}", params).fetchone()[0]
    except Exception:
        return 10**9   # БД недоступна → fail-closed (не открываем новое)


def _radar_symbol_busy(db_path, symbol: str) -> bool:
    """Уже есть живая radar-сделка/лимитка по символу — новый сетап не дублируем."""
    try:
        with sqlite3.connect(db_path, timeout=5) as c:
            cond, params = _radar_types()
            return c.execute(
                "SELECT 1 FROM simulated_trades WHERE symbol=? AND status IN ('OPEN', 'PENDING_ENTRY') "
                f"AND {cond} LIMIT 1",
                (symbol, *params)).fetchone() is not None
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



def _pending_where() -> str:
    """
    SQL-условие «источник ведётся ЦЕНТРАЛЬНЫМ pending-лайфциклом».

    🔴 21.08: раньше здесь был РУЧНОЙ список из пяти LIKE-шаблонов. Добавление
    `impulse_fib_15m` его не задело: шаблон `'%"trade_mode": "impulse_fib"%'`
    требует закрывающую кавычку и не ловит имя с суффиксом. Лимитки нового
    источника молча выпали из лайфцикла — ни проверки фила, ни отмены по TTL.
    Теперь список приходит из реестра: объявил стратегию — подхватилась везде.
    Отказ реестра → прежний набор, чтобы лайфцикл не встал совсем.
    """
    try:
        from core.trading.source_registry import pending_sql
        return pending_sql()
    except Exception as e:                                   # noqa: BLE001
        logger.warning("[RADAR] реестр недоступен (%s) — запасной список", e)
        return ("(features_json LIKE '%\"trade_mode\": \"radar\"%' "
                "OR features_json LIKE '%\"trade_mode\": \"atr_s2\"%' "
                "OR features_json LIKE '%\"trade_mode\": \"impulse_fib\"%' "
                "OR features_json LIKE '%\"trade_mode\": \"impulse_fib_15m\"%' "
                "OR features_json LIKE '%\"trade_mode\": \"choch_wavec\"%')")


async def _check_pending(bot, ttl_sec: float) -> None:
    """PENDING_ENTRY-чекер: fill → OPEN (+actual_entry, захваты, post-fill хук);
    TTL истёк → cancel лимитки → CANCELLED. SL/финальный TP привязаны к самому
    LIMIT-ордеру (place_bracket_order) — до fill на бирже нечего защищать.

    08.07 (спринт LIMIT v1.1): ведёт и atr_s2 LIMIT-входы (mark_pending из scan_loop).
    Мульти-TP/BE-хуки для них no-op (radar_tps/radar_tp_oids нет → ранние выходы).
    ⚠️ Лайфцикл живёт в этом лупе: radar_armed.enabled=false остановит и atr_s2-pending."""
    import datetime as _dt
    db_path = bot.trade_simulator.db_path
    try:
        with sqlite3.connect(db_path, timeout=5) as c:
            c.row_factory = sqlite3.Row
            rows = [dict(r) for r in c.execute(
                "SELECT id, symbol, direction, exchange_order_id, created_at, entry_price "
                "FROM simulated_trades "
                "WHERE status='PENDING_ENTRY' AND " + _pending_where())]
    except Exception:
        return
    if not rows:
        return
    om = getattr(bot, "order_executor", None)
    if om is None or not om.is_live():
        return
    now = _dt.datetime.now(_dt.timezone.utc)
    # fill-детект ACCOUNT-AGNOSTIC (04.07 фикс): ордер мог зафиллиться на ЛЮБОМ субакке
    # (роутер балансирует), а sticky-client по symbol смотрел не тот акк → fill невидим,
    # позиция висла PENDING + cancel_order бил чужой акк = 109400 вечным циклом (JUP #41708
    # зафиллилась +$3.26, но БД держала PENDING 4ч). Позиция в агрегате всех субакков =
    # зафиллено. entry = avgPrice позиции.
    from core.exchange.position_parser import parse_positions
    try:
        om._invalidate_positions()
        agg = parse_positions(await om._get_positions_cached())
    except Exception as _pe:
        logger.debug("[RADAR-ARMED] pending: positions err %s", _pe)
        return
    live = {(pp.symbol_our, pp.side): pp for pp in agg if pp.qty > 0}
    for t in rows:
        tid, symbol = t["id"], t["symbol"]
        direction = (t["direction"] or "").upper()
        oid = str(t["exchange_order_id"] or "")
        try:
            pp = live.get((symbol, direction))
            # 🔴 20.08 ЗАЩИТА ОТ ЧУЖОЙ ПОЗИЦИИ. Раньше фил засчитывался ПО ФАКТУ наличия
            # позиции на (symbol, direction) — без сверки с нашей заявкой. Если другой
            # источник открывал тот же символ по рынку, наша PENDING-строка получала
            # ЧУЖУЮ цену входа и чужой position_id, а `repair_missing_sl` ставил наш стоп
            # на чужую позицию. Своя лимитка при этом оставалась на бирже без надзора.
            # Дешёвая проверка без лишних запросов: фактическая цена обязана быть рядом
            # с нашим лимитом. Лимитка не может исполниться далеко от заявки — расхождение
            # больше допуска означает, что позиция не наша.
            if pp is not None:
                _decl = float(t["entry_price"] or 0)
                _got = float(getattr(pp, "entry", 0) or 0)
                if _decl > 0 and _got > 0:
                    _gap = abs(_got - _decl) / _decl * 100
                    if _gap > _FILL_PRICE_TOL_PCT:
                        logger.warning(
                            "[RADAR-ARMED] #%d %s %s: позиция на бирже по %.6g, а наш лимит "
                            "%.6g (расхождение %.2f%% > %.2f%%) — ЧУЖАЯ позиция, фил НЕ "
                            "засчитан", tid, symbol, direction, _got, _decl, _gap,
                            _FILL_PRICE_TOL_PCT)
                        pp = None
            if pp is not None:                            # зафиллено (позиция в агрегате)
                fill_price = float(getattr(pp, "entry", 0) or 0)
                with sqlite3.connect(db_path, timeout=5) as c:
                    upd = {"status": "OPEN"}
                    if fill_price > 0:
                        c.execute("UPDATE simulated_trades SET status='OPEN', actual_entry_price=? "
                                  "WHERE id=? AND status='PENDING_ENTRY'", (fill_price, tid))
                    else:
                        c.execute("UPDATE simulated_trades SET status='OPEN' "
                                  "WHERE id=? AND status='PENDING_ENTRY'", (tid,))
                    c.commit()
                logger.info("[RADAR-ARMED] #%d %s %s LIMIT FILLED @ %.6g → OPEN", tid, symbol, direction, fill_price)
                # ✅ ВХОД-уведомление (09.07, Егор «как отличить вход от сетапа»): факт fill →
                # ACTION. Сетап = 🚀/⏳/📈 (предложение радара), вход = ✅ (позиция открыта).
                try:
                    from oko_feed.alerts import send_tg as _stg
                    _feats = _read_features(db_path, tid)
                    _tps = _feats.get("radar_tps") or []
                    with sqlite3.connect(db_path, timeout=5) as _c_sl:
                        _r_sl = _c_sl.execute("SELECT stop_loss FROM simulated_trades WHERE id=?",
                                              (tid,)).fetchone()
                    _sl_v = float(_r_sl[0]) if (_r_sl and _r_sl[0]) else 0.0
                    _sl_pct = (abs(fill_price - _sl_v) / fill_price * 100) if (_sl_v and fill_price) else 0
                    _dot = "🟢" if direction == "LONG" else "🔴"
                    _mid_e = _stg(f"✅ <b>ВХОД #{tid}</b> {_dot} <code>{symbol.split('/')[0]}</code> "
                         f"{direction} @ <code>{fill_price:.6g}</code>\n"
                         + (f"стоп: <code>{_sl_v:.6g}</code> (−{_sl_pct:.2f}%)\n" if _sl_v else "")
                         + f"источник: {_feats.get('trigger_source', 'radar')}\n"
                         + (f"цели: {' / '.join(f'{t:.6g}' for t in _tps)}\n" if _tps else "")
                         + f"<i>SL и тейки на бирже; остаток поведёт пивот-трейл</i>\n\n"
                         f"#ENTRY #{symbol.split('/')[0]}", channel="action",
                         reply_to=_feats.get("radar_tg_msg_id"))   # 💬 reply на сетап = цикл виден
                    if isinstance(_mid_e, int):
                        _patch_features(db_path, tid, {"entry_tg_msg_id": _mid_e})
                except Exception as _ne:
                    logger.debug("[RADAR-ARMED] entry-notify #%d: %s", tid, _ne)
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
            # 20.08: TTL ПО ИСТОЧНИКУ. У radar/atr_s2 лимитка живёт минуты (entry_ttl_min),
            # у impulse_fib — ровно WAIT_BARS баров 1h, как в замере механики: лимит на
            # откате 0.382 актуален 12 часов, дальше сетап протух и его надо снять.
            # 🔴 21.08 TTL ИЗ РЕЕСТРА, а не из веток if/elif по имени источника.
            # Ветка знала только `impulse_fib` и дала бы `impulse_fib_15m` те же
            # 12 ЧАСОВ вместо 3 — WAIT_BARS одинаковый, но бары разной длины.
            _ttl = ttl_sec
            try:
                _tm = (_read_features(db_path, tid) or {}).get("trade_mode")
                from core.trading.source_registry import ttl_for as _ttl_for
                _ttl = _ttl_for(_tm, default_sec=ttl_sec)
            except Exception:
                pass
            if age_s is not None and age_s > _ttl:
                # ГОНКА fill→быстрый-exit (ARB #41633): LIMIT зафиллился и закрылся по SL
                # МЕЖДУ циклами → позиции уже нет, но это НЕ «не сработал». Проверяем filled
                # по orderId на всех субакках: нашли → OPEN (exit резолвит position_sync/exec_ws,
                # честный SL/TP), НЕ CANCELLED (иначе теряем реальный убыток из метрик).
                try:
                    router = om._get_router()
                    accs = list(getattr(router, "accounts", [1]))
                except Exception:
                    router, accs = None, [1]
                was_filled = False
                _fill_cli = _fill_o = None
                for acc in accs:
                    cli = router.client_for_account(acc) if router else await om._get_client_synced(symbol)
                    if cli is None:
                        continue
                    try:
                        for o in await cli.get_filled_orders(symbol, limit=20):
                            if str(o.get("orderId")) == oid:
                                was_filled = True
                                _fill_cli, _fill_o = cli, o
                                break
                    except Exception:
                        continue
                    if was_filled:
                        break
                if was_filled:
                    with sqlite3.connect(db_path, timeout=5) as c:
                        c.execute("UPDATE simulated_trades SET status='OPEN' "
                                  "WHERE id=? AND status='PENDING_ENTRY'", (tid,))
                        c.commit()
                    logger.info("[RADAR-ARMED] #%d %s LIMIT зафиллился (позиция уже закрыта?) "
                                "→ OPEN + verify-flat", tid, symbol)
                    # 🔴 14.07 SAND-класс (#47688 вечный OPEN): «резолвит position_sync» больше
                    # НЕ работает — close-by-price выключен CUTOVER'ом. Если позиция уже флэт —
                    # немедленно дотянуть закрывающий fill (REST, positionID-якорь) → close_trade.
                    if _fill_cli is not None and _fill_o is not None:
                        asyncio.create_task(_late_fill_verify_close(bot, tid, symbol, _fill_cli, _fill_o))
                    continue
                # реально не сработал: cancel account-aware → CANCELLED
                cancelled = False
                for acc in accs:
                    cli = router.client_for_account(acc) if router else await om._get_client_synced(symbol)
                    if cli is None:
                        continue
                    try:
                        resp = await cli.cancel_order(symbol, oid)
                        if (resp.get("code", -1) if isinstance(resp, dict) else -1) == 0:
                            cancelled = True
                            break
                    except Exception:
                        continue
                with sqlite3.connect(db_path, timeout=5) as c:
                    c.execute("UPDATE simulated_trades SET status='CANCELLED', closed_at=? "
                              "WHERE id=? AND status='PENDING_ENTRY'", (now.isoformat(), tid))
                    c.commit()
                logger.info("[RADAR-ARMED] #%d %s LIMIT TTL %.0fмин → CANCELLED (cancel_ok=%s)",
                            tid, symbol, age_s / 60, cancelled)
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
        # ACCOUNT-AWARE: TP ставим на КЛИЕНТ аккаунта позиции (роутер балансирует по субаккам;
        # sticky-client по symbol мог бы дать чужой акк → TP мимо позиции). pid из того же снимка.
        client, pid = await om._resolve_position_client(symbol, direction)
        side_close = "SELL" if direction == "LONG" else "BUY"
        # Separate Isolated: TP = close-ордер → positionId ОБЯЗАТЕЛЕН (109400, HBAR #41530).
        if not pid:
            try:
                with sqlite3.connect(bot.trade_simulator.db_path, timeout=5) as c:
                    r = c.execute("SELECT position_id FROM simulated_trades WHERE id=?", (trade_id,)).fetchone()
                pid = str(r[0]) if (r and r[0]) else None
            except Exception:
                pass
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


def _runner_floor(price: float, direction: str, pivots: dict,
                  be: float, buf_pct: float = 0.15) -> float | None:
    """SPRING-RUNNER-TSL (09.07): «этаж» раннера = последний ПРОБИТЫЙ R/S-пивот дня.

    MFE-статистика n=68: брали +0.04%/сд при потенциале +2.84% (62% сделок давали >2%
    ПОСЛЕ выхода) — BE-у-цены + TSL-1R душили раннеров. Дизайн Егора (разбор ARB 1h):
    держать ПОКА above R-пивотов; SL = под пробитый этаж (−buf), только ВВЕРХ, не ниже BE.
    LONG: цена выше R2 → SL под R2; выше R1 → под R1; ниже R1 → BE. SHORT зеркально.
    Пивоты дня пересчитываются сами с новыми сутками (future-эффект бесплатно)."""
    lvls = (("R3", "R2", "R1", "PP") if direction == "LONG" else ("S3", "S2", "S1", "PP"))
    k = 1 - buf_pct / 100 if direction == "LONG" else 1 + buf_pct / 100
    for name in lvls:                                  # от дальнего этажа к ближнему
        lv = pivots.get(name)
        if lv is None:
            continue
        broken = price > lv if direction == "LONG" else price < lv
        if broken:
            floor = lv * k
            better_than_be = floor > be if direction == "LONG" else floor < be
            return floor if better_than_be else None   # этаж хуже BE — не трогаем
    return None                                        # ни один этаж не пробит — сидим на BE


def _swing_floor(df, direction: str, price: float, buf_pct: float = 0.3) -> float | None:
    """Стоп за ПОСЛЕДНИМ ПОДТВЕРЖДЁННЫМ структурным свингом (Егор 12.07 «микро-отскок!
    где СТРУКТУРНЫЙ трейл?!» — v1 на 5m±2 была микрошумом: LAB выбило тиком в 2.3%
    от цены, а структурный LH 0.5768 дышал бы и ехал дальше).

    v2 = канон OKO-SM: 15m + confirmed_swings(length=5) [[calib_choch_length5]].
    SHORT → ПОСЛЕДНИЙ подтверждённый swing high (LH) ВЫШЕ цены: его слом = CHoCH =
    структура развернулась = выходим. LONG → последний подтверждённый HL НИЖЕ.
    НЕ ближайший микропик (= слабейший уровень = шум).

    🔴 ВАЛИДНОСТЬ (урок churn'а 12.07): стоп ОБЯЗАН быть на правильной стороне рынка —
    SHORT выше цены (STOP BUY), LONG ниже. Фильтр p>price*1.002 / p<price*0.998."""
    if df is None or len(df) < 30 or price <= 0:
        return None
    try:
        from core.smc.smc_engine import confirmed_swings
        sw = sorted(confirmed_swings(df, 5), key=lambda x: x[0])
    except Exception:
        return None
    if direction == "SHORT":
        cands = [p for _, p, k in sw if k == "H" and p > price * 1.002]
        return cands[-1] * (1 + buf_pct / 100) if cands else None
    cands = [p for _, p, k in sw if k == "L" and p < price * 0.998]
    return cands[-1] * (1 - buf_pct / 100) if cands else None


async def _daily_pivots(bot, symbol: str) -> dict:
    """Classic floor пивоты ТЕКУЩЕГО дня (по вчерашней D-свече) из data_collector.
    force_refresh (11.07, ARB-пивот-баг): этажи двигают РЕАЛЬНЫЙ SL — свечи только свежие
    (раннеров ≤5, вызов раз в 60с — REST-цена копеечная)."""
    try:
        df = await bot.data_collector.get_ohlcv(symbol, "1d", limit=3, force_refresh=True)
        if df is None or len(df) < 2:
            return {}
        prev = df.iloc[-2]
        h, l, cl = float(prev["high"]), float(prev["low"]), float(prev["close"])
        pp = (h + l + cl) / 3
        return {"PP": pp, "R1": 2 * pp - l, "S1": 2 * pp - h,
                "R2": pp + (h - l), "S2": pp - (h - l),
                "R3": h + 2 * (pp - l), "S3": l - 2 * (h - pp)}
    except Exception:
        return {}


async def _runner_ceiling(bot, symbol: str, direction: str, price: float) -> tuple[float | None, str]:
    """🏔 RUNNER-CEILINGS-W (10.07, разбор ARB с Егором: «+ немного глобального взгляда —
    ARB пришёл в середину 1W FVG»): потолок раннера = ближайший СТАРШИЙ уровень по ходу
    сделки: weekly-пивоты + дневные FVG-midline + 0.79/0.886 ретрейса 1h-структуры.
    У потолка ФИКСИРУЮТ, не надеются. → (уровень, источник) или (None, '')."""
    cands: list[tuple[float, str]] = []
    try:
        # force_refresh (11.07): потолок считается ОДИН раз на сделку и кэшируется в features —
        # протухший 1d-кэш заморозил бы кривой потолок навсегда (класс ARB-пивот-бага)
        df_d = await bot.data_collector.get_ohlcv(symbol, "1d", limit=60, force_refresh=True)
        if df_d is not None and len(df_d) >= 15:
            import pandas as pd
            d = df_d.copy()
            if not isinstance(d.index, pd.DatetimeIndex) and "time" in d.columns:
                d.index = pd.to_datetime(d["time"], unit="ms")
            # weekly-пивоты прошлой завершённой недели
            wk = d.resample("W").agg({"high": "max", "low": "min", "close": "last"}).dropna()
            if len(wk) >= 2:
                p = wk.iloc[-2]
                pp = (float(p["high"]) + float(p["low"]) + float(p["close"])) / 3
                for lv, nm in ((pp, "W-PP"), (2 * pp - float(p["low"]), "W-R1"),
                               (2 * pp - float(p["high"]), "W-S1"),
                               (pp + float(p["high"]) - float(p["low"]), "W-R2"),
                               (pp - float(p["high"]) + float(p["low"]), "W-S2")):
                    cands.append((lv, nm))
            # дневные FVG-midline (незакрытые)
            from scripts.oi_fast_poller import _fvg_zones
            hs, ls = list(d["high"].values), list(d["low"].values)
            for z in _fvg_zones(hs, ls):
                cands.append(((z["top"] + z["bot"]) / 2, f"FVG-1D-{z['kind']}"))
    except Exception as e:
        logger.debug("[CEIL] %s daily: %s", symbol, e)
    try:
        # 0.79/0.886 ретрейса структуры 1h (нога против сделки = потолок отката)
        df_h = await bot.data_collector.get_ohlcv(symbol, "1h", limit=400)
        if df_h is not None and len(df_h) >= 100:
            import pandas as pd
            h = df_h.copy()
            if not isinstance(h.index, pd.DatetimeIndex) and "time" in h.columns:
                h.index = pd.to_datetime(h["time"], unit="ms")
            from core.smc.ote_matrix import structure_trend
            st = structure_trend(h)
            org = st.get("impulse_origin") or st.get("break_level")
            ext = st.get("extreme")
            if org and ext:
                for f in (0.79, 0.886):
                    cands.append((ext + f * (org - ext), f"1h-retr{f}"))
    except Exception as e:
        logger.debug("[CEIL] %s 1h: %s", symbol, e)
    ahead = [(lv, nm) for lv, nm in cands
             if (lv > price * 1.002 if direction == "LONG" else lv < price * 0.998)]
    if not ahead:
        return None, ""
    best = min(ahead, key=lambda x: abs(x[0] - price))
    return float(best[0]), best[1]


async def _manage_runners(bot) -> None:
    """Раннер-фаза (после fill TP1, be_activated=1): SL по пивот-этажам вместо TSL-удушения.
    Потолок v1 = attached финальный TP (уже на бирже). Троттлинг: раз в 60с."""
    if not bool(_cfg(bot).get("runner_pivot_trail", True)):
        return
    om = getattr(bot, "order_executor", None)
    if om is None or not om.is_live():
        return
    now = time.time()
    if now - getattr(_manage_runners, "_last", 0) < 60:
        return
    _manage_runners._last = now
    db_path = bot.trade_simulator.db_path
    try:
        with sqlite3.connect(db_path, timeout=5) as c:
            c.row_factory = sqlite3.Row
            rows = [dict(r) for r in c.execute(
                "SELECT id, symbol, direction, actual_entry_price, entry_price, stop_loss, "
                "exchange_sl_order_id FROM simulated_trades WHERE status='OPEN' "
                f"AND be_activated=1 AND {_radar_types()[0]}", _radar_types()[1])]
    except Exception:
        return
    for t in rows:
        try:
            symbol, direction = t["symbol"], (t["direction"] or "").upper()
            px = float(await bot.data_collector.get_current_price(symbol) or 0)
            if px <= 0:
                # WsFeed-тикера нет (не подписан/устарел), 1m-кэш пуст → REST через ApiEngine
                # (кэш+ретраи). Без цены раннер стоял МОЛЧА (BONK 11.07: ceiling не считался).
                try:
                    _df1 = await bot.data_collector.get_ohlcv(symbol, "1m", limit=2)
                    if _df1 is not None and len(_df1) > 0:
                        px = float(_df1.iloc[-1]["close"])
                except Exception as _pxe:
                    logger.warning("[RUNNER] #%s %s: REST-цена не взялась: %s", t.get("id"), symbol, _pxe)
            if px <= 0:
                logger.warning("[RUNNER] #%s %s: нет цены (ws+кэш+REST) — пропуск цикла", t.get("id"), symbol)
                continue
            # 🏔 потолок старшего ТФ: считается ОДИН раз при входе в раннер-фазу (кэш features)
            feats_r = _read_features(db_path, t["id"])
            ceil_v = feats_r.get("runner_ceiling")
            if ceil_v is None:
                cv, csrc = await _runner_ceiling(bot, symbol, direction, px)
                if cv:
                    _patch_features(db_path, t["id"], {"runner_ceiling": cv,
                                                       "runner_ceiling_src": csrc})
                    ceil_v = cv
                    logger.info("[CEIL] #%d %s потолок %.6g (%s)", t["id"], symbol, cv, csrc)
                else:
                    _patch_features(db_path, t["id"], {"runner_ceiling": 0})   # не нашли — не искать снова
            # у потолка ФИКСИРУЮТ: цена в 0.3% от уровня → market close остатка
            if ceil_v and float(ceil_v) > 0:
                cv = float(ceil_v)
                near = (px >= cv * 0.997) if direction == "LONG" else (px <= cv * 1.003)
                if near:
                    try:
                        client, pid = await om._resolve_position_client(symbol, direction)
                        qty_c = await om.get_position_qty(symbol, direction)
                        if client is not None and qty_c > 0:
                            # 🔴 14.08: close_position_market ждёт сторону ОТКРЫТИЯ (BUY=закрыть
                            # LONG). Со стороной закрытия биржа отвечала 101205, а fallback'а тут
                            # нет → фиксация у потолка не срабатывала НИ РАЗУ (0 из 62 потолков).
                            side_open = "BUY" if direction == "LONG" else "SELL"
                            resp = await client.close_position_market(symbol, side_open, qty_c,
                                                                      position_id=pid)
                            code = resp.get("code", -1) if isinstance(resp, dict) else -1
                            if code == 0:
                                logger.info("[CEIL] #%d %s ФИКСАЦИЯ у потолка %.6g (%s) qty=%s",
                                            t["id"], symbol, cv, feats_r.get("runner_ceiling_src"), qty_c)
                                from oko_feed.alerts import send_tg as _stg_c
                                _stg_c(f"🏔 <b>ПОТОЛОК #{t['id']}</b> <code>{symbol.split('/')[0]}</code> — "
                                       f"остаток зафиксирован у <code>{cv:.6g}</code> "
                                       f"({feats_r.get('runner_ceiling_src')})\n"
                                       f"<i>у магнита фиксируют — метод</i>\n\n#CEILING",
                                       channel="action", reply_to=feats_r.get("entry_tg_msg_id"))
                                continue                     # позиция закрыта — этажи не нужны
                    except Exception as _ce:
                        logger.debug("[CEIL] close #%s: %s", t.get("id"), _ce)
            piv = await _daily_pivots(bot, symbol)
            if not piv:
                continue
            entry = float(t["actual_entry_price"] or t["entry_price"] or 0)
            be = entry * (1.001 if direction == "LONG" else 0.999)
            floor_piv = _runner_floor(px, direction, piv, be)
            # СТРУКТУРНЫЙ ЭТАЖ (Егор «стоп за экстремум», хвост): за swing high/low — туже
            # редких дневных пивотов. Комбинируем с пивотом → тугой ВАЛИДНЫЙ (сторона рынка).
            floor_sw = None
            if bool(_cfg(bot).get("runner_swing_floor", True)):
                try:
                    _cnd = await bot.data_collector.get_ohlcv(symbol, "15m", limit=120)
                    floor_sw = _swing_floor(_cnd, direction, px)
                except Exception as _swe:
                    logger.debug("[RUNNER] swing_floor #%s: %s", t.get("id"), _swe)
            # валидные (правильная сторона рынка) → тугой: SHORT=min(ниже, ближе сверху), LONG=max
            _valid = [f for f in (floor_piv, floor_sw) if f is not None
                      and ((f > px) if direction == "SHORT" else (f < px))]
            floor = (min(_valid) if direction == "SHORT" else max(_valid)) if _valid else None
            cur_sl = float(t["stop_loss"] or 0)
            if floor is None or cur_sl <= 0:
                continue
            improves = floor > cur_sl * 1.0015 if direction == "LONG" else floor < cur_sl * 0.9985
            if not improves:
                continue
            qty_rest = await om.get_position_qty(symbol, direction)
            new_id = await om.update_sl(
                symbol, direction, old_sl_order_id=str(t["exchange_sl_order_id"] or ""),
                new_sl_price=floor, qty=qty_rest or 0.0, old_sl_price=cur_sl,
                limit_buffer_pct=0.15)
            if new_id:
                with sqlite3.connect(db_path, timeout=5) as c:
                    c.execute("UPDATE simulated_trades SET stop_loss=?, exchange_sl_order_id=? "
                              "WHERE id=? AND status='OPEN'", (floor, new_id, t["id"]))
                    c.commit()
                logger.info("[RUNNER] #%d %s SL → этаж %.6g (цена %.6g, BE %.6g)",
                            t["id"], symbol, floor, px, be)
                try:                                     # 💬 жизнь сделки тредом
                    from oko_feed.alerts import send_tg as _stg_rn
                    _f_rn = _read_features(db_path, t["id"])
                    _stg_rn(f"🪜 <b>ЭТАЖ #{t['id']}</b> <code>{symbol.split('/')[0]}</code> — "
                            f"стоп поднят: <code>{floor:.6g}</code> (цена <code>{px:.6g}</code>)\n\n#TRAIL",
                            channel="action", reply_to=_f_rn.get("entry_tg_msg_id"))
                except Exception:
                    pass
        except Exception as e:
            # warning, не debug: молчание уже прятало баги (BE-чекер 10.07, цена 11.07)
            logger.warning("[RUNNER] #%s: %s", t.get("id"), e)


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
                f"AND {_radar_types()[0]} "
                "AND features_json LIKE '%\"radar_tp_oids\"%'", _radar_types()[1])]
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
            # БАГ 10.07 (IOTA #45257) + 11.07 (BONK #45327): сработавший TAKE_PROFIT_MARKET
            # BingX исполняется под НОВЫМ orderId → матч по oid в allOrders слеп; окно
            # get_filled_orders(limit=20) отдаёт СТАРЕЙШИЕ ордера символа — свежий fill
            # туда не попадает при длинной истории. Надёжный детект: точечный GET order
            # по СТАРОМУ oid — биржа возвращает актуальный (новый исполненный) ордер.
            close_side = "BUY" if direction == "SHORT" else "SELL"
            _o = await client.get_order(symbol, str(tp1[0]))
            tp1_filled = (str(_o.get("status") or "") == "FILLED"
                          and str(_o.get("side") or "").upper() == close_side)
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
                # ХВОСТ-РАННЕР (11.07, Егор «рано вышли» — IOTA каскад −12.7%, взяли 2.8%):
                # хвост уже защищён БУ-стопом → снимаем attached финальный TP (measured-move
                # резал каскадные хвосты), дальше хвост ведут пивот-этажи + потолок 1W.
                # repair_missing_tp radar-сделки не трогает — TP не пересоздастся.
                if bool(_cfg(bot).get("runner_tail", True)):
                    try:
                        tpf = float(feats.get("radar_tp_final") or 0)
                        known = {str(o[0]) for o in oids if o}
                        for oo in await client.get_open_orders(symbol):
                            if str(oo.get("type") or "") not in ("TAKE_PROFIT_MARKET", "TAKE_PROFIT"):
                                continue
                            if str(oo.get("side") or "").upper() != close_side:
                                continue
                            if str(oo.get("orderId")) in known:      # частичные TP2/TP3 не трогаем
                                continue
                            sp = float(oo.get("stopPrice") or oo.get("price") or 0)
                            # снимаем ТОЛЬКО при подтверждённом матче цены с нашим tp_final —
                            # на символе может жить чужой TP (ote_nested и др.), его не трогаем
                            if not (tpf > 0 and sp > 0 and abs(sp - tpf) / tpf <= 0.005):
                                continue
                            r_c = await client.cancel_order(symbol, str(oo.get("orderId")))
                            logger.info("[RADAR-ARMED] #%d %s ХВОСТ: финальный TP @ %.6g снят "
                                        "(oid=%s, code=%s) — ведут этажи+потолок", t["id"], symbol,
                                        sp, oo.get("orderId"), r_c.get("code") if isinstance(r_c, dict) else "?")
                    except Exception as _tre:
                        logger.warning("[RADAR-ARMED] #%d хвост-раннер снятие TP: %s", t["id"], _tre)
                try:                                     # 💬 жизнь сделки тредом (Егор 09.07)
                    from oko_feed.alerts import send_tg as _stg_tp
                    _stg_tp(f"🎯 <b>TP1 #{t['id']}</b> <code>{symbol.split('/')[0]}</code> — "
                            f"40% зафиксировано @ <code>{tp1[1]:.6g}</code>\n"
                            f"стоп остатка → БУ <code>{be:.6g}</code>, дальше пивот-этажи\n\n#TP",
                            channel="action", reply_to=feats.get("entry_tg_msg_id"))
                except Exception:
                    pass
        except Exception as e:
            # warning, не debug: молчание уже прятало баги (BE-чекер 10.07, цена 11.07)
            logger.warning("[RADAR-ARMED] BE-чекер #%s: %s", t.get("id"), e)


async def _notify_closed(bot) -> None:
    """🏁 Финал жизни сделки тредом (Егор 09.07 «полную жизнь видно — будет круто»):
    radar-сделка закрылась (любой статус) → итог reply'ем на ✅ ВХОД. Однократно
    (features_json.closed_notified)."""
    db_path = bot.trade_simulator.db_path
    try:
        with sqlite3.connect(db_path, timeout=5) as c:
            c.row_factory = sqlite3.Row
            rows = [dict(r) for r in c.execute(
                "SELECT id, symbol, direction, status, profit_pct, exit_price "
                "FROM simulated_trades WHERE status IN ('TP','SL','TSL','EXPIRED','CANCELLED') "
                f"AND {_radar_types()[0]} "
                "AND features_json LIKE '%entry_tg_msg_id%' "
                "AND features_json NOT LIKE '%closed_notified%' LIMIT 10", _radar_types()[1])]
    except Exception:
        return
    for t in rows:
        try:
            feats = _read_features(db_path, t["id"])
            pp = t["profit_pct"]
            if t["status"] == "CANCELLED":
                head, tail = "🚫 <b>ОТМЕНА", "лимитка не сработала (TTL)"
            else:
                win = pp is not None and float(pp) > 0.05
                head = "🏆 <b>ЗАКРЫТА" if win else ("🟡 <b>ЗАКРЫТА" if pp is not None and abs(float(pp)) <= 0.05 else "🔻 <b>ЗАКРЫТА")
                tail = (f"{t['status']} · {float(pp):+.2f}%" if pp is not None else t["status"])
            from oko_feed.alerts import send_tg as _stg_cl
            _stg_cl(f"{head} #{t['id']}</b> <code>{str(t['symbol']).split('/')[0]}</code> "
                    f"{t['direction']}\n{tail}"
                    + (f" · выход <code>{float(t['exit_price']):.6g}</code>" if t["exit_price"] else "")
                    + "\n\n#CLOSED", channel="action", reply_to=feats.get("entry_tg_msg_id"))
            _patch_features(db_path, t["id"], {"closed_notified": 1})
        except Exception as e:
            logger.debug("[RADAR-ARMED] close-notify #%s: %s", t.get("id"), e)


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
    # пустой список = фильтр по типу выключен (все типы проходят)
    pump_kinds = [str(k) for k in (cfg.get("pump_kinds") or [])]
    max_pos = int(cfg.get("max_positions", 5))
    logger.info("[RADAR-ARMED] started: poll=%ds ttl=%dмин types=%s pump_grades=%s "
                "pump_kinds=%s max_pos=%d",
                poll_sec, ttl_sec / 60, sig_types, pump_grades, pump_kinds or "все", max_pos)

    while True:
        try:
            await asyncio.sleep(poll_sec)
            # 14.07 hot-reload лимита (Егор «не успеваем»): тюнинг без рестарта
            max_pos = int(_cfg(bot).get("max_positions", 10))
            # pending-lifecycle: fill→OPEN / TTL→cancel (до чтения новых — освобождает слоты)
            await _check_pending(bot, ttl_sec)
            # авто-БУ по fill TP1 (шаг 6): SL→BE тугим STOP-LIMIT, остаток ведёт TSL
            await _check_be_after_tp1(bot)
            # SPRING-RUNNER (09.07): раннеры после TP1 — SL по пивот-этажам (не душить)
            await _manage_runners(bot)
            # 🏁 итоги закрытых — reply на ВХОД (полный цикл тредом)
            await _notify_closed(bot)
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
                # 🔴 28.09 ФИЛЬТР ПО ТИПУ СЕТАПА (решение Егора «радар — фильтр»).
                # Замер всего журнала (2 984 сигнала, 1 610 исполненных на наших 1m-паркетах,
                # контроль ±10 дн, боевой выход 40/30/30 + безубыток) показал: грейд различал не
                # качество, а ТИП, и платит ровно один из трёх:
                #   фейд пампа (шорт вершины, RSI 80)  n=555  Δr +0.45
                #   фейд дампа (лонг дна, RSI 20)      n=319  Δr −0.19
                #   продолжение дампа (шорт вниз)      n=232  Δr −0.67
                # Прежний фильтр `pump_grades: [A, B]` работал наоборот: фейд пампа почти целиком
                # помечался C и выбрасывался, а продолжение дампа (только A/B) оставалось.
                if st == "pump" and pump_kinds:
                    _kind = _setup_kind(RADAR_DB, sym_feed, ts, str(o["side"]))
                    if _kind not in pump_kinds:
                        _set_status(RADAR_DB, sym_feed, ts, "SKIPPED", f"тип «{_kind}» off")
                        continue
                # 🔴 14.07 (лоси дня, Егор): pump-разворот ТОЛЬКО после выдоха — ранние ноги
                # минусят (VST-срез: leg≤2 n=8 −2.77% vs leg≥3 n=11 +14.21%, Δ=1.64%/сд;
                # LAB leg=1 −3.64 vs AGLD-класс выдох +4). None (старые без фичи) — пропуск.
                _wl = o.get("wave_leg")
                if st == "pump" and _wl is not None and int(_wl) < int(cfg.get("pump_min_wave_leg", 3)):
                    _set_status(RADAR_DB, sym_feed, ts, "SKIPPED", f"wave_leg {_wl} < 3 (рано, разгон)")
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


def _setup_kind(db_path, symbol: str, ts: int, side: str) -> str:
    """Тип pump-сетапа: фейд пампа / фейд дампа / продолжение дампа.

    Детектор (`scripts/oi_fast_poller.py`) знает тип по `up = d_px > 0` и `dump_cont`, но в
    `radar_orders` его не пишет — восстанавливаем по знаку движения из `pump_signals` (та же БД).
    Допуск ±120 с: у ARMED-порта и журнала сигналов время ставится раздельно.
    """
    try:
        with sqlite3.connect(db_path, timeout=5) as c:
            r = c.execute(
                "SELECT d_px FROM pump_signals WHERE symbol=? AND ABS(ts-?)<=120 "
                "ORDER BY ABS(ts-?) LIMIT 1", (symbol, ts, ts)).fetchone()
    except Exception as e:                                           # noqa: BLE001
        logger.debug("[RADAR-ARMED] тип сетапа %s: %s", symbol, e)
        return "неизвестно"
    if not r or r[0] is None:
        return "неизвестно"
    if float(r[0]) > 0:
        return "фейд пампа"
    return "продолжение дампа" if str(side).upper() == "SHORT" else "фейд дампа"


async def _wave_ctx_on_demand(bot, sym: str, side: str, entry: float) -> dict | None:
    """Волновой контекст пары, когда в шине его нет: считаем ЗДЕСЬ по 4h + 1d.

    Заявок у радара 2-3 в сутки, так что цена расчёта (mark_impulse в отдельном потоке)
    ничтожна, а без этого признак пуст у 85% сделок. Кадры режем тем же `_dt_closed`,
    что и wave_loop — один калькулятор, не копия ([[principle_reuse_not_duplication]]).
    """
    try:
        import pandas as pd
        from bot.loops.wave_loop import _dt_closed
        from core.waves.wave_analyst import wave_bus_context, wave_zone_for
        dc = getattr(bot, "data_collector", None)
        if dc is None:
            return {"wave_ctx": "нет data_collector"}
        d4 = await dc.get_ohlcv(sym, "4h", limit=400)
        if d4 is None or len(d4) < 160:
            return {"wave_ctx": f"мало 4h ({0 if d4 is None else len(d4)})"}
        dd = await dc.get_ohlcv(sym, "1d", limit=200)
        d4c = _dt_closed(d4, 4)
        ddc = _dt_closed(dd, 24) if (dd is not None and len(dd) >= 60) else None
        if len(d4c) < 150:
            return {"wave_ctx": f"мало закрытых 4h ({len(d4c)})"}
        ctx = await asyncio.to_thread(wave_bus_context, d4c, ddc, pd.Timestamp.utcnow())
        out = wave_zone_for(ctx, side, entry)
        out["wave_ctx_src"] = "посчитан на месте"
        return out
    except Exception as e:                                           # noqa: BLE001
        return {"wave_ctx": f"расчёт не удался: {type(e).__name__}"}


async def _try_register(bot, o: dict, radar_db) -> None:
    """Один сетап порта → TradingRecommendation → trade_router.submit(source='radar')."""
    try:
        from core.signals.signal_models import TradingRecommendation, SignalDirection, MarketContext
        from core.context.context_factory import build_market_context
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

    px_now = 0.0
    try:
        px_now = float(await bot.data_collector.get_current_price(symbol) or 0)
    except Exception:
        pass

    # ПЕРЕЯКОРИВАНИЕ Binance→BingX (04.07, Егор заметил расхождение цен; замер: avg 0.055%,
    # max 0.14%): уровни сетапа посчитаны на Binance-данных радара, торгуем на BingX.
    # Для SL-дистанций 0.2-0.5% сдвиг = до трети дистанции. Масштабируем мультипликативно
    # k = BingX_now / Binance_now (одновременные цены). Не вышло — уровни как есть (≤0.14%).
    if px_now > 0:
        def _bn_px_fetch():
            import urllib.request
            import json as _j
            url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={sym_feed}USDT"
            with urllib.request.urlopen(url, timeout=5) as r:
                return float(_j.load(r)["price"])
        try:
            _bn = await asyncio.get_running_loop().run_in_executor(None, _bn_px_fetch)
            _k = px_now / _bn if _bn else 1.0
            if 0.97 <= _k <= 1.03 and abs(_k - 1) > 0.0002:
                entry, sl = entry * _k, sl * _k
                tps = [t * _k for t in tps]
                logger.info("[RADAR-ARMED] %s уровни переякорены Binance→BingX k=%.5f (%+.3f%%)",
                            sym_feed, _k, (_k - 1) * 100)
        except Exception as _bne:
            logger.debug("[RADAR-ARMED] %s binance px недоступна (%s) — уровни как есть", sym_feed, _bne)

    # take_profit = ДАЛЬНЯЯ цель: ближние TP1/TP2 — частичные (multi-TP, шаг 5); финальная в БД,
    # чтобы симуляторный TP-детект/repair_missing_tp не закрыли позицию на первой цели (разведка §1-2).
    tp_final = tps[-1]

    # TP-inversion / протух по цене: цена уже за первой целью → сетап отработал без нас
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
        # 29.09: контекст собирает ШИНА (было volume_24h=0.0 — оборот терялся)
        market_context=build_market_context(bot, symbol, current_price=entry),
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
        "radar_tg_msg_id": o.get("tg_msg_id"),           # 💬 цикл сетап→вход (reply в TG)
    }
    # 🌊 ФАЗА-ФИЧИ (12.07, VANRY-разбор): build_chain_n + ltf_hh_progress → прозрачно в features
    try:
        import json as _pj
        _ph = _pj.loads(o.get("phase_json") or "{}")
        for _k, _v in _ph.items():
            extra[f"radar_{_k}"] = _v
    except Exception:
        pass
    # 🌊 ВОЛНОВОЙ КОНТЕКСТ ИЗ ШИНЫ (26.09, Егор «с третьего»: сначала копим признак, потом решаем).
    # SHADOW — только запись, НЕ гейт. Повод: у радара СВОЙ счёт ног (ZigZag 15m/24ч по Binance),
    # а про ядро OKO-SM он не знает вовсе. Замер 26.09 на 58 сделках с РЕАЛЬНЫМИ ценами:
    #   пятёрка ядра 4h встретилась радару 2 раза из 74 — как фильтр не годится, масштабы не пересекаются;
    #   зато тренд 4h: против тренда +1.08%/сд против −0.85 по тренду;
    #   и позиция в ноге: у экстремума (0.79-1.0) +1.73, в середине (<0.5) −0.68.
    # Выборки по 10-29 сделок — это гипотеза, а не эдж. Пишем признак, чтобы через месяц судить честно.
    # «нет в шине» пишется явно — молчаливый пропуск не прячем ([[feedback_selftest_every_strategy_loud]]).
    try:
        from core.waves.wave_analyst import wave_zone_for
        _side_w = "LONG" if is_long else "SHORT"
        _bus = getattr(bot, "pair_context", None)
        _z = (wave_zone_for(_bus.get(str(rec.symbol)), _side_w, float(entry))
              if _bus is not None else {"wave_ctx": "шины нет"})
        # Шина держит 120 пар и обходит их раз в 15 мин, радар ловит ВСЮ вселенную — проверка
        # по 150 сделкам с 15.09: контекст нашёлся только в 23 (15%), остальные «нет в шине».
        # Без добора признак был бы пустым у 85% заявок и копить его не имело бы смысла.
        if _z.get("wave_ctx") != "ok":
            _z = await _wave_ctx_on_demand(bot, str(rec.symbol), _side_w, float(entry)) or _z
        extra.update(_z)
    except Exception as _e:                                          # noqa: BLE001
        extra["wave_ctx"] = f"ошибка: {type(_e).__name__}"
    # 🔭 ШИРОКОЕ ЗРЕНИЕ (04.08, Егор): рыночный контекст как ФИЧИ (не гейты). Разбор 129 сделок
    # radar_pump показал ЗЕРКАЛО нашего фейда: одиночный сигнал PF 1.36 против кластера ≥4 PF 0.78,
    # возвратный режим PF 3.14 против импульсного 0.72. Пишем, чтобы судить по форварду.
    try:
        from core.context.market_regime import context_features
        extra.update(context_features(str(rec.symbol).split("/")[0]))
    except Exception:
        pass
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
