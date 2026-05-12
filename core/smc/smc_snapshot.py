"""
SMC Snapshot — агрегатор структурных данных для PairState.smc_snap.

ARCH-89 / Куб Метатрона, Сфера 4:
объединяет FVG / Order Blocks / BOS / CHoCH / Swings / Fibonacci
по набору TF в единый snap-словарь для публикации в PairContextBus.

Потребители:
  - NarrativeBuilder — добавляет структурные факторы в narrative (ARCH-90)
  - OutcomePredictor — фичи `nearest_ob_strength`, `price_in_ote` и т.д.
  - Dashboard — визуализация структуры пары

Производительность: целевой бюджет < 50мс на пару.
Все существующие SMC-детекторы переиспользуются, новых расчётов нет.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from core.smc.fvg import detect_fvg
from core.smc.order_blocks import detect_order_blocks
from core.smc.structure import detect_structure, BreakType

logger = logging.getLogger(__name__)

# Приоритет TF для выбора swing high/low и Fibonacci (старший → младший)
_TF_PRIORITY = ["1w", "1d", "4h", "1h", "15m", "5m", "3m"]

# Fibonacci-уровни в snap (включают OTE 0.705 / 0.79 из ARCH-89 спека)
_FIB_RATIOS = (0.236, 0.382, 0.500, 0.618, 0.705, 0.786, 0.79, 0.886)
_OTE_TOP_RATIO = 0.705
_OTE_BOT_RATIO = 0.79


def _pick_senior_tf(ohlcv_by_tf: Dict[str, pd.DataFrame]) -> Optional[str]:
    """Возвращает старший TF с достаточным объёмом данных (>=30 баров)."""
    for tf in _TF_PRIORITY:
        df = ohlcv_by_tf.get(tf)
        if df is not None and not df.empty and len(df) >= 30:
            return tf
    return None


def _distance_pct(level: float, price: float) -> float:
    """+ если level выше цены, − если ниже."""
    if price <= 0:
        return 0.0
    return (level - price) / price * 100.0


def _ob_snap(ob, tf: str, price: float, bars_n: int) -> Dict[str, Any]:
    """Сериализует OrderBlock → dict для snap."""
    return {
        "tf": tf,
        "top": ob.top,
        "bottom": ob.bottom,
        "strength": int(ob.strength),
        "distance_pct": round(_distance_pct(ob.midpoint, price), 3),
        "age_bars": max(0, bars_n - 1 - int(ob.index)),
    }


def _fvg_snap(fvg, tf: str, bars_n: int) -> Dict[str, Any]:
    return {
        "tf": tf,
        "top": fvg.top,
        "bottom": fvg.bottom,
        "mitigation_pct": round(fvg.mitigation_pct * 100.0, 1),
        "age_bars": max(0, bars_n - 1 - int(fvg.index)),
    }


def _break_snap(brk, tf: str, bars_n: int) -> Dict[str, Any]:
    direction = "UP" if brk.direction == "LONG" else "DOWN"
    return {
        "tf": tf,
        "direction": direction,
        "age_bars": max(0, bars_n - 1 - int(brk.break_index)),
    }


def _calc_fib_levels(impulse_high: float, impulse_low: float, direction: str) -> Dict[str, float]:
    """LONG: ретрейсмент от high вниз; SHORT: от low вверх."""
    diff = impulse_high - impulse_low
    if diff <= 0:
        return {}
    out: Dict[str, float] = {}
    for r in _FIB_RATIOS:
        if direction == "LONG":
            out[f"{r:.3f}"] = impulse_high - diff * r
        else:
            out[f"{r:.3f}"] = impulse_low + diff * r
    return out


def build_smc_snapshot(
    symbol: str,
    ohlcv_by_tf: Dict[str, pd.DataFrame],
) -> Optional[Dict[str, Any]]:
    """Агрегирует FVG/OB/BOS/CHoCH/Swings/Fib по TF в единый snap.

    Args:
        symbol:       торговая пара (для логов).
        ohlcv_by_tf:  словарь {tf: DataFrame(OHLCV)}. Пустые/короткие DF игнорируются.

    Returns:
        Словарь с ключами, перечисленными в спеке ARCH-89, либо None, если
        данных недостаточно (все DF короче 30 баров).
    """
    if not ohlcv_by_tf:
        return None

    # Текущая цена — из самого младшего TF с данными (обычно entry TF = 15m)
    current_price = 0.0
    for tf in reversed(_TF_PRIORITY):
        df = ohlcv_by_tf.get(tf)
        if df is not None and not df.empty and "close" in df.columns:
            current_price = float(df["close"].iloc[-1])
            break
    if current_price <= 0:
        return None

    tfs_processed: List[str] = []
    all_bull_obs: List[Dict[str, Any]] = []
    all_bear_obs: List[Dict[str, Any]] = []
    bull_fvg_active: List[Dict[str, Any]] = []
    bear_fvg_active: List[Dict[str, Any]] = []

    latest_bos: Optional[Dict[str, Any]] = None   # по свежести (age_bars min)
    latest_choch: Optional[Dict[str, Any]] = None

    structures_by_tf: Dict[str, Any] = {}

    for tf, df in ohlcv_by_tf.items():
        if df is None or df.empty or len(df) < 30:
            continue
        try:
            struct = detect_structure(df)
        except Exception as e:
            logger.debug("[SMC_SNAP] %s detect_structure(%s) error: %s", symbol, tf, e)
            continue

        structures_by_tf[tf] = struct
        tfs_processed.append(tf)
        bars_n = len(df)

        try:
            ob_res = detect_order_blocks(df, struct)
            for ob in ob_res.active_bull:
                all_bull_obs.append(_ob_snap(ob, tf, current_price, bars_n))
            for ob in ob_res.active_bear:
                all_bear_obs.append(_ob_snap(ob, tf, current_price, bars_n))
        except Exception as e:
            logger.debug("[SMC_SNAP] %s detect_order_blocks(%s) error: %s", symbol, tf, e)

        try:
            fvg_res = detect_fvg(df)
            for fvg in fvg_res.active_bull:
                bull_fvg_active.append(_fvg_snap(fvg, tf, bars_n))
            for fvg in fvg_res.active_bear:
                bear_fvg_active.append(_fvg_snap(fvg, tf, bars_n))
        except Exception as e:
            logger.debug("[SMC_SNAP] %s detect_fvg(%s) error: %s", symbol, tf, e)

        # Последний BOS / CHoCH по свежести среди всех TF (меньший age_bars = свежее)
        if struct.breaks:
            for brk in reversed(struct.breaks):
                snap = _break_snap(brk, tf, bars_n)
                if brk.break_type in (BreakType.BULLISH_BOS, BreakType.BEARISH_BOS):
                    if latest_bos is None or snap["age_bars"] < latest_bos["age_bars"]:
                        latest_bos = snap
                    break
            for brk in reversed(struct.breaks):
                snap = _break_snap(brk, tf, bars_n)
                if brk.break_type in (BreakType.BULLISH_CHOCH, BreakType.BEARISH_CHOCH):
                    if latest_choch is None or snap["age_bars"] < latest_choch["age_bars"]:
                        latest_choch = snap
                    break

    if not tfs_processed:
        return None

    # Nearest OB среди всех TF — по |distance_pct|
    nearest_bull_ob = (
        min(all_bull_obs, key=lambda o: abs(o["distance_pct"])) if all_bull_obs else None
    )
    nearest_bear_ob = (
        min(all_bear_obs, key=lambda o: abs(o["distance_pct"])) if all_bear_obs else None
    )

    # Swing H/L и Fibonacci — из старшего доступного TF
    senior_tf = _pick_senior_tf(ohlcv_by_tf)
    swing_high: Optional[Dict[str, Any]] = None
    swing_low: Optional[Dict[str, Any]] = None
    fib_levels: Dict[str, float] = {}
    price_in_ote = False
    current_retracement = 0.0
    ote_direction: Optional[str] = None  # DEV-209: "LONG" | "SHORT" — направление импульса
    ote_tf: Optional[str] = None         # senior TF на котором посчитан OTE

    if senior_tf is not None and senior_tf in structures_by_tf:
        df_sr = ohlcv_by_tf[senior_tf]
        try:
            struct_sr = structures_by_tf[senior_tf]
            sa = struct_sr.swing_analysis
            bars_sr = len(df_sr)
            if sa.last_high is not None:
                swing_high = {
                    "tf": senior_tf,
                    "price": sa.last_high.value,
                    "age_bars": max(0, bars_sr - 1 - int(sa.last_high.index)),
                }
            if sa.last_low is not None:
                swing_low = {
                    "tf": senior_tf,
                    "price": sa.last_low.value,
                    "age_bars": max(0, bars_sr - 1 - int(sa.last_low.index)),
                }
            # Направление импульса: что свежее — high или low
            if sa.last_high is not None and sa.last_low is not None:
                impulse_high = sa.last_high.value
                impulse_low = sa.last_low.value
                if impulse_high > impulse_low:
                    direction = "LONG" if sa.last_high.index > sa.last_low.index else "SHORT"
                    ote_direction = direction
                    ote_tf = senior_tf
                    fib_levels = _calc_fib_levels(impulse_high, impulse_low, direction)
                    diff = impulse_high - impulse_low
                    if diff > 0:
                        if direction == "LONG":
                            current_retracement = round(
                                (impulse_high - current_price) / diff * 100.0, 2
                            )
                        else:
                            current_retracement = round(
                                (current_price - impulse_low) / diff * 100.0, 2
                            )
                        ote_top = fib_levels.get(f"{_OTE_TOP_RATIO:.3f}")
                        ote_bot = fib_levels.get(f"{_OTE_BOT_RATIO:.3f}")
                        if ote_top is not None and ote_bot is not None:
                            lo, hi = min(ote_top, ote_bot), max(ote_top, ote_bot)
                            price_in_ote = lo <= current_price <= hi
        except Exception as e:
            logger.debug("[SMC_SNAP] %s senior_tf(%s) error: %s", symbol, senior_tf, e)

    snap = {
        "timestamp": pd.Timestamp.utcnow().isoformat(),
        "tfs_processed": tfs_processed,
        "nearest_bull_ob": nearest_bull_ob,
        "nearest_bear_ob": nearest_bear_ob,
        "bull_fvg_active": bull_fvg_active,
        "bear_fvg_active": bear_fvg_active,
        "last_bos": latest_bos,
        "last_choch": latest_choch,
        "swing_high": swing_high,
        "swing_low": swing_low,
        "fib_levels": fib_levels,
        "price_in_ote": price_in_ote,
        "current_retracement": current_retracement,
        "ote_direction": ote_direction,  # DEV-209
        "ote_tf": ote_tf,                # DEV-209
    }
    return snap
