"""
Confluence Scanner — Lookback-детектор мульти-факторных сетапов.

Ищет в окне lookback_bars баров совпадение условий (LONG и SHORT):

  LONG (бычий сетап):
    1. WT был в OS зоне (wt1 < -60)           → +20 очков
    2. TSL пересечение UP (тренд сменился 1)   → +20 очков
    3. Цена была у поддержки (S1/S2/PP)        → +25 очков
    4. Бычья дивергенция WT (price LL, wt HL)  → +20 очков
    5. Текущая цена выше дневного PP           → +15 очков

  SHORT (медвежий сетап):
    1. WT был в OB зоне (wt1 > +60)           → +20 очков
    2. TSL пересечение DOWN (тренд сменился -1) → +20 очков
    3. Цена была у сопротивления (R1/R2/PP)    → +25 очков
    4. Медвежья дивергенция WT (price HH, wt LH) → +20 очков
    5. Текущая цена ниже дневного PP           → +15 очков

Порог сигнала: strength ≥ 60 (3+ факторов).
Функция синхронная — не делает API-запросов, только считает по готовым df.
"""
import logging
from datetime import datetime
from typing import List, Dict, Any, Tuple

import numpy as np
import pandas as pd

from core.indicators import calculate_trend, calculate_wt
from core.signal_models import SignalData, SignalType, SignalDirection

logger = logging.getLogger(__name__)

# ── Дефолты (перекрываются через config.yaml → analysis.confluence) ──────────
_DEFAULT_WT_OS = -60   # OS зона: wt1 < -60
_DEFAULT_WT_OB = 60    # OB зона: wt1 > +60
_DEFAULT_PIVOT_PCT = 1.0
_DEFAULT_MIN_STRENGTH = 60
_DEFAULT_DIV_MIN_BARS = 3
_DEFAULT_LOOKBACK = 30

# Очки за каждое условие
_SCORE_WT_ZONE = 20     # WT в OS (LONG) или OB (SHORT)
_SCORE_TSL_CROSS = 20   # TSL пересечение в нужном направлении
_SCORE_NEAR_PIVOT = 25  # Цена у ключевого уровня
_SCORE_DIVERGENCE = 20  # Дивергенция WT
_SCORE_PP_CONFIRM = 15  # Цена по отношению к дневному PP
_SCORE_WT_CROSS = 15    # WT cross (wt1/wt2 пересечение) в lookback-окне


def _get_cfg(cfg) -> dict:
    """Извлекает analysis.confluence из объекта конфига (поддерживает ConfigLoader и dict)."""
    if cfg is None:
        return {}
    if hasattr(cfg, "get"):
        block = cfg.get("analysis.confluence", None)
        if isinstance(block, dict):
            return block
        return (cfg.get("analysis") or {}).get("confluence", {})
    return {}


