"""
SOFT gate: penalty при strength < min_strength policy.

Если итоговая strength (после всех SOFT penalties) окажется ниже policy.min_strength —
сделка регистрируется в БД, но exchange order НЕ открывается (через policy логику в router).

Сам gate всегда passed=True. Penalty = 0 — это маркер для router, что итоговый strength
ниже порога биржевого исполнения.

Реализация: gate возвращает penalty=0, но в features указывает below_min=True.
Router использует это для решения по open_bracket.
"""
from __future__ import annotations

from core.trading.gates.base import Gate, GateContext, GateResult, GateType


class StrengthThresholdGate(Gate):
    name = "strength_threshold"
    gate_type = GateType.SOFT

    async def check(self, ctx: GateContext) -> GateResult:
        min_str = int(ctx.policy.min_strength)
        if ctx.strength < min_str:
            # SOFT — не блокирует регистрацию, только маркирует
            return GateResult(
                passed=True,
                gate_name=self.name,
                gate_type=self.gate_type,
                reason=f"strength={ctx.strength} < min_strength={min_str}",
                strength_penalty=0,
                features={"below_min_strength": True, "min_strength": min_str},
            )
        return self._pass(features={"below_min_strength": False})
