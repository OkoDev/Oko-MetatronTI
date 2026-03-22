"""
Проверки отдельных типов сигналов — чистые функции, не зависящие от класса.
Принимают (symbol, df) и возвращают List[SignalData].
"""
import logging
from datetime import datetime
from typing import List

import pandas as pd

from core.entry_config import get_primary_entry_tf
from core.signal_models import SignalData, SignalDirection, SignalType

try:
    from core.config_loader import config as _cfg
except ImportError:
    _cfg = None

try:
    from core.dynamic_thresholds import compute_dynamic_thresholds, os_method_label as _os_method_label
    _DYN_THRESH_AVAILABLE = True
except ImportError:
    _DYN_THRESH_AVAILABLE = False

# DEV-17: per-symbol Isolation Forest кеш (обучается лениво при первом вызове)
_anomaly_models: dict = {}

try:
    from core.anomaly_model import AnomalyModel as _AnomalyModel
    _IF_AVAILABLE = True
except ImportError:
    _IF_AVAILABLE = False
    _AnomalyModel = None

try:
    from core.indicators import (
        calculate_trend, calculate_wt,
        compute_volume_ratio as _compute_volume_ratio,
    )
except ImportError:
    import logging as _log
    _log.getLogger(__name__).error(
        "КРИТИЧЕСКАЯ ОШИБКА: core.indicators недоступен — используются заглушки! "
        "Тренд и TSL будут некорректны!"
    )
    _compute_volume_ratio = None

    def calculate_trend(df, atr_period=43, factor=1.0):  # noqa: stub
        df = df.copy(); df["trend"] = 1; return df

    def calculate_wt(df, n1=10, n2=21):  # noqa: stub
        df = df.copy(); df["wt1"] = 0; df["wt2"] = 0; return df

logger = logging.getLogger(__name__)


def _wt_params() -> tuple:
    """Возвращает (n1, n2, ob_threshold, os_threshold) из конфига или дефолты."""
    if _cfg is None:
        return 10, 21, 60, -60
    n1  = _cfg.get("analysis.indicators.wavetrend.n1", 10)
    n2  = _cfg.get("analysis.indicators.wavetrend.n2", 21)
    ob  = _cfg.get("analysis.indicators.wavetrend.ob_threshold", 60)
    os_ = _cfg.get("analysis.indicators.wavetrend.os_threshold", -60)
    return int(n1), int(n2), float(ob), float(os_)


def _trend_params() -> tuple:
    """Возвращает (atr_period, factor) из конфига или дефолты."""
    if _cfg is None:
        return 43, 1.0
    atr = _cfg.get("analysis.indicators.trend.atr_period", 43)
    fac = _cfg.get("analysis.indicators.trend.factor", 1.0)
    return int(atr), float(fac)


def _anomaly_params() -> tuple:
    """Возвращает (min_bars, ma_period, ratio_thr, str_trend, str_counter) из конфига."""
    if _cfg is None:
        return 20, 20, 3.0, 12, 8
    min_bars  = _cfg.get("detectors.anomaly.min_bars", 20)
    ma_period = _cfg.get("detectors.anomaly.volume_ma_period", 20)
    ratio_thr = _cfg.get("detectors.anomaly.volume_ratio_threshold", 3.0)
    str_trend = _cfg.get("detectors.anomaly.strength_trend_multiplier", 12)
    str_ctr   = _cfg.get("detectors.anomaly.strength_counter_multiplier", 8)
    return int(min_bars), int(ma_period), float(ratio_thr), int(str_trend), int(str_ctr)


