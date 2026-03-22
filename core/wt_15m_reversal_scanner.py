"""
WT 15m Reversal Scanner — детектор разворотного сетапа на 15m.

Ищет в окне lookback_bars (8 баров = 2 часа) совпадение условий:

  Обязательные gate (без них сигнала нет):
    - WT был в OS/OB зоне в окне
    - WT кросс (wt1 × wt2) — в зоне или вне
    - TSL пересечение с close confirmation

  Очки за качество:
    WT кросс в зоне OS/OB (идеально)      → +25
    WT кросс вне зоны (но WT был в OS/OB)  → +15
    TSL пересечение + close confirmation    → +25
    Цена коснулась пивота (≤0.15%)          → +25
    Дивергенция WT                          → +20

  Порог: strength ≥ 60. Минимум = TSL(25) + WT_CROSS(15|25) = 40|50 + ещё 1 фактор.

  MTF context (bias, тренд 1h, PP position) применяется СНАРУЖИ через
  _apply_mtf_context() с floor 0.75 для CONFLUENCE.

Функция синхронная — не делает API-запросов, только считает по готовым df.

Замена: core/confluence_scanner.py (scan_confluence). SignalType.CONFLUENCE сохранён
для обратной совместимости с БД и стратегиями.
"""
import logging
from datetime import datetime
from typing import List, Dict, Any, Tuple

import numpy as np
import pandas as pd

from core.dynamic_thresholds import compute_dynamic_thresholds, os_method_label
from core.entry_config import get_primary_entry_tf
from core.indicators import calculate_trend, calculate_wt
from core.pivot_calculator_fixed import PivotCalculatorFixed
from core.signal_models import SignalData, SignalType, SignalDirection

logger = logging.getLogger(__name__)

# ── Дефолты (перекрываются через config.yaml → analysis.confluence) ──────────
_DEFAULT_WT_OS = -60   # OS зона: wt1 < -60
_DEFAULT_WT_OB = 60    # OB зона: wt1 > +60
_DEFAULT_PIVOT_TOUCH_PCT = 0.15  # % расстояния для "коснулся пивота"
_DEFAULT_MIN_STRENGTH = 60
_DEFAULT_DIV_MIN_BARS = 5
_DEFAULT_LOOKBACK = 8   # 8 баров × 15м = 2 часа контекста

# Динамический OB/OS (эксперимент): mean ± k*std по последним N барам
_DEFAULT_DYN_OS_ENABLED = False  # выключен по умолчанию — явно включать в конфиге
_DEFAULT_DYN_OS_K = 0.8          # порог: mean - 0.8*std
_DEFAULT_DYN_OS_WINDOW = 50      # баров для расчёта mean/std

# Очки за каждое условие
_SCORE_WT_CROSS_IN_ZONE = 25        # WT кросс прямо в зоне OS/OB (идеальный вход)
_SCORE_WT_CROSS_OUT_ZONE = 15       # WT кросс вне зоны, но WT ранее был в OS/OB
_SCORE_TSL_CROSS = 25               # TSL пересечение с close confirmation
_SCORE_PIVOT_TOUCH = 25             # Цена коснулась/пробила пивот
_SCORE_DIVERGENCE = 20              # Дивергенция WT (регулярная)
_SCORE_HIDDEN_DIV = 15              # Скрытая дивергенция WT (продолжение тренда)
# ARCH-27: Бонус за кросс-TF конфлюэнцию пивотов (добавляется к PIVOT_TOUCH)
_SCORE_PIVOT_CONFLUENCE_1W_1D = 15  # 1W + 1D уровни совпали
_SCORE_PIVOT_CONFLUENCE_1M = 20     # 1M + 1W или 1M + 1D уровни совпали

# ARCH-27: singleton для вычисления конфлюэнций — не создаём каждый вызов
_pivot_calc = PivotCalculatorFixed()


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


