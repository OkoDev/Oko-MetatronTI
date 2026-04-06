"""
TriggerBus — DEV-95 / ARCH-61 / Куб Метатрона Фаза 3.

Лёгкие триггеры для event-driven re-entry:
  OteReentryTrigger  — цена вошла в OTE зону из post_tsl_data
  CascadeTrigger     — пара с cascade_count >= min_cascade
  PivotTouchTrigger  — DEV-129: цена коснулась R1/R2/S1/S2 на 1D/1W

Все триггеры stateless: state берётся из PairContextBus.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, Optional

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


class PivotTouchTrigger(Trigger):
    """
    DEV-129: цена коснулась ключевого пивотного уровня R1/R2/S1/S2 на 1D или 1W.

    Shadow mode (по умолчанию): логирует WOULD_FIRE, не запускает анализ.
    Cooldown: 1 тригер/пара/60 мин (защита от флаппинга у уровня).

    pivot_snap передаётся извне (из trigger_loop) — не делает I/O.
    Формат pivot_snap: {"1D": {"R1": 0.1234, "S1": 0.1100, ...}, "1W": {...}}
    """
    name = "pivot_touch"

    # Уровни по спеке ARCH (R1/R2/S1/S2, не PP)
    _LEVELS = ("R1", "R2", "S1", "S2")
    _TFS    = ("1D", "1W")

    def __init__(self, threshold_pct: float = 0.003, cooldown_minutes: int = 60):
        self.threshold_pct   = threshold_pct    # 0.3% от цены
        self.cooldown_minutes = cooldown_minutes
        # cooldown: {symbol: last_fire_time}
        self._last_fire: Dict[str, datetime] = {}

    def check(
        self,
        symbol: str,
        current_price: float,
        state: "PairState",
        pivot_snap: Optional[Dict] = None,
    ) -> TriggerResult:
        if not pivot_snap or current_price <= 0:
            return TriggerResult(False)

        # Cooldown
        last = self._last_fire.get(symbol)
        if last is not None:
            elapsed_min = (datetime.now(timezone.utc) - last).total_seconds() / 60
            if elapsed_min < self.cooldown_minutes:
                return TriggerResult(False, reason=f"cooldown {elapsed_min:.0f}/{self.cooldown_minutes}min")

        for tf in self._TFS:
            tf_snap = pivot_snap.get(tf) or {}
            for level_name in self._LEVELS:
                lvl_price = tf_snap.get(level_name)
                if not lvl_price or lvl_price <= 0:
                    continue
                dist_pct = abs(current_price - lvl_price) / lvl_price
                if dist_pct <= self.threshold_pct:
                    self._last_fire[symbol] = datetime.now(timezone.utc)
                    direction = "LONG" if level_name.startswith("S") else "SHORT"
                    return TriggerResult(
                        True,
                        reason=(
                            f"{tf}_{level_name}={lvl_price:.6g} "
                            f"price={current_price:.6g} "
                            f"dist={dist_pct*100:.2f}% "
                            f"→ {direction}"
                        ),
                    )
        return TriggerResult(False)