async def check_anomaly_signals(symbol: str, df: pd.DataFrame) -> List[SignalData]:
    """Проверка аномалий объема."""
    signals = []
    try:
        min_bars, ma_period, ratio_thr, str_trend, str_ctr = _anomaly_params()
        if df is None or len(df) < min_bars:
            return signals

        volume_current = df["volume"].iloc[-1]
        # Volume ratio — единый источник из indicators.py
        _vr = _compute_volume_ratio(df["volume"], period=ma_period) if _compute_volume_ratio else None
        if _vr is None:
            volume_mean = df["volume"].rolling(ma_period).mean().iloc[-1]
            _vr = volume_current / volume_mean if volume_mean > 0 else 1.0
        volume_mean = volume_current / _vr if _vr > 0 else 0
        volume_ratio = _vr

        # DEV-17: Isolation Forest — дополнительная проверка перед rule-based порогом
        # Если IF обучена и говорит "норма" → пропускаем даже если ratio_thr превышен
        _use_if = _IF_AVAILABLE and _cfg and _cfg.get("detectors.anomaly.use_isolation_forest", True)
        if _use_if:
            if symbol not in _anomaly_models:
                _anomaly_models[symbol] = _AnomalyModel()
            _am = _anomaly_models[symbol]
            if not _am.is_trained:
                _am.fit(df)  # ленивое обучение на первом вызове

        if volume_ratio > ratio_thr:
            price_change = (df["close"].iloc[-1] - df["close"].iloc[-2]) / df["close"].iloc[-2] * 100
            direction = SignalDirection.LONG if price_change > 0 else SignalDirection.SHORT
            # Адаптивный strength: объём по тренду = сильнее, против тренда = слабее
            try:
                atr_p, fac = _trend_params()
                df_t = calculate_trend(df, atr_period=atr_p, factor=fac)
                trend_val = df_t["trend"].iloc[-1]  # 1=UP, -1=DOWN
                trend_matches = (trend_val == 1 and direction == SignalDirection.LONG) or \
                                (trend_val == -1 and direction == SignalDirection.SHORT)
            except Exception:
                trend_matches = False
            if trend_matches:
                anom_strength = min(int(volume_ratio * str_trend), 100)
            else:
                anom_strength = min(int(volume_ratio * str_ctr), 80)

            # DEV-17: IF score → корректировка strength
            if _use_if and _am.is_trained:
                if_score = _am.score(df)
                if if_score is not None:
                    if_strength = _am.anomaly_strength(if_score)
                    # Блендинг: 60% rule-based + 40% IF
                    anom_strength = int(0.6 * anom_strength + 0.4 * if_strength)
                    anom_strength = max(0, min(100, anom_strength))
                    logger.debug("[%s] ANOMALY IF score=%.3f if_str=%d blended_str=%d",
                                 symbol, if_score, if_strength, anom_strength)

            logger.debug("[%s] ANOMALY %s vol_ratio=%.1f price_chg=%.2f%% str=%d trend_match=%s",
                         symbol, direction.value, volume_ratio, price_change, anom_strength, trend_matches)
            signals.append(SignalData(
                symbol=symbol,
                signal_type=SignalType.ANOMALY,
                direction=direction,
                strength=anom_strength,
                confidence=0.7,
                timestamp=datetime.now(),
                data={"volume_ratio": volume_ratio, "price_change": price_change,
                      "volume_current": volume_current, "volume_mean": volume_mean,
                      "trend_match": trend_matches},
                timeframe=get_primary_entry_tf(_cfg),
            ))
    except Exception:
        logger.exception("Ошибка проверки аномалий для %s", symbol)
    return signals


