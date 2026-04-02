"""
TriggerBus — DEV-95 / ARCH-61 / Куб Метатрона Фаза 3.

Лёгкие триггеры для event-driven re-entry:
  OteReentryTrigger — цена вошла в OTE зону из post_tsl_data
  CascadeTrigger    — пара с cascade_count >= min_cascade

Все триггеры stateless: state берётся из PairContextBus.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.context.pair_context import PairState


class TriggerResult:
    def __init__(self, fired: bool, reason: str = ""):
        self.fired  = fired
        self.reason = reason


class Trigger(ABC):
    name: str = "base"

    @abstractmethod
    def check(self, symbol: str, current_price: float, state: "PairState") -> TriggerResult: ...


class OteReentryTrigger(Trigger):
    """TR-010: цена вошла в OTE зону [ote_bot, ote_top] из post_tsl_data."""
    name = "ote_reentry"

    def check(self, symbol: str, current_price: float, state: "PairState") -> TriggerResult:
        d = state.post_tsl_data
        if not d:
            return TriggerResult(False)
        elapsed_h = (datetime.now(timezone.utc) - d["exit_time"]).total_seconds() / 3600
        if elapsed_h > d["ttl_hours"]:
            return TriggerResult(False, reason="ttl_expired")
        if d["ote_bot"] <= current_price <= d["ote_top"]:
            return TriggerResult(
                True,
                reason=f"price={current_price:.4f} in OTE [{d['ote_bot']:.4f},{d['ote_top']:.4f}] dir={d['direction']}"
            )
        return TriggerResult(False)


class CascadeTrigger(Trigger):
    """Пара с cascade_count >= min_cascade → горячая, запустить полный анализ."""
    name = "cascade"

    def __init__(self, min_cascade: int = 3):
        self.min_cascade = min_cascade

    def check(self, symbol: str, current_price: float, state: "PairState") -> TriggerResult:
        if state.cascade_count >= self.min_cascade and state.last_close_status in ("TSL", "TP"):
            return TriggerResult(
                True,
                reason=f"cascade={state.cascade_count} dir={state.last_direction} avg_r={state.avg_r_cascade:.2f}"
            )
        return TriggerResult(False)
