"""
DS-325: pydantic-settings схема config.yaml.

Поглощает config_validator.py. extra=\"forbid\" ловит orphan-секции.
Ф1: схема по доменам. Ф2: ConfigProxy.get(\"a.b.c\").
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# Вложенные модели (домены)
# ═══════════════════════════════════════════════════════════════════════════════


class TradingSlTp(BaseModel):
    """Внутренний sl_tp (старая секция trading.sl_tp)."""
    model_config = ConfigDict(extra="forbid")

    atr_multiplier: float = Field(default=1.2, ge=0.1, le=10.0)
    sl_min_pct: float = Field(default=0.5, ge=0.1, le=5.0)
    sl_max_pct: float = Field(default=3.0, ge=0.5, le=20.0)
    tp_fallback_rr: float = Field(default=3.0, ge=1.0, le=20.0)
    max_rr: float = Field(default=3.0, ge=1.0, le=100.0)
    max_rr_range: float = Field(default=2.5, ge=0.5, le=20.0)
    require_pivot_tp: bool = False
    tp_pivot_min_r: float = Field(default=3.0, ge=1.0, le=20.0)
    tp_pivot_min_r_range: float = Field(default=1.2, ge=0.5, le=10.0)
    tp_reversal_min_r: float = Field(default=3.0, ge=1.0, le=20.0)
    tp_partial_pct: float = Field(default=0.2, ge=0.0, le=1.0)
    atr_dynamic: bool = True
    atr_expand_threshold: float = Field(default=1.3, ge=0.5, le=5.0)
    atr_contract_threshold: float = Field(default=0.8, ge=0.1, le=5.0)
    struct_sl_buffer_pct: float = Field(default=0.3, ge=0.0, le=5.0)
    struct_sl_max_dist: float = Field(default=2.0, ge=0.5, le=20.0)
    tsl_too_tight_pct: float = Field(default=1.0, ge=0.1, le=10.0)


class TradingSlTpEngine(BaseModel):
    """sl_tp_engine (основная секция exit/risk/TSL)."""
    model_config = ConfigDict(extra="forbid")

    tp_selector_enabled: bool = False
    tp_selector_shadow: bool = False
    tp_selector_eps_pct: float = Field(default=0.5, ge=0.1, le=10.0)
    tp_selector_alpha: float = Field(default=1.5, ge=0.5, le=5.0)
    tp_selector_max_dist_pct: float = Field(default=15.0, ge=1.0, le=100.0)

    use_tsl: bool = False
    tsl_hybrid_enabled: bool = False
    tsl_activation_r: float = Field(default=1.0, ge=0.1, le=10.0)
    tsl_min_move_pct: float = Field(default=0.15, ge=0.01, le=5.0)
    tsl_activation_r_range: float = Field(default=0.7, ge=0.1, le=5.0)
    tsl_activation_r_per_strategy: Dict[str, float] = Field(default_factory=dict)

    cascade_tsl_deescalation_r: float = Field(default=3.0, ge=0.5, le=20.0)
    cascade_tsl_opts: Dict[str, Any] = Field(default_factory=dict)

    dual_tp: Dict[str, Any] = Field(default_factory=dict)
    narrative: Dict[str, Any] = Field(default_factory=dict)
    adaptive_weights: Dict[str, Any] = Field(default_factory=dict)

    breakeven_activation_r: float = Field(default=1.5, ge=0.1, le=10.0)
    # 13.08.2026: потолок 5.0 → 12.0. Замер на боевой базе показал, что порог 5% даёт
    # безубыток (PF 1.06), а 4% — убыток в 5 раз меньше прежнего; упираться в 5.0 нельзя.
    # Верхняя граница согласована с trading.max_stop_pct=12.0 — стоп шире контракта смысла не имеет.
    min_sl_dist_pct: float = Field(default=0.5, ge=0.1, le=12.0)
    sl_limit_buffer_pct: float = Field(default=0.1, ge=0.0, le=2.0)
    max_positions: int = Field(default=50, ge=1, le=500)
    # BE-sync на биржу (DEV-40 Breakeven доезжает на биржу, bug_be_not_synced)
    be_exchange_sync: bool = True
    be_limit_buffer_pct: float = Field(default=0.15, ge=0.0, le=2.0)

    # Дополнено после валидации config.yaml (14.06)
    cascade_tsl: bool = True
    use_breakeven: bool = True
    use_be_after_tp1: bool = True
    expired_extend_min_r: float = Field(default=5.0, ge=0.0, le=100.0)
    expired_extend_hours: int = Field(default=120, ge=0, le=10000)
    expired_management: Dict[str, Any] = Field(default_factory=dict)
    max_positions_per_direction: int = Field(default=0, ge=0, le=500)
    sl_tp: Dict[str, Any] = Field(default_factory=dict)  # дубль trading.sl_tp внутри sl_tp_engine


class TradingSection(BaseModel):
    """trading — основная торговая секция."""
    model_config = ConfigDict(extra="forbid")

    risk_pct: float = Field(default=1.0, ge=0.01, le=20.0)
    leverage: int = Field(default=5, ge=1, le=125)
    deposit_usdt: float = Field(default=500.0, ge=0.0)
    min_rr: float = Field(default=1.5, ge=0.5, le=20.0)
    max_rr: float = Field(default=10.0, ge=1.0, le=100.0)
    entry_delay_seconds: int = Field(default=0, ge=0, le=300)

    sl_tp: TradingSlTp = Field(default_factory=TradingSlTp)
    # sl_tp_engine merge target — это поля sl_tp_engine, скопированные в trading
    # (приходят через ConfigLoader merge, не из YAML напрямую)


class PerformanceSection(BaseModel):
    """performance — метрики и троттлинг."""
    model_config = ConfigDict(extra="forbid")

    scan_semaphore_size: int = Field(default=8, ge=1, le=100)
    api_rps: float = Field(default=5.0, ge=0.1, le=100.0)
    event_loop_debug: bool = False
    ohlcv_scan_limit: int = Field(default=200, ge=50, le=1000)

    # Дополнено после валидации config.yaml (14.06)
    check_open_semaphore: int = Field(default=15, ge=1, le=100)
    sim_check_interval_sec: int = Field(default=300, ge=10, le=10000)
    analyze_semaphore_size: int = Field(default=3, ge=1, le=50)
    prefetch_pivots_semaphore_size: int = Field(default=2, ge=1, le=20)
    background_check_semaphore_size: int = Field(default=5, ge=1, le=50)
    cascade_div_semaphore_size: int = Field(default=3, ge=1, le=50)
    api_semaphore_size: int = Field(default=10, ge=1, le=100)
    ohlcv_slow_threshold_sec: float = Field(default=8.0, ge=0.1, le=300.0)
    divergence_slow_threshold_sec: float = Field(default=3.0, ge=0.1, le=60.0)
    pair_slow_threshold_sec: float = Field(default=10.0, ge=0.1, le=300.0)
    scan_cycle_warning_threshold_sec: float = Field(default=70.0, ge=0.1, le=600.0)
    ws_enabled: bool = False
    slow_callback_threshold_sec: float = Field(default=1.0, ge=0.1, le=60.0)
    scan_blacklist: List[str] = Field(default_factory=list)
    ws_ticker_batch_size: int = Field(default=75, ge=1, le=500)
    ws_ohlcv_batch_size: int = Field(default=80, ge=1, le=500)
    ws_batch_start_delay_sec: float = Field(default=5.0, ge=0.0, le=60.0)
    ws_reconnect_base_delay_sec: float = Field(default=5.0, ge=0.1, le=60.0)
    ws_ohlcv_error_pause_sec: float = Field(default=1.0, ge=0.0, le=300.0)
    sim_time_exit_hours: int = Field(default=48, ge=0, le=10000)  # анти-орфан SIM


class SignalQualitySection(BaseModel):
    """signal_quality — гейты и пороги стратегий."""
    model_config = ConfigDict(extra="forbid")

    min_strength: int = Field(default=70, ge=0, le=100)
    min_strength_register: int = Field(default=70, ge=0, le=100)
    dedup_minutes: int = Field(default=0, ge=0, le=1440)


class MarketWsSection(BaseModel):
    """market_ws — WebSocket рыночных данных."""
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    use_ws: bool = False
    throttle_ms: int = Field(default=5000, ge=100, le=60000)
    timeframes: List[str] = Field(default_factory=lambda: ["5m", "15m"])
    batch_pairs: int = Field(default=50, ge=1, le=500)


class LoggingSection(BaseModel):
    """logging."""
    model_config = ConfigDict(extra="forbid")
    level: str = "INFO"
    file: str = "logs/bot.log"
    max_bytes: int = Field(default=10_485_760, ge=0)
    max_size: str = "10MB"  # формат из config.yaml: "10MB"
    backup_count: int = Field(default=5, ge=0)


# ═══════════════════════════════════════════════════════════════════════════════
# Корневая модель
# ═══════════════════════════════════════════════════════════════════════════════


class OkoConfig(BaseModel):
    """Корневая модель config.yaml. extra=\"forbid\" = orphan-секции → ValidationError."""
    model_config = ConfigDict(extra="forbid")

    # ── Критичные (типизированы полностью) ──
    trading: Dict[str, Any] = Field(default_factory=dict)
    sl_tp_engine: TradingSlTpEngine = Field(default_factory=TradingSlTpEngine)
    performance: PerformanceSection = Field(default_factory=PerformanceSection)
    signal_quality: Dict[str, Any] = Field(default_factory=dict)
    market_ws: MarketWsSection = Field(default_factory=MarketWsSection)
    logging: LoggingSection = Field(default_factory=LoggingSection)

    # ── Некритичные (тип = dict, без детализации) ──
    strategy_name: str = "multi_signal"
    database: Dict[str, Any] = Field(default_factory=dict)
    telegram: Dict[str, Any] = Field(default_factory=dict)
    monitoring: Dict[str, Any] = Field(default_factory=dict)
    analysis: Dict[str, Any] = Field(default_factory=dict)
    signals: Dict[str, Any] = Field(default_factory=dict)
    subscriptions: Dict[str, Any] = Field(default_factory=dict)
    notifications: Dict[str, Any] = Field(default_factory=dict)
    dashboard: Dict[str, Any] = Field(default_factory=dict)
    arch104: Dict[str, Any] = Field(default_factory=dict)
    ml: Dict[str, Any] = Field(default_factory=dict)
    advisor: Dict[str, Any] = Field(default_factory=dict)
    detectors: Dict[str, Any] = Field(default_factory=dict)
    future_pivots: Dict[str, Any] = Field(default_factory=dict)
    risk_management: Dict[str, Any] = Field(default_factory=dict)
    market_regime: Dict[str, Any] = Field(default_factory=dict)
    outcome_predictor: Dict[str, Any] = Field(default_factory=dict)
    trade_analyzer: Dict[str, Any] = Field(default_factory=dict)
    sideways_mode: Dict[str, Any] = Field(default_factory=dict)
    simulation: Dict[str, Any] = Field(default_factory=dict)   # 12.07: sl_touch_all + costs (net)
    signal_router: Dict[str, Any] = Field(default_factory=dict)
    strategy: Dict[str, Any] = Field(default_factory=dict)
    proxy_pool: Dict[str, Any] = Field(default_factory=dict)
    event_bus: Dict[str, Any] = Field(default_factory=dict)
    trigger_bus: Dict[str, Any] = Field(default_factory=dict)
    exchanges: Dict[str, Any] = Field(default_factory=dict)
    ote: Dict[str, Any] = Field(default_factory=dict)
    arch104: Dict[str, Any] = Field(default_factory=dict)
    arch118: Dict[str, Any] = Field(default_factory=dict)
    arch96: Dict[str, Any] = Field(default_factory=dict)
    # THE GRAPH (03.07, Сфера 6.5): api_key для thegraph_client/graph-shadow. Секция добавлена
    # в config.yaml ПОСЛЕ схемы → extra_forbidden ронял ВСЮ валидацию в default-режим (08.07).
    the_graph: Dict[str, Any] = Field(default_factory=dict)

    # ── Валидация (поглощает config_validator.py) ──

    @field_validator("trading", mode="before")
    @classmethod
    def _trading_must_be_dict(cls, v):
        if not isinstance(v, dict):
            raise ValueError(f"trading должен быть dict, получен {type(v).__name__}")
        return v

    @model_validator(mode="after")
    def _validate_critical_ranges(self):
        """Поглощает 15 правил config_validator.py."""
        # trading.risk_pct
        tr = self.trading
        if isinstance(tr, dict):
            rp = tr.get("risk_pct")
            if rp is not None and (not isinstance(rp, (int, float)) or rp < 0.01 or rp > 20.0):
                logger.warning("[CONFIG] trading.risk_pct=%s вне [0.01..20]", rp)
            lev = tr.get("leverage")
            if lev is not None and (not isinstance(lev, int) or lev < 1 or lev > 125):
                logger.warning("[CONFIG] trading.leverage=%s вне [1..125]", lev)
            dep = tr.get("deposit_usdt")
            if dep is not None and (not isinstance(dep, (int, float)) or dep < 0):
                logger.warning("[CONFIG] trading.deposit_usdt=%s < 0", dep)

        # performance
        sem = self.performance.scan_semaphore_size
        if sem < 1 or sem > 100:
            logger.warning("[CONFIG] performance.scan_semaphore_size=%s вне [1..100]", sem)
        rps = self.performance.api_rps
        if rps < 0.1 or rps > 100.0:
            logger.warning("[CONFIG] performance.api_rps=%s вне [0.1..100]", rps)

        # signal_quality
        sq = self.signal_quality
        if isinstance(sq, dict):
            ms = sq.get("min_strength")
            if ms is not None and (not isinstance(ms, int) or ms < 0 or ms > 100):
                logger.warning("[CONFIG] signal_quality.min_strength=%s вне [0..100]", ms)
            msr = sq.get("min_strength_register")
            if msr is not None and (not isinstance(msr, int) or msr < 0 or msr > 100):
                logger.warning("[CONFIG] signal_quality.min_strength_register=%s вне [0..100]", msr)
            dm = sq.get("dedup_minutes")
            if dm is not None and (not isinstance(dm, int) or dm < 0 or dm > 1440):
                logger.warning("[CONFIG] signal_quality.dedup_minutes=%s вне [0..1440]", dm)

        return self


