"""
HARD gate: валидация входных параметров recommendation.

Блокирует если:
  - entry_price <= 0
  - direction не в (LONG, SHORT)
  - оба stop_loss и take_profit отсутствуют

Соответствует логике trade_simulator.register_trade_async() строки 268-286.
"""
from __future__ import annotations

from core.trading.gates.base import Gate, GateContext, GateResult, GateType


class ValidateInputsGate(Gate):
    name = "validate_inputs"
    gate_type = GateType.HARD

    async def check(self, ctx: GateContext) -> GateResult:
        rec = ctx.rec
        entry = _get_attr(rec, "entry_price")
        if entry is None or float(entry) <= 0:
            return self._drop("no entry_price")

        if ctx.direction not in ("LONG", "SHORT"):
            return self._drop(f"direction={ctx.direction} (need LONG|SHORT)")

        sl = _get_attr(rec, "stop_loss")
        tp = _get_attr(rec, "take_profit")
        if sl is None and tp is None:
            return self._drop("no SL and no TP")

        return self._pass()


def _get_attr(obj, name, default=None):
    """Берёт атрибут из dataclass / SimpleNamespace / dict."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)