def scan_confluence(
    symbol: str,
    df_15m: pd.DataFrame,
    df_1h: pd.DataFrame,
    pivot_cache: Dict[str, Any],
    lookback_bars: int = _DEFAULT_LOOKBACK,
    cfg=None,
) -> List[SignalData]:
    """
    Lookback-сканер конфлюэнции. Возвращает список SignalData (обычно 0-2 сигнала).

    Args:
        symbol:        торговая пара (напр. "BTC/USDT")
        df_15m:        OHLCV DataFrame 15m (>= lookback_bars строк)
        df_1h:         OHLCV DataFrame 1h (>= lookback_bars строк)
        pivot_cache:   bot.pivot_calculator.pivot_cache (dict ключ = f"{sym}_1D")
        lookback_bars: глубина поиска в барах 15m (~7.5 часов при 30 барах)
        cfg:           объект конфига (ConfigLoader или dict) — читает analysis.confluence
    """
    results: List[SignalData] = []

    try:
        conf_cfg = _get_cfg(cfg)
        if not conf_cfg.get("enabled", True):
            return results

        lookback_bars = int(conf_cfg.get("lookback_bars", lookback_bars))
        wt_os_thr    = float(conf_cfg.get("wt_os_threshold", _DEFAULT_WT_OS))
        wt_ob_thr    = float(conf_cfg.get("wt_ob_threshold", _DEFAULT_WT_OB))
        pivot_pct    = float(conf_cfg.get("pivot_proximity_pct", _DEFAULT_PIVOT_PCT))
        min_strength = int(conf_cfg.get("min_strength", _DEFAULT_MIN_STRENGTH))
        div_min_bars = int(conf_cfg.get("div_min_bars", _DEFAULT_DIV_MIN_BARS))

        if df_15m is None or len(df_15m) < max(lookback_bars + 5, 50):
            return results

        # ── Расчёт индикаторов ────────────────────────────────────────────
        _factor = 1.0
        if cfg is not None and hasattr(cfg, "get"):
            _factor = float(cfg.get("analysis.indicators.trend.factor", 1.0))
        df = calculate_wt(df_15m, n1=10, n2=21)
        df = calculate_trend(df, atr_period=43, factor=_factor)

        # Исключаем открытую (незакрытую) свечу из lookback — lookahead bias
        window = df.iloc[-lookback_bars - 1:-1].reset_index(drop=True)
        current_price = float(df["close"].iloc[-1])
        if current_price <= 0:
            return results

        # ── Дневные пивоты из кеша ────────────────────────────────────────
        daily_pivots = pivot_cache.get(f"{symbol}_1D") or {}

        wt_min = float(window["wt1"].min())
        wt_max = float(window["wt1"].max())
        wt_current = float(window["wt1"].iloc[-1])

        trend_series = window["trend"].values

        # ── LONG сетап ────────────────────────────────────────────────────
        score_long = 0
        factors_long: List[str] = []
        data_long: Dict[str, Any] = {}

        # 1L. WT в OS зоне (<-60) в окне, сейчас не в OB (сигнал не устарел)
        if wt_min < wt_os_thr and wt_current < wt_ob_thr:
            score_long += _SCORE_WT_ZONE
            factors_long.append("WT_OS")
            data_long["wt_min"] = round(wt_min, 1)

        # 2L. TSL пересечение UP (-1 → 1)
        tsl_cross_up = any(
            trend_series[i] == -1 and trend_series[i + 1] == 1
            for i in range(len(trend_series) - 1)
        )
        if tsl_cross_up:
            score_long += _SCORE_TSL_CROSS
            factors_long.append("TSL_CROSS_UP")

        # 2bL. WT cross UP (wt1 пересёк wt2 снизу вверх) в закрытых барах
        if "wt2" in window.columns:
            wt1_arr = window["wt1"].values
            wt2_arr = window["wt2"].values
            wt_cross_up = any(
                wt1_arr[i] <= wt2_arr[i] and wt1_arr[i + 1] > wt2_arr[i + 1]
                for i in range(len(wt1_arr) - 1)
            )
            if wt_cross_up:
                score_long += _SCORE_WT_CROSS
                factors_long.append("WT_CROSS_UP")

        # 3L. Цена у поддержки (S1/S2/PP дневной или недельный)
        pivot_hit_l, pivot_desc_l = _check_near_support(
            window, daily_pivots, pivot_cache, symbol, pivot_pct
        )
        if pivot_hit_l:
            score_long += _SCORE_NEAR_PIVOT
            factors_long.append("NEAR_SUPPORT")
            data_long["pivot_hit"] = pivot_desc_l

        # 4L. Бычья дивергенция WT (price LL, wt HL)
        div_bull, div_bull_desc = _check_bullish_divergence_wt(window, div_min_bars)
        if div_bull:
            score_long += _SCORE_DIVERGENCE
            factors_long.append("WT_DIVERGENCE")
            data_long["div_desc"] = div_bull_desc

        # 5L. Текущая цена выше дневного PP
        daily_pp = daily_pivots.get("PP") or 0.0
        if daily_pp > 0 and current_price > daily_pp:
            score_long += _SCORE_PP_CONFIRM
            factors_long.append("ABOVE_PP")
            data_long["daily_pp"] = round(daily_pp, 8)

        # WT_CROSS_UP обязателен — без подтверждённого кросса сигнал не выдаём
        if score_long >= min_strength and "WT_CROSS_UP" in factors_long:
            sig = _make_signal(
                symbol, SignalDirection.LONG, score_long, factors_long, data_long,
                lookback_bars, current_price
            )
            logger.info("[confluence] %s: LONG score=%d %s", symbol, score_long, factors_long)
            results.append(sig)
        elif score_long >= min_strength:
            logger.debug("[confluence] %s: LONG score=%d пропущен — нет WT_CROSS_UP", symbol, score_long)

        # ── SHORT сетап ───────────────────────────────────────────────────
        score_short = 0
        factors_short: List[str] = []
        data_short: Dict[str, Any] = {}

        # 1S. WT в OB зоне (>+60) в окне, сейчас не в OS (сигнал не устарел)
        if wt_max > wt_ob_thr and wt_current > wt_os_thr:
            score_short += _SCORE_WT_ZONE
            factors_short.append("WT_OB")
            data_short["wt_max"] = round(wt_max, 1)

        # 2S. TSL пересечение DOWN (1 → -1)
        tsl_cross_down = any(
            trend_series[i] == 1 and trend_series[i + 1] == -1
            for i in range(len(trend_series) - 1)
        )
        if tsl_cross_down:
            score_short += _SCORE_TSL_CROSS
            factors_short.append("TSL_CROSS_DOWN")

        # 2bS. WT cross DOWN (wt1 пересёк wt2 сверху вниз) в закрытых барах
        if "wt2" in window.columns:
            wt1_arr = window["wt1"].values
            wt2_arr = window["wt2"].values
            wt_cross_down = any(
                wt1_arr[i] >= wt2_arr[i] and wt1_arr[i + 1] < wt2_arr[i + 1]
                for i in range(len(wt1_arr) - 1)
            )
            if wt_cross_down:
                score_short += _SCORE_WT_CROSS
                factors_short.append("WT_CROSS_DOWN")

        # 3S. Цена у сопротивления (R1/R2/PP дневной или недельный)
        pivot_hit_s, pivot_desc_s = _check_near_resistance(
            window, daily_pivots, pivot_cache, symbol, pivot_pct
        )
        if pivot_hit_s:
            score_short += _SCORE_NEAR_PIVOT
            factors_short.append("NEAR_RESISTANCE")
            data_short["pivot_hit"] = pivot_desc_s

        # 4S. Медвежья дивергенция WT (price HH, wt LH)
        div_bear, div_bear_desc = _check_bearish_divergence_wt(window, div_min_bars)
        if div_bear:
            score_short += _SCORE_DIVERGENCE
            factors_short.append("WT_DIVERGENCE")
            data_short["div_desc"] = div_bear_desc

        # 5S. Текущая цена ниже дневного PP
        if daily_pp > 0 and current_price < daily_pp:
            score_short += _SCORE_PP_CONFIRM
            factors_short.append("BELOW_PP")
            data_short["daily_pp"] = round(daily_pp, 8)

        # WT_CROSS_DOWN обязателен — без подтверждённого кросса сигнал не выдаём
        if score_short >= min_strength and "WT_CROSS_DOWN" in factors_short:
            sig = _make_signal(
                symbol, SignalDirection.SHORT, score_short, factors_short, data_short,
                lookback_bars, current_price
            )
            logger.info("[confluence] %s: SHORT score=%d %s", symbol, score_short, factors_short)
            results.append(sig)
        elif score_short >= min_strength:
            logger.debug("[confluence] %s: SHORT score=%d пропущен — нет WT_CROSS_DOWN", symbol, score_short)

        if not results:
            logger.debug(
                "[confluence] %s: нет сигнала (long=%d short=%d)",
                symbol, score_long, score_short
            )

    except Exception:
        logger.exception("[confluence] Ошибка scan_confluence для %s", symbol)

    return results