async def check_wt_signals(symbol: str, df: pd.DataFrame, df_1h: pd.DataFrame = None) -> List[SignalData]:
    """Проверка Wavetrend сигналов (15m) с опциональным фильтром по 1h."""
    signals = []
    try:
        if df is None or len(df) < 50:
            return signals

        n1, n2, ob, os_ = _wt_params()
        df_wt = calculate_wt(df, n1=n1, n2=n2)
        if "wt1" not in df_wt.columns or "wt2" not in df_wt.columns:
            return signals

        wt1_last, wt2_last = df_wt["wt1"].iloc[-1], df_wt["wt2"].iloc[-1]
        wt1_prev, wt2_prev = df_wt["wt1"].iloc[-2], df_wt["wt2"].iloc[-2]

        cross_up = wt1_prev < wt2_prev and wt1_last > wt2_last and (wt1_last - wt2_last) >= 3
        cross_down = wt1_prev > wt2_prev and wt1_last < wt2_last and (wt2_last - wt1_last) >= 3

        # WT 1h для фильтра: отсекаем сигналы против старшего ТФ
        wt1_1h = None
        if df_1h is not None and len(df_1h) >= 50:
            try:
                df_1h_wt = calculate_wt(df_1h, n1=n1, n2=n2)
                if "wt1" in df_1h_wt.columns:
                    wt1_1h = float(df_1h_wt["wt1"].iloc[-1])
            except Exception:
                pass

        # Адаптивный strength по глубине зоны WT
        wt1_abs = abs(wt1_last)
        if wt1_abs >= 80:
            wt_strength = 85
        elif wt1_abs >= 70:
            wt_strength = 75
        elif wt1_abs >= 60:
            wt_strength = 65
        else:
            wt_strength = 55

        # Бонус за импульс: большой разрыв WT1-WT2 = сильный разворот (данные: WR 60% vs 37% при gap>=10)
        gap = abs(wt1_last - wt2_last)
        if gap >= 10:
            wt_strength = min(90, wt_strength + 5)

        # ── DEV-23: Shadow-mode динамических порогов (не меняет gate) ─────────
        _dyn_os = os_
        _dyn_ob = ob
        _dyn_computed = False
        if _DYN_THRESH_AVAILABLE and _cfg is not None:
            _dyn_enabled = _cfg.get("analysis.confluence.dynamic_os_enabled", False)
            if _dyn_enabled and "wt1" in df_wt.columns:
                _dyn_k  = float(_cfg.get("analysis.confluence.dyn_os_k", 0.8))
                _dyn_win = int(_cfg.get("analysis.confluence.dyn_os_window", 50))
                _wt1_hist = df_wt["wt1"].dropna().values
                _dyn_os, _dyn_ob, _dyn_computed = compute_dynamic_thresholds(
                    _wt1_hist, k=_dyn_k, window=_dyn_win, fixed_os=os_, fixed_ob=ob,
                )
                if _dyn_computed:
                    logger.debug(
                        "[wt_signal] %s: shadow dyn_os=%.1f dyn_ob=%.1f vs fixed %.1f/%.1f",
                        symbol, _dyn_os, _dyn_ob, os_, ob,
                    )

        if cross_up and wt1_last < os_:
            if wt1_1h is not None and wt1_1h > ob:
                logger.debug("[%s] WT CrossUp отклонён: 1h OB (wt1_1h=%.1f)", symbol, wt1_1h)
            else:
                _fixed_trig = wt1_last < os_
                _dyn_trig = _dyn_computed and wt1_last < _dyn_os
                _os_m = _os_method_label(_fixed_trig, _dyn_trig, _dyn_computed) if _DYN_THRESH_AVAILABLE else "fixed"
                logger.debug("[%s] WT CrossUp OS wt1=%.1f str=%d wt1_1h=%s os_method=%s", symbol, wt1_last, wt_strength, f"{wt1_1h:.1f}" if wt1_1h is not None else "N/A", _os_m)
                signals.append(SignalData(
                    symbol=symbol, signal_type=SignalType.WT_SIGNAL, direction=SignalDirection.LONG,
                    strength=wt_strength, confidence=0.8, timestamp=datetime.now(),
                    data={"wt1": wt1_last, "wt2": wt2_last, "zone": "OS", "wt1_1h": wt1_1h, "os_method": _os_m}, timeframe=get_primary_entry_tf(_cfg),
                ))
        elif cross_down and wt1_last > ob:
            if wt1_1h is not None and wt1_1h < os_:
                logger.debug("[%s] WT CrossDown отклонён: 1h OS (wt1_1h=%.1f)", symbol, wt1_1h)
            else:
                _fixed_trig = wt1_last > ob
                _dyn_trig = _dyn_computed and wt1_last > _dyn_ob
                _ob_m = _os_method_label(_fixed_trig, _dyn_trig, _dyn_computed) if _DYN_THRESH_AVAILABLE else "fixed"
                logger.debug("[%s] WT CrossDown OB wt1=%.1f str=%d wt1_1h=%s ob_method=%s", symbol, wt1_last, wt_strength, f"{wt1_1h:.1f}" if wt1_1h is not None else "N/A", _ob_m)
                signals.append(SignalData(
                    symbol=symbol, signal_type=SignalType.WT_SIGNAL, direction=SignalDirection.SHORT,
                    strength=wt_strength, confidence=0.8, timestamp=datetime.now(),
                    data={"wt1": wt1_last, "wt2": wt2_last, "zone": "OB", "wt1_1h": wt1_1h, "os_method": _ob_m}, timeframe=get_primary_entry_tf(_cfg),
                ))
    except Exception:
        logger.exception("Ошибка проверки WT для %s", symbol)
    return signals


# ── WT тип B: вспомогательные функции ────────────────────────────────────────

def _wt_b_bullish_div(wt1_vals: list, os_: float) -> dict:
    """Bullish дивергенция для типа B: min второй половины > min первой (оба в OS)."""
    half = len(wt1_vals) // 2
    if half < 5:
        return {"found": False}
    os1 = [v for v in wt1_vals[:half] if v < os_]
    os2 = [v for v in wt1_vals[half:] if v < os_]
    if not os1 or not os2:
        return {"found": False}
    min1, min2 = min(os1), min(os2)
    if min2 <= min1:
        return {"found": False}
    return {"found": True, "div_strength": round(min2 - min1, 2), "depth": round(min1, 2)}


