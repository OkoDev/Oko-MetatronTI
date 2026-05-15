"""
SOFT gate: penalty при опасных regime × direction комбо.

История (HARD блоки до DEV-199..205):
  - wt_signal SHORT в TREND_UP/HIGH_VOL (DEV-186): avgR=-1.12, n=22
  - LONG в TREND_DOWN: иногда убыточно
  - SHORT в TREND_UP: иногда убыточно

В Confirmation-Driven (DISCUSSION 09.05.2026): "НЕТ regime-gate. Бот не молчит."
Поэтому здесь — только soft penalty к strength.

Penalty значения из config.yaml → signal_router.penalties.regime_safety.
"""
from __future__ import annotations

from core.trading.gates.base import Gate, GateContext, GateResult, GateType


class RegimeSafetyGate(Gate):
    name = "regime_safety"
    gate_type = GateType.SOFT

    async def check(self, ctx: GateContext) -> GateResult:
        regime = ctx.regime
        if not regime:
            return self._pass()

        try:
            penalties = ctx.bot.config.get("signal_router.penalties.regime_safety", {}) or {}
        except Exception:
            penalties = {}

        # wt_signal SHORT в TREND_UP/HIGH_VOL (DEV-186)
        if ctx.signal_type == "wt_signal" and ctx.direction == "SHORT" and regime in ("TREND_UP", "HIGH_VOL"):
            penalty = int(penalties.get("wt_signal_short_trend_up", 15))
            return self._penalty(
                penalty,
                f"wt_signal SHORT в {regime} (DEV-186 история avgR=-1.12)",
                features={"regime": regime, "rule": "dev186_wt_signal_regime"},
            )

        # SHORT в TREND_UP — общий penalty
        if ctx.direction == "SHORT" and regime == "TREND_UP":
            penalty = int(penalties.get("short_in_trend_up", 0))
            if penalty > 0:
                return self._penalty(
                    penalty, f"SHORT в TREND_UP", features={"regime": regime},
                )

        # LONG в TREND_DOWN — общий penalty
        if ctx.direction == "LONG" and regime == "TREND_DOWN":
            penalty = int(penalties.get("long_in_trend_down", 0))
            if penalty > 0:
                return self._penalty(
                    penalty, f"LONG в TREND_DOWN", features={"regime": regime},
                )

        return self._pass(features={"regime": regime})