# ── Вспомогательные функции ───────────────────────────────────────────────────

def _make_signal(
    symbol: str,
    direction: SignalDirection,
    score: int,
    factors: List[str],
    factor_data: Dict[str, Any],
    lookback_bars: int,
    current_price: float,
) -> SignalData:
    dir_str = "LONG ↑" if direction == SignalDirection.LONG else "SHORT ↓"
    desc = f"Конфлюэнция {dir_str} ({'|'.join(factors)})"
    interpretation = f"score={score}/100 — {len(factors)} из 5 условий: {', '.join(factors)}"
    return SignalData(
        symbol=symbol,
        signal_type=SignalType.CONFLUENCE,
        direction=direction,
        strength=min(score, 100),
        confidence=round(score / 100.0, 2),
        timestamp=datetime.now(),
        data={
            "score": score,
            "factors": factors,
            **factor_data,
            "lookback_bars": lookback_bars,
            "current_price": current_price,
            "timeframe": "15m",
        },
        timeframe="15m",
        description=desc,
        interpretation=interpretation,
    )


def _check_near_support(
    window: pd.DataFrame,
    daily_pivots: Dict,
    pivot_cache: Dict,
    symbol: str,
    proximity_pct: float = _DEFAULT_PIVOT_PCT,
) -> Tuple[bool, str]:
    """
    Цена (low) была у поддержки S1/S2/PP в окне.
    Fallback: недельные пивоты.
    """
    pivots = daily_pivots or pivot_cache.get(f"{symbol}_1W") or {}
    if not pivots:
        return False, ""

    lows = window["low"].values
    for level in ("S1", "S2", "PP"):
        pv = pivots.get(level) or 0.0
        if pv <= 0:
            continue
        for price in lows:
            if abs(price - pv) / pv * 100 <= proximity_pct:
                return True, f"1D_{level}={round(pv, 8)}"

    return False, ""


