"""
position_sync.py — синхронизация биржевых позиций с TradeSimulator.

Правильный подход (DEV-145):
  Не угадываем статус по цене — читаем реальный статус исполненного ордера через
  GET /allOrders → ищем FILLED STOP_MARKET (→ SL) или TAKE_PROFIT_MARKET (→ TP/TSL),
  берём avgPrice как exit_price.

  TSL NOTE: наш TSL двигает обычный STOP ордер (cancel+replace), поэтому при срабатывании
  он возвращается как STOP_MARKET → "SL". После _resolve_exit проверяем tsl_activated=1
  и корректируем статус на "TSL".

  Если filled ордер не найден (редкая ситуация: позиция закрыта вручную или API лаг)
  — используем текущую mark_price с биржи (не угадываем статус, ставим EXPIRED).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Тип ордера → статус сделки в симуляторе
_ORDER_TYPE_TO_STATUS = {
    "STOP_MARKET":          "SL",
    "STOP":                 "SL",
    "TAKE_PROFIT_MARKET":   "TP",
    "TAKE_PROFIT":          "TP",
    "TRAILING_STOP_MARKET": "TSL",
}


async def _resolve_exit(
    client, symbol: str, direction: str, mark_price: float | None,
    sl_order_id: str | None = None, tp_order_id: str | None = None,
    position_id: str | None = None,
) -> tuple[str, float | None]:
    """
    Определяет статус (SL/TP/TSL/EXPIRED) и exit_price через filled orders на бирже.

    ПРИОРИТЕТ матчей (от надёжного к эвристике):
      0) positionID сделки — якорь жизни позиции (вход+SL+TP+перевыставленные SL = ОДИН
         positionID). Устойчив к cancel+replace SL (лечит протухший exchange_sl_order_id),
         повторным входам, старым ордерам. fake-R фикс 19.06 [[bug_phantom_exit_resolve]].
      1) orderId сделки (sl_order_id/tp_order_id) — точный, но None при незахвате /
         протухает после cancel+replace SL.
      2) эвристика symbol+side с sanity по mark — последний рубеж (хватала ЧУЖОЙ avgPrice
         по символу → фантомный exit, STG R=264 при max_R_possible=1.3).

    Returns:
        (status, exit_price)  — exit_price может быть None если данных нет.
    """
    try:
        filled = await client.get_filled_orders(symbol, limit=50)  # DEV-148: 20→50 (TP с R<0 баг)
        # LONG закрывается SELL-ордером, SHORT — BUY-ордером
        close_side = "SELL" if direction == "LONG" else "BUY"

        # 0) ЯКОРЬ positionID — самый надёжный матч. Берём close-side FILLED ордер ЭТОЙ позиции
        # (casing разный: ордер несёт `positionID`, снимок позиции — `positionId`). При нескольких
        # (частичные/перевыставленные) — последний по updateTime = реальный финальный выход.
        if position_id:
            _pid = str(position_id)
            _cands = [
                o for o in filled
                if str(o.get("positionID") or o.get("positionId") or "") == _pid
                and str(o.get("side", "")).upper() == close_side
            ]
            if _cands:
                o = max(_cands, key=lambda x: int(x.get("updateTime") or x.get("time") or 0))
                _avg = o.get("avgPrice") or o.get("stopPrice") or o.get("price")
                _status = _ORDER_TYPE_TO_STATUS.get(o.get("type", ""), "EXPIRED")
                _exit = float(_avg) if _avg else mark_price
                logger.debug("[POSITION-SYNC] %s %s: exit по positionID=%s → %s @ %.8g",
                             symbol, direction, _pid, _status, _exit or 0)
                return _status, _exit

        # 1) ТОЧНЫЙ матч по orderId сделки — нет путаницы между сделками одного символа.
        _id_map: dict[str, str] = {}
        if sl_order_id:
            _id_map[str(sl_order_id)] = "SL"
        if tp_order_id:
            _id_map[str(tp_order_id)] = "TP"
        if _id_map:
            for o in filled:
                _oid = str(o.get("orderId") or "")
                if _oid and _oid in _id_map:
                    _avg = o.get("avgPrice") or o.get("stopPrice") or o.get("price")
                    _status = _id_map[_oid]
                    _exit = float(_avg) if _avg else mark_price
                    logger.debug("[POSITION-SYNC] %s %s: exit по orderId=%s → %s @ %.8g",
                                 symbol, direction, _oid, _status, _exit or 0)
                    return _status, _exit

        # 2) FALLBACK: order id нет / ордер ещё не в истории — эвристика symbol+side.
        for o in filled:
            order_type = o.get("type", "")
            order_side = o.get("side", "")
            avg_price  = o.get("avgPrice") or o.get("stopPrice") or o.get("price")
            if order_side.upper() == close_side and order_type in _ORDER_TYPE_TO_STATUS:
                # SANITY (18.06): filled-история по символу НЕ привязана к нашей позиции
                # (нет orderId/времени). Close-ордер исполнен недавно → его цена близка к
                # mark. Если avgPrice отличается от mark в разы — это ордер ДРУГОЙ сделки
                # по тому же символу (повторные входы/hedge) → пропускаем, ищем дальше.
                # Иначе фантомный exit → R>>MFE (STG R=264 при max_R_possible=1.3). Корень
                # = матч по symbol+side без дискриминатора (класс багов data-integrity аудита).
                if avg_price and mark_price and mark_price > 0:
                    _ratio = float(avg_price) / float(mark_price)
                    if _ratio > 1.5 or _ratio < 0.67:
                        logger.debug("[POSITION-SYNC] %s %s: skip filled @ %.8g (mark=%.8g, ratio=%.2f) — чужая сделка",
                                     symbol, direction, float(avg_price), float(mark_price), _ratio)
                        continue
                status     = _ORDER_TYPE_TO_STATUS[order_type]
                exit_price = float(avg_price) if avg_price else mark_price
                logger.debug("[POSITION-SYNC] %s %s: filled %s @ %.6f → %s",
                             symbol, direction, order_type, exit_price or 0, status)
                return status, exit_price
    except Exception as e:
        logger.debug("[POSITION-SYNC] get_filled_orders %s: %s", symbol, e)

    # Fallback: позиция закрыта вручную или данных нет — ставим EXPIRED с mark_price
    return "EXPIRED", mark_price


async def _emergency_close_check(bot, sym: str, trade: dict, position: dict) -> bool:
    """
    DEV-185.2 (27.04.2026): Emergency watchdog для STOP-LIMIT non-execution.

    Сценарий: STOP-LIMIT trigger срабатывает, но limit-ордер не fill из-за gap
    (цена ушла >buffer за trigger). Позиция остаётся открытой → продолжает терять.
    Пример: #8010 APE 26.04 — overshoot 32.7%, R=-11.83 за 3 часа.

    Алгоритм:
      1. Текущая цена ушла за stop_loss > overshoot_threshold (default 0.5%)
      2. Прошло > dwell_seconds (default 300=5 мин) с момента первого нарушения
      3. → emergency market close, лог STOP_LIMIT_EMERGENCY_FILL

    Возвращает True если выполнили emergency close (вызывающий должен пропустить trade).
    """
    cfg = bot.config
    if not cfg.get("trading.dev185_2_emergency_enabled", True):
        return False

    trade_id = trade.get("id")
    direction = trade.get("direction", "LONG")
    sl = float(trade.get("stop_loss") or 0)
    entry = float(trade.get("entry_price") or 0)
    if sl <= 0 or entry <= 0:
        return False

    overshoot_threshold = float(cfg.get("trading.dev185_2_overshoot_threshold_pct", 0.5))
    dwell_seconds = int(cfg.get("trading.dev185_2_dwell_seconds", 300))

    # Текущая цена — из position data (markPrice) или с тикера
    cur_price = 0.0
    try:
        cur_price = float(position.get("markPrice") or position.get("avgPrice") or 0)
    except Exception:
        pass
    if cur_price <= 0:
        try:
            cur_price = await bot.data_collector.get_current_price(sym)
        except Exception:
            return False

    # Считаем overshoot (положительный = цена ушла за SL в плохую для нас сторону)
    if direction == "LONG":
        overshoot_pct = (sl - cur_price) / entry * 100  # cur_price ниже SL → overshoot >0
    else:
        overshoot_pct = (cur_price - sl) / entry * 100  # cur_price выше SL → overshoot >0

    # State: dict {trade_id: first_seen_ts} в bot
    dwell_state = getattr(bot, "_emergency_dwell_state", None)
    if dwell_state is None:
        dwell_state = {}
        bot._emergency_dwell_state = dwell_state

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    # OPS-06 (12.06): ВТОРОЙ триггер emergency — симулятор детектил exit (SL/TSL hit) на этой
    # сделке + прошёл live_guard_timeout, а биржа ВСЁ ЕЩЁ держит позицию (мы здесь = pos на бирже).
    # Биржевой SL мог не сработать при касании (ghost/109400) при малом overshoot → dev185_2 молчит.
    # Закрываем позицию по факту детекта (не ждём overshoot). Это правильное место для LIVE-GUARD:
    # есть состояние биржи → закрываем РЕАЛЬНУЮ позицию + БД (а не только БД в симуляторе = orphan).
    _lg_detect = getattr(bot.trade_simulator, "_live_guard_first_detect", {}).get(f"{trade_id}_exit")
    _lg_timeout_s = float(cfg.get("trading.live_guard_timeout_min", 7)) * 60
    _lg_trig = _lg_detect is not None and (now - _lg_detect).total_seconds() >= _lg_timeout_s

    if overshoot_pct < overshoot_threshold and not _lg_trig:
        # ни overshoot, ни LIVE-GUARD таймаут — норма
        if trade_id in dwell_state:
            del dwell_state[trade_id]
        return False

    # overshoot требует dwell-выдержки; LIVE-GUARD триггер уже «выждал» live_guard_timeout
    if not _lg_trig:
        first_seen = dwell_state.get(trade_id)
        if first_seen is None:
            dwell_state[trade_id] = now
            logger.info(
                "[DEV-185.2] %s #%d: overshoot %.2f%% > %.2f%% — start dwell timer (%ds)",
                sym, trade_id, overshoot_pct, overshoot_threshold, dwell_seconds,
            )
            return False
        elapsed = (now - first_seen).total_seconds()
        if elapsed < dwell_seconds:
            return False
    else:
        elapsed = (now - _lg_detect).total_seconds()
        logger.warning(
            "[OPS-06][LIVE-GUARD] %s #%d: симулятор детектил exit + %.0f мин, биржа держит "
            "→ emergency close позиции (orphan-prevent)",
            sym, trade_id, elapsed / 60,
        )

    # Триггер emergency close
    qty = float(trade.get("qty") or 0)
    if qty <= 0:
        try:
            qty = float(position.get("positionAmt") or position.get("availableAmt") or 0)
            qty = abs(qty)
        except Exception:
            pass
    if qty <= 0:
        logger.warning(
            "[DEV-185.2][EMERGENCY] %s #%d: qty неизвестен — не могу закрыть market",
            sym, trade_id,
        )
        return False

    try:
        order_mgr = getattr(bot, "order_executor", None)
        if order_mgr is None or not order_mgr.is_live():
            return False
        # multiacct-safe: client аккаунта позиции + positionId (КОРЕНЬ 101205); не основной acc
        client, _pid = await order_mgr._resolve_position_client(sym, direction)
        side_close = "SELL" if direction == "LONG" else "BUY"
        logger.warning(
            "[DEV-185.2][EMERGENCY][STOP_LIMIT_EMERGENCY_FILL] %s #%d %s: "
            "overshoot %.2f%% за %.0fс — market close qty=%s",
            sym, trade_id, direction, overshoot_pct, elapsed, qty,
        )
        resp = await client.close_position_market(sym, side_close, qty, position_id=_pid)
        code = resp.get("code", 0) if isinstance(resp, dict) else 0
        if code != 0:
            logger.warning(
                "[DEV-185.2][EMERGENCY] %s #%d market close failed code=%s — one-click fallback",
                sym, trade_id, code,
            )
            # Fallback: one-click
            resp2 = await client.close_position_one_click(sym)
            code2 = resp2.get("code", 0) if isinstance(resp2, dict) else 0
            logger.warning(
                "[DEV-185.2][EMERGENCY] %s #%d one-click fallback: code=%s",
                sym, trade_id, code2,
            )
            if code2 != 0:
                # Оба метода провалились — сбрасываем таймер, retry через dwell_seconds
                dwell_state[trade_id] = now
                logger.error(
                    "[DEV-185.2][EMERGENCY] %s #%d: оба закрытия провалились "
                    "(market=%s, one-click=%s) — retry через %ds",
                    sym, trade_id, code, code2, dwell_seconds,
                )
                return False
        # Удаляем из state — закрытие прошло успешно
        if trade_id in dwell_state:
            del dwell_state[trade_id]
        # OPS-06 (09.06): emergency закрыл ПОЗИЦИЮ НА БИРЖЕ — синхронно закрыть БД с РЕАЛЬНЫМ
        # статусом/R (через _resolve_exit по filled-ордеру). Без этого sync_positions уже не
        # видит позицию (закрыта) → orphan висит OPEN навсегда → потеря реального SL (−1R),
        # искажение метрик (avgR/WR завышены = «бумажная иллюзия»). Корень USELESS #21703.
        try:
            _st6, _px6 = await _resolve_exit(client, sym, direction, cur_price,
                                             trade.get("exchange_sl_order_id"), trade.get("exchange_tp_order_id"),
                                             trade.get("position_id"))
            if bot.trade_simulator.close_trade(trade_id, _st6, _px6):
                logger.info("[OPS-06] %s #%d: БД закрыта %s @ %.6f после emergency (orphan-prevent)",
                            sym, trade_id, _st6, _px6 or 0)
                # OPS-06: очистить LIVE-GUARD трекеры — сделка закрыта (и БД, и позиция)
                getattr(bot.trade_simulator, "_live_guard_first_detect", {}).pop(f"{trade_id}_exit", None)
                getattr(bot.trade_simulator, "_live_guard_logged", {}).pop(f"{trade_id}_exit", None)
        except Exception as _e6:
            logger.error("[OPS-06] %s #%d close_trade после emergency: %s", sym, trade_id, _e6)
        return True
    except Exception as e:
        logger.warning("[DEV-185.2][EMERGENCY] %s #%d ошибка: %s", sym, trade_id, e)
        return False


_LAST_BAL_SNAPSHOT_TS = 0.0  # ARCH-DB-V2 Ф1: throttle снапшота баланса (раз ~10 мин)
_LAST_SL_RECONCILE_TS = 0.0  # SL-RECONCILE (#1): throttle сверки SL-ордеров (раз ~5 мин)
_LAST_RECONCILE_WD_TS = 0.0  # SPHERE-SHADOW reconcile-watchdog (§6): throttle (раз ~2 мин)


async def sync_positions(bot) -> None:
    """
    Сравнивает открытые сделки в симуляторе с реальными позициями на бирже.
    Если сделка есть в симуляторе (с exchange_order_id), но позиции нет на бирже
    — читаем filled orders, определяем статус и exit_price.

    Вызывается только в VST/LIVE режиме из exchange_loop каждые 60 сек.
    SIM-сделки (exchange_order_id IS NULL) не трогает.
    """
    try:
        # DEV-145: используем OrderManager с синхронизированным временем
        order_mgr = getattr(bot, "order_executor", None)
        if order_mgr is None or not order_mgr.is_live():
            return

        # ARCH-DB-V2 Ф1: периодический снапшот баланса per-account (раз ~10 мин) для equity-графика
        import time as _t_snap
        global _LAST_BAL_SNAPSHOT_TS
        if _t_snap.time() - _LAST_BAL_SNAPSHOT_TS > 600:
            _LAST_BAL_SNAPSHOT_TS = _t_snap.time()
            try:
                from core.db import balance_repo
                _snaps = await order_mgr.snapshot_balances_per_account()
                _pc_bal = getattr(bot, "pair_context", None)
                for _b in _snaps:
                    balance_repo.save_snapshot(
                        _b["account_id"], _b["equity"], available=_b["available"],
                        used_margin=_b["used_margin"], unrealized_pnl=_b["unrealized_pnl"],
                        source="poll")
                    # BUS-L2: equity → ШИНА (REST fallback к EXEC-WS push). Без этого equity
                    # null до первого ACCOUNT_UPDATE → risk_pct/equity на дашборде пустые.
                    if _pc_bal is not None:
                        _pc_bal.update_account(_b["account_id"], equity=_b["equity"],
                                               available=_b["available"], used_margin=_b["used_margin"])
                if _snaps:
                    logger.info("[POSITION-SYNC][DB-V2] balance snapshot: %d акк", len(_snaps))
            except Exception as _bse:
                logger.warning("[POSITION-SYNC][DB-V2] balance snapshot: %s: %s",
                               type(_bse).__name__, _bse)

        client = await order_mgr._get_client_synced()

        # Получаем открытые позиции на бирже
        # FAIL-CLOSED: если get_positions() бросает — пропускаем весь цикл.
        # Пустой список из-за ошибки API нельзя считать "нет позиций" —
        # это приводит к массовому ложному закрытию tracked сделок.
        # D-061: через OrderManager кеш (15s TTL) — экономия API calls
        try:
            positions = await order_mgr._get_positions_cached()
        except Exception as _pos_err:
            # D-057: type(e).__name__ для exceptions без message
            logger.warning(
                "[POSITION-SYNC] get_positions failed → пропуск синхронизации: %s: %s",
                type(_pos_err).__name__, _pos_err,
            )
            return

        # 27.05.2026: парсинг через core.exchange.position_parser (DRY + hedge-aware).
        # До этого hedge-bug в dust-close: side = "BUY" if qty>0 else "SELL" — для SHORT
        # positionAmt тоже >0 (hedge) → BUY на SHORT, биржа отвергала.
        from core.exchange.position_parser import parse_positions, by_symbol_side
        parsed_all = parse_positions(positions)

        # ARCH-DB-V2 Ф2: сохранить current-state позиций (account_id=1 = главный клиент)
        try:
            from core.db import balance_repo as _br
            _br.upsert_positions(1, parsed_all)
        except Exception as _upe:
            logger.debug("[POSITION-SYNC][DB-V2] positions upsert: %s", _upe)

        # BUS-L2: позиции acc1 в шину (init + backup-maintain). EXEC-WS ACCOUNT_UPDATE P[]
        # держит шину живой между snapshot'ами; здесь — полный снимок (set, удаляет закрытые).
        try:
            _pc = getattr(bot, "pair_context", None)
            if _pc is not None and hasattr(_pc, "set_account_positions"):
                _snap = {
                    pp.symbol_our: {
                        "qty": abs(getattr(pp, "qty", 0) or 0), "side": pp.side,
                        "entry": getattr(pp, "entry", None),
                        "upnl": getattr(pp, "unrealized_pnl", None),
                        # РЕАЛЬНЫЕ с биржи (REST get_positions) — leverage=подтверждение
                        # выставленного плеча, mark=реальная текущая цена позиции.
                        "leverage": getattr(pp, "leverage", None),
                        "mark": getattr(pp, "mark", None),
                    }
                    for pp in parsed_all if pp.margin >= 0.01
                }
                _pc.set_account_positions(1, _snap)
        except Exception as _pbe:
            logger.debug("[POSITION-SYNC] positions→bus: %s", _pbe)

        open_pairs: dict[tuple[str, str], object] = {}  # (sym_our, side) → ParsedPosition
        for pp in parsed_all:
            if pp.margin >= 0.01:
                open_pairs[(pp.symbol_our, pp.side)] = pp
            else:
                logger.info(
                    "[POSITION-SYNC] %s %s dust position (margin=%.6f qty=%.8f) — closing on exchange",
                    pp.symbol_our, pp.side, pp.margin, pp.qty,
                )
                try:
                    close_side = "SELL" if pp.side == "LONG" else "BUY"
                    # multiacct-safe: client аккаунта позиции + positionId (КОРЕНЬ 101205)
                    _dcli, _dpid = await order_mgr._resolve_position_client(pp.symbol_our, pp.side)
                    resp = await _dcli.close_position_market(pp.symbol_our, close_side, pp.qty,
                                                             position_id=_dpid)
                    if resp.get("code", 0) != 0:
                        resp2 = await _dcli.close_position_one_click(pp.symbol_our)
                        logger.info("[POSITION-SYNC] %s dust one-click close: %s", pp.symbol_our, resp2.get("code"))
                    else:
                        logger.info("[POSITION-SYNC] %s dust closed on exchange OK", pp.symbol_our)
                except Exception as _dust_err:
                    logger.warning("[POSITION-SYNC] %s dust close failed: %s", pp.symbol_our, _dust_err)
        # SL-RECONCILE (#1, BACKLOG): позиции без живого SL-ордера → выставить из БД stop_loss.
        # Корень: SL ставится при открытии, но если исчез с биржи (исполнен/отменён/не выставлен) —
        # никто не пере-выставляет → позиция без защиты (ликвидация-риск, было 211 в DATA-AUDIT-2).
        # shadow: лог "выставил бы"; live: place_sl_order. Throttle ~5мин (REST per position).
        import time as _t_slr
        global _LAST_SL_RECONCILE_TS
        _slr_cfg = getattr(bot, "config", None)
        _slr_mode = str(_slr_cfg.get("trading.sl_reconcile", "off")).lower() if _slr_cfg else "off"
        if _slr_mode in ("shadow", "live") and open_pairs and (_t_slr.time() - _LAST_SL_RECONCILE_TS > 300):
            _LAST_SL_RECONCILE_TS = _t_slr.time()
            _db_path_slr = bot.trade_simulator.db_path
            for (_sym, _side), _pp in open_pairs.items():
                try:
                    _sl_oid = await order_mgr.get_sl_order_id(_sym, _side)
                    if _sl_oid:
                        continue  # SL на бирже есть — защищена
                    import sqlite3 as _sq_slr
                    with _sq_slr.connect(_db_path_slr, timeout=10) as _c_slr:
                        _r = _c_slr.execute(
                            "SELECT stop_loss FROM simulated_trades WHERE symbol=? AND direction=? "
                            "AND status='OPEN' AND stop_loss NOT IN ('','OPEN','0') ORDER BY id DESC LIMIT 1",
                            (_sym, _side),
                        ).fetchone()
                    _db_sl = float(_r[0]) if (_r and _r[0]) else None
                    if not _db_sl:
                        continue
                    if _slr_mode == "shadow":
                        logger.warning("[SL-RECONCILE][shadow] %s %s БЕЗ SL на бирже — выставил бы sl=%.6f (qty=%.6f)",
                                       _sym, _side, _db_sl, abs(_pp.qty))
                    else:
                        _oid = await order_mgr.place_sl_order(_sym, _side, _db_sl, abs(_pp.qty))
                        logger.warning("[SL-RECONCILE][live] %s %s SL выставлен sl=%.6f oid=%s",
                                       _sym, _side, _db_sl, _oid)
                except Exception as _slre:
                    logger.debug("[SL-RECONCILE] %s %s: %s", _sym, _side, _slre)

        # Legacy совместимость для основного цикла + _detect_orphans (sym → raw position).
        # ВНИМАНИЕ: ключ без direction — для hedge пар одна перезаписывает другую.
        # Основной цикл ниже использует open_pairs (sym, dir) для hedge-aware lookup.
        open_on_exchange: dict = {pp.symbol_our: pp.raw for pp in open_pairs.values()}

        # DEV-149: защита от API-сбоя — пропускаем синхронизацию только если
        # snapshot был пустой ДВА цикла подряд. Одиночное пустое значение может
        # быть реальным (все закрылись). Две подряд — почти наверняка API-сбой.
        open_sim_count = sum(
            1 for t in bot.trade_simulator.get_open_trades()
            if t.get("exchange_order_id")
        )
        _prev_empty = getattr(bot, "_position_sync_prev_empty", False)
        _now_empty  = len(open_on_exchange) == 0 and open_sim_count > 0
        bot._position_sync_prev_empty = _now_empty
        if _now_empty and _prev_empty:
            logger.warning(
                "[POSITION-SYNC] snapshot пустой 2-й цикл подряд (tracked=%d) — пропуск",
                open_sim_count,
            )
            return

        open_sim = bot.trade_simulator.get_open_trades()
        synced = 0

        # DEV-185.2: emergency watchdog — перед основным циклом закрытия проверяем
        # "висящие" позиции (STOP-LIMIT trigger сработал, но limit не fill из-за gap).
        for trade in open_sim:
            if not trade.get("exchange_order_id"):
                continue
            sym_w = trade.get("symbol", "")
            # hedge-aware: точная сторона. open_on_exchange (sym→raw) при LONG+SHORT
            # по паре перезаписывает одну сторону другой → emergency мог взять qty/markPrice
            # ЧУЖОЙ позиции и закрыть неверным размером. open_pairs ключ (sym, side).
            dir_w = (trade.get("direction") or "LONG").upper()
            pp_w = open_pairs.get((sym_w, dir_w))
            if pp_w is None:
                continue  # позиции этой стороны на бирже нет — обработается основным циклом
            try:
                await _emergency_close_check(bot, sym_w, trade, pp_w.raw)
            except Exception as _ew:
                logger.debug("[DEV-185.2] watchdog error %s: %s", sym_w, _ew)

        # 🔴 CUTOVER (Ф5): close-by-price ВЫКЛ — ExecutionSphere (on_close из WS-exit) +
        # reconcile-watchdog авторитетны. Этот REST close-by-price = старый buggy путь (корень
        # fake-R: _resolve_exit по 15s-mark врал). Орфан-детект ниже (нет OPEN-строки) НЕ тронут.
        _cutover = bool(getattr(bot, "config", None) and bot.config.get("trading.exec_ws.sphere_cutover", False))
        if _cutover and open_sim:
            logger.debug("[POSITION-SYNC] close-by-price OFF (sphere_cutover — Sphere авторитетен), %d OPEN пропущено", len(open_sim))
        for trade in (() if _cutover else open_sim):
            if not trade.get("exchange_order_id"):
                continue  # SIM-сделка — не трогаем

            sym       = trade.get("symbol", "")
            trade_id  = trade.get("id")
            direction = (trade.get("direction") or "LONG").upper()

            # 27.05.2026 (hedge): lookup по (sym, direction). Раньше lookup был по sym
            # без направления → если на бирже жил противоположный direction по той же паре,
            # этот trade ошибочно считался "ещё открытым".
            if (sym, direction) in open_pairs:
                continue  # позиция ещё открыта — всё нормально

            # Позиции нет на бирже → закрылась (SL/TP/TSL/вручную)
            # Читаем mark_price из данных позиции (если была) или из тикера
            mark_price: float | None = None
            try:
                mark_price = await bot.data_collector.get_current_price(sym)
            except Exception:
                pass

            status, exit_price = await _resolve_exit(client, sym, direction, mark_price,
                                                     trade.get("exchange_sl_order_id"), trade.get("exchange_tp_order_id"),
                                                     trade.get("position_id"))

            # TSL реализован через STOP ордер (cancel+replace), поэтому на бирже он
            # срабатывает как STOP_MARKET → _resolve_exit возвращает "SL".
            # Критерий TSL-exit: original_sl != stop_loss (SL реально двигался TSL'ом).
            # Это надёжнее tsl_activated (флаг ставится при +1R, но SL мог не двинуться).
            if status == "SL":
                _orig_sl = trade.get("original_sl")
                _curr_sl = float(trade.get("stop_loss") or 0)
                if (
                    _orig_sl is not None
                    and _curr_sl > 0
                    and abs(_curr_sl - float(_orig_sl)) / float(_orig_sl) > 0.0001
                ):
                    status = "TSL"
                    logger.info(
                        "[POSITION-SYNC] #%d %s: SL→TSL (orig_sl=%.6f → curr_sl=%.6f)",
                        trade_id, sym, float(_orig_sl), _curr_sl,
                    )

            if exit_price is None:
                exit_price = float(trade.get("entry_price", 0))
                logger.warning("[POSITION-SYNC] #%d %s: exit_price неизвестен, используем entry", trade_id, sym)

            # ── SANITY CHECK: exit_price не должен давать аномальный R ──────
            # Если position_sync получил текущую цену (а не реальный fill),
            # цена могла уйти далеко от SL/TP → аномальный R.
            # Fix: используем SL/TP цену как exit если status определён.
            _entry = float(trade.get("entry_price", 0))
            _sl = float(trade.get("stop_loss") or 0)
            _tp = float(trade.get("take_profit") or 0)
            _one_r = abs(_entry - _sl) if _sl and _entry != _sl else 0

            if _one_r > 0 and exit_price:
                if direction == "LONG":
                    _r_calc = (exit_price - _entry) / _one_r
                else:
                    _r_calc = (_entry - exit_price) / _one_r

                # SL не может дать R > 3 (или profit > entry×3%). Если даёт — exit_price ложный.
                # DEV-241 (02.06.2026): покрываем и TSL — TSL исполняется как STOP_MARKET,
                # переклассифицируется в "TSL" выше (строка 329) ДО этой проверки.
                if status in ("SL", "TSL") and _r_calc > 3:
                    logger.warning(
                        "[POSITION-SYNC] #%d %s: SANITY FAIL — %s exit=%.6f даёт R=%.1f "
                        "(>3). Заменяем на SL-цену %.6f",
                        trade_id, sym, status, exit_price, _r_calc, _sl,
                    )
                    exit_price = _sl

                # DEV-175 / D-049 (2026-05-23): SL с slippage R<-2 — artifact mark_price
                # fallback. _resolve_exit может не найти filled order (>50 limit, или
                # cancelled/replaced TSL'ом) → fallback на current mark_price.
                # Между fill time (T0) и position_sync detect (T1, +30-60s polling)
                # цена могла уйти далеко → artificial -7R loss.
                #
                # Реальный кейс HANA T4_S_09: 3 SHORT trades все закрылись по
                # exit=0.03829 в разные times (23:17, 00:36, 02:17). exit ≈ current
                # mark, not actual fill.
                #
                # Conservative fix: заменить exit на SL price (R = -1.0).
                # Сохраняем real slippage в log для аудита.
                #
                # DEV-241 (02.06.2026): РАСШИРЕНО на "TSL". Корень: SL→TSL переклассификация
                # (строка 329) происходит ДО этого sanity-check → 22 биржевых SHORT с
                # status=TSL проскакивали мимо D-049 → artifact mark → R=-15 (-174.5R).
                # Для TSL _sl = текущая TSL-линия (DEV-189 обновляет stop_loss при движении,
                # только tighter) → exit на TSL-линии даёт реальный R (симуляция: -174.5R → +12R).
                if status in ("SL", "TSL") and _r_calc < -2.0:
                    _orig_sl = float(trade.get("original_sl") or 0)
                    logger.warning(
                        "[POSITION-SYNC][D-049/DEV-241] #%d %s: SLIPPAGE — %s mark=%.6f R=%.1f (<-2). "
                        "SL=%.6f, orig_sl=%.6f. STOP_MARKET gap %.2f%%. "
                        "Заменяем exit_price=mark→SL (artifact mark_price fallback).",
                        trade_id, sym, status, exit_price, _r_calc, _sl, _orig_sl,
                        abs(exit_price - (_orig_sl or _sl)) / _entry * 100 if _entry else 0,
                    )
                    exit_price = _sl

                # TP не может дать R < -1. Если даёт — exit_price ложный.
                if status == "TP" and _r_calc < -1 and _tp:
                    logger.warning(
                        "[POSITION-SYNC] #%d %s: SANITY FAIL — TP exit=%.6f даёт R=%.1f "
                        "(<-1). Заменяем на TP-цену %.6f",
                        trade_id, sym, exit_price, _r_calc, _tp,
                    )
                    exit_price = _tp

                # 27.05.2026: TP overshoot — exit_price даёт R сильно выше планируемого
                # tp_rr (типично 3R). На LIVE такого не должно быть — реальный TP закрывается
                # на TP-цене или близко к ней. На VST бывают artefact'ы fill engine
                # (FHE #15191: TP=3R, но exit_price=0.0308 → R=+15 clamp). Пока только
                # лог — наблюдаем частоту; exit_price НЕ подменяем (LIVE данные не трогаем).
                _tp_rr_guess = abs(_tp - _entry) / _one_r if _one_r and _tp else 0
                if status == "TP" and _r_calc > _tp_rr_guess + 1 and _tp_rr_guess > 0:
                    logger.warning(
                        "[POSITION-SYNC][TP-OVERSHOOT] #%d %s: exit=%.6f R=%.1f >> tp_rr=%.1f+1 "
                        "(TP planned=%.6f). VST artefact или реальный gap — exit_price НЕ заменён.",
                        trade_id, sym, exit_price, _r_calc, _tp_rr_guess, _tp,
                    )

                # EXPIRED с огромным R — текущая цена ушла далеко от входа
                if status == "EXPIRED" and abs(_r_calc) > 10 and _sl:
                    logger.warning(
                        "[POSITION-SYNC] #%d %s: EXPIRED exit=%.6f даёт R=%.1f "
                        "(>10). Заменяем на SL-цену %.6f",
                        trade_id, sym, exit_price, _r_calc, _sl,
                    )
                    exit_price = _sl
                    status = "SL"

            # 28.05.2026: статус EXPIRED отменён полностью. Если closing-ордер не найден
            # (manual close / TSL cancel+replace / >50 orders / API лаг), позиция всё равно
            # закрыта на бирже — классифицируем по факту P&L, чтобы не плодить зомби-OPEN
            # и не писать EXPIRED. profit → TP (TSL если SL двигался), loss → SL.
            if status == "EXPIRED":
                if _one_r > 0 and exit_price:
                    _r_final = ((exit_price - _entry) if direction == "LONG"
                                else (_entry - exit_price)) / _one_r
                else:
                    _r_final = 0.0
                _orig_sl_x = trade.get("original_sl")
                _curr_sl_x = float(trade.get("stop_loss") or 0)
                _sl_moved = (
                    _orig_sl_x and _curr_sl_x > 0
                    and abs(_curr_sl_x - float(_orig_sl_x)) / float(_orig_sl_x) > 0.0001
                )
                status = "SL" if _r_final < 0 else ("TSL" if _sl_moved else "TP")
                logger.info(
                    "[POSITION-SYNC] #%d %s: closing-ордер не найден → классифицирован "
                    "по P&L: R=%.2f → %s (EXPIRED отменён)",
                    trade_id, sym, _r_final, status,
                )

            try:
                bot.trade_simulator.close_trade(trade_id, status, exit_price)
                logger.info("[POSITION-SYNC] #%d %s %s → %s @ %.6f",
                            trade_id, sym, direction, status, exit_price)
                synced += 1
            except Exception as e:
                logger.warning("[POSITION-SYNC] close_trade #%d error: %s", trade_id, e)

        if synced:
            logger.info("[POSITION-SYNC] синхронизировано %d закрытых позиций", synced)

        # D-070 (25.05): Orphan position detector.
        # На бирже есть позиция, в БД нет соответствующей status='OPEN' записи.
        # Это критическая ситуация: бот не контролирует позицию (нет SL/TP в БД,
        # TSL не работает, position_sync не закроет). Источник: ручное открытие,
        # рассинхрон после bot crash, или баг закрытия (как PIEVERSE 25.05).
        try:
            await _detect_orphans(bot, open_on_exchange, open_sim)
        except Exception as _orphan_err:
            logger.warning("[D-070] orphan detector error: %s", _orphan_err)

        # SPHERE-SHADOW reconcile-watchdog (§6, CUTOVER-страховка): store-open vs биржа-флэт
        # N циклов подряд → пропущенное WS-закрытие / «?»-exit. Shadow: лог «would-close»
        # (реально НЕ закрывает; on_close=None). Только если sphere построен (sphere_shadow).
        import time as _t_wd
        global _LAST_RECONCILE_WD_TS
        _sphere = getattr(bot, "_exec_sphere", None)
        if _sphere is not None:
            # BACKFILL positionId в store ИЗ БД (simulated_trades.position_id = 100% via tsl_updater;
            # WS pid НЕ даёт — корень «?»-exit). Каждый цикл (~60s), локально, без REST. Закрывает
            # CUTOVER-гейт: с pid close резолвится даже при гонке fill↔pa=0.
            try:
                _nbf = _sphere.backfill_position_ids(open_sim)
                if _nbf:
                    logger.info("[SPHERE-SHADOW] backfill pid из БД: %d позиций", _nbf)
            except Exception as _bfe:
                logger.debug("[SPHERE-SHADOW] backfill pid err: %s", _bfe)
        if _sphere is not None and (_t_wd.time() - _LAST_RECONCILE_WD_TS > 120):
            _LAST_RECONCILE_WD_TS = _t_wd.time()
            try:
                _accs = list(getattr(_sphere._adapter._router, "accounts", [1]))
            except Exception:
                _accs = [1]
            for _acc_wd in _accs:
                try:
                    _esc = await _sphere.reconcile_watchdog(_acc_wd, min_cycles=2)
                    for _it in _esc:
                        _ex = _it.exit
                        logger.warning(
                            "[SPHERE-SHADOW] RECONCILE would-close %s %s acc=%s → %s @ %s "
                            "(store-open, биржа-флэт ≥2 цикла; WS-close пропущен/«?»-exit)",
                            _it.symbol, _it.side, _acc_wd,
                            (_ex.status if _ex else "?"),
                            (f"{_ex.exit_price:.8g}" if _ex else "?"))
                except Exception as _wde:
                    logger.debug("[SPHERE-SHADOW] reconcile_watchdog acc=%s: %s", _acc_wd, _wde)

    except Exception as e:
        logger.warning("[POSITION-SYNC] ошибка: %s", e)


async def _detect_orphans(bot, open_on_exchange: dict, open_sim: list) -> None:
    """D-070: находит позиции на бирже без OPEN записи в БД, шлёт Telegram alert.

    Hedge-aware: каждая (symbol, side) пара — независимая позиция.
    Парсинг через core.exchange.position_parser (один источник правды).

    Throttle: один алерт на (symbol, side) раз в 30 минут.
    """
    from core.exchange.position_parser import parse_position
    if not open_on_exchange:
        return
    # tracked_pairs/hedge-skip — ТОЛЬКО биржевые сделки (VST/LIVE или с реальным
    # exchange_order_id). Чистые SIM-тени НЕ маскируют биржевых орфанов (баг 20.06:
    # SIM-строка #31821 DOLPHIN LONG скрыла живого призрака от детектора).
    def _is_exch_trade(t):
        return (str(t.get("execution_mode") or "").upper() != "SIM"
                or str(t.get("exchange_order_id") or "") not in ("", "SIM"))
    _exch_open = [t for t in open_sim if t.get("symbol") and _is_exch_trade(t)]
    tracked_pairs = {
        (t.get("symbol"), (t.get("direction") or "").upper())
        for t in _exch_open
    }

    import time as _t
    state = getattr(bot, "_orphan_alert_last", None)
    if state is None:
        state = {}
        bot._orphan_alert_last = state
    now = _t.time()
    THROTTLE_SEC = 1800   # 30 минут на (symbol, side)

    # D-070 PREVENTION (19.06): orphan auto-close (config-gated, паттерн sl_reconcile).
    # off=только alert · shadow=лог "закрыл бы" · live=account-aware close (one_click_on_fail).
    # Корень рассинхрона БД↔биржа: emergency-close не до-флэтнул / SIM-утечка → orphan висит.
    _ac_cfg = getattr(bot, "config", None)
    _autoclose_mode = str(_ac_cfg.get("trading.orphan_autoclose", "off")).lower() if _ac_cfg else "off"
    _ac_om = getattr(bot, "order_executor", None)
    if _ac_om is None or not _ac_om.is_live():
        _autoclose_mode = "off"   # без live-клиента close невозможен
    # ХЕДЖ-SAFETY: символы где БД держит ЛЮБОЙ OPEN — one-click задел бы управляемого брата
    # → skip auto-close (точечный close_hedge_orphans вручную). Pure-orphan символы безопасны.
    _ac_open_syms = {t.get("symbol") for t in _exch_open}

    for sym, pos in open_on_exchange.items():
        pp = parse_position(pos)
        if pp is None:
            continue

        if (pp.symbol_our, pp.side) in tracked_pairs:
            continue   # есть OPEN запись — не orphan

        key = f"{pp.symbol_our}:{pp.side}"
        last = state.get(key, 0)
        if (now - last) < THROTTLE_SEC:
            continue
        state[key] = now

        text = (
            f"🚨 *D-070 ORPHAN POSITION*\n"
            f"`{pp.symbol_our}` {pp.side} (без OPEN в БД!)\n"
            f"qty=`{pp.qty:.4f}`  mark=`{pp.mark:.6f}`\n"
            f"notional=`${pp.notional:.2f}`  leverage=`{pp.leverage}x`\n"
            f"margin=`${pp.margin:.2f}`  unrealPnL=`${pp.unrealized_pnl:+.2f}`\n"
            f"⚠️ Бот НЕ управляет позицией. Проверь BingX UI и закрой вручную либо разберись с рассинхроном."
        )
        logger.error("[D-070] ORPHAN %s %s qty=%.4f mark=%.6f pnl=%.2f",
                     pp.symbol_our, pp.side, pp.qty, pp.mark, pp.unrealized_pnl)
        try:
            from bot.monitoring import broadcast_with_subscription_check
            await broadcast_with_subscription_check(bot, text, "orphan_position")
        except Exception as _alert_err:
            logger.warning("[D-070] TG alert error: %s", _alert_err)

        # D-070 PREVENTION (19.06): авто-закрытие orphan'а (config-gated, hedge-safe).
        if _autoclose_mode in ("shadow", "live"):
            if pp.symbol_our in _ac_open_syms:
                logger.warning(
                    "[D-070][autoclose] %s %s — символ с DB-OPEN (hedge) → skip (ручной close_hedge_orphans)",
                    pp.symbol_our, pp.side)
            elif _autoclose_mode == "shadow":
                logger.warning("[D-070][autoclose][shadow] %s %s закрыл бы market qty=%.6f",
                               pp.symbol_our, pp.side, abs(pp.qty))
            else:
                try:
                    # account-aware (КОРЕНЬ 101205) + one_click_on_fail (символ без DB-OPEN → брата нет)
                    _ac_side = "SELL" if pp.side == "LONG" else "BUY"
                    _ac_cli, _ac_pid = await _ac_om._resolve_position_client(pp.symbol_our, pp.side)
                    _ac_resp = await _ac_cli.close_position_market(
                        pp.symbol_our, _ac_side, abs(pp.qty), one_click_on_fail=True, position_id=_ac_pid)
                    _ac_code = _ac_resp.get("code", 0) if isinstance(_ac_resp, dict) else 0
                    if _ac_code == 0:
                        logger.warning("[D-070][autoclose][live] %s %s ЗАКРЫТ market (positionId=%s)",
                                       pp.symbol_our, pp.side, _ac_pid)
                    else:
                        logger.error("[D-070][autoclose][live] %s %s close FAILED code=%s msg=%s",
                                     pp.symbol_our, pp.side, _ac_code, str(_ac_resp.get('msg', ''))[:50])
                except Exception as _ace:
                    logger.error("[D-070][autoclose][live] %s %s err: %s", pp.symbol_our, pp.side, _ace)


async def fix_zero_r_trades(bot, dry_run: bool = True) -> int:
    """
    DEV-145: Чистка исторических VST сделок с exit_price = entry_price (R=0).

    Для каждой такой сделки:
      1. Пытается найти реальный exit через get_filled_orders() API.
      2. Если находит — обновляет exit_price и status.
      3. Если нет — помечает status='UNKNOWN' чтобы не искажать статистику.

    dry_run=True (по умолчанию) — только логирует, не меняет БД.
    Возвращает количество найденных / обновлённых записей.

    Запуск:
        import asyncio
        from core.exchange.position_sync import fix_zero_r_trades
        asyncio.run(fix_zero_r_trades(bot, dry_run=False))
    """
    import sqlite3

    order_mgr = getattr(bot, "order_executor", None)
    if order_mgr is None or not order_mgr.is_live():
        logger.warning("[fix_zero_r] OrderManager недоступен или режим SIM")
        return 0

    client = await order_mgr._get_client_synced()

    # Ищем VST-сделки (exchange_order_id есть) с exit ≈ entry (R=0)
    try:
        with sqlite3.connect(bot.trade_simulator.db_path, timeout=10) as conn:
            conn.execute("PRAGMA busy_timeout=10000")  # DEV-148
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT id, symbol, direction, entry_price, stop_loss, exit_price, status
                FROM simulated_trades
                WHERE status IN ('TP', 'SL', 'TSL')
                  AND exchange_order_id IS NOT NULL
                  AND exchange_order_id != ''
                  AND exit_price IS NOT NULL
                  AND ABS(exit_price - entry_price) < 0.000001
                ORDER BY closed_at DESC
                LIMIT 200
            """).fetchall()
    except Exception as e:
        logger.error("[fix_zero_r] БД ошибка: %s", e)
        return 0

    logger.info("[fix_zero_r] найдено %d сделок с exit_price=entry_price (R=0)", len(rows))
    updated = 0

    for row in rows:
        trade_id  = row["id"]
        sym       = row["symbol"]
        entry     = float(row["entry_price"] or 0)
        direction = row["direction"]

        new_exit: float | None = None
        new_status: str | None = None

        # Ищем реальный exit в filled orders
        try:
            filled = await client.get_filled_orders(sym, limit=50)
            filled = sorted(
                filled,
                key=lambda o: int(o.get("updateTime") or o.get("time") or 0),
                reverse=True,
            )
            close_side = "SELL" if direction == "LONG" else "BUY"
            for o in filled:
                o_type  = (o.get("type") or "").upper()
                o_side  = (o.get("side") or "").upper()
                o_price = float(o.get("avgPrice") or o.get("price") or 0)
                if o_side == close_side and o_price > 0 and abs(o_price - entry) > entry * 0.0001:
                    new_exit   = o_price
                    new_status = _ORDER_TYPE_TO_STATUS.get(o_type)
                    if new_status is None:
                        sl = float(row["stop_loss"] or 0)
                        if sl:
                            new_status = "SL" if (
                                (direction == "LONG" and o_price <= sl * 1.002) or
                                (direction == "SHORT" and o_price >= sl * 0.998)
                            ) else "TP"
                        else:
                            new_status = "TP"
                    break
        except Exception as e:
            logger.debug("[fix_zero_r] %s filled_orders error: %s", sym, e)

        if new_exit is None:
            # Реальных данных нет — помечаем UNKNOWN
            new_status = "UNKNOWN"
            new_exit   = entry

        if dry_run:
            logger.info("[fix_zero_r][DRY] #%d %s %s: %s→%s exit=%.8f",
                        trade_id, sym, direction, row["status"], new_status, new_exit)
        else:
            try:
                with sqlite3.connect(bot.trade_simulator.db_path, timeout=10) as conn:
                    conn.execute("PRAGMA busy_timeout=10000")  # DEV-148
                    conn.execute(
                        "UPDATE simulated_trades SET exit_price=?, status=?, R_multiple=NULL WHERE id=?",
                        (new_exit, new_status, trade_id),
                    )
                logger.info("[fix_zero_r] #%d %s: %s→%s exit=%.8f",
                            trade_id, sym, row["status"], new_status, new_exit)
                updated += 1
            except Exception as e:
                logger.warning("[fix_zero_r] update #%d: %s", trade_id, e)

    total = len(rows)
    logger.info("[fix_zero_r] итог: %s %d/%d",
                "dry_run" if dry_run else "обновлено", updated if not dry_run else total, total)
    return updated if not dry_run else total