def scan_wt_15m_reversal(
    symbol: str,
    df_15m: pd.DataFrame,
    df_1h: pd.DataFrame,
    pivot_cache: Dict[str, Any],
    lookback_bars: int = _DEFAULT_LOOKBACK,
    cfg=None,
    df_4h: pd.DataFrame = None,
) -> List[SignalData]:
    """
    Детектор разворотного сетапа на 15m. Возвращает список SignalData (обычно 0-2).

    Args:
        symbol:        торговая пара (напр. "BTC/USDT")
        df_15m:        OHLCV DataFrame 15m (>= lookback_bars + 5 строк)
        df_1h:         OHLCV DataFrame 1h — для 1h контекста (WT, тренд)
        pivot_cache:   bot.pivot_calculator.pivot_cache (dict ключ = f"{sym}_1D")
        lookback_bars: глубина поиска в барах 15m (8 баров = 2 часа)
        cfg:           объект конфига (ConfigLoader или dict) — читает analysis.confluence
        df_4h:         OHLCV DataFrame 4h — для 4h контекста (WT, тренд)
    """
    results: List[SignalData] = []

    try:
        conf_cfg = _get_cfg(cfg)
        if not conf_cfg.get("enabled", True):
            return results

        lookback_bars  = int(conf_cfg.get("lookback_bars", lookback_bars))
        wt_os_thr      = float(conf_cfg.get("wt_os_threshold", _DEFAULT_WT_OS))
        wt_ob_thr      = float(conf_cfg.get("wt_ob_threshold", _DEFAULT_WT_OB))
        pivot_touch    = float(conf_cfg.get("pivot_touch_pct", _DEFAULT_PIVOT_TOUCH_PCT))
        min_strength   = int(conf_cfg.get("min_strength", _DEFAULT_MIN_STRENGTH))
        div_min_bars   = int(conf_cfg.get("div_min_bars", _DEFAULT_DIV_MIN_BARS))
        dyn_os_enabled = bool(conf_cfg.get("dynamic_os_enabled", _DEFAULT_DYN_OS_ENABLED))
        dyn_os_k       = float(conf_cfg.get("dynamic_os_k", _DEFAULT_DYN_OS_K))
        dyn_os_window  = int(conf_cfg.get("dynamic_os_window", _DEFAULT_DYN_OS_WINDOW))

        if df_15m is None or len(df_15m) < max(lookback_bars + 5, 30):
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

        # ── Динамические пороги OS/OB (эксперимент) ───────────────────────
        # mean ± k*std по последним dyn_os_window барам (без открытой свечи)
        dyn_os_thr = wt_os_thr  # fallback к фиксированному
        dyn_ob_thr = wt_ob_thr
        _dyn_computed = False
        if dyn_os_enabled and "wt1" in df.columns:
            wt1_hist = df["wt1"].dropna().values
            dyn_os_thr, dyn_ob_thr, _dyn_computed = compute_dynamic_thresholds(
                wt1_hist, k=dyn_os_k, window=dyn_os_window,
                fixed_os=wt_os_thr, fixed_ob=wt_ob_thr,
            )
            if _dyn_computed:
                logger.debug(
                    "[wt_15m_rev] %s: dyn_os=%.1f dyn_ob=%.1f vs fixed=%.1f/%.1f",
                    symbol, dyn_os_thr, dyn_ob_thr, wt_os_thr, wt_ob_thr,
                )
            else:
                dyn_os_enabled = False  # недостаточно данных

        trend_series  = window["trend"].values
        trendup_arr   = window["trendup"].values
        trenddown_arr = window["trenddown"].values
        close_arr     = window["close"].values

        # ── Объединённые gate-флаги (fixed OR dynamic) ────────────────────
        wt_was_in_os_fixed = (wt_min < wt_os_thr)
        wt_was_in_ob_fixed = (wt_max > wt_ob_thr)
        wt_was_in_os_dyn   = dyn_os_enabled and (wt_min < dyn_os_thr)
        wt_was_in_ob_dyn   = dyn_os_enabled and (wt_max > dyn_ob_thr)

        # ── TSL CROSS (обязательный gate) ─────────────────────────────────
        # Ищем ПОСЛЕДНЕЕ пересечение TSL в окне с close confirmation
        last_tsl_cross = None  # "UP" | "DOWN" | None
        for i in range(1, len(trend_series)):
            prev_trend = trend_series[i - 1]
            curr_trend = trend_series[i]
            curr_close = close_arr[i]
            prev_trenddown = trenddown_arr[i - 1]
            prev_trendup = trendup_arr[i - 1]
            if prev_trend == -1 and curr_trend == 1 and not np.isnan(prev_trenddown):
                if curr_close > prev_trenddown:
                    last_tsl_cross = "UP"
            elif prev_trend == 1 and curr_trend == -1 and not np.isnan(prev_trendup):
                if curr_close < prev_trendup:
                    last_tsl_cross = "DOWN"

        # ── WT CROSS (обязательный gate) ──────────────────────────────────
        # Определяем: кросс в зоне OS/OB (идеально) или вне зоны
        last_wt_cross = None       # "UP" | "DOWN" | None
        wt_cross_in_zone = False   # кросс произошёл прямо в зоне (fixed OR dynamic)?
        if "wt2" in window.columns:
            wt1_arr = window["wt1"].values
            wt2_arr = window["wt2"].values
            for i in range(len(wt1_arr) - 1):
                # UP cross: wt1 пересекает wt2 снизу вверх
                if wt1_arr[i] <= wt2_arr[i] and wt1_arr[i + 1] > wt2_arr[i + 1]:
                    last_wt_cross = "UP"
                    wt_cross_in_zone = (
                        (wt1_arr[i] < wt_os_thr) or
                        (dyn_os_enabled and wt1_arr[i] < dyn_os_thr)
                    )
                # DOWN cross: wt1 пересекает wt2 сверху вниз
                elif wt1_arr[i] >= wt2_arr[i] and wt1_arr[i + 1] < wt2_arr[i + 1]:
                    last_wt_cross = "DOWN"
                    wt_cross_in_zone = (
                        (wt1_arr[i] > wt_ob_thr) or
                        (dyn_os_enabled and wt1_arr[i] > dyn_ob_thr)
                    )

        # ── WT в зоне OS/OB (fixed OR dynamic) ───────────────────────────
        wt_was_in_os = wt_was_in_os_fixed or wt_was_in_os_dyn
        wt_was_in_ob = wt_was_in_ob_fixed or wt_was_in_ob_dyn

        # ── ARCH-26: 4h WT gate — WT momentum на старшем ТФ ──────────────
        # wt1 > wt2 на 4h = бычий тренд, иначе медвежий (не ATR, WT momentum)
        _4h_gate_enabled = bool(conf_cfg.get("4h_gate_enabled", True))
        _4h_dir: str | None = None
        _4h_wt1: float | None = None
        _4h_zone: str = ""
        if df_4h is not None and len(df_4h) >= 20:
            try:
                _df4h_calc = calculate_wt(df_4h, n1=10, n2=21)
                _4h_wt1 = round(float(_df4h_calc["wt1"].iloc[-2]), 1)
                _4h_wt2 = round(float(_df4h_calc["wt2"].iloc[-2]), 1)
                _4h_dir = "UP" if _4h_wt1 > _4h_wt2 else "DOWN"
                _4h_zone = ("OS" if _4h_wt1 < _DEFAULT_WT_OS
                            else "OB" if _4h_wt1 > _DEFAULT_WT_OB
                            else "N")
                logger.debug("[wt_15m_rev] %s: 4h WT=%s dir=%s zone=%s",
                             symbol, _4h_wt1, _4h_dir, _4h_zone)
            except Exception:
                pass

        # ── LONG сетап ────────────────────────────────────────────────────
        # Gates: WT был в OS + WT кросс UP + TSL кросс UP
        # ARCH-26: дополнительно — 4h WT momentum не должен быть DOWN
        _long_4h_blocked = _4h_gate_enabled and _4h_dir == "DOWN"
        if _long_4h_blocked:
            logger.debug("[wt_15m_rev] %s: LONG заблокирован gate 4h DOWN (wt=%s)", symbol, _4h_wt1)
        if wt_was_in_os and last_wt_cross == "UP" and last_tsl_cross == "UP" and not _long_4h_blocked:
            score_long = 0
            factors_long: List[str] = []
            data_long: Dict[str, Any] = {}

            # TSL cross (обязателен, всегда +25)
            score_long += _SCORE_TSL_CROSS
            factors_long.append("TSL_CROSS_UP")

            # WT cross: в зоне OS (+25) или вне зоны (+15)
            if wt_cross_in_zone:
                score_long += _SCORE_WT_CROSS_IN_ZONE
                factors_long.append("WT_CROSS_IN_OS")
                data_long["wt_cross_quality"] = "in_zone"
            else:
                score_long += _SCORE_WT_CROSS_OUT_ZONE
                factors_long.append("WT_CROSS_UP")
                data_long["wt_cross_quality"] = "out_of_zone"
            data_long["wt_min"] = round(wt_min, 1)
            # Какой метод определения OS сработал (shadow аналитика)
            data_long["os_method"] = os_method_label(wt_was_in_os_fixed, wt_was_in_os_dyn, _dyn_computed)
            if _dyn_computed:
                data_long["dyn_os_thr"] = round(dyn_os_thr, 1)

            # Цена коснулась пивота (support)
            pivot_hit, pivot_desc = _check_pivot_touch_support(
                window, daily_pivots, pivot_cache, symbol, pivot_touch
            )
            if pivot_hit:
                score_long += _SCORE_PIVOT_TOUCH
                factors_long.append("PIVOT_TOUCH")
                data_long["pivot_hit"] = pivot_desc
            # ARCH-27: бонус за кросс-TF конфлюэнцию (1W+1D или 1M+...)
            _conf_bonus, _conf_label = _check_pivot_confluence_at_price(
                current_price, symbol, daily_pivots, pivot_cache, pivot_touch
            )
            if _conf_label:
                score_long += _conf_bonus
                factors_long.append("PIVOT_CONFLUENCE")
                data_long["pivot_confluence"] = _conf_label
            # Ближайшие уровни всех ТФ (для отображения в сообщении)
            data_long["nearby_pivots"] = _nearby_pivot_labels(
                current_price, symbol, daily_pivots, pivot_cache
            )

            # Дивергенция WT (бычья регулярная: price LL + wt HL)
            div_bull, div_desc = _check_bullish_divergence_wt(window, div_min_bars)
            if div_bull:
                score_long += _SCORE_DIVERGENCE
                factors_long.append("WT_DIVERGENCE")
                data_long["div_desc"] = div_desc
                data_long["div_type"] = "regular_bull"
            else:
                # Скрытая бычья (price HL + wt LL): продолжение восходящего тренда
                div_hidden, div_desc = _check_hidden_bullish_divergence_wt(window, div_min_bars)
                if div_hidden:
                    score_long += _SCORE_HIDDEN_DIV
                    factors_long.append("WT_HIDDEN_DIV")
                    data_long["div_desc"] = div_desc
                    data_long["div_type"] = "hidden_bull"

            # ARCH-26: 4h WT контекст (всегда пишем если данные есть)
            if _4h_wt1 is not None:
                data_long["mtf_4h_trend"] = _4h_dir
                data_long["mtf_4h_wt"]    = _4h_wt1
                data_long["mtf_4h_zone"]  = _4h_zone

            if score_long >= min_strength:
                sig = _make_signal(
                    symbol, SignalDirection.LONG, score_long, factors_long,
                    data_long, lookback_bars, current_price
                )
                logger.info("[wt_15m_rev] %s: LONG score=%d %s", symbol, score_long, factors_long)
                results.append(sig)
            else:
                logger.debug("[wt_15m_rev] %s: LONG score=%d < %d", symbol, score_long, min_strength)

        # ── SHORT сетап ───────────────────────────────────────────────────
        # Gates: WT был в OB + WT кросс DOWN + TSL кросс DOWN
        # ARCH-26: дополнительно — 4h WT momentum не должен быть UP
        _short_4h_blocked = _4h_gate_enabled and _4h_dir == "UP"
        if _short_4h_blocked:
            logger.debug("[wt_15m_rev] %s: SHORT заблокирован gate 4h UP (wt=%s)", symbol, _4h_wt1)
        if wt_was_in_ob and last_wt_cross == "DOWN" and last_tsl_cross == "DOWN" and not _short_4h_blocked:
            score_short = 0
            factors_short: List[str] = []
            data_short: Dict[str, Any] = {}

            # TSL cross (обязателен, всегда +25)
            score_short += _SCORE_TSL_CROSS
            factors_short.append("TSL_CROSS_DOWN")

            # WT cross: в зоне OB (+25) или вне зоны (+15)
            if wt_cross_in_zone:
                score_short += _SCORE_WT_CROSS_IN_ZONE
                factors_short.append("WT_CROSS_IN_OB")
                data_short["wt_cross_quality"] = "in_zone"
            else:
                score_short += _SCORE_WT_CROSS_OUT_ZONE
                factors_short.append("WT_CROSS_DOWN")
                data_short["wt_cross_quality"] = "out_of_zone"
            data_short["wt_max"] = round(wt_max, 1)
            # Какой метод определения OB сработал (shadow аналитика)
            data_short["ob_method"] = os_method_label(wt_was_in_ob_fixed, wt_was_in_ob_dyn, _dyn_computed)
            if _dyn_computed:
                data_short["dyn_ob_thr"] = round(dyn_ob_thr, 1)

            # Цена коснулась пивота (resistance)
            pivot_hit, pivot_desc = _check_pivot_touch_resistance(
                window, daily_pivots, pivot_cache, symbol, pivot_touch
            )
            if pivot_hit:
                score_short += _SCORE_PIVOT_TOUCH
                factors_short.append("PIVOT_TOUCH")
                data_short["pivot_hit"] = pivot_desc
            # ARCH-27: бонус за кросс-TF конфлюэнцию (1W+1D или 1M+...)
            _conf_bonus, _conf_label = _check_pivot_confluence_at_price(
                current_price, symbol, daily_pivots, pivot_cache, pivot_touch
            )
            if _conf_label:
                score_short += _conf_bonus
                factors_short.append("PIVOT_CONFLUENCE")
                data_short["pivot_confluence"] = _conf_label
            # Ближайшие уровни всех ТФ (для отображения в сообщении)
            data_short["nearby_pivots"] = _nearby_pivot_labels(
                current_price, symbol, daily_pivots, pivot_cache
            )

            # Дивергенция WT (медвежья регулярная: price HH + wt LH)
            div_bear, div_desc = _check_bearish_divergence_wt(window, div_min_bars)
            if div_bear:
                score_short += _SCORE_DIVERGENCE
                factors_short.append("WT_DIVERGENCE")
                data_short["div_desc"] = div_desc
                data_short["div_type"] = "regular_bear"
            else:
                # Скрытая медвежья (price LH + wt HH): продолжение нисходящего тренда
                div_hidden, div_desc = _check_hidden_bearish_divergence_wt(window, div_min_bars)
                if div_hidden:
                    score_short += _SCORE_HIDDEN_DIV
                    factors_short.append("WT_HIDDEN_DIV")
                    data_short["div_desc"] = div_desc
                    data_short["div_type"] = "hidden_bear"

            # ARCH-26: 4h WT контекст (всегда пишем если данные есть)
            if _4h_wt1 is not None:
                data_short["mtf_4h_trend"] = _4h_dir
                data_short["mtf_4h_wt"]    = _4h_wt1
                data_short["mtf_4h_zone"]  = _4h_zone

            if score_short >= min_strength:
                sig = _make_signal(
                    symbol, SignalDirection.SHORT, score_short, factors_short,
                    data_short, lookback_bars, current_price
                )
                logger.info("[wt_15m_rev] %s: SHORT score=%d %s", symbol, score_short, factors_short)
                results.append(sig)
            else:
                logger.debug("[wt_15m_rev] %s: SHORT score=%d < %d", symbol, score_short, min_strength)

        # ── 1h контекст (только если есть сигнал — без лишних вычислений) ──
        if results and df_1h is not None and len(df_1h) >= 20:
            try:
                # DEV-30: WT momentum вместо ATR trailing stop для 1h контекста
                _df1h = calculate_wt(df_1h, n1=10, n2=21)
                _1h_wt1   = round(float(_df1h["wt1"].iloc[-2]), 1)
                _1h_wt2   = round(float(_df1h["wt2"].iloc[-2]), 1)
                _1h_dir   = "UP" if _1h_wt1 > _1h_wt2 else "DOWN"
                for sig in results:
                    sig.data["mtf_1h_trend"] = _1h_dir
                    sig.data["mtf_1h_wt"]    = _1h_wt1
            except Exception:
                pass

        if not results:
            logger.debug(
                "[wt_15m_rev] %s: нет сигнала (wt_os=%s wt_ob=%s wt_cross=%s tsl_cross=%s)",
                symbol, wt_was_in_os, wt_was_in_ob, last_wt_cross, last_tsl_cross
            )

    except Exception:
        logger.exception("[wt_15m_rev] Ошибка scan_wt_15m_reversal для %s", symbol)

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
    desc = f"Reversal 15m {dir_str} ({'|'.join(factors)})"
    # Максимум 5 факторов: TSL_CROSS + WT_CROSS + PIVOT_TOUCH + WT_DIVERGENCE + WT_HIDDEN_DIV
    interpretation = f"score={score}/100 — {len(factors)} из 5 факторов: {', '.join(factors)}"
    return SignalData(
        symbol=symbol,
        signal_type=SignalType.CONFLUENCE,  # сохранено для совместимости с БД
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
            "timeframe": get_primary_entry_tf(),
        },
        timeframe=get_primary_entry_tf(),
        description=desc,
        interpretation=interpretation,
    )