def _check_near_resistance(
    window: pd.DataFrame,
    daily_pivots: Dict,
    pivot_cache: Dict,
    symbol: str,
    proximity_pct: float = _DEFAULT_PIVOT_PCT,
) -> Tuple[bool, str]:
    """
    Цена (high) была у сопротивления R1/R2/PP в окне.
    Fallback: недельные пивоты.
    """
    pivots = daily_pivots or pivot_cache.get(f"{symbol}_1W") or {}
    if not pivots:
        return False, ""

    highs = window["high"].values
    for level in ("R1", "R2", "PP"):
        pv = pivots.get(level) or 0.0
        if pv <= 0:
            continue
        for price in highs:
            if abs(price - pv) / pv * 100 <= proximity_pct:
                return True, f"1D_{level}={round(pv, 8)}"

    return False, ""


def _check_bullish_divergence_wt(
    window: pd.DataFrame,
    div_min_bars: int = _DEFAULT_DIV_MIN_BARS,
) -> Tuple[bool, str]:
    """
    Бычья дивергенция WT в окне: price LL, wt1 HL.
    Ищем два трога wt1 (локальных минимума) где wt1[i2] > wt1[i1] и low[i2] < low[i1].
    """
    wt1 = window["wt1"].values
    lows = window["low"].values
    n = len(wt1)

    if n < div_min_bars * 2 + 1:
        return False, ""

    troughs = [
        i for i in range(1, n - 1)
        if wt1[i] < wt1[i - 1] and wt1[i] < wt1[i + 1] and wt1[i] < -30
    ]

    if len(troughs) < 2:
        return False, ""

    for j in range(1, len(troughs)):
        i1, i2 = troughs[j - 1], troughs[j]
        if i2 - i1 < div_min_bars:
            continue
        if lows[i2] < lows[i1] and wt1[i2] > wt1[i1]:
            desc = (
                f"price_low: {round(lows[i1], 6)}→{round(lows[i2], 6)}, "
                f"wt: {round(wt1[i1], 1)}→{round(wt1[i2], 1)}"
            )
            return True, desc

    return False, ""