def _wt_b_bearish_div(wt1_vals: list, ob: float) -> dict:
    """Bearish дивергенция для типа B: max второй половины < max первой (оба в OB)."""
    half = len(wt1_vals) // 2
    if half < 5:
        return {"found": False}
    ob1 = [v for v in wt1_vals[:half] if v > ob]
    ob2 = [v for v in wt1_vals[half:] if v > ob]
    if not ob1 or not ob2:
        return {"found": False}
    max1, max2 = max(ob1), max(ob2)
    if max2 >= max1:
        return {"found": False}
    return {"found": True, "div_strength": round(max1 - max2, 2), "depth": round(max1, 2)}


def _wt_b_strength(div_strength: float, depth: float, direction: str) -> int:
    """Strength для типа B по данным бэктеста (103 пары, WR=85%)."""
    if div_strength >= 10:
        base = 90   # WR=100% в бэктесте
    elif div_strength >= 6:
        base = 80   # WR=82%
    else:
        base = 70   # WR=73%
    # Бонус за глубину лоу (только LONG)
    if direction == "LONG" and depth < -70:
        base = min(95, base + 5)
    return base


async def check_wt_b_signals(symbol: str, df_1h: pd.DataFrame) -> list:
    """
    WT тип B (1h): crossover В OS/OB зоне + дивергенция WT1.

    Фильтры из бэктеста (103 пары, 180 дней):
      - Adaptive OS/OB: p10/p90 от серии wt1
      - div_strength: 3-20 (разрыв лоу/хай в OS/OB зоне)
      - LOOKBACK: 35 баров
    Результат: n=59, WR=84.9%, avgRet=+4.82%.
    """
    import numpy as np
    signals = []
    try:
        if df_1h is None or len(df_1h) < 80:
            return signals

        n1, n2   = 10, 21
        LOOKBACK = 35
        DIV_MIN  = 3.0
        DIV_MAX  = 20.0

        df_wt = calculate_wt(df_1h, n1=n1, n2=n2)
        if "wt1" not in df_wt.columns:
            return signals

        wt1_arr = df_wt["wt1"].values
        wt2_arr = df_wt["wt2"].values

        # Адаптивные пороги p10/p90
        os_ = float(np.percentile(wt1_arr, 10))
        ob  = float(np.percentile(wt1_arr, 90))

        wt1_last, wt2_last = wt1_arr[-1], wt2_arr[-1]
        wt1_prev, wt2_prev = wt1_arr[-2], wt2_arr[-2]

        cross_up   = wt1_prev < wt2_prev and wt1_last > wt2_last
        cross_down = wt1_prev > wt2_prev and wt1_last < wt2_last
        if not cross_up and not cross_down:
            return signals

        window = list(wt1_arr[-(LOOKBACK + 1):-1])

        if cross_up and wt1_last < os_:
            d = _wt_b_bullish_div(window, os_)
            if d["found"] and DIV_MIN <= d["div_strength"] <= DIV_MAX:
                strength = _wt_b_strength(d["div_strength"], d["depth"], "LONG")
                logger.info("[%s] WT-B LONG wt1=%.1f os=%.1f div_str=%.1f str=%d",
                            symbol, wt1_last, os_, d["div_strength"], strength)
                signals.append(SignalData(
                    symbol=symbol, signal_type=SignalType.WT_B_SIGNAL,
                    direction=SignalDirection.LONG,
                    strength=strength, confidence=0.88,
                    timestamp=datetime.now(), timeframe="1h",
                    data={
                        "wt1": round(wt1_last, 2), "zone": "OS",
                        "div_strength": d["div_strength"], "depth": d["depth"],
                        "os_adaptive": round(os_, 1),
                    },
                ))

        if cross_down and wt1_last > ob:
            d = _wt_b_bearish_div(window, ob)
            if d["found"] and DIV_MIN <= d["div_strength"] <= DIV_MAX:
                strength = _wt_b_strength(d["div_strength"], d["depth"], "SHORT")
                logger.info("[%s] WT-B SHORT wt1=%.1f ob=%.1f div_str=%.1f str=%d",
                            symbol, wt1_last, ob, d["div_strength"], strength)
                signals.append(SignalData(
                    symbol=symbol, signal_type=SignalType.WT_B_SIGNAL,
                    direction=SignalDirection.SHORT,
                    strength=strength, confidence=0.88,
                    timestamp=datetime.now(), timeframe="1h",
                    data={
                        "wt1": round(wt1_last, 2), "zone": "OB",
                        "div_strength": d["div_strength"], "depth": d["depth"],
                        "ob_adaptive": round(ob, 1),
                    },
                ))
    except Exception:
        logger.exception("Ошибка check_wt_b_signals для %s", symbol)
    return signals