def _check_pivot_confluence_at_price(
    price: float,
    symbol: str,
    daily_pivots: Dict,
    pivot_cache: Dict,
    touch_pct: float = _DEFAULT_PIVOT_TOUCH_PCT,
) -> Tuple[int, str]:
    """
    ARCH-27: Проверяет, находится ли цена вблизи кросс-TF конфлюэнции пивотов.

    Приоритет: 1M+1W > 1M+1D > 1W+1D (по силе конфлюэнции).

    Returns:
        (bonus_score, label) — бонус к score и метка вида "1W+1D:S1≈S2".
        (0, "") если конфлюэнции рядом нет.
    """
    try:
        pivots_data: Dict = {}
        if daily_pivots:
            pivots_data["1D"] = daily_pivots
        w = pivot_cache.get(f"{symbol}_1W") or {}
        if w:
            pivots_data["1W"] = w
        m = pivot_cache.get(f"{symbol}_1M") or {}
        if m:
            pivots_data["1M"] = m

        if len(pivots_data) < 2:
            return 0, ""

        confluences = _pivot_calc._find_all_confluences(pivots_data)
        if not confluences:
            return 0, ""

        # Допуск поиска конфлюэнции: шире чем touch_pct (конфлюэнция — зона, не точка)
        search_pct = max(touch_pct + 0.5, 1.0)

        best_bonus = 0
        best_label = ""

        for c in confluences:
            tf_a = c["tf_a"]
            tf_b = c["tf_b"]
            # Пропускаем same-TF (1D+1D_prev, 1W+1W_prev) — не кросс-TF
            if {tf_a, tf_b} in ({"1D", "1D_prev"}, {"1W", "1W_prev"}):
                continue

            avg_price = (c["price_a"] + c["price_b"]) / 2.0
            if avg_price <= 0:
                continue
            dist_pct = abs(price - avg_price) / avg_price * 100
            if dist_pct > search_pct:
                continue

            # Бонус зависит от TF-пары
            involves_monthly = "1M" in (tf_a, tf_b)
            bonus = _SCORE_PIVOT_CONFLUENCE_1M if involves_monthly else _SCORE_PIVOT_CONFLUENCE_1W_1D

            if bonus > best_bonus:
                best_bonus = bonus
                la = c.get("level_a", tf_a)
                lb = c.get("level_b", tf_b)
                best_label = f"{tf_a}_{la}+{tf_b}_{lb}≈{round(avg_price, 6)}"

        return best_bonus, best_label

    except Exception:
        return 0, ""


