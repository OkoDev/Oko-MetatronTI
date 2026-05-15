"""
SOFT gate: penalty после серии SL по паре (pair_cooldown_sl_streak).

ARCH-88: если у пары N SL подряд — пара "не в форме", penalty.
Раньше был HARD блок, теперь soft.

Конфиг signal_quality.pair_cooldown_sl_streak (default 5).
Penalty: signal_router.penalties.pair_cooldown_streak.after_N_sl (default 15).
"""
from __future__ import annotations

import sqlite3

from core.trading.gates.base import Gate, GateContext, GateResult, GateType


class PairCooldownStreakGate(Gate):
    name = "pair_cooldown_streak"
    gate_type = GateType.SOFT

    async def check(self, ctx: GateContext) -> GateResult:
        try:
            threshold = int(ctx.bot.config.get("signal_quality.pair_cooldown_sl_streak", 5))
        except Exception:
            threshold = 5

        if threshold <= 0:
            return self._pass()

        try:
            db_path = ctx.bot.trade_simulator.db_path
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT status FROM simulated_trades "
                    "WHERE symbol=? AND status IN ('TP','TSL','SL','EXPIRED') "
                    "ORDER BY closed_at DESC LIMIT ?",
                    (ctx.symbol, threshold),
                ).fetchall()
            statuses = [r[0] for r in rows]
        except Exception:
            return self._pass()

        if len(statuses) >= threshold and all(s == "SL" for s in statuses):
            try:
                penalty = int(ctx.bot.config.get(
                    "signal_router.penalties.pair_cooldown_streak.after_5_sl", 15))
            except Exception:
                penalty = 15
            return self._penalty(
                penalty,
                f"{threshold} SL подряд для {ctx.symbol}",
                features={"sl_streak": threshold},
            )
        return self._pass(features={"recent_statuses": statuses})
