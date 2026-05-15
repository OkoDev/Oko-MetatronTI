"""
HARD gate: RR (risk/reward) фильтр.

Блокирует если |TP - entry| / |entry - SL| < min_rr_ratio (default 2.0).
Соответствует логике trade_simulator.py:386-398.

Применяется только когда есть и SL, и TP.
"""
from __future__ import annotations

from core.trading.gates.base import Gate, GateContext, GateResult, GateType


class RrFilterGate(Gate):
    name = "rr_filter"
    gate_type = GateType.HARD

    async def check(self, ctx: GateContext) -> GateResult:
        rec = ctx.rec
        entry = _get(rec, "entry_price")
        sl    = _get(rec, "stop_loss")
        tp    = _get(rec, "take_profit")

        if entry is None or sl is None or tp is None:
            return self._pass()
        try:
            entry, sl, tp = float(entry), float(sl), float(tp)
        except (TypeError, ValueError):
            return self._pass()

        if entry <= 0:
            return self._pass()

        sl_dist = abs(entry - sl)
        tp_dist = abs(tp - entry)
        if sl_dist <= 0:
            return self._pass()

        rr = tp_dist / sl_dist
        try:
            min_rr = float(ctx.bot.config.get("trading.min_rr_ratio", 2.0))
        except Exception:
            min_rr = 2.0

        if rr < min_rr:
            return self._drop(
                f"RR={rr:.2f} < min_rr={min_rr}",
                features={"rr": rr, "min_rr": min_rr, "sl_dist": sl_dist, "tp_dist": tp_dist},
            )
        return self._pass(features={"rr": rr})


def _get(obj, name):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)