def _pivot_sources(symbol: str, daily_pivots: Dict, pivot_cache: Dict) -> list:
    """Возвращает список (tf_label, pivots_dict) в порядке приоритета: 1D → 1W → 1M."""
    sources = []
    if daily_pivots:
        sources.append(("1D", daily_pivots))
    w = pivot_cache.get(f"{symbol}_1W") or {}
    if w:
        sources.append(("1W", w))
    m = pivot_cache.get(f"{symbol}_1M") or {}
    if m:
        sources.append(("1M", m))
    return sources


def _nearby_pivot_labels(
    price: float,
    symbol: str,
    daily_pivots: Dict,
    pivot_cache: Dict,
    nearby_pct: float = 1.5,
) -> str:
    """Возвращает строку ближайших пивот-уровней всех ТФ в радиусе nearby_pct% от цены.
    Пример: '1D_S3=6.033  1W_PP=6.705  1M_R1=7.278'
    """
    labels = []
    for tf, pv_dict in _pivot_sources(symbol, daily_pivots, pivot_cache):
        for lvl in ("S3", "S2", "S1", "PP", "R1", "R2", "R3"):
            pv = pv_dict.get(lvl) or 0.0
            if pv <= 0:
                continue
            if abs(price - pv) / pv * 100 <= nearby_pct:
                labels.append(f"{tf}_{lvl}={round(pv, 6)}")
    return "  ".join(labels)


