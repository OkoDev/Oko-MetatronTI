"""
LIQUIDITY_SWEEP detector (DEV-82).

Логика сигнала:
  LONG  -> последний 1h-бар снимает значимую sell-side ликвидность
           и закрывается обратно выше уровня.
  SHORT -> последний 1h-бар снимает значимую buy-side ликвидность
           и закрывается обратно ниже уровня.

Антишум-фильтры:
  - не используем любой локальный swing сам по себе
  - уровень должен быть либо кластером ликвидности с >= 2 swing'ами,
    либо weekly pivot (W:S1/W:S2/W:R1/W:R2)
  - sweep обязан иметь минимальную глубину прокола и возврата
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from core.signals.signal_models import SignalData, SignalDirection, SignalType

logger = logging.getLogger(__name__)

_WT_OS = -50.0
_WT_OB = 50.0
_MIN_BARS = 120
_PIVOT_BONUS = 15
_MIN_CLUSTER_SWINGS = 2
_LIQ_CLUSTER_TOLERANCE_PCT = 0.3
_MIN_SWEEP_DEPTH_PCT = 0.12
_MIN_RECLAIM_PCT = 0.05


def _has_wt(df: pd.DataFrame) -> bool:
    return "wt1" in df.columns and "wt2" in df.columns


def _pct_distance(a: float, b: float) -> float:
    if not a:
        return 0.0
    return abs(a - b) / a * 100.0


def _find_sweep_level_and_direction(
    df: pd.DataFrame,
    pivot_cache: dict,
    symbol: str,
) -> tuple[Optional[float], Optional[str], bool]:
    """
    Ищет значимый уровень sweep на последнем баре.

    Returns:
        (sweep_level, direction, pivot_bonus)
    """
    last = df.iloc[-1]
    bar_low = float(last["low"])
    bar_high = float(last["high"])
    bar_close = float(last["close"])

    try:
        from core.smc.liquidity import detect_liquidity
        from core.smc.swing_points import detect_swing_points

        history_df = df.iloc[:-1]
        swings = detect_swing_points(history_df, period=10)
        liquidity = detect_liquidity(
            history_df,
            swings,
            cluster_tolerance_pct=_LIQ_CLUSTER_TOLERANCE_PCT,
            track_sweeps=True,
        )
    except Exception as exc:
        logger.debug("[LIQSWEEP] %s ошибка анализа ликвидности: %s", symbol, exc)
        return None, None, False

    candidate_long: Optional[float] = None
    for zone in reversed(liquidity.sell_side):
        if zone.swept or zone.swing_count < _MIN_CLUSTER_SWINGS:
            continue
        if bar_low >= zone.zone_bottom or bar_close <= zone.level:
            continue

        depth_pct = (zone.level - bar_low) / zone.level * 100
        reclaim_pct = (bar_close - zone.level) / zone.level * 100
        if depth_pct >= _MIN_SWEEP_DEPTH_PCT and reclaim_pct >= _MIN_RECLAIM_PCT:
            candidate_long = zone.level
            break

    candidate_short: Optional[float] = None
    for zone in reversed(liquidity.buy_side):
        if zone.swept or zone.swing_count < _MIN_CLUSTER_SWINGS:
            continue
        if bar_high <= zone.zone_top or bar_close >= zone.level:
            continue

        depth_pct = (bar_high - zone.level) / zone.level * 100
        reclaim_pct = (zone.level - bar_close) / zone.level * 100
        if depth_pct >= _MIN_SWEEP_DEPTH_PCT and reclaim_pct >= _MIN_RECLAIM_PCT:
            candidate_short = zone.level
            break

    try:
        # pivot_cache ключи: "{symbol}_1W", "{symbol}_1D", "{symbol}_1M"
        # значения: {"PP": ..., "S1": ..., "S2": ..., "R1": ..., "R2": ...}
        pivots_1w = pivot_cache.get(f"{symbol}_1W", {})
        pivots_1d = pivot_cache.get(f"{symbol}_1D", {})
        pivots_1m = pivot_cache.get(f"{symbol}_1M", {})
        _pivot_srcs = [s for s in (pivots_1w, pivots_1d, pivots_1m) if s]
        long_pivot = next(
            (
                float(pv)
                for src in _pivot_srcs
                for key in ("S1", "S2", "S3")
                if (pv := src.get(key)) and bar_low < float(pv) < bar_close
            ),
            None,
        )
        short_pivot = next(
            (
                float(pv)
                for src in _pivot_srcs
                for key in ("R1", "R2", "R3")
                if (pv := src.get(key)) and bar_high > float(pv) > bar_close
            ),
            None,
        )
    except Exception:
        long_pivot = None
        short_pivot = None

    if candidate_long is not None:
        pivot_bonus = long_pivot is not None and _pct_distance(candidate_long, long_pivot) <= 0.5
        return candidate_long, "LONG", pivot_bonus
    if candidate_short is not None:
        pivot_bonus = short_pivot is not None and _pct_distance(candidate_short, short_pivot) <= 0.5
        return candidate_short, "SHORT", pivot_bonus
    if long_pivot is not None:
        return long_pivot, "LONG", True
    if short_pivot is not None:
        return short_pivot, "SHORT", True

    return None, None, False


def detect_liquidity_sweep(
    symbol: str,
    df: pd.DataFrame,
    pivot_cache: Optional[dict] = None,
    cfg=None,
) -> Optional[SignalData]:
    if df is None or len(df) < _MIN_BARS:
        return None

    if pivot_cache is None:
        pivot_cache = {}

    if not _has_wt(df):
        try:
            from core.indicators.indicators import calculate_wt

            df = calculate_wt(df)
        except Exception:
            logger.debug("[LIQSWEEP] %s: не удалось вычислить WT", symbol)
            return None

    wt1_last = float(df["wt1"].iloc[-1])
    sweep_level, direction, pivot_bonus = _find_sweep_level_and_direction(df, pivot_cache, symbol)
    if sweep_level is None or direction is None:
        return None

    if direction == "LONG" and wt1_last >= _WT_OS:
        return None
    if direction == "SHORT" and wt1_last <= _WT_OB:
        return None

    bar_low = float(df["low"].iloc[-1])
    bar_high = float(df["high"].iloc[-1])
    bar_close = float(df["close"].iloc[-1])

    if direction == "LONG":
        sweep_depth_pct = (sweep_level - bar_low) / sweep_level * 100
        wt_bonus = max(0, int((-wt1_last - 40) / 2))
    else:
        sweep_depth_pct = (bar_high - sweep_level) / sweep_level * 100
        wt_bonus = max(0, int((wt1_last - 40) / 2))

    base_strength = 55 + min(20, int(sweep_depth_pct * 5)) + wt_bonus
    if pivot_bonus:
        base_strength += _PIVOT_BONUS
    strength = min(95, base_strength)

    sig_dir = SignalDirection.LONG if direction == "LONG" else SignalDirection.SHORT

    logger.info(
        "[DEV-82-LIQSWEEP] %s dir=%s sweep_lvl=%.6f close=%.6f wt1=%.1f pivot_bonus=%s str=%d",
        symbol,
        direction,
        sweep_level,
        bar_close,
        wt1_last,
        pivot_bonus,
        strength,
    )

    return SignalData(
        symbol=symbol,
        signal_type=SignalType.LIQUIDITY_SWEEP,
        direction=sig_dir,
        strength=strength,
        confidence=0.58 + (0.07 if pivot_bonus else 0.0),
        timestamp=datetime.now(timezone.utc),
        timeframe="1h",
        entry_price=bar_close,
        data={
            "sweep_level": sweep_level,
            "sweep_depth_pct": round(sweep_depth_pct, 3),
            "wt1": wt1_last,
            "pivot_bonus": pivot_bonus,
        },
        description=f"Sweep {'sell-side' if direction == 'LONG' else 'buy-side'} @ {sweep_level:.6g}",
        interpretation=(
            f"Снятие {'sell-side' if direction == 'LONG' else 'buy-side'} ликвидности "
            f"в районе {sweep_level:.6g} с разворотом {'вверх' if direction == 'LONG' else 'вниз'}"
        ),
    )
