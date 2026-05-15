"""
HARD gate: qty/notional валидация перед exchange order.

Вызывается ПОСЛЕ persist в БД (поэтому не блокирует регистрацию в БД,
а только блокирует open_bracket на бирже).

Сейчас сделан как placeholder — реальная проверка qty происходит внутри
TradeRouter._place_exchange_order() через position_sizer.calc_qty().
Этот gate в pipeline не используется (зарезервирован для будущего).
"""
from __future__ import annotations

from core.trading.gates.base import Gate, GateContext, GateResult, GateType


class QtyValidationGate(Gate):
    """Зарезервирован — текущая проверка qty в TradeRouter._place_exchange_order."""
    name = "qty_validation"
    gate_type = GateType.HARD

    async def check(self, ctx: GateContext) -> GateResult:
        return self._pass()
