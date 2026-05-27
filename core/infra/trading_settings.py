"""
trading_settings.py — единственный источник правды о default-ах trading.*

До этого 6 файлов делали config.get("trading.deposit_usdt", 1000.0) и т.п.
с разными default-ами (один писал 5.0, другой 5 для leverage; кто-то 1.0,
кто-то 0.5 для risk). При смене defaults — ошибка в одном месте.

Использование:
    from core.infra.trading_settings import TradingSettings
    ts = TradingSettings.from_config(config)   # deposit/risk/leverage/mode
    if ts.is_live: ...
    qty = ts.deposit_usdt * ts.risk_pct / 100 * ts.leverage / sl_dist_usdt

Или точечно:
    from core.infra.trading_settings import get_deposit, get_leverage
    dep = get_deposit(config)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_DEPOSIT_USDT: float = 1000.0
DEFAULT_RISK_PCT:     float = 1.0
DEFAULT_LEVERAGE:     int   = 5
DEFAULT_EXEC_MODE:    str   = "sim_only"
LIVE_MODES = ("vst", "live")


def _safe_float(cfg: Any, key: str, default: float) -> float:
    try:
        v = cfg.get(key, default) if hasattr(cfg, "get") else default
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _safe_int(cfg: Any, key: str, default: int) -> int:
    try:
        v = cfg.get(key, default) if hasattr(cfg, "get") else default
        return int(float(v)) if v is not None else default
    except (TypeError, ValueError):
        return default


def get_deposit(config: Any) -> float:
    return _safe_float(config, "trading.deposit_usdt", DEFAULT_DEPOSIT_USDT)


def get_risk_pct(config: Any) -> float:
    return _safe_float(config, "trading.risk_pct", DEFAULT_RISK_PCT)


def get_leverage(config: Any) -> int:
    return _safe_int(config, "trading.leverage", DEFAULT_LEVERAGE)


def get_execution_mode(config: Any) -> str:
    try:
        v = config.get("trading.execution_mode", DEFAULT_EXEC_MODE) if hasattr(config, "get") else DEFAULT_EXEC_MODE
        return str(v or DEFAULT_EXEC_MODE).lower()
    except Exception:
        return DEFAULT_EXEC_MODE


def is_live(config: Any) -> bool:
    """vst/live → True, sim_only → False."""
    return get_execution_mode(config) in LIVE_MODES


@dataclass(frozen=True)
class TradingSettings:
    deposit_usdt: float
    risk_pct: float
    leverage: int
    execution_mode: str

    @property
    def is_live(self) -> bool:
        return self.execution_mode in LIVE_MODES

    @classmethod
    def from_config(cls, config: Any) -> "TradingSettings":
        return cls(
            deposit_usdt=get_deposit(config),
            risk_pct=get_risk_pct(config),
            leverage=get_leverage(config),
            execution_mode=get_execution_mode(config),
        )
