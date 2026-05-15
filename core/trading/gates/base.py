"""
База для Gate pipeline TradeRouter.

Gate — единица проверки в pipeline регистрации сделки.
  HARD — блокирует регистрацию (validate_inputs, dedup, sl_cooldown, min_sl_dist, rr_filter, qty_validation)
  SOFT — снижает strength через penalty, не блокирует (regime_safety, btc_market, time_gate, ...)

Все trading gates становятся SOFT по принципу feedback_no_blocking: "никаких блоков".
Только operational/technical проверки остаются HARD.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class GateType(str, Enum):
    HARD = "hard"   # блокирует регистрацию (passed=False → drop)
    SOFT = "soft"   # снижает strength (passed=True всегда, strength_penalty > 0 при срабатывании)


@dataclass
class GateContext:
    """Контекст одного вызова submit() — read-only кроме strength."""
    rec: Any                                  # TradingRecommendation или duck-typed
    symbol: str
    direction: str                            # "LONG" | "SHORT"
    signal_type: str
    strength: int                             # mutates через SOFT penalty (router'ом)
    source: str                               # "atr_change", "monitoring", "wt_sideways", ...
    extra_features: dict
    policy: "SourcePolicy"                    # forward ref — см. core/trading/source_policies.py
    regime: Optional[str]                     # вычисляется до gates, может быть None
    open_trades: list[dict]                   # snapshot открытых для dedup/corr_guard
    bot: Any                                  # для доступа к pivot_calculator, data_collector
    timestamp_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class GateResult:
    """Результат одного gate.check()."""
    passed: bool
    gate_name: str
    gate_type: GateType
    reason: str = ""
    strength_penalty: int = 0                 # для SOFT: вычитается из ctx.strength
    features: dict = field(default_factory=dict)   # дописывается в extra_features


@dataclass
class SubmitResult:
    """Результат TradeRouter.submit() — что произошло на всех этапах."""
    trade_id: Optional[int]
    exchange_order_id: Optional[str]
    soft_penalties: list[tuple[str, int, str]] = field(default_factory=list)   # [(gate, penalty, reason), ...]
    hard_drops: list[tuple[str, str]]         = field(default_factory=list)    # [(gate, reason), ...]
    final_strength: int = 0
    is_registered: bool = False               # True если trade_id != None


class Gate(ABC):
    """Базовый класс для всех gates."""

    name: str = "abstract"
    gate_type: GateType = GateType.HARD

    @abstractmethod
    async def check(self, ctx: GateContext) -> GateResult:
        """Проверяет ctx и возвращает GateResult."""
        ...

    def _pass(self, features: dict | None = None) -> GateResult:
        """Helper: gate пропустил (нет drop / нет penalty)."""
        return GateResult(
            passed=True,
            gate_name=self.name,
            gate_type=self.gate_type,
            features=features or {},
        )

    def _drop(self, reason: str, features: dict | None = None) -> GateResult:
        """Helper: HARD gate блокирует."""
        return GateResult(
            passed=False,
            gate_name=self.name,
            gate_type=self.gate_type,
            reason=reason,
            features=features or {},
        )

    def _penalty(self, penalty: int, reason: str, features: dict | None = None) -> GateResult:
        """Helper: SOFT gate применяет penalty."""
        return GateResult(
            passed=True,
            gate_name=self.name,
            gate_type=self.gate_type,
            reason=reason,
            strength_penalty=penalty,
            features=features or {},
        )