# ═══════════════════════════════════════════════════════════════════════════════
# ConfigProxy — обёртка поверх Settings (Ф2)
# ═══════════════════════════════════════════════════════════════════════════════


class ConfigProxy:
    """
    Прокси поверх OkoConfig. Совместим с config.get(\"a.b.c\", default).

    Использование:
        from core.infra.pydantic_config import load_oko_config
        cfg = ConfigProxy(load_oko_config())
        cfg.get(\"trading.risk_pct\")        # 1.0
        cfg.get(\"trading.sl_tp.atr_multiplier\")  # 1.2
        cfg.get(\"no.such.key\", 42)          # 42 (default)
    """

    def __init__(self, model: OkoConfig):
        self._model = model

    def get(self, path: str, default: Any = None) -> Any:
        """dot-path доступ к pydantic-модели: dict приоритетнее атрибута."""
        keys = path.split(".")
        node: Any = self._model

        for k in keys:
            if node is None:
                return default
            if isinstance(node, dict):
                if k in node:
                    node = node[k]
                else:
                    return default
            elif hasattr(node, k):
                node = getattr(node, k)
            else:
                return default
        return node

    def set(self, key: str, value: Any) -> None:
        """Устанавливает значение по dot-path (in-memory, для обратной совместимости)."""
        keys = key.split(".")
        node: Any = self._model
        for k in keys[:-1]:
            if isinstance(node, dict):
                node = node.setdefault(k, {})
            elif hasattr(node, k):
                node = getattr(node, k)
            else:
                return
        last = keys[-1]
        if isinstance(node, dict):
            node[last] = value
        elif hasattr(node, last):
            setattr(node, last, value)

    def __repr__(self) -> str:
        return f"ConfigProxy(trading={len(self._model.trading)}k, sl_tp_engine={len(self._model.sl_tp_engine.model_dump())}k)"


# ═══════════════════════════════════════════════════════════════════════════════
# Загрузка
# ═══════════════════════════════════════════════════════════════════════════════


def load_oko_config(yaml_path: str = "config.yaml", strict: bool = False) -> OkoConfig:
    """
    Загружает config.yaml → OkoConfig.

    strict=False: log-режим (ValidationError → лог + default-модель).
    strict=True:  raise ValidationError (боевой режим).
    """
    import yaml

    with open(yaml_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    try:
        model = OkoConfig.model_validate(raw)
        logger.info("[CONFIG] pydantic-валидация пройдена. Секций: %d", len(raw))
        return model
    except Exception as e:
        logger.error("[CONFIG] pydantic-валидация НЕ ПРОЙДЕНА: %s", e)
        if strict:
            raise
        # fallback: создать модель с defaults
        logger.warning("[CONFIG] Использую default-модель (лог-режим)")
        return OkoConfig()


def create_config_proxy(yaml_path: str = "config.yaml", strict: bool = False) -> ConfigProxy:
    """Загружает конфиг и оборачивает в ConfigProxy."""
    return ConfigProxy(load_oko_config(yaml_path, strict=strict))
