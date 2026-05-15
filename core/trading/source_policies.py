"""
Per-source policies для TradeRouter.

Каждый источник сигналов (atr_change/monitoring/wt_sideways/...) имеет свой профиль:
  min_strength: порог силы (после SOFT penalties) для биржевой регистрации
  exchange_enabled: открывать ли биржевой ордер через order_executor
  trade_mode: маркер для dedup в trade_simulator (SWING/SCALP/atr_change/sideways)
  soft_gates_enabled: какие SOFT gates применять (white-list)

Загружается из config.yaml → signal_router.source_policies.<source>.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


DEFAULT_SOFT_GATES = [
    "strength_threshold",
    "regime_safety",
    "btc_market",
    "time_gate",
    "correlation_guard",
    "market_stress",
    "pair_cooldown_streak",
]


@dataclass
class SourcePolicy:
    source: str
    min_strength: int = 50
    exchange_enabled: bool = True
    trade_mode: str = ""
    soft_gates_enabled: list[str] = field(default_factory=lambda: list(DEFAULT_SOFT_GATES))

    @classmethod
    def from_config(cls, config: Any, source: str) -> "SourcePolicy":
        """
        Загружает policy для source из config.yaml.
        Если конкретный source не определён — используется default_policy.
        Если signal_router не настроен — возвращает дефолт.
        """
        sr_cfg = config.get("signal_router", {}) or {}
        default = sr_cfg.get("default_policy", {}) or {}
        per_src  = (sr_cfg.get("source_policies", {}) or {}).get(source, {}) or {}

        def _pick(key: str, fallback: Any) -> Any:
            if key in per_src:
                return per_src[key]
            if key in default:
                return default[key]
            return fallback

        return cls(
            source=source,
            min_strength=int(_pick("min_strength", 50)),
            exchange_enabled=bool(_pick("exchange_enabled", True)),
            trade_mode=str(_pick("trade_mode", "")),
            soft_gates_enabled=list(_pick("soft_gates_enabled", DEFAULT_SOFT_GATES)),
        )
