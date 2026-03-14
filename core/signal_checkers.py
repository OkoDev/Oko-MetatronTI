"""
Проверки отдельных типов сигналов — чистые функции, не зависящие от класса.
Принимают (symbol, df) и возвращают List[SignalData].
"""
import logging
from datetime import datetime
from typing import List

import pandas as pd

from core.signal_models import SignalData, SignalDirection, SignalType

try:
    from core.config_loader import config as _cfg
except ImportError:
    _cfg = None

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
                timeframe="15m",
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

        cross_up = wt1_prev < wt2_prev and wt1_last > wt2_last
        cross_down = wt1_prev > wt2_prev and wt1_last < wt2_last

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

        if cross_up and wt1_last < os_:
            if wt1_1h is not None and wt1_1h > ob:
                logger.debug("[%s] WT CrossUp отклонён: 1h OB (wt1_1h=%.1f)", symbol, wt1_1h)
            else:
                logger.debug("[%s] WT CrossUp OS wt1=%.1f str=%d wt1_1h=%s", symbol, wt1_last, wt_strength, f"{wt1_1h:.1f}" if wt1_1h is not None else "N/A")
                signals.append(SignalData(
                    symbol=symbol, signal_type=SignalType.WT_SIGNAL, direction=SignalDirection.LONG,
                    strength=wt_strength, confidence=0.8, timestamp=datetime.now(),
                    data={"wt1": wt1_last, "wt2": wt2_last, "zone": "OS", "wt1_1h": wt1_1h}, timeframe="15m",
                ))
        elif cross_down and wt1_last > ob:
            if wt1_1h is not None and wt1_1h < os_:
                logger.debug("[%s] WT CrossDown отклонён: 1h OS (wt1_1h=%.1f)", symbol, wt1_1h)
            else:
                logger.debug("[%s] WT CrossDown OB wt1=%.1f str=%d wt1_1h=%s", symbol, wt1_last, wt_strength, f"{wt1_1h:.1f}" if wt1_1h is not None else "N/A")
                signals.append(SignalData(
                    symbol=symbol, signal_type=SignalType.WT_SIGNAL, direction=SignalDirection.SHORT,
                    strength=wt_strength, confidence=0.8, timestamp=datetime.now(),
                    data={"wt1": wt1_last, "wt2": wt2_last, "zone": "OB", "wt1_1h": wt1_1h}, timeframe="15m",
                ))
    except Exception:
        logger.exception("Ошибка проверки WT для %s", symbol)
    return signals


async def check_mtf_signals(
    symbol: str, df_1h: pd.DataFrame, df_15m: pd.DataFrame, df_3m: pd.DataFrame
) -> List[SignalData]:
    """Проверка мультитаймфреймовых сигналов."""
    signals = []
    try:
        if any(x is None for x in (df_1h, df_15m, df_3m)):
            return signals

        n1, n2, ob, os_ = _wt_params()
        atr_period, factor = _trend_params()
        df_1h_trend = calculate_trend(df_1h, atr_period=atr_period, factor=factor)
        trend_1h = df_1h_trend["trend"].iloc[-1] if "trend" in df_1h_trend.columns else 0

        df_15m_wt = calculate_wt(df_15m, n1=n1, n2=n2)
        if "wt1" not in df_15m_wt.columns or "wt2" not in df_15m_wt.columns:
            return signals

        wt1_15m, wt2_15m = df_15m_wt["wt1"].iloc[-1], df_15m_wt["wt2"].iloc[-1]
        df_3m_wt = calculate_wt(df_3m, n1=n1, n2=n2)
        if "wt1" not in df_3m_wt.columns:
            return signals

        wt1_3m = df_3m_wt["wt1"].iloc[-1]
        common = dict(symbol=symbol, signal_type=SignalType.MTF_SIGNAL, strength=85, confidence=0.9,
                      timestamp=datetime.now(), timeframe="MTF",
                      data={"trend_1h": trend_1h, "wt1_15m": wt1_15m, "wt2_15m": wt2_15m, "wt1_3m": wt1_3m})

        if trend_1h == 1 and wt1_15m > wt2_15m and wt1_3m < os_:
            signals.append(SignalData(direction=SignalDirection.LONG, **common))
        elif trend_1h == -1 and wt1_15m < wt2_15m and wt1_3m > ob:
            signals.append(SignalData(direction=SignalDirection.SHORT, **common))
    except Exception:
        logger.exception("Ошибка проверки MTF для %s", symbol)
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
            timeframe="15m",
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
