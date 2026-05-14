"""
Sideways Mode Strategy — WT OS/OB на 30m при RANGE-режиме.

Активируется параллельно основным стратегиям когда pair_state.sideways_mode_active=True.
Не изменяет существующую логику — только добавляет сигналы в боковике.

Логика: WT crossup из OS (<-45) → LONG, crossdown из OB (>+45) → SHORT.
SL: ATR trendline (factor=1.25). TP: 2R fixed. TSL активируется после +1R.

Бэктест 30 дней, 50 пар (05.05.2026):
  wt_os45 на 30m: avgR=+0.184, WR=46.2%, n=584
  wt_div30 на 30m: avgR=+0.201, WR=46.6%, n=382
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Optional

import pandas as pd

from core.indicators.indicators import calculate_wt, calculate_trend

logger = logging.getLogger(__name__)

_TIMEFRAME = "30m"
_WT_LONG_THRESH  = -45.0   # WT < -45 → OS зона для LONG
_WT_SHORT_THRESH = +45.0   # WT > +45 → OB зона для SHORT
_ATR_FACTOR      = 1.25    # TSL factor
_ATR_PERIOD      = 43      # период ATR (как в основном коде)
_TP_RR           = 2.0     # TP = entry ± sl_dist × 2.0
_MIN_SL_PCT      = 0.008   # минимальный SL от цены (0.8%) — защита от micro-SL на альтах
_MAX_SL_PCT      = 0.06    # максимальный SL от цены (6%)


def _build_rec(
    symbol: str,
    direction: str,
    entry: float,
    sl: float,
    tp: float,
    strength: int,
    wt1: float,
) -> SimpleNamespace:
    """Создаёт duck-typed объект рекомендации для register_trade_async."""
    _sig = SimpleNamespace(
        signal_type=SimpleNamespace(value="wt_sideways"),
        direction=SimpleNamespace(value=direction),
        strength=strength,
    )
    return SimpleNamespace(
        symbol=symbol,
        action="BUY" if direction == "LONG" else "SELL",
        direction=SimpleNamespace(value=direction),
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        tp1_price=None,
        overall_strength=strength,
        confidence=0.55,
        risk_level="MEDIUM",
        timestamp=datetime.now(timezone.utc),
        market_context=None,
        supporting_signals=[_sig],
        conflicting_signals=[],
        sl_source="atr_trendline_30m",
        tp_source=f"rr_{_TP_RR}",
        timeframe=_TIMEFRAME,
        metadata={"sideways_mode": True, "wt1": round(wt1, 2)},
        signals_count=1,
        reasoning=[f"WT {direction} crossover из {'OS' if direction=='LONG' else 'OB'} зоны на {_TIMEFRAME}"],
        atr_entry_tf=None,
    )


def analyze_sideways(
    symbol: str,
    df_30m: pd.DataFrame,
    min_strength: int = 60,
    df_1h: Optional[pd.DataFrame] = None,
) -> Optional[SimpleNamespace]:
    """
    Анализирует 30m данные на предмет WT OS/OB crossover.

    Cross-gate убран 14.05 (B1 backtest):
        SHORT в TREND_UP = +187.7R (n=891, avgR=+0.211) — gate блокировал прибыльные сделки.
        df_1h используется только для записи atr_1h_bias в metadata (observability).

    Возвращает recommendation-like объект или None.
    """
    if df_30m is None or len(df_30m) < 100:
        return None

    try:
        df = calculate_wt(df_30m)
        df = calculate_trend(df, atr_period=_ATR_PERIOD, factor=_ATR_FACTOR)
    except Exception as e:
        logger.debug("[sideways] %s: ошибка индикаторов: %s", symbol, e)
        return None

    if len(df) < 2:
        return None

    last  = df.iloc[-1]
    prev  = df.iloc[-2]

    wt1_cur  = float(last.get("wt1", 0))
    wt2_cur  = float(last.get("wt2", 0))
    wt1_prev = float(prev.get("wt1", 0))
    wt2_prev = float(prev.get("wt2", 0))

    # Bullish crossover: wt1 пересёк wt2 снизу вверх в OS зоне
    bull_cross = (wt1_prev <= wt2_prev and wt1_cur > wt2_cur and wt1_prev < _WT_LONG_THRESH)
    # Bearish crossover: wt1 пересёк wt2 сверху вниз в OB зоне
    bear_cross = (wt1_prev >= wt2_prev and wt1_cur < wt2_cur and wt1_prev > _WT_SHORT_THRESH)

    if not bull_cross and not bear_cross:
        return None

    entry = float(last.get("close", 0))
    if entry <= 0:
        return None

    direction = "LONG" if bull_cross else "SHORT"

    # ── atr_trend_1h_bias для observability (gate УБРАН 14.05) ─────────────
    # Gate 3e1ca17 (12.05): SHORT в TREND_UP блокировался.
    # Бэктест B1 (14.05): SHORT в TREND_UP = +187.7R (n=891, avgR=+0.211) — counter-trend работает!
    # LONG в TREND_DOWN = -123.8R — тоже убыточно, но не блокируем (правило: нет блоков).
    # Bias записывается в metadata для последующего анализа.
    _atr_1h_bias = None
    if df_1h is not None and "trend" in df_1h.columns and len(df_1h) >= 2:
        try:
            _trend_1h_closed = df_1h["trend"].iloc[-2]
            if not pd.isna(_trend_1h_closed):
                _atr_1h_bias = "UP" if int(_trend_1h_closed) == 1 else "DOWN"
        except Exception as _ge:
            logger.debug("[sideways] %s: atr_1h_bias err: %s", symbol, _ge)

    # SL по TSL-линии
    if direction == "LONG":
        tsl_line = float(last.get("trendup", 0))
        if tsl_line <= 0 or tsl_line >= entry:
            tsl_line = entry * (1 - 0.02)  # fallback 2%
        sl = tsl_line
    else:
        tsl_line = float(last.get("trenddown", 0))
        if tsl_line <= 0 or tsl_line <= entry:
            tsl_line = entry * (1 + 0.02)  # fallback 2%
        sl = tsl_line

    sl_dist = abs(entry - sl)
    sl_pct  = sl_dist / entry

    # Защита от слишком узкого/широкого SL
    if sl_pct < _MIN_SL_PCT:
        sl = entry * (1 - _MIN_SL_PCT) if direction == "LONG" else entry * (1 + _MIN_SL_PCT)
        sl_dist = abs(entry - sl)
    elif sl_pct > _MAX_SL_PCT:
        logger.debug("[sideways] %s: SL слишком далеко (%.1f%%) — пропуск", symbol, sl_pct * 100)
        return None

    tp = (entry + sl_dist * _TP_RR) if direction == "LONG" else (entry - sl_dist * _TP_RR)

    # Strength: базовый + бонус за глубину OS/OB
    depth = abs(wt1_prev)
    strength = min(85, min_strength + int((depth - 45) * 0.5))

    logger.info(
        "[sideways] %s: %s crossover wt1_prev=%.1f→wt1=%.1f entry=%.6f sl=%.6f tp=%.6f str=%d bias_1h=%s",
        symbol, direction, wt1_prev, wt1_cur, entry, sl, tp, strength, _atr_1h_bias,
    )

    rec = _build_rec(symbol, direction, entry, sl, tp, strength, wt1_cur)
    rec.metadata["atr_1h_bias"] = _atr_1h_bias  # для observability
    return rec