def _check_pivot_touch_support(
    window: pd.DataFrame,
    daily_pivots: Dict,
    pivot_cache: Dict,
    symbol: str,
    touch_pct: float = _DEFAULT_PIVOT_TOUCH_PCT,
) -> Tuple[bool, str]:
    """Цена (low) коснулась/пробила поддержку S1/S2/S3/PP — проверяет 1D → 1W → 1M."""
    lows = window["low"].values
    for tf, pivots in _pivot_sources(symbol, daily_pivots, pivot_cache):
        for level in ("S1", "S2", "S3", "PP"):
            pv = pivots.get(level) or 0.0
            if pv <= 0:
                continue
            for price in lows:
                if price <= pv and abs(price - pv) / pv * 100 <= touch_pct + 0.5:
                    return True, f"{tf}_{level}={round(pv, 8)}"
                if abs(price - pv) / pv * 100 <= touch_pct:
                    return True, f"{tf}_{level}={round(pv, 8)}"
    return False, ""


def _check_pivot_touch_resistance(
    window: pd.DataFrame,
    daily_pivots: Dict,
    pivot_cache: Dict,
    symbol: str,
    touch_pct: float = _DEFAULT_PIVOT_TOUCH_PCT,
) -> Tuple[bool, str]:
    """Цена (high) коснулась/пробила сопротивление R1/R2/R3/PP — проверяет 1D → 1W → 1M."""
    highs = window["high"].values
    for tf, pivots in _pivot_sources(symbol, daily_pivots, pivot_cache):
        for level in ("R1", "R2", "R3", "PP"):
            pv = pivots.get(level) or 0.0
            if pv <= 0:
                continue
            for price in highs:
                if price >= pv and abs(price - pv) / pv * 100 <= touch_pct + 0.5:
                    return True, f"{tf}_{level}={round(pv, 8)}"
                if abs(price - pv) / pv * 100 <= touch_pct:
                    return True, f"{tf}_{level}={round(pv, 8)}"
    return False, ""


