"""
Regime Strategy Adapter — ARCH-04.

Адаптирует параметры торговой стратегии в зависимости от рыночного режима:

  TREND_UP / TREND_DOWN:
    - strategy_type → DUAL_TSL (70% на TP1=пивот, 30% под TSL до конца тренда)
    - sl_factor → 0.85 (более тёсный SL, выше RR)

  RANGE:
    - strategy_type → DUAL_TP (консервативный фиксинг)
    - sl_factor → 1.15 (шире SL под боковик)

  HIGH_VOL:
    - position_size_multiplier → 0.5 (вдвое меньше риска)
    - tp1_r → 0.5 (TP1 обязателен сразу при +0.5R)
    - strategy_type → DUAL_TP (не пытаемся удерживать в хаосе)

  None / UNKNOWN:
    - Все параметры по умолчанию (без изменений)

Параметры можно переопределить в config.yaml:
  risk_management:
    regime_strategy:
      trend_sl_factor: 0.85
      trend_strategy_type: DUAL_TSL
      range_sl_factor: 1.15
      range_strategy_type: DUAL_TP
      high_vol_position_multiplier: 0.5
      high_vol_tp1_r: 0.5
      high_vol_strategy_type: DUAL_TP
      enabled: true
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Порядок стратегий от «слабейшей» к «сильнейшей»
_STRATEGY_ORDER = ["SINGLE", "DUAL_TP", "DUAL_TSL"]


@dataclass
class RegimeParams:
    """Параметры адаптации для конкретного режима рынка."""

    # Множитель SL-дистанции (< 1 = тёсный, > 1 = широкий)
    sl_factor: float = 1.0

    # Минимальный strategy_type (не понижаем ниже этого, но можем повысить)
    min_strategy_type: Optional[str] = None

    # Максимальный strategy_type (не повышаем выше этого)
    max_strategy_type: Optional[str] = None

    # Множитель размера позиции (1.0 = без изменений)
    position_size_multiplier: float = 1.0

    # Форсированный TP1 при N × R (None = не форсировать)
    tp1_r: Optional[float] = None

    # Человекочитаемое описание для логирования
    label: str = "DEFAULT"


# Дефолтные параметры для каждого режима
_DEFAULT_PARAMS: dict[str, RegimeParams] = {
    "TREND_UP": RegimeParams(
        sl_factor=0.85,
        min_strategy_type=None,  # DEV-124: SINGLE (данные: DUAL_TP/DUAL_TSL → -88.5R, SINGLE → +1866R)
        position_size_multiplier=1.0,
        label="TREND_UP",
    ),
    "TREND_DOWN": RegimeParams(
        sl_factor=0.85,
        min_strategy_type=None,  # DEV-124: SINGLE
        position_size_multiplier=1.0,
        label="TREND_DOWN",
    ),
    "RANGE": RegimeParams(
        sl_factor=1.15,
        max_strategy_type="SINGLE",    # было DUAL_TP — RANGE всегда фиксирует на первом пивоте
        position_size_multiplier=1.0,
        label="RANGE",
    ),
    "HIGH_VOL": RegimeParams(
        sl_factor=1.0,
        max_strategy_type="DUAL_TP",
        position_size_multiplier=0.5,
        tp1_r=0.5,
        label="HIGH_VOL",
    ),
}

_FALLBACK = RegimeParams(label="DEFAULT")


def get_regime_params(regime: Optional[str], cfg=None) -> RegimeParams:
    """
    Возвращает RegimeParams для заданного режима рынка.

    Parameters
    ----------
    regime : str | None
        Режим: "TREND_UP", "TREND_DOWN", "RANGE", "HIGH_VOL" или None.
    cfg : ConfigLoader | dict | None
        Конфиг бота — читает risk_management.regime_strategy.*

    Returns
    -------
    RegimeParams
    """
    if not regime:
        return _FALLBACK

    # Проверяем enabled флаг в конфиге
    if cfg is not None and hasattr(cfg, "get"):
        enabled = cfg.get("risk_management.regime_strategy.enabled", True)
        if not enabled:
            return _FALLBACK

    base = _DEFAULT_PARAMS.get(regime, _FALLBACK)

    # Переопределяем из конфига если есть
    if cfg is None or not hasattr(cfg, "get"):
        return base

    try:
        pfx = "risk_management.regime_strategy"
        if regime in ("TREND_UP", "TREND_DOWN"):
            sl_f = cfg.get(f"{pfx}.trend_sl_factor", base.sl_factor)
            min_st = cfg.get(f"{pfx}.trend_strategy_type", base.min_strategy_type)
            return RegimeParams(
                sl_factor=float(sl_f),
                min_strategy_type=str(min_st) if min_st else base.min_strategy_type,
                position_size_multiplier=float(cfg.get(f"{pfx}.trend_position_multiplier", 1.0)),
                label=regime,
            )
        if regime == "RANGE":
            sl_f = cfg.get(f"{pfx}.range_sl_factor", base.sl_factor)
            max_st = cfg.get(f"{pfx}.range_strategy_type", base.max_strategy_type)
            return RegimeParams(
                sl_factor=float(sl_f),
                max_strategy_type=str(max_st) if max_st else base.max_strategy_type,
                position_size_multiplier=float(cfg.get(f"{pfx}.range_position_multiplier", 1.0)),
                label="RANGE",
            )
        if regime == "HIGH_VOL":
            sl_f = cfg.get(f"{pfx}.high_vol_sl_factor", base.sl_factor)
            max_st = cfg.get(f"{pfx}.high_vol_strategy_type", base.max_strategy_type)
            tp1_r = cfg.get(f"{pfx}.high_vol_tp1_r", base.tp1_r)
            psm = cfg.get(f"{pfx}.high_vol_position_multiplier", base.position_size_multiplier)
            return RegimeParams(
                sl_factor=float(sl_f),
                max_strategy_type=str(max_st) if max_st else base.max_strategy_type,
                position_size_multiplier=float(psm),
                tp1_r=float(tp1_r) if tp1_r is not None else None,
                label="HIGH_VOL",
            )
    except Exception as e:
        logger.debug("[regime_strategy] Ошибка чтения конфига: %s", e)

    return base


def apply_regime_to_strategy(
    strategy_type: str,
    entry: float,
    stop_loss: float,
    take_profit: float,
    tp1_price: Optional[float],
    direction: str,
    regime: Optional[str],
    cfg=None,
) -> tuple[str, Optional[float]]:
    """
    Применяет режим рынка к strategy_type и tp1_price.

    Parameters
    ----------
    strategy_type : str         — текущий тип стратегии ("SINGLE"|"DUAL_TP"|"TRIPLE_TP_TSL")
    entry : float               — цена входа
    stop_loss : float           — стоп-лосс
    take_profit : float         — тейк-профит
    tp1_price : float | None    — уже рассчитанный TP1
    direction : str             — "LONG" | "SHORT"
    regime : str | None         — режим рынка
    cfg                         — конфиг бота

    Returns
    -------
    (adjusted_strategy_type, adjusted_tp1_price)
    """
    if not regime:
        return strategy_type, tp1_price

    params = get_regime_params(regime, cfg)
    # sl_factor из RegimeParams зарезервирован для будущего использования.
    # SL рассчитывается в trading_intelligence.py (ATR / pivot) и передаётся готовым.
    # Применять sl_factor здесь намеренно не нужно — изменение SL нарушает R:R логику.
    sl_dist = abs(entry - stop_loss) if stop_loss else 0.0
    sign = 1.0 if direction == "LONG" else -1.0

    # Применяем min/max strategy_type
    current_idx = _STRATEGY_ORDER.index(strategy_type) if strategy_type in _STRATEGY_ORDER else 0
    adj_idx = current_idx

    if params.min_strategy_type and params.min_strategy_type in _STRATEGY_ORDER:
        min_idx = _STRATEGY_ORDER.index(params.min_strategy_type)
        adj_idx = max(adj_idx, min_idx)

    if params.max_strategy_type and params.max_strategy_type in _STRATEGY_ORDER:
        max_idx = _STRATEGY_ORDER.index(params.max_strategy_type)
        adj_idx = min(adj_idx, max_idx)

    adjusted_strategy = _STRATEGY_ORDER[adj_idx]

    # Если strategy_type изменился → пересчитываем TP1
    adjusted_tp1 = tp1_price
    if adjusted_strategy != strategy_type and sl_dist > 0 and entry > 0:
        if adjusted_strategy in ("DUAL_TP", "DUAL_TSL"):
            # TP1 = take_profit (первый пивот по иерархии)
            adjusted_tp1 = take_profit

    # Форсированный TP1 при HIGH_VOL (перекрывает выше)
    if params.tp1_r is not None and sl_dist > 0:
        adjusted_tp1 = entry + sign * sl_dist * params.tp1_r

    if adjusted_strategy != strategy_type:
        logger.info(
            "[regime_strategy] %s: %s → %s (tp1=%.6f)",
            regime, strategy_type, adjusted_strategy, adjusted_tp1 or 0,
        )

    return adjusted_strategy, adjusted_tp1
