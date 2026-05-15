"""
Gate pipeline для TradeRouter (Сфера 9 Куба Метатрона — Decision Core, Phase 1).

HARD gates — блокируют регистрацию (technical safety).
SOFT gates — снижают strength через penalty (trading logic, без блоков).

Каждый gate — отдельный модуль с классом Gate.check(ctx) → GateResult.
"""
from core.trading.gates.base import (
    Gate,
    GateContext,
    GateResult,
    GateType,
    SubmitResult,
)

__all__ = ["Gate", "GateContext", "GateResult", "GateType", "SubmitResult"]
