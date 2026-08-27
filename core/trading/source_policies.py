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

    # ── РЕЕСТР СТРАТЕГИЙ, фаза 1 (21.08.2026): поля ЧИТАЮТСЯ, но ЕЩЁ НЕ ПРИМЕНЯЮТСЯ.
    # Повод: к свойствам стратегии код ходит по ЧЕТЫРЁМ ключам (ctx.source / trade_mode /
    # extra_features["signal_type_override"] / trade["signal_type"]), и у них РАЗНЫЕ
    # запасные значения (min_sl_dist: router 0.5, simulator 0.5, order_manager 0.1).
    # У impulse_fib ключи совпали СЛУЧАЙНО; у wt_sideways уже расходятся
    # (source=wt_sideways, trade_mode=sideways) — мина ждёт. См. scripts/strategy_preflight.py.
    # Здесь собираем ЕДИНЫЙ вид по ключу `source`; переключение потребителей — фаза 2,
    # по одному, с замером до/после. None = «не задано, работает глобальный порог».
    min_sl_dist_pct: float | None = None
    min_rr: float | None = None
    tsl_activation_r: float | None = None
    tp_mode: str = "DUAL"          # SINGLE, если источник в trading.single_tp_sources
    rr_cap_exempt: bool = False    # освобождён ли от обрезки RR (DEV-64A)

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
        # ── реестр, фаза 1: собираем свойства по ЕДИНОМУ ключу `source` ──
        def _per(section: str) -> Any:
            tbl = config.get(f"trading.{section}", {}) or {}
            return tbl.get(source) if isinstance(tbl, dict) else None

        _single = config.get("trading.single_tp_sources") or ["ote_nested", "impulse_fib"]
        _exempt = (config.get("trading.sl_management.rr_cap_exempt")
                   or ["ote_nested", "impulse_fib"])
        _msd = _per("min_sl_dist_per_strategy")
        _mrr = _per("min_rr_per_strategy")
        _tsl = _per("tsl_activation_r_per_strategy")

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
            min_sl_dist_pct=None if _msd is None else float(_msd),
            min_rr=None if _mrr is None else float(_mrr),
            tsl_activation_r=None if _tsl is None else float(_tsl),
            tp_mode="SINGLE" if source in _single else "DUAL",
            rr_cap_exempt=source in _exempt,
        )
