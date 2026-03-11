"""
Market Regime Classifier — Этап 4.
Классифицирует рыночный режим на основе ADX, ATR-percentile и наклона EMA.

Режимы:
  TREND_UP   — восходящий тренд (ADX высокий, EMA растёт)
  TREND_DOWN — нисходящий тренд (ADX высокий, EMA падает)
  RANGE      — боковик (ADX низкий, ATR в норме)
  HIGH_VOL   — высокая волатильность (ATR резко выше медианы)

Использование:
    from core.market_regime import MarketRegimeClassifier

    clf = MarketRegimeClassifier()
    regime = clf.classify_from_ohlcv(ohlcv)   # ohlcv: list of [ts, o, h, l, c, v]
    # → "TREND_UP" | "TREND_DOWN" | "RANGE" | "HIGH_VOL" | None
"""
import logging
from typing import List, Optional
from core.indicators import compute_atr_values, compute_ema_values

logger = logging.getLogger(__name__)

# Пороги
_ADX_TREND_THRESHOLD = 25.0     # ADX > 25 → тренд
_ATR_HIGH_VOL_MULT = 1.8        # ATR > 1.8 × median → HIGH_VOL
_EMA_SLOPE_MIN = 0.0002         # минимальный наклон EMA (доля от цены) для определения направления
_MIN_CANDLES = 30               # минимум свечей для надёжного расчёта


# Используем единые функции из core/indicators.py
_ema = compute_ema_values
_atr = compute_atr_values


def _adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Optional[float]:
    """ADX — последнее значение."""
    n = len(closes)
    if n < period * 2:
        return None
    dm_plus, dm_minus, tr = [], [], []
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        dm_plus.append(max(up, 0) if up > down else 0)
        dm_minus.append(max(down, 0) if down > up else 0)
        h, l, pc = highs[i], lows[i], closes[i - 1]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))

    def smooth(lst, p):
        s = [sum(lst[:p])]
        for v in lst[p:]:
            s.append(s[-1] - s[-1] / p + v)
        return s

    str_ = smooth(tr, period)
    sdm_plus = smooth(dm_plus, period)
    sdm_minus = smooth(dm_minus, period)

    di_plus = [100 * p / t if t else 0 for p, t in zip(sdm_plus, str_)]
    di_minus = [100 * m / t if t else 0 for m, t in zip(sdm_minus, str_)]
    dx = [
        100 * abs(p - m) / (p + m) if (p + m) else 0
        for p, m in zip(di_plus, di_minus)
    ]
    if len(dx) < period:
        return None
    adx_vals = [sum(dx[:period]) / period]
    for v in dx[period:]:
        adx_vals.append((adx_vals[-1] * (period - 1) + v) / period)
    return adx_vals[-1] if adx_vals else None


class MarketRegimeClassifier:
    """
    Классифицирует рыночный режим по последним свечам OHLCV.

    Parameters
    ----------
    adx_period : int  — период ADX (default 14)
    ema_period : int  — период EMA для определения наклона (default 20)
    atr_period : int  — период ATR (default 14)
    """

    def __init__(
        self,
        adx_period: int = 14,
        ema_period: int = 20,
        atr_period: int = 14,
    ):
        self.adx_period = adx_period
        self.ema_period = ema_period
        self.atr_period = atr_period

    def classify_from_ohlcv(self, ohlcv: List) -> Optional[str]:
        """
        Parameters
        ----------
        ohlcv : list of [timestamp, open, high, low, close, volume]
                (формат ccxt / BingX)

        Returns
        -------
        str | None — "TREND_UP", "TREND_DOWN", "RANGE", "HIGH_VOL", или None при ошибке
        """
        try:
            if not ohlcv or len(ohlcv) < _MIN_CANDLES:
                logger.debug("MarketRegimeClassifier: недостаточно свечей (%d)", len(ohlcv) if ohlcv else 0)
                return None

            highs = [float(c[2]) for c in ohlcv]
            lows = [float(c[3]) for c in ohlcv]
            closes = [float(c[4]) for c in ohlcv]

            # ATR
            atr_vals = _atr(highs, lows, closes, self.atr_period)
            if not atr_vals:
                return None
            last_atr = atr_vals[-1]
            median_atr = sorted(atr_vals)[len(atr_vals) // 2]

            # HIGH_VOL — проверяем первой (перекрывает всё)
            if median_atr > 0 and last_atr > _ATR_HIGH_VOL_MULT * median_atr:
                return "HIGH_VOL"

            # ADX
            adx_val = _adx(highs, lows, closes, self.adx_period)

            # EMA slope — наклон последних N точек относительно цены
            ema_vals = _ema(closes, self.ema_period)
            ema_slope: Optional[float] = None
            if len(ema_vals) >= 5:
                ema_slope = (ema_vals[-1] - ema_vals[-5]) / (closes[-1] if closes[-1] else 1)

            # Классификация
            if adx_val is not None and adx_val >= _ADX_TREND_THRESHOLD:
                if ema_slope is not None and ema_slope >= _EMA_SLOPE_MIN:
                    return "TREND_UP"
                if ema_slope is not None and ema_slope <= -_EMA_SLOPE_MIN:
                    return "TREND_DOWN"
                # ADX высокий, но наклон неопределён — смотрим по DM
                return "TREND_UP" if (ema_slope or 0) >= 0 else "TREND_DOWN"

            return "RANGE"

        except Exception as e:
            logger.exception("MarketRegimeClassifier: ошибка — %s", e)
            return None