async def check_trend_signals(symbol: str, df: pd.DataFrame) -> List[SignalData]:
    """Проверка трендовых сигналов."""
    signals = []
    try:
        if df is None or len(df) < 50:
            return signals

        atr_period, factor = _trend_params()
        df_trend = calculate_trend(df, atr_period=atr_period, factor=factor)
        if "trend" not in df_trend.columns:
            return signals

        trend_current = df_trend["trend"].iloc[-1]
        trend_prev = df_trend["trend"].iloc[-2]

        if trend_current != trend_prev:
            direction = SignalDirection.LONG if trend_current == 1 else SignalDirection.SHORT
            logger.debug("[%s] TREND flip %s→%s", symbol, trend_prev, trend_current)
            signals.append(SignalData(
                symbol=symbol, signal_type=SignalType.TREND_SIGNAL, direction=direction,
                strength=60, confidence=0.7, timestamp=datetime.now(),
                data={"trend_current": trend_current, "trend_prev": trend_prev}, timeframe="1h",
            ))
    except Exception:
        logger.exception("Ошибка проверки тренда для %s", symbol)
    return signals


async def check_smc_signals(symbol: str, df: pd.DataFrame) -> List[SignalData]:
    """
    Проверка SMC-структуры (BOS / CHoCH) на 15m.

    BOS (Break of Structure) — подтверждение продолжения тренда, strength=65.
    CHoCH (Change of Character) — первый сигнал разворота, strength=55.
    BOS приоритетнее CHoCH (detect_structure возвращает BOS если оба найдены).
    """
    signals = []
    try:
        if df is None or len(df) < 30:
            return signals

        from core.structure_detector import detect_structure
        result = detect_structure(df)

        if result["signal"] is None:
            return signals

        direction = SignalDirection.LONG if result["signal"] == "LONG" else SignalDirection.SHORT
        stype = result["signal_type"]  # "BOS" or "CHOCH"
        struct_info = result["bos"] if stype == "BOS" else result["choch"]
        confidence = 0.75 if stype == "BOS" else 0.65

        logger.debug(
            "[%s] SMC %s %s level=%.6g str=%d",
            symbol, stype, direction.value,
            struct_info.get("level", 0), result["strength"],
        )
        signals.append(SignalData(
            symbol=symbol,
            signal_type=SignalType.SMC_STRUCTURE,
            direction=direction,
            strength=result["strength"],
            confidence=confidence,
            timestamp=datetime.now(),
            data={
                "smc_type": stype,                          # "BOS" | "CHOCH"
                "struct_type": struct_info.get("type", ""), # "BULLISH_BOS" etc.
                "level": struct_info.get("level", 0),       # пробитый уровень
                "current_price": struct_info.get("current_price", 0),
            },
            timeframe=get_primary_entry_tf(_cfg),
        ))
    except Exception:
        logger.exception("Ошибка проверки SMC для %s", symbol)
    return signals


async def check_mtf_bias_signal(
    symbol: str,
    data_collector,
    regime: str = None,
    cfg=None,
) -> List[SignalData]:
    """
    MTF Bias — автономный интерпретатор TF-alignment.
    Собирает MTF-снапшот через collect_mtf_data и передаёт в MTFInterpreter.
    """
    signals = []
    try:
        from core.mtf_checker import collect_mtf_data
        from core.mtf_interpreter import interpret

        snapshot = await collect_mtf_data(symbol, data_collector)
        if not snapshot:
            return signals

        sig = interpret(snapshot, regime=regime, cfg=cfg)
        if sig is not None:
            sig.symbol = symbol
            logger.info(
                "[mtf_bias] %s: %s score=%d bull=%d%% entry=%s senior=%d/3",
                symbol,
                sig.direction.value,
                sig.strength,
                sig.data.get("bull_pct", 0),
                sig.data.get("entry_tf"),
                sig.data.get("senior_matches", 0),
            )
            signals.append(sig)
    except Exception:
        logger.exception("[mtf_bias] Ошибка check_mtf_bias_signal для %s", symbol)
    return signals


