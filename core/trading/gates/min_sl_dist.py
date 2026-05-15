"""
HARD gate: SL дистанция от entry не должна быть слишком близкой.

Блокирует если |entry - sl| / entry < min_sl_dist_pct (default 0.1%).
Соответствует DEV-157/164 в trade_simulator.py:368-384.
"""
from __future__ import annotations

from core.trading.gates.base import Gate, GateContext, GateResult, GateType


class MinSlDistGate(Gate):
    name = "min_sl_dist"
    gate_type = GateType.HARD

    async def check(self, ctx: GateContext) -> GateResult:
        rec = ctx.rec
        entry = _get(rec, "entry_price")
        sl    = _get(rec, "stop_loss")
        if entry is None or sl is None or float(entry) <= 0:
            return self._pass()   # пропускаем валидацию — validate_inputs ловит

        try:
            min_pct = float(ctx.bot.config.get("trading.min_sl_dist_pct", 0.1))
        except Exception:
            min_pct = 0.1

        sl_dist = abs(float(entry) - float(sl))
        sl_dist_pct = (sl_dist / float(entry)) * 100.0

        if sl_dist_pct < min_pct:
            return self._drop(
                f"SL too close: {sl_dist_pct:.4f}% < {min_pct:.2f}%",
                features={"sl_dist_pct": sl_dist_pct, "min_sl_dist_pct": min_pct, "entry": float(entry), "sl": float(sl)},
            )
        return self._pass(features={"sl_dist_pct": sl_dist_pct})


def _get(obj, name):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)
