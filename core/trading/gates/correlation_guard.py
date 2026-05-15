"""
SOFT gate: penalty при превышении лимита позиций в направлении.

Конфиг trading.max_positions_per_direction (DEV-14): сколько LONG/SHORT можно открыть.
Раньше был HARD блок (return None), теперь soft.

Penalty: signal_router.penalties.correlation_guard.per_direction_overflow (default 8).
"""
from __future__ import annotations

from core.trading.gates.base import Gate, GateContext, GateResult, GateType


class CorrelationGuardGate(Gate):
    name = "correlation_guard"
    gate_type = GateType.SOFT

    async def check(self, ctx: GateContext) -> GateResult:
        try:
            max_per_dir = int(ctx.bot.config.get("trading.max_positions_per_direction", 0))
        except Exception:
            max_per_dir = 0

        if max_per_dir <= 0:
            return self._pass()

        open_in_dir = sum(
            1 for t in ctx.open_trades
            if (t.get("direction") or "").upper() == ctx.direction
        )

        if open_in_dir >= max_per_dir:
            try:
                penalty = int(ctx.bot.config.get(
                    "signal_router.penalties.correlation_guard.per_direction_overflow", 8))
            except Exception:
                penalty = 8
            return self._penalty(
                penalty,
                f"{open_in_dir}/{max_per_dir} {ctx.direction} positions",
                features={"open_in_dir": open_in_dir, "max_per_dir": max_per_dir},
            )
        return self._pass(features={"open_in_dir": open_in_dir})
