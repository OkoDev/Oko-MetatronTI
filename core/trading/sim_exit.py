# -*- coding: utf-8 -*-
"""core.trading.sim_exit — SIM-exit движок (EXEC-SIM-SPLIT шаг 6, 13.07).

Дом SIM-исполнения выхода. После CUTOVER монитор разделён политикой: биржевые сделки
закрывает ExecutionSphere (WS-истина), SIM-полигон — этот детект. Здесь:
  detect_candle_exit()   — ЧИСТАЯ функция свечного детекта SL/TP/TP1/TP2 (touch-паритет
                           с биржей, sl_touch_all, data-era 11.07) — юнит-тестируема
  sim_time_exit_if_due() — тайм-выход SIM-сделки (анти-орфан, EXPIRED после N часов)

Вынесено из trade_simulator.check_open_trades_with_tsl (монолит; graphify: TradeSimulator
god node → ФАСАД НЕИЗМЕНЕН). Side-effects (запись tp-хитов в БД, шина TP1_HIT, close_trade)
остаются у вызывающего — детект только РЕШАЕТ. Перенос 1:1: parity-смоук обязателен.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

STATUS_TP = "TP"
STATUS_SL = "SL"


@dataclass
class CandleExitResult:
    """Решение свечного детекта (side-effects применяет вызывающий)."""
    exit_status: Optional[str] = None     # TP | SL | None
    exit_price: Optional[float] = None
    tp1_hit_now: bool = False             # TP1 сработал в ЭТОМ проходе (записать tp1_hit_at)
    tp2_hit_now: bool = False
    max_high: float = 0.0                 # экстремумы прохода (MFE-трекинг)
    min_low: float = float("inf")


def detect_candle_exit(df, *, direction: str, sl: Optional[float], tp: Optional[float],
                       tp1_price: Optional[float], tp1_hit_at, tp2_price: Optional[float],
                       tp2_hit_at, sl_check_close: bool, tsl_active: bool) -> CandleExitResult:
    """Свечной детект выхода (перенос 1:1 из монитора 2754-2854).

    Правила (выстраданы, не менять без data-era пометки):
    - SIM=TOUCH (11.07): SL бьётся ФИТИЛЁМ (low/high), как биржевой STOP; close-режим
      только для tsl_line-источников при выключенном sl_touch_all (sl_check_close).
    - TP1/TP2 (DUAL_TP): tp1 фиксирует часть (только если ещё не сработал), tp2 после tp1 —
      финальный выход.
    - DEV-TSL-SUPREMACY: при активном TSL фиксированный TP не режет раннера.
    - Обе цели в одной свече (hit_sl и hit_tp): тай-брейк по близости к open.
    """
    res = CandleExitResult()
    _tp1_hit_at = tp1_hit_at
    _tp2_hit_at = tp2_hit_at

    for _, row in df.iterrows():
        high = float(row.get("high", 0) or 0)
        low = float(row.get("low", 0) or 0)
        close = float(row.get("close", 0) or 0)
        open_ = float(row.get("open", 0) or 0)

        if high > 0:
            res.max_high = max(res.max_high, high)
        if low > 0:
            res.min_low = min(res.min_low, low)

        if direction == "LONG":
            hit_sl = sl is not None and (close <= sl if sl_check_close else low <= sl)
            if tp1_price and _tp1_hit_at is None and high >= tp1_price:
                _tp1_hit_at = datetime.now(timezone.utc).isoformat()
                res.tp1_hit_now = True
            if tp2_price and _tp2_hit_at is None and _tp1_hit_at and high >= tp2_price:
                _tp2_hit_at = datetime.now(timezone.utc).isoformat()
                res.tp2_hit_now = True
                res.exit_status, res.exit_price = STATUS_TP, tp2_price
            hit_tp = (not tsl_active and tp is not None and tp2_price is None
                      and tp1_price is None and high >= tp)
            if not res.exit_status:
                if hit_sl and hit_tp:
                    res.exit_status, res.exit_price = \
                        (STATUS_SL, sl) if (open_ - sl <= tp - open_) else (STATUS_TP, tp)
                elif hit_sl:
                    res.exit_status, res.exit_price = STATUS_SL, sl
                elif hit_tp:
                    res.exit_status, res.exit_price = STATUS_TP, tp
        else:  # SHORT
            hit_sl = sl is not None and (close >= sl if sl_check_close else high >= sl)
            if tp1_price and _tp1_hit_at is None and low <= tp1_price:
                _tp1_hit_at = datetime.now(timezone.utc).isoformat()
                res.tp1_hit_now = True
            if tp2_price and _tp2_hit_at is None and _tp1_hit_at and low <= tp2_price:
                _tp2_hit_at = datetime.now(timezone.utc).isoformat()
                res.tp2_hit_now = True
                res.exit_status, res.exit_price = STATUS_TP, tp2_price
            hit_tp = (not tsl_active and tp is not None and tp2_price is None
                      and tp1_price is None and low <= tp)
            if not res.exit_status:
                if hit_sl and hit_tp:
                    res.exit_status, res.exit_price = \
                        (STATUS_SL, sl) if (sl - open_ <= open_ - tp) else (STATUS_TP, tp)
                elif hit_sl:
                    res.exit_status, res.exit_price = STATUS_SL, sl
                elif hit_tp:
                    res.exit_status, res.exit_price = STATUS_TP, tp
        if res.exit_status:
            break

    return res


async def sim_time_exit_if_due(sim, trade: dict, te_hours: float, data_collector) -> bool:
    """SIM-time-exit (анти-орфан, перенос 1:1 из монитора): SIM-сделка старше te_hours →
    EXPIRED по текущей цене. Биржевые не трогаем (их время следит VST-time-exit в
    position_sync). Возврат True = закрыта (вызывающий прекращает обработку сделки)."""
    if te_hours <= 0:
        return False
    _created = trade.get("created_at")
    if not _created:
        return False
    try:
        _ct = datetime.fromisoformat(str(_created).replace("Z", "+00:00"))
        if _ct.tzinfo is None:
            _ct = _ct.replace(tzinfo=timezone.utc)
        _age_h = (datetime.now(timezone.utc) - _ct).total_seconds() / 3600.0
        if _age_h > te_hours:
            _px = await data_collector.get_current_price(trade["symbol"])
            _px = float(_px) if _px else float(trade["entry_price"])
            sim.close_trade(trade["id"], "EXPIRED", _px)
            logger.info("[SIM-TIME-EXIT] #%d %s EXPIRED (age %.0fh > %.0fh)",
                        trade["id"], trade["symbol"], _age_h, te_hours)
            return True
    except Exception as _tee:
        logger.debug("[SIM-TIME-EXIT] %s: %s", trade.get("symbol"), _tee)
    return False
