"""
SOFT gate: penalty при BTC counter-trend.

Если BTC 4h trend = UP, а direction = SHORT → penalty.
Если BTC 4h trend = DOWN, а direction = LONG → penalty.

Соответствует ARCH-78 BTC counter-trend gate из monitoring.py — но soft вместо hard.
Использует кеш bot._btc_4h_regime_cache (если есть).
"""
from __future__ import annotations

from core.trading.gates.base import Gate, GateContext, GateResult, GateType


class BtcMarketGate(Gate):
    name = "btc_market"
    gate_type = GateType.SOFT

    async def check(self, ctx: GateContext) -> GateResult:
        # Не пенализируем сам BTC
        if "BTC" in ctx.symbol:
            return self._pass()

        btc_regime = _btc_4h_regime(ctx.bot)
        if not btc_regime:
            return self._pass()

        try:
            penalties = ctx.bot.config.get("signal_router.penalties.btc_market", {}) or {}
        except Exception:
            penalties = {}

        counter_trend = (
            (btc_regime == "TREND_UP" and ctx.direction == "SHORT") or
            (btc_regime == "TREND_DOWN" and ctx.direction == "LONG")
        )
        if counter_trend:
            penalty = int(penalties.get("counter_trend", 10))
            return self._penalty(
                penalty,
                f"BTC 4h={btc_regime}, direction={ctx.direction}",
                features={"btc_4h_regime": btc_regime},
            )
        return self._pass(features={"btc_4h_regime": btc_regime})


def _btc_4h_regime(bot) -> str | None:
    """Берёт из кеша bot._btc_4h_regime_cache если есть."""
    cache = getattr(bot, "_btc_4h_regime_cache", None)
    if cache:
        return cache.get("regime")
    return None
