"""
FUNDING_EXTREME detector (DEV-81) — Shadow mode (2 недели лог, без TG).

Логика:
  funding_rate < -THRESHOLD → все шортят → LONG squeeze возможен
  funding_rate > +THRESHOLD → все лонгуют → SHORT squeeze возможен

Условия:
  1. |funding_rate| > 0.0005 (по умолчанию)
  2. WT cross в правильном направлении в зоне OS (<-40) / OB (>+40)
  3. (опционально) цена у структурного уровня (pivot)

Shadow mode: сигнал попадает в all_scan_signals для аналитики,
             НО НЕ в signals_to_broadcast (TG не отправляем 2 недели).
Включить в production: убрать "shadow" из data и добавить в broadcast.
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from datetime import datetime, timezone

from core.signals.signal_models import SignalData, SignalDirection, SignalType

logger = logging.getLogger(__name__)

# Порог funding rate для «экстремального» значения
_DEFAULT_THRESHOLD = 0.0005   # 0.05% за 8ч → ~0.18%/день
_WT_OS_LEVEL      = -40.0
_WT_OB_LEVEL      =  40.0


def _has_wt(df: pd.DataFrame) -> bool:
    return "wt1" in df.columns and "wt2" in df.columns


def _wt_cross(df: pd.DataFrame, direction: str, os_level: float = -40.0, ob_level: float = 40.0) -> bool:
    """
    Проверяет наличие WT cross в нужном направлении за последние 3 бара.

    LONG: wt1 пересёк wt2 снизу вверх (wt1[-1] > wt2[-1], wt1[-2] <= wt2[-2])
          И wt1 в зоне OS (< os_level) хотя бы на одном из этих баров
    SHORT: аналогично вниз в OB.
    """
    if len(df) < 3:
        return False
    w1 = df["wt1"].values
    w2 = df["wt2"].values
    if direction == "LONG":
        # Cross up: prev below, curr above
        cross = w1[-1] > w2[-1] and w1[-2] <= w2[-2]
        in_zone = w1[-1] < os_level or w1[-2] < os_level
        return cross and in_zone
    else:
        cross = w1[-1] < w2[-1] and w1[-2] >= w2[-2]
        in_zone = w1[-1] > ob_level or w1[-2] > ob_level
        return cross and in_zone


def detect_funding_extreme(
    symbol: str,
    df: pd.DataFrame,
    funding_rate: float,
    cfg=None,
) -> Optional[SignalData]:
    """
    Детектор экстремального funding rate (DEV-81).

    Args:
        symbol:       тикер пары
        df:           OHLCV с pre-computed wt1/wt2 (если нет — вычисляются внутри)
        funding_rate: текущий funding rate с биржи (float, напр. -0.0008)
        cfg:          config объект (опционально, для кастомного threshold)

    Returns:
        SignalData или None если условия не выполнены.
    """
    if df is None or len(df) < 5:
        return None
    if funding_rate is None:
        return None

    threshold = float(cfg.get("detectors.funding.threshold", _DEFAULT_THRESHOLD)) if cfg else _DEFAULT_THRESHOLD
    if abs(funding_rate) < threshold:
        return None

    direction = "LONG" if funding_rate < 0 else "SHORT"

    # Если wt не pre-computed — вычисляем
    if not _has_wt(df):
        try:
            from core.indicators import calculate_wt
            df = calculate_wt(df)
        except Exception:
            logger.debug("[FUNDING] %s: не удалось вычислить WT", symbol)
            return None

    if not _wt_cross(df, direction, _WT_OS_LEVEL, _WT_OB_LEVEL):
        return None

    # Strength: чем экстремальнее funding — тем сильнее сигнал
    ratio = abs(funding_rate) / threshold
    strength = min(100, int(50 + ratio * 15))

    current_price = float(df["close"].iloc[-1]) if len(df) > 0 else 0.0
    sig_dir = SignalDirection.LONG if direction == "LONG" else SignalDirection.SHORT

    logger.info(
        "[DEV-81-FUNDING] %s fr=%.6f dir=%s str=%d [shadow_mode]",
        symbol, funding_rate, direction, strength,
    )

    return SignalData(
        symbol=symbol,
        signal_type=SignalType.FUNDING_EXTREME,
        direction=sig_dir,
        strength=strength,
        confidence=0.55 + (ratio - 1) * 0.05,
        timestamp=datetime.now(timezone.utc),
        timeframe="8h",
        entry_price=current_price,
        data={
            "funding_rate": funding_rate,
            "threshold": threshold,
            "shadow": True,          # shadow mode — не отправляем в TG
            "wt1": float(df["wt1"].iloc[-1]),
        },
        description=f"Funding {'медвежий' if direction == 'LONG' else 'бычий'}: {funding_rate:.6f}",
        interpretation=(
            "Все шортят → squeeze вверх возможен" if direction == "LONG"
            else "Все лонгуют → dump вниз возможен"
        ),
    )
