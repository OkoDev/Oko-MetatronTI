"""
SOFT gate: penalty вне торговых сессий.

DEV-170: время суток влияет на avgR. 09-18 UTC = +0.15, 23-06 UTC = -0.3.

Конфиг:
  signal_quality.time_gate.enabled (bool)
  signal_quality.time_gate.start_hour_utc / end_hour_utc
  signal_quality.time_gate.overrides.<signal_type>.start/end

Penalty из signal_router.penalties.time_gate.off_session (default 5).
"""
from __future__ import annotations

from core.trading.gates.base import Gate, GateContext, GateResult, GateType


class TimeGate(Gate):
    name = "time_gate"
    gate_type = GateType.SOFT

    async def check(self, ctx: GateContext) -> GateResult:
        try:
            tg = ctx.bot.config.get("signal_quality.time_gate", {}) or {}
        except Exception:
            tg = {}

        if not tg.get("enabled", False):
            return self._pass()

        hour = ctx.timestamp_utc.hour
        # Override по signal_type
        overrides = tg.get("overrides", {}) or {}
        ov = overrides.get(ctx.signal_type, {}) or {}
        start = int(ov.get("start_hour_utc", tg.get("start_hour_utc", 9)))
        end   = int(ov.get("end_hour_utc",   tg.get("end_hour_utc",   18)))

        # window [start, end)
        in_window = start <= hour < end

        if not in_window:
            try:
                penalty = int(ctx.bot.config.get("signal_router.penalties.time_gate.off_session", 5))
            except Exception:
                penalty = 5
            return self._penalty(
                penalty,
                f"hour={hour} UTC вне окна [{start}, {end})",
                features={"hour_utc": hour, "window_start": start, "window_end": end},
            )
        return self._pass(features={"hour_utc": hour})
