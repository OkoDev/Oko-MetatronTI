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
    # Per-source sizing (19.06): None → fallback на глобальный trading.leverage/risk_pct.
    # Корень: плечо/риск были ГЛОБАЛЬНЫМИ → подключение 2-й стратегии унаследовало бы чужой
    # режим (напр. ote_nested 50x потёк бы на новую стратегию). Локализуем под источник.
    leverage: int | None = None
    risk_pct: float | None = None
    # Тип входного ордера (Фаза 1, 25.06): "MARKET" (по рынку, slippage) или "LIMIT" (по
    # entry_price = OTE 0.618, без slippage). oko_ote → LIMIT (вход ровно в зону, метод Егора).
    entry_order_type: str = "MARKET"
    # Плечо set-to-max (04.07): True (дефолт, ote_nested) → order_manager поднимает плечо до
    # макс безопасного (экономия маржи). False (radar) → уважать запрошенное (cap-down only):
    # импульсная торговля + гэп мимо SL достаёт близкую ликвидацию высокого плеча.
    lev_set_to_max: bool = True

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

        _lev = _pick("leverage", None)
        _risk = _pick("risk_pct", None)
        return cls(
            source=source,
            min_strength=int(_pick("min_strength", 50)),
            exchange_enabled=bool(_pick("exchange_enabled", True)),
            trade_mode=str(_pick("trade_mode", "")),
            soft_gates_enabled=list(_pick("soft_gates_enabled", DEFAULT_SOFT_GATES)),
            leverage=int(_lev) if _lev is not None else None,
            risk_pct=float(_risk) if _risk is not None else None,
            entry_order_type=str(_pick("entry_order_type", "MARKET")).upper(),
            lev_set_to_max=bool(_pick("lev_set_to_max", True)),
        )
