"""
Market Regime Classifier — Этап 4 / ARCH-09п6.

Два режима работы:
  classify_from_ohlcv()       — старый метод (ADX + EMA slope), обратная совместимость
  classify_from_dataframes()  — новый MTF метод (trend + WT + ATR, ARCH-09п6)

Новый метод (ARCH-09п6):
  ATR > 1.8×median → HIGH_VOL (перекрывает всё)
  MTF alignment (trend 15m == 1h [== 4h]) + |WT1-WT2| > 10 → TREND_UP/DOWN
  MTF alignment + |WT1-WT2| ≤ 10 → RANGE (тренд затухает)
  MTF конфликт → RANGE

Старый метод (обратная совместимость):
  ADX > 25 + EMA slope → TREND_UP/TREND_DOWN
  ADX ≤ 25 → RANGE
  ATR > 1.8×median → HIGH_VOL

Использование:
    from core.market_regime import MarketRegimeClassifier

    clf = MarketRegimeClassifier()
    regime = clf.classify_from_ohlcv(ohlcv)          # ohlcv: list of [ts, o, h, l, c, v]
    regime = clf.classify_from_dataframes(df_15m, df_1h)  # DataFrame с trend/wt1/wt2
    # → "TREND_UP" | "TREND_DOWN" | "RANGE" | "HIGH_VOL" | None
"""
import logging
from typing import List, Optional
import pandas as pd
from core.indicators import compute_atr_values, compute_ema_values, compute_adx

logger = logging.getLogger(__name__)

# Пороги
_ADX_TREND_THRESHOLD = 25.0     # ADX > 25 → тренд
_ATR_HIGH_VOL_MULT = 1.8        # ATR > 1.8 × median → HIGH_VOL
_EMA_SLOPE_MIN = 0.0002         # минимальный наклон EMA (доля от цены) для определения направления
_MIN_CANDLES = 30               # минимум свечей для надёжного расчёта