async def check_divergence_signals(symbol: str, df: pd.DataFrame) -> List[SignalData]:
    """
    Обёртка DivergenceDetector → List[SignalData] (принимает готовый df).
    Используется в тестах и backtesting_engine (без внешнего data_collector).

    Порядок проверки: Regular Bullish → Regular Bearish → Hidden Bullish → Hidden Bearish.
    """
    signals = []
    try:
        if df is None or len(df) < 100:
            return signals

        from core.divergence_detector import DivergenceDetector
        from core.indicators import calculate_wt as _calc_wt

        det = DivergenceDetector()
        df_wt = _calc_wt(df.copy(), n1=10, n2=21)
        if "wt1" not in df_wt.columns:
            return signals

        checks = [
            (det.detect_regular_bullish(df_wt, "wt1"), "REGULAR_BULLISH", "LONG"),
            (det.detect_regular_bearish(df_wt, "wt1"), "REGULAR_BEARISH", "SHORT"),
            (det.detect_hidden_bullish(df_wt, "wt1"),  "HIDDEN_BULLISH",  "LONG"),
            (det.detect_hidden_bearish(df_wt, "wt1"),  "HIDDEN_BEARISH",  "SHORT"),
        ]
        for result, div_type, dir_str in checks:
            if not result:
                continue
            strength = int(det._calculate_strength(result, div_type))
            direction = SignalDirection.LONG if dir_str == "LONG" else SignalDirection.SHORT
            logger.debug("[%s] DIV %s str=%d", symbol, div_type, strength)
            signals.append(SignalData(
                symbol=symbol,
                signal_type=SignalType.DIVERGENCE,
                direction=direction,
                strength=strength,
                confidence=0.75,
                timestamp=datetime.now(),
                data={"type": div_type, "direction": dir_str, "details": result},
                timeframe=get_primary_entry_tf(_cfg),
            ))
            break  # один сигнал (наивысший приоритет)
    except Exception:
        logger.exception("Ошибка check_divergence_signals для %s", symbol)
    return signals


async def check_pivot_signals(
    symbol: str,
    df: pd.DataFrame,
    proximity_pct: float = 2.0,
) -> List[SignalData]:
    """
    Находит сигналы разворота у локальных max-High / min-Low (S/R из OHLCV).
    Простая обёртка для тестов и backtesting_engine (не требует pivot_calculator).

    Алгоритм: берёт max(high) и min(low) за последние 60 баров (без последних 5),
    проверяет что текущая цена в пределах proximity_pct% от уровня.
    """
    signals = []
    try:
        if df is None or len(df) < 30:
            return signals

        current_price = float(df["close"].iloc[-1])
        if current_price <= 0:
            return signals

        # Исторические бары — исключаем последние 5 (они ещё формируются)
        tail = min(len(df) - 5, 60)
        hist = df.iloc[-(tail + 5):-5]

        resistance = float(hist["high"].max())
        support    = float(hist["low"].min())

        # Цена у сопротивления → SHORT
        dist_res = abs(current_price - resistance) / resistance * 100
        if current_price < resistance and dist_res <= proximity_pct:
            strength = max(40, min(80, int((1 - dist_res / proximity_pct) * 40 + 40)))
            logger.debug("[%s] PIVOT SHORT near resistance=%.6g dist=%.2f%%", symbol, resistance, dist_res)
            signals.append(SignalData(
                symbol=symbol,
                signal_type=SignalType.PIVOT_REVERSAL,
                direction=SignalDirection.SHORT,
                strength=strength,
                confidence=0.65,
                timestamp=datetime.now(),
                data={"level": resistance, "pivot_type": "resistance", "distance_pct": dist_res},
                timeframe=get_primary_entry_tf(_cfg),
            ))

        # Цена у поддержки → LONG
        dist_sup = abs(current_price - support) / support * 100
        if current_price > support and dist_sup <= proximity_pct:
            strength = max(40, min(80, int((1 - dist_sup / proximity_pct) * 40 + 40)))
            logger.debug("[%s] PIVOT LONG near support=%.6g dist=%.2f%%", symbol, support, dist_sup)
            signals.append(SignalData(
                symbol=symbol,
                signal_type=SignalType.PIVOT_REVERSAL,
                direction=SignalDirection.LONG,
                strength=strength,
                confidence=0.65,
                timestamp=datetime.now(),
                data={"level": support, "pivot_type": "support", "distance_pct": dist_sup},
                timeframe=get_primary_entry_tf(_cfg),
            ))
    except Exception:
        logger.exception("Ошибка check_pivot_signals для %s", symbol)
    return signals
