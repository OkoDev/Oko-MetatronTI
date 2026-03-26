"""
LIQUIDITY_SWEEP detector (DEV-82).

Паттерн "sweep and reverse":
  LONG:  Последний бар пробил swing_low (low < sweep_level),
         но закрылся обратно выше (close > sweep_level),
         + WT1 в OS зоне (<-40).
         → Стопы лонгистов собраны, разворот вверх.

  SHORT: Последний бар пробил swing_high (high > sweep_level),
         но закрылся ниже (close < sweep_level),
         + WT1 в OB зоне (>+40).
         → Стопы шортистов собраны, разворот вниз.

Уровни sweep:
  1. Последний swing_low/high из detect_swing_points (period=5)
  2. Weekly pivot S1/R1 из pivot_cache (если доступен)
  Если совпадают (оба пробиты одним баром) → strength бонус +15

Зависимости:
  core/smc/swing_points.py  — detect_swing_points()
  core/signals/signal_models — SignalData, SignalType
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from core.signals.signal_models import SignalData, SignalDirection, SignalType

logger = logging.getLogger(__name__)

_WT_OS = -40.0
_WT_OB = 40.0
_MIN_BARS = 30           # минимум баров для swing analysis
_LOOKBACK_SWING = 2      # сколько последних свингов проверять
_PIVOT_BONUS = 15        # бонус если sweep совпал с pivot уровнем


def _has_wt(df: pd.DataFrame) -> bool:
    return "wt1" in df.columns and "wt2" in df.columns


def _find_sweep_level_and_direction(
    df: pd.DataFrame,
    pivot_cache: dict,
    symbol: str,
) -> tuple[Optional[float], Optional[str], bool]:
    """
    Ищет уровень sweep на последнем баре.

    Returns:
        (sweep_level, direction, pivot_bonus)
        direction: "LONG" (swept sell-side) или "SHORT" (swept buy-side)
        pivot_bonus: True если уровень совпадает с Weekly S1/R1
    """
    last = df.iloc[-1]
    bar_low  = float(last["low"])
    bar_high = float(last["high"])
    bar_close = float(last["close"])

    sweep_level = None
    direction = None
    pivot_bonus = False

    # 1. Swing points analysis
    try:
        from core.smc.swing_points import detect_swing_points
        sa = detect_swing_points(df.iloc[:-1], period=5)  # без последнего бара (он сам sweep)
    except Exception as e:
        logger.debug("[LIQSWEEP] %s swing_points error: %s", symbol, e)
        return None, None, False

    # LONG: last bar swept a recent swing_low
    if sa.lows:
        recent_lows = sorted(sa.lows, key=lambda x: x.index, reverse=True)[:_LOOKBACK_SWING]
        for sp in recent_lows:
            lvl = sp.value
            if bar_low < lvl and bar_close > lvl:
                # Sweep confirmed: проткнули ниже, закрылись выше
                sweep_level = lvl
                direction = "LONG"
                break

    # SHORT: last bar swept a recent swing_high
    if direction is None and sa.highs:
        recent_highs = sorted(sa.highs, key=lambda x: x.index, reverse=True)[:_LOOKBACK_SWING]
        for sp in recent_highs:
            lvl = sp.value
            if bar_high > lvl and bar_close < lvl:
                sweep_level = lvl
                direction = "SHORT"
                break

    if sweep_level is None:
        return None, None, False

    # 2. Проверка совпадения с pivot (бонус)
    try:
        _piv = pivot_cache.get(symbol, {})
        # Weekly pivots: W:S1, W:S2 для LONG; W:R1, W:R2 для SHORT
        _piv_keys = ["W:S1", "W:S2"] if direction == "LONG" else ["W:R1", "W:R2"]
        for _pk in _piv_keys:
            _pv = _piv.get(_pk)
            if _pv and abs(sweep_level - _pv) / _pv < 0.005:  # ±0.5%
                pivot_bonus = True
                break
    except Exception:
        pass

    return sweep_level, direction, pivot_bonus


def detect_liquidity_sweep(
    symbol: str,
    df: pd.DataFrame,
    pivot_cache: Optional[dict] = None,
    cfg=None,
) -> Optional[SignalData]:
    """
    Детектор паттерна Liquidity Sweep (DEV-82).

    Args:
        symbol:       тикер пары
        df:           OHLCV DataFrame с pre-computed wt1/wt2 (если нет — вычисляются внутри)
        pivot_cache:  словарь pivot уровней {symbol: {"W:S1": ..., ...}}
        cfg:          config объект (опционально)

    Returns:
        SignalData или None.
    """
    if df is None or len(df) < _MIN_BARS:
        return None

    if pivot_cache is None:
        pivot_cache = {}

    # Проверка WT
    if not _has_wt(df):
        try:
            from core.indicators import calculate_wt
            df = calculate_wt(df)
        except Exception:
            logger.debug("[LIQSWEEP] %s: не удалось вычислить WT", symbol)
            return None

    wt1_last = float(df["wt1"].iloc[-1])

    # Найти sweep уровень
    sweep_level, direction, pivot_bonus = _find_sweep_level_and_direction(df, pivot_cache, symbol)
    if sweep_level is None or direction is None:
        return None

    # Фильтр WT зоны
    if direction == "LONG" and wt1_last >= _WT_OS:
        return None
    if direction == "SHORT" and wt1_last <= _WT_OB:
        return None

    # Strength: чем глубже вынос + чем ниже WT → тем сильнее
    bar_low   = float(df["low"].iloc[-1])
    bar_high  = float(df["high"].iloc[-1])
    bar_close = float(df["close"].iloc[-1])

    if direction == "LONG":
        sweep_depth_pct = (sweep_level - bar_low) / sweep_level * 100
        wt_bonus = max(0, int((-wt1_last - 40) / 2))   # WT ниже -40 → бонус
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
        symbol, direction, sweep_level, bar_close, wt1_last, pivot_bonus, strength,
    )

    return SignalData(
        symbol=symbol,
        signal_type=SignalType.LIQUIDITY_SWEEP,
        direction=sig_dir,
        strength=strength,
        confidence=0.58 + (0.07 if pivot_bonus else 0),
        timestamp=datetime.now(timezone.utc),
        timeframe="15m",
        entry_price=bar_close,
        data={
            "sweep_level": sweep_level,
            "sweep_depth_pct": round(sweep_depth_pct, 3),
            "wt1": wt1_last,
            "pivot_bonus": pivot_bonus,
        },
        description=f"Sweep {'sell-side' if direction == 'LONG' else 'buy-side'} @ {sweep_level:.6g}",
        interpretation=(
            f"Вынос стопов {'лонгистов' if direction == 'LONG' else 'шортистов'} "
            f"за уровень {sweep_level:.6g} — разворот {'вверх' if direction == 'LONG' else 'вниз'}"
        ),
    )