# Используем единые функции из core/indicators.py
_ema = compute_ema_values
_atr = compute_atr_values
_adx = compute_adx  # ADX централизован в indicators.py


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
            if ohlcv is None:
                logger.debug("MarketRegimeClassifier: ohlcv is None")
                return None
            # DataFrame → list
            if hasattr(ohlcv, "values"):
                ohlcv = ohlcv.values.tolist()
            if len(ohlcv) < _MIN_CANDLES:
                logger.debug("MarketRegimeClassifier: недостаточно свечей (%d)", len(ohlcv))
                return None

            highs = [float(c[2]) for c in ohlcv]
            lows = [float(c[3]) for c in ohlcv]
            closes = [float(c[4]) for c in ohlcv]

            # ATR
            atr_vals = _atr(highs, lows, closes, self.atr_period)
            if not atr_vals:
                return None
            median_atr = sorted(atr_vals)[len(atr_vals) // 2]

            # HIGH_VOL — проверяем первой (перекрывает всё)
            # Fix 1 (DEV-88): avg последних 3 ATR вместо single bar, порог 1.5× вместо 1.8×
            recent_atr_avg = sum(atr_vals[-3:]) / min(3, len(atr_vals))
            if median_atr > 0 and recent_atr_avg > 1.5 * median_atr:
                return "HIGH_VOL"

            # Fix 3 (DEV-88): spike guard — бар с range > 3× median за последние 5 баров
            ranges = [h - l for h, l in zip(highs, lows)]
            median_range = sorted(ranges)[len(ranges) // 2]
            if median_range > 0 and any(r > 3 * median_range for r in ranges[-5:]):
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

    def classify_from_dataframes(
        self,
        df_15m: "pd.DataFrame",
        df_1h: "Optional[pd.DataFrame]" = None,
        df_4h: "Optional[pd.DataFrame]" = None,
    ) -> Optional[str]:
        """
        MTF-режим (ARCH-09п6): trend + WT + ATR.

        Требует DataFrame с колонками после calculate_trend() и calculate_wt():
          trend  — 1 (UP) / -1 (DOWN)
          wt1, wt2  — WaveTrend осцилляторы (опционально)
          high, low, close  — для ATR

        Parameters
        ----------
        df_15m : основной TF (обязательный)
        df_1h  : старший TF (опциональный, улучшает точность)
        df_4h  : ещё старший TF (опциональный)
        """
        try:
            if df_15m is None or len(df_15m) < _MIN_CANDLES:
                return None

            # HIGH_VOL — ATR по 15m (перекрывает всё)
            if "high" in df_15m.columns and "low" in df_15m.columns and "close" in df_15m.columns:
                highs  = df_15m["high"].tolist()
                lows   = df_15m["low"].tolist()
                closes = df_15m["close"].tolist()
                atr_vals = _atr(highs, lows, closes, self.atr_period)
                if atr_vals:
                    last_atr   = atr_vals[-1]
                    median_atr = sorted(atr_vals)[len(atr_vals) // 2]
                    if median_atr > 0 and last_atr > _ATR_HIGH_VOL_MULT * median_atr:
                        return "HIGH_VOL"

            # MTF trend alignment
            def _trend_val(df: "pd.DataFrame") -> Optional[int]:
                if df is not None and "trend" in df.columns and len(df) > 0:
                    try:
                        return int(df["trend"].iloc[-1])
                    except Exception:
                        pass
                return None

            t_15 = _trend_val(df_15m)
            t_1h = _trend_val(df_1h)
            t_4h = _trend_val(df_4h)

            # Собираем только доступные TF
            available = [t for t in (t_15, t_1h, t_4h) if t is not None]
            if not available:
                return "RANGE"

            # MTF aligned: все совпадают
            mtf_aligned = len(set(available)) == 1
            trend_dir   = available[0]  # направление при выравнивании

            # WT divergence |WT1 - WT2| из df_15m
            wt_diff = 0.0
            if "wt1" in df_15m.columns and "wt2" in df_15m.columns:
                try:
                    wt_diff = abs(float(df_15m["wt1"].iloc[-1]) - float(df_15m["wt2"].iloc[-1]))
                except Exception:
                    pass

            if mtf_aligned:
                # Тренд подтверждён на всех доступных TF
                if wt_diff > 10:
                    return "TREND_UP" if trend_dir == 1 else "TREND_DOWN"
                # wt_diff ≤ 10 — тренд затухает или флэт
                return "RANGE"

            return "RANGE"

        except Exception as e:
            logger.exception("MarketRegimeClassifier.classify_from_dataframes: %s", e)
            return None

    def classify_v2(
        self,
        df_15m: "pd.DataFrame",
        df_1h:  "Optional[pd.DataFrame]" = None,
    ) -> str:
        """
        DEV-90 / ARCH-59: Гибридный классификатор v2 (3 слоя).

        Слой 1 — Spike Guard: spike за последние 5 баров → HIGH_VOL (быстрый override).
        Слой 2 — Структурный режим на 1h: HH/HL паттерн через detect_structural_regime().
        Слой 3 — MTF подтверждение: classify_from_dataframes(df_15m, df_1h).
                  Если Слой 2 и Слой 3 согласованы → возвращаем результат.
                  Конфликт → RANGE (консервативно).

        Shadow mode: не заменяет текущий classify_from_ohlcv/classify_from_dataframes.
        Управляется через config: market_regime.use_v2 (default: false).
        """
        try:
            from core.signals.structure_detector import detect_structural_regime

            # Слой 1: Spike Guard по df_15m
            if df_15m is not None and len(df_15m) >= _MIN_CANDLES:
                if "high" in df_15m.columns and "low" in df_15m.columns:
                    ranges = (df_15m["high"] - df_15m["low"]).tolist()
                    if ranges:
                        med_range = sorted(ranges)[len(ranges) // 2]
                        if med_range > 0 and any(r > 3 * med_range for r in ranges[-5:]):
                            return "HIGH_VOL"

            # Слой 2: Структурный режим по 1h DF
            struct_regime = None
            if df_1h is not None and len(df_1h) >= _MIN_CANDLES:
                struct_regime = detect_structural_regime(df_1h, period=5)

            # Слой 3: MTF подтверждение
            mtf_regime = self.classify_from_dataframes(df_15m, df_1h)

            # Решение
            if struct_regime is None:
                # Недостаточно swing points — доверяем MTF
                return mtf_regime or "RANGE"

            if mtf_regime in ("TREND_UP", "TREND_DOWN", "RANGE"):
                # Согласованность: оба указывают на тренд или оба — RANGE
                if struct_regime == mtf_regime:
                    return struct_regime
                # Один тренд, другой RANGE → RANGE (консервативно)
                if "TREND" in struct_regime and "TREND" in (mtf_regime or ""):
                    # Оба тренд, но разные направления (редко) → RANGE
                    if struct_regime != mtf_regime:
                        return "RANGE"
                return "RANGE"

            # mtf_regime is None или HIGH_VOL
            if mtf_regime == "HIGH_VOL":
                return "HIGH_VOL"
            return struct_regime or "RANGE"

        except Exception as e:
            logger.warning("[classify_v2] error: %s", e)
            return "RANGE"
