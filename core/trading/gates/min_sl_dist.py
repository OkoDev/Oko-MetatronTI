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
            min_pct = float(ctx.bot.config.get("trading.min_sl_dist_pct", 0.5))
        except Exception:
            min_pct = 0.5

        entry_f = float(entry); sl_f = float(sl)
        sl_dist = abs(entry_f - sl_f)
        sl_dist_pct = (sl_dist / entry_f) * 100.0

        # OTE-RBUG (14.06): валидация СТОРОНЫ SL. LONG: SL должен быть НИЖЕ entry,
        # SHORT: ВЫШЕ. Инвертный SL (HOME LONG sl>entry) → R/size взрыв. REJECT.
        direction = _get(rec, "direction")
        dir_str = str(getattr(direction, "value", direction) or "").upper()
        if dir_str in ("LONG", "BUY") and sl_f >= entry_f:
            return self._drop(
                f"SL на неверной стороне (LONG): sl={sl_f} >= entry={entry_f}",
                features={"entry": entry_f, "sl": sl_f, "direction": dir_str},
            )
        if dir_str in ("SHORT", "SELL") and sl_f <= entry_f:
            return self._drop(
                f"SL на неверной стороне (SHORT): sl={sl_f} <= entry={entry_f}",
                features={"entry": entry_f, "sl": sl_f, "direction": dir_str},
            )

        if sl_dist_pct < min_pct:
            return self._drop(
                f"SL too close: {sl_dist_pct:.4f}% < {min_pct:.2f}%",
                features={"sl_dist_pct": sl_dist_pct, "min_sl_dist_pct": min_pct, "entry": entry_f, "sl": sl_f},
            )
        return self._pass(features={"sl_dist_pct": sl_dist_pct})


def _get(obj, name):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)
