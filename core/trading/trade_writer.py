# -*- coding: utf-8 -*-
"""core.trading.trade_writer — финализация закрытия сделки (EXEC-SIM-SPLIT шаг 5, 13.07).

ОДИН калькулятор финализации для обоих контуров (SIM-полигон и VST/биржа):
  compute_finalize()  — ЧИСТАЯ математика (R-math, частичный TP1, MFE, duration, косты) — без IO
  persist_close()     — UPDATE simulated_trades
  emit_close_events() — хвосты-сайдэффекты одним блоком (DEV-39, POST_TSL, Куб, DEV-94, SSE, DEV-222)

Вынесен из trade_simulator.close_trade (монолит 3152 строк; graphify: TradeSimulator =
god node, 101 ребро → ФАСАД НЕИЗМЕНЕН, наружу торчит только close_trade, внутренности —
здесь). Различия контуров SIM/VST = параметры resolve-слоя (clamp применяет вызывающий),
финализация ЕДИНА → обучение (Сфера 11) кормится одинаково от обоих контуров.

Перенос 1:1 (13.07): логика не менялась, parity-тест на копии БД обязателен при правках.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FinalizeResult:
    """Результат финализации — всё, что пишется в БД при закрытии."""
    profit_pct: Optional[float]
    r_multiple: Optional[float]
    max_R_possible: Optional[float]
    captured_R_pct: Optional[float]
    duration_minutes: Optional[float]
    total_fee: float
    costs_pct: float


def compute_finalize(*, trade_id: int, symbol: str, dir_up: str, entry: float,
                     exit_price: float, sl: Optional[float], original_sl: Optional[float],
                     tp1_price: Optional[float], tp1_hit_at, max_price: Optional[float],
                     min_price: Optional[float], created_at, closed_at: datetime,
                     qty: Optional[float]) -> FinalizeResult:
    """Чистая математика закрытия (перенос из close_trade 1712-1805, 1:1).

    R-multiple через core.trading.r_math (1R = |entry − original_sl|), частичный TP1
    (tp1_fix_pct% позиции), умный clamp по причине (sl_dist≈0 артефакт), MFE
    (max_R_possible/captured_R_pct), duration, комиссия qty-сделок, costs_pct (ЗАКОН №1:
    net% = gross − косты; работает и для SIM без qty).
    """
    from core.trading.r_math import compute_one_r, compute_r, clamp_r_smart

    one_r, _r_src = compute_one_r(entry, original_sl, fallback_sl=sl)
    r_multiple = None

    # profit_pct и R с учётом частичного TP1 (tp1_fix_pct% позиции)
    if tp1_hit_at and tp1_price and one_r:
        _tp1_fix = 0.7
        try:
            from core.infra.config_loader import config as _cfg_fix
            _tp1_fix = float(
                (_cfg_fix.get("trading.dual_tp") or {}).get("tp1_fix_pct", 70)
            ) / 100.0
        except Exception:
            pass
        _tp2_fix = 1.0 - _tp1_fix
        r_tp1 = compute_r(dir_up, entry, tp1_price, one_r) or 0.0
        r_exit = compute_r(dir_up, entry, exit_price, one_r) or 0.0
        if dir_up == "LONG":
            pct_tp1 = (tp1_price - entry) / entry * 100.0
            pct_exit = (exit_price - entry) / entry * 100.0
        else:
            pct_tp1 = (entry - tp1_price) / entry * 100.0
            pct_exit = (entry - exit_price) / entry * 100.0
        r_multiple = round(_tp1_fix * r_tp1 + _tp2_fix * r_exit, 3)
        profit_pct = round(_tp1_fix * pct_tp1 + _tp2_fix * pct_exit, 4)
    else:
        # Обычный выход без частичного TP
        if dir_up == "LONG":
            profit_pct = (exit_price - entry) / entry * 100.0
        else:
            profit_pct = (entry - exit_price) / entry * 100.0
        if one_r:
            r_multiple = compute_r(dir_up, entry, exit_price, one_r)

    # Умный clamp по ПРИЧИНЕ (sl_dist), не величине: раннеры дышат, артефакт sl_dist≈0 клампится
    if r_multiple is not None:
        _clamped = clamp_r_smart(r_multiple, entry, one_r)
        if _clamped != r_multiple:
            logger.warning(
                "R_multiple clamp: id=%s %s R=%.2f → %.2f (sl_dist≈0 артефакт, src=%s)",
                trade_id, dir_up, r_multiple, _clamped, _r_src,
            )
        r_multiple = round(_clamped, 3)

    # MFE: максимально достижимый R и % захваченного потенциала (one_r от original_sl)
    max_R_possible = None
    captured_R_pct = None
    if one_r and one_r > 0:
        _peak = max_price if dir_up == "LONG" else min_price
        if _peak:
            _mfe = compute_r(dir_up, entry, _peak, one_r)
            max_R_possible = round(clamp_r_smart(_mfe, entry, one_r), 3) if _mfe is not None else None
        if max_R_possible and max_R_possible > 0 and r_multiple is not None:
            # captured = % захвата ПОЛОЖИТЕЛЬНОГО потенциала, clamp [0,100]
            _cap_raw = (r_multiple / max_R_possible) * 100.0
            captured_R_pct = round(max(0.0, min(100.0, _cap_raw)), 1)

    # duration_minutes (оба timestamp aware UTC)
    try:
        if isinstance(created_at, str):
            created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        else:
            created_dt = created_at
        if created_dt.tzinfo is None:
            created_dt = created_dt.replace(tzinfo=timezone.utc)
        _closed_utc = closed_at if closed_at.tzinfo else closed_at.replace(tzinfo=timezone.utc)
        duration_minutes = (_closed_utc - created_dt).total_seconds() / 60.0
        if duration_minutes < 0:
            duration_minutes = abs(duration_minutes)
            logger.warning("[trade %d] negative duration corrected: created=%s closed=%s",
                           trade_id, created_at, closed_at)
    except Exception:
        duration_minutes = None

    # комиссия round-trip: qty × entry × 0.1% (только сделки с реальным qty)
    total_fee = round(float(qty) * entry * 0.001, 4) if qty else 0.0

    # COSTS-PCT (12.07): косты в % для net (работают и для SIM без qty). ЗАКОН №1.
    try:
        from core.infra.config_loader import config as _cfg_cost
        _taker = float(_cfg_cost.get("simulation.taker_fee_pct", 0.045))
        _fund_nom = float(_cfg_cost.get("simulation.funding_est_pct", 0.01))
    except Exception:
        _taker, _fund_nom = 0.045, 0.01
    _hold_h = (duration_minutes / 60.0) if duration_minutes else 0.0
    costs_pct = round(_taker * 2 + (_hold_h / 8.0) * _fund_nom, 4)

    return FinalizeResult(profit_pct=profit_pct, r_multiple=r_multiple,
                          max_R_possible=max_R_possible, captured_R_pct=captured_R_pct,
                          duration_minutes=duration_minutes, total_fee=total_fee,
                          costs_pct=costs_pct)


def persist_close(cursor, trade_id: int, status: str, exit_price: float,
                  closed_at: datetime, res: FinalizeResult) -> None:
    """UPDATE simulated_trades финальными полями (перенос из close_trade 1807-1818, 1:1)."""
    cursor.execute(
        """
        UPDATE simulated_trades
        SET status = ?, exit_price = ?, profit_pct = ?, R_multiple = ?,
            closed_at = ?, duration_minutes = ?, max_R_possible = ?, captured_R_pct = ?,
            total_fee = ?, costs_pct = ?
        WHERE id = ?
        """,
        (status, exit_price, res.profit_pct, res.r_multiple,
         closed_at.isoformat(), res.duration_minutes,
         res.max_R_possible, res.captured_R_pct, res.total_fee, res.costs_pct, trade_id),
    )


def emit_close_events(sim, *, trade_id: int, status: str, symbol: str, direction,
                      entry: float, sl: Optional[float], exit_price: float,
                      r_multiple: Optional[float], max_R_possible: Optional[float],
                      max_price_db: Optional[float], min_price_db: Optional[float],
                      entry_tf_db) -> None:
    """Хвосты закрытия одним блоком (перенос из close_trade 1822-1928, 1:1) —
    каждый срабатывает ровно один раз, независимо от контура (SIM/VST):
      DEV-39 market-event окно SL · DEV-92 post-TSL очередь · Куб POSITION_CLOSED ·
      DEV-94 PostTradeAnalyser · SSE дашборда · DEV-222 TG-reply.
    sim = TradeSimulator (duck-typed: _sl_timestamps/_post_tsl_queue/_pair_context_bus/
    _post_trade_callback/_sse_trade_closed/_tg_close_callback/_db_connect/
    _mark_market_event_in_window)."""
    from core.trading.trade_simulator import STATUS_SL, STATUS_TSL

    # 26.09: закрываем запись live_orders вместе со сделкой. Раньше её закрывал только
    # sync_with_exchange при старте бота — после простоя 24–25.09 девять записей остались
    # OPEN с уже закрытыми сделками, и /api/live показывал в рынке то, чего там нет.
    try:
        from core.trading.position_manager import PositionManager
        _n_lo = PositionManager().close_by_sim_trade(trade_id)
        if _n_lo:
            logger.info("[live_orders] закрыто записей: %d (сделка #%d)", _n_lo, trade_id)
    except Exception as _e_lo:                                   # noqa: BLE001
        logger.debug("[live_orders] close_by_sim_trade #%s: %s", trade_id, _e_lo)

    # DEV-39: Market Event Marker — скользящее окно SL
    if status == STATUS_SL:
        try:
            from core.infra.config_loader import config as _cfg
            _me = _cfg.get("trading", {}).get("market_event_marker", {}) if _cfg else {}
            if _me.get("enabled", True):
                _sl_count_thr = int(_me.get("sl_count", 5))
                _window_min = int(_me.get("window_minutes", 30))
                _now = datetime.now(timezone.utc)
                sim._sl_timestamps.append(_now)
                _window_start = _now - timedelta(minutes=_window_min)
                sim._sl_timestamps = [t for t in sim._sl_timestamps if t >= _window_start]
                if len(sim._sl_timestamps) >= _sl_count_thr:
                    logger.warning(
                        "[DEV-39] Market Event: %d SL за %d мин → маркируем сделки в окне",
                        len(sim._sl_timestamps), _window_min,
                    )
                    sim._mark_market_event_in_window(_window_start)
        except Exception as _e:
            logger.debug("[DEV-39] Market Event Marker error: %s", _e)

    # DEV-92 / TR-010: Post-TSL очередь для OTE Re-entry мониторинга
    if status == STATUS_TSL and symbol:
        _dir92 = str(direction).upper() if direction else None
        sim._post_tsl_queue[symbol] = {
            "direction": _dir92,
            "exit_price": exit_price,
            "impulse_high": max_price_db,
            "impulse_low": min_price_db,
            "exit_time": datetime.now(timezone.utc),
            "ttl_hours": 8,
        }
        logger.info(
            "[POST_TSL_QUEUE] %s: добавлен direction=%s impulse=[%.4f, %.4f]",
            symbol, _dir92, min_price_db or 0, max_price_db or 0,
        )

    # Куб: Сфера 10 (Exit Manager) → bus: POSITION_CLOSED
    _pcb = getattr(sim, "_pair_context_bus", None)
    if _pcb is not None and symbol:
        try:
            from core.context.pair_context import SphereEvent
            _pcb.publish(symbol, SphereEvent.POSITION_CLOSED, {
                "trade_id": trade_id,
                "status": status,
                "r_multiple": round(r_multiple, 3) if r_multiple is not None else 0.0,
                "direction": str(direction).upper() if direction else "LONG",
                "exit_price": exit_price,
            })
        except Exception as _epc:
            logger.debug("[Cube] POSITION_CLOSED publish error: %s", _epc)

    # DEV-94: callback для PostTradeAnalyser (async, не блокируем)
    if sim._post_trade_callback and symbol:
        try:
            import asyncio as _asyncio
            _r = r_multiple if r_multiple is not None else 0.0
            _sl_dist = abs(entry - (sl or entry))
            _asyncio.create_task(sim._post_trade_callback(
                trade_id=trade_id,
                status=status,
                symbol=symbol,
                direction=str(direction).upper() if direction else "LONG",
                r_multiple=_r,
                entry_price=entry,
                sl_dist=_sl_dist,
                max_price=max_price_db,
                min_price=min_price_db,
                entry_tf=entry_tf_db or "15m",
            ))
        except Exception as _ecb:
            logger.debug("[DEV-94] post_trade_callback error: %s", _ecb)

    # SSE broadcast: уведомляем дашборд о закрытой сделке
    if sim._sse_trade_closed:
        try:
            import asyncio as _aio_sse
            _aio_sse.create_task(sim._sse_trade_closed(trade_id))
        except Exception as _esse:
            logger.debug("[SSE] sse_trade_closed callback error: %s", _esse)

    # DEV-222: TG reply при закрытии (reply на сообщение об открытии)
    if sim._tg_close_callback:
        try:
            import asyncio as _aio_tg
            _tsl_act = 0
            try:
                with sim._db_connect() as _tg_conn:
                    _tg_row = _tg_conn.execute(
                        "SELECT tsl_activated FROM simulated_trades WHERE id=?", (trade_id,)
                    ).fetchone()
                    _tsl_act = int(_tg_row[0]) if _tg_row else 0
            except Exception:
                pass
            _aio_tg.create_task(sim._tg_close_callback(
                trade_id=trade_id,
                status=status,
                symbol=symbol,
                direction=str(direction).upper() if direction else "LONG",
                r_multiple=r_multiple if r_multiple is not None else 0.0,
                tsl_activated=_tsl_act,
                max_r_possible=max_R_possible,
            ))
        except Exception as _etg:
            logger.debug("[DEV-222] tg_close_callback error: %s", _etg)