def _check_bullish_divergence_wt(
    window: pd.DataFrame,
    div_min_bars: int = _DEFAULT_DIV_MIN_BARS,
) -> Tuple[bool, str]:
    """Бычья дивергенция WT: price LL, wt1 HL."""
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
    """Медвежья дивергенция WT: price HH, wt1 LH."""
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


def _check_hidden_bullish_divergence_wt(
    window: pd.DataFrame,
    div_min_bars: int = _DEFAULT_DIV_MIN_BARS,
) -> Tuple[bool, str]:
    """Скрытая бычья дивергенция WT: price HL (higher low), wt1 LL (lower low).
    Сигнал продолжения восходящего тренда — откат завершён."""
    wt1 = window["wt1"].values
    lows = window["low"].values
    n = len(wt1)

    if n < div_min_bars * 2 + 1:
        return False, ""

    troughs = [
        i for i in range(1, n - 1)
        if wt1[i] < wt1[i - 1] and wt1[i] < wt1[i + 1] and wt1[i] < -20
    ]

    if len(troughs) < 2:
        return False, ""

    for j in range(1, len(troughs)):
        i1, i2 = troughs[j - 1], troughs[j]
        if i2 - i1 < div_min_bars:
            continue
        # price HL (лоу выше) + wt1 LL (wt ниже) = скрытая бычья
        if lows[i2] > lows[i1] and wt1[i2] < wt1[i1]:
            desc = (
                f"price_low: {round(lows[i1], 6)}→{round(lows[i2], 6)}, "
                f"wt: {round(wt1[i1], 1)}→{round(wt1[i2], 1)}"
            )
            return True, desc

    return False, ""