def _check_bearish_divergence_wt(
    window: pd.DataFrame,
    div_min_bars: int = _DEFAULT_DIV_MIN_BARS,
) -> Tuple[bool, str]:
    """
    Медвежья дивергенция WT в окне: price HH, wt1 LH.
    Ищем два пика wt1 (локальных максимума) где wt1[i2] < wt1[i1] и high[i2] > high[i1].
    """
    wt1 = window["wt1"].values
    highs = window["high"].values
    n = len(wt1)

    if n < div_min_bars * 2 + 1:
        return False, ""

    peaks = [
        i for i in range(1, n - 1)
        if wt1[i] > wt1[i - 1] and wt1[i] > wt1[i + 1] and wt1[i] > 30
    ]

    if len(peaks) < 2:
        return False, ""

    for j in range(1, len(peaks)):
        i1, i2 = peaks[j - 1], peaks[j]
        if i2 - i1 < div_min_bars:
            continue
        if highs[i2] > highs[i1] and wt1[i2] < wt1[i1]:
            desc = (
                f"price_high: {round(highs[i1], 6)}→{round(highs[i2], 6)}, "
                f"wt: {round(wt1[i1], 1)}→{round(wt1[i2], 1)}"
            )
            return True, desc

    return False, ""


def confluence_message(symbol: str, sig: "SignalData") -> str:
    """Форматирует TG-сообщение для confluence сигнала (LONG и SHORT)."""
    from core.message_builder import tv_link
    data = sig.data or {}
    factors = data.get("factors", [])
    score = data.get("score", 0)
    price = data.get("current_price", 0)

    is_long = sig.direction == SignalDirection.LONG
    dir_label = "LONG ↑" if is_long else "SHORT ↓"
    dir_icon  = "🟢" if is_long else "🔴"

    emoji_map = {
        "WT_OS":            "🌊 WT OS",
        "WT_OB":            "🌊 WT OB",
        "TSL_CROSS_UP":     "📈 TSL↑",
        "TSL_CROSS_DOWN":   "📉 TSL↓",
        "WT_CROSS_UP":      "⚡ WT✕↑",
        "WT_CROSS_DOWN":    "⚡ WT✕↓",
        "NEAR_SUPPORT":     "🎯 Поддержка",
        "NEAR_RESISTANCE":  "🎯 Сопротивление",
        "WT_DIVERGENCE":    "🔄 Дивер",
        "ABOVE_PP":         "✅ >PP",
        "BELOW_PP":         "❌ <PP",
    }
    factor_str = "  ·  ".join(emoji_map.get(f, f) for f in factors)
    strength_emoji = "🔥🔥🔥" if score >= 80 else "🔥🔥" if score >= 60 else "🔥"

    tf = data.get("timeframe", "15m")
    lines = [
        "\n",
        f"🔗 <b>CONFLUENCE · {tv_link(symbol)} · {dir_icon} {dir_label}</b>",
        f"⏱ <code>{tf}</code>  {strength_emoji} <b>{score}/100</b>  ({len(factors)}/5 факторов)",
        "",
        f"  {factor_str}",
    ]

    pivot_hit = data.get("pivot_hit", "")
    div_desc  = data.get("div_desc", "")
    if pivot_hit:
        lines.append(f"  📍 {pivot_hit}")
    if div_desc:
        arrow = "↗️" if is_long else "↘️"
        lines.append(f"  {arrow} {div_desc}")
    if price:
        try:
            from core.intelligence_formatter import _fmt_price
            lines += ["", f"  Цена: <code>{_fmt_price(float(price))}</code>"]
        except Exception:
            lines += ["", f"  Цена: {price}"]

    lines += ["", f"⏰ {datetime.now().strftime('%d.%m %H:%M')}", "\n"]
    return "\n".join(lines)
