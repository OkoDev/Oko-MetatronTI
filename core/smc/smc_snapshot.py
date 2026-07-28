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
from core.smc.liquidity import detect_equal_highs_lows
from core.smc.smc_engine import ote_retest_setups

logger = logging.getLogger(__name__)

# Per-ТФ zigzag (depth, dev) из ТОГО ЖЕ config/ote_setups.yaml, что ote_signal_generator.
# Единый OTE-калькулятор → snapshot и торговля не расходятся (см. bug_ote_impulse_period5).
_ZZ_PARAMS: Optional[Dict[str, Any]] = None


def _zz_params(tf: str) -> tuple:
    global _ZZ_PARAMS
    if _ZZ_PARAMS is None:
        try:
            import yaml
            from pathlib import Path
            cfg_path = Path(__file__).resolve().parents[2] / "config" / "ote_setups.yaml"
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            _ZZ_PARAMS = cfg.get("zigzag_params", {}) or {}
        except Exception:
            _ZZ_PARAMS = {}
    p = _ZZ_PARAMS.get(tf) or {}
    return int(p.get("depth") or 11), float(p.get("dev") or 3.0)

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
    by_tf: Dict[str, Any] = {}   # per-TF раскрытие (Егор 29.07): OB/FVG/CHoCH/BOS отдельно по каждому
                                 # ТФ — раньше схлопывалось в nearest/latest, MTF-нюанс терялся.

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
        ob_res = None
        fvg_res = None

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

        # per-TF раскрытие (аддитивно): ближайший OB↑/↓ + FVG-плотность + последний CHoCH/BOS
        # НА ЭТОМ ТФ (не схлопнутый). Читают: фильтр-конструктор + будущие MTF-гейты.
        try:
            _obb = [_ob_snap(o, tf, current_price, bars_n) for o in getattr(ob_res, "active_bull", [])]
            _obr = [_ob_snap(o, tf, current_price, bars_n) for o in getattr(ob_res, "active_bear", [])]
            _ch = _bs = None
            for brk in reversed(struct.breaks or []):
                _d = "UP" if brk.direction == "LONG" else "DOWN"
                if _ch is None and brk.break_type in (BreakType.BULLISH_CHOCH, BreakType.BEARISH_CHOCH):
                    _ch = _d
                if _bs is None and brk.break_type in (BreakType.BULLISH_BOS, BreakType.BEARISH_BOS):
                    _bs = _d
            by_tf[tf] = {
                "ob_bull": min(_obb, key=lambda x: abs(x["distance_pct"])) if _obb else None,
                "ob_bear": min(_obr, key=lambda x: abs(x["distance_pct"])) if _obr else None,
                "fvg_bull": len(getattr(fvg_res, "active_bull", [])),
                "fvg_bear": len(getattr(fvg_res, "active_bear", [])),
                "choch": _ch,
                "bos": _bs,
            }
        except Exception as e:
            logger.debug("[SMC_SNAP] %s by_tf(%s) error: %s", symbol, tf, e)

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

    if senior_tf is not None and senior_tf in ohlcv_by_tf:
        df_sr = ohlcv_by_tf[senior_tf]
        bars_sr = len(df_sr)
        # swing_high/low (метки для отображения) — из structure (period=5 ок для меток)
        struct_sr = structures_by_tf.get(senior_tf)
        if struct_sr is not None:
            sa = struct_sr.swing_analysis
            if sa.last_high is not None:
                swing_high = {"tf": senior_tf, "price": sa.last_high.value,
                              "age_bars": max(0, bars_sr - 1 - int(sa.last_high.index))}
            if sa.last_low is not None:
                swing_low = {"tf": senior_tf, "price": sa.last_low.value,
                             "age_bars": max(0, bars_sr - 1 - int(sa.last_low.index))}
        # OTE — ЕДИНЫЙ источник: zigzag (как ote_signal_generator торгует), НЕ period=5.
        # Устраняет дрейф snapshot↔торговля (bug_ote_impulse_period5): импульс берётся
        # от значимого CHoCH-слома (zigzag_atr), а не от последних мелких свингов.
        try:
            depth, dev = _zz_params(senior_tf)
            ote_setups = ote_retest_setups(df_sr, depth=depth, dev_mult=dev,
                                           only_choch=False, provisional=True)
            if ote_setups:
                h = ote_setups[-1]
                lo_o, hi_o = h["ote"]
                lo, hi = min(lo_o, hi_o), max(lo_o, hi_o)
                ote_direction = "LONG" if str(h.get("direction")).lower() == "long" else "SHORT"
                ote_tf = senior_tf
                price_in_ote = lo <= current_price <= hi
                frm, to = h.get("from"), h.get("to")   # импульс (idx, price)
                if frm is not None and to is not None:
                    impulse_low = float(min(frm[1], to[1]))
                    impulse_high = float(max(frm[1], to[1]))
                    fib_levels = _calc_fib_levels(impulse_high, impulse_low, ote_direction)
                    diff = impulse_high - impulse_low
                    if diff > 0:
                        if ote_direction == "LONG":
                            current_retracement = round((impulse_high - current_price) / diff * 100.0, 2)
                        else:
                            current_retracement = round((current_price - impulse_low) / diff * 100.0, 2)
        except Exception as e:
            logger.debug("[SMC_SNAP] %s ote_retest_setups(%s) error: %s", symbol, senior_tf, e)

    # ARCH-120: EQH/EQL liquidity pools на senior TF (магниты для TPSelector/ARCH-122)
    eqh_level: Optional[float] = None
    eql_level: Optional[float] = None
    eqh_near = False
    eql_near = False
    if senior_tf is not None and senior_tf in ohlcv_by_tf:
        try:
            _liq = detect_equal_highs_lows(ohlcv_by_tf[senior_tf])
            eqh_level = _liq.get("eqh_level")
            eql_level = _liq.get("eql_level")
            eqh_near = bool(_liq.get("eqh_near"))
            eql_near = bool(_liq.get("eql_near"))
        except Exception as e:
            logger.debug("[SMC_SNAP] %s detect_equal_highs_lows(%s) error: %s", symbol, senior_tf, e)

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
        # ARCH-120: liquidity pools (EQH/EQL) — магниты + stop-hunt контекст
        "eqh_level": eqh_level,
        "eql_level": eql_level,
        "eqh_near": eqh_near,
        "eql_near": eql_near,
        "liq_tf": senior_tf,
        "by_tf": by_tf,   # per-TF раскрытие (аддитивно, Егор 29.07)
    }
    return snap