def _check_hidden_bearish_divergence_wt(
    window: pd.DataFrame,
    div_min_bars: int = _DEFAULT_DIV_MIN_BARS,
) -> Tuple[bool, str]:
    """Скрытая медвежья дивергенция WT: price LH (lower high), wt1 HH (higher high).
    Сигнал продолжения нисходящего тренда — отскок завершён."""
    wt1 = window["wt1"].values
    highs = window["high"].values
    n = len(wt1)

    if n < div_min_bars * 2 + 1:
        return False, ""

    peaks = [
        i for i in range(1, n - 1)
        if wt1[i] > wt1[i - 1] and wt1[i] > wt1[i + 1] and wt1[i] > 20
    ]

    if len(peaks) < 2:
        return False, ""

    for j in range(1, len(peaks)):
        i1, i2 = peaks[j - 1], peaks[j]
        if i2 - i1 < div_min_bars:
            continue
        # price LH (хай ниже) + wt1 HH (wt выше) = скрытая медвежья
        if highs[i2] < highs[i1] and wt1[i2] > wt1[i1]:
            desc = (
                f"price_high: {round(highs[i1], 6)}→{round(highs[i2], 6)}, "
                f"wt: {round(wt1[i1], 1)}→{round(wt1[i2], 1)}"
            )
            return True, desc

    return False, ""


def reversal_message(symbol: str, sig: "SignalData") -> str:
    """Форматирует TG-сообщение для reversal сигнала. Thin wrapper над format_signal_message."""
    from core.intelligence_formatter import format_signal_message
    return format_signal_message(symbol, sig, signal_type="reversal")
