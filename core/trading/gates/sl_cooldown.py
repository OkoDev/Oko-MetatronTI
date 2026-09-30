"""
HARD gate: пара в SL-cooldown.

Блокирует если по паре было SL-закрытие в течение sl_cooldown_hours (config).
Соответствует монолитной _is_in_sl_cooldown() из bot/monitoring.py:628-647.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from core.trading.gates.base import Gate, GateContext, GateResult, GateType


class SlCooldownGate(Gate):
    name = "sl_cooldown"
    gate_type = GateType.HARD

    async def check(self, ctx: GateContext) -> GateResult:
        try:
            hours = float(ctx.bot.config.get("signal_quality.sl_cooldown_hours", 1.0))
        except Exception:
            hours = 1.0

        if hours <= 0:
            return self._pass()

        try:
            db_path = ctx.bot.trade_simulator.db_path
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            # DEV-215 bug fix: strftime с пробелом vs ISO 'T' в closed_at — SQLite
            # string compare давал T(84) > ' '(32) → все ISO timestamps всегда >= cutoff.
            # datetime() нормализует оба формата корректно.
            cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%S")
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT id, closed_at FROM simulated_trades "
                    "WHERE symbol=? AND status='SL' AND datetime(closed_at)>=datetime(?) "
                    # 30.09: сделка, открытая симуляцией филла, — наблюдение, не торговля
                    "AND (features_json IS NULL OR features_json NOT LIKE '%sim_fill_at%') "
                    "ORDER BY closed_at DESC LIMIT 1",
                    (ctx.symbol, cutoff_str),
                ).fetchone()
        except Exception as e:
            return self._pass(features={"sl_cooldown_err": str(e)})

        if row:
            return self._drop(
                f"SL closed at {row[1]} (cooldown {hours}h)",
                features={"sl_trade_id": row[0], "sl_closed_at": row[1], "cooldown_hours": hours},
            )
        return self._pass()
