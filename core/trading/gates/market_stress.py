"""
SOFT gate: penalty при стрессе рынка (серия SL за короткое окно).

ARCH-42: если за последние N минут было K SL — рынок в стрессе.
Раньше был HARD блок, теперь soft.

Конфиг:
  trading.market_stress.window_minutes (default 30)
  trading.market_stress.sl_threshold   (default 5)

Penalty: signal_router.penalties.market_stress.sl_serie (default 12).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from core.trading.gates.base import Gate, GateContext, GateResult, GateType


class MarketStressGate(Gate):
    name = "market_stress"
    gate_type = GateType.SOFT

    async def check(self, ctx: GateContext) -> GateResult:
        try:
            window_min = int(ctx.bot.config.get("trading.market_stress.window_minutes", 30))
            sl_thresh  = int(ctx.bot.config.get("trading.market_stress.sl_threshold", 5))
        except Exception:
            window_min, sl_thresh = 30, 5

        if window_min <= 0 or sl_thresh <= 0:
            return self._pass()

        try:
            db_path = ctx.bot.trade_simulator.db_path
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_min)
            # ISO 'T' separator — SQLite datetime() нормализует оба формата.
            # Bug fix DEV-215: strftime("%Y-%m-%d %H:%M:%S") давал пробел вместо 'T',
            # SQLite string compare 'T'(84) > ' '(32) → все ISO closed_at всегда >= cutoff.
            cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%S")
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM simulated_trades "
                    "WHERE status='SL' AND datetime(closed_at)>=datetime(?)",
                    (cutoff_str,),
                ).fetchone()
            sl_count = int(row[0] if row else 0)
        except Exception:
            return self._pass()

        if sl_count >= sl_thresh:
            try:
                penalty = int(ctx.bot.config.get(
                    "signal_router.penalties.market_stress.sl_serie", 12))
            except Exception:
                penalty = 12
            return self._penalty(
                penalty,
                f"{sl_count} SL за {window_min}min",
                features={"sl_count": sl_count, "window_min": window_min, "threshold": sl_thresh},
            )
        return self._pass(features={"sl_count": sl_count})
