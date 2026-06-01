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
    from core.indicators.market_regime import MarketRegimeClassifier

    clf = MarketRegimeClassifier()
    regime = clf.classify_from_ohlcv(ohlcv)          # ohlcv: list of [ts, o, h, l, c, v]
    regime = clf.classify_from_dataframes(df_15m, df_1h)  # DataFrame с trend/wt1/wt2
    # → "TREND_UP" | "TREND_DOWN" | "RANGE" | "HIGH_VOL" | None
"""
import logging
from typing import List, Optional
import pandas as pd
from core.indicators.indicators import compute_atr_values, compute_ema_values, compute_adx

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

    def classify_mode(
        self,
        df_4h: "pd.DataFrame",
        df_1h: "pd.DataFrame",
        df_15m: "Optional[pd.DataFrame]" = None,
    ) -> str:
        """
        DEV-137 (ARCH-68 Фаза 2): Reversal Mode Detector — shadow only.

        Returns
        -------
        "REVERSAL" — WT 4h в OB/OS + ADX 1h падает 3 бара + CHoCH на 1h или 15m
        "TREND"    — ADX 1h растёт + WT 4h вне OB/OS + нет CHoCH
        "UNCLEAR"  — всё остальное
        """
        try:
            # ── 1. WT 4h: зона OB/OS ──────────────────────────────────────────
            wt_extreme = False
            if (df_4h is not None
                    and "wt1" in df_4h.columns
                    and len(df_4h) > 0):
                wt1_4h = float(df_4h["wt1"].iloc[-1])
                wt_extreme = wt1_4h > 60 or wt1_4h < -60
            else:
                wt1_4h = 0.0

            # ── 2. ADX 1h: slope за последние 3 бара ─────────────────────────
            adx_declining = False
            adx_rising    = False
            if (df_1h is not None
                    and len(df_1h) >= self.adx_period * 2 + 2
                    and "high" in df_1h.columns):
                h1 = df_1h["high"].tolist()
                l1 = df_1h["low"].tolist()
                c1 = df_1h["close"].tolist()
                adx_vals = []
                for cut in [2, 1, 0]:
                    sl_h = h1[:-cut] if cut else h1
                    sl_l = l1[:-cut] if cut else l1
                    sl_c = c1[:-cut] if cut else c1
                    adx_vals.append(_adx(sl_h, sl_l, sl_c, self.adx_period))
                if all(v is not None for v in adx_vals):
                    adx_declining = adx_vals[0] > adx_vals[1] > adx_vals[2]
                    adx_rising    = adx_vals[0] < adx_vals[1] < adx_vals[2]

            # ── 3. CHoCH на 1h и/или 15m ─────────────────────────────────────
            choch_present = False
            try:
                from core.smc.structure import detect_structure
                for _df in (df_1h, df_15m):
                    if _df is not None and len(_df) >= 30:
                        sa = detect_structure(_df)
                        if sa.last_break is not None and sa.last_break.is_choch:
                            choch_present = True
                            break
            except Exception as _e:
                logger.debug("[classify_mode] CHoCH error: %s", _e)

            # ── Решение ──────────────────────────────────────────────────────
            logger.debug(
                "[classify_mode] wt_extreme=%s(wt1_4h=%.1f) adx_declining=%s choch=%s",
                wt_extreme, wt1_4h, adx_declining, choch_present,
            )
            # DEV-149: ослабляем до 2 из 3 — WT extreme + любой из (adx_declining, choch)
            _rev_score = int(wt_extreme) + int(adx_declining) + int(choch_present)
            if wt_extreme and _rev_score >= 2:
                return "REVERSAL"
            if adx_rising and not wt_extreme and not choch_present:
                return "TREND"
            return "UNCLEAR"

        except Exception as e:
            logger.warning("[classify_mode] error: %s", e)
            return "UNCLEAR"

    def classify_v2(
        self,
        df_15m: "pd.DataFrame",
        df_1h:  "Optional[pd.DataFrame]" = None,
        df_4h:  "Optional[pd.DataFrame]" = None,
    ) -> str:
        """
        ARCH-124 (02.06.2026): HTF-доминантный классификатор v2 (shadow).

        Корень мислейбла v1 (classify_from_dataframes): требует синхронности ВСЕХ
        TF (15m==1h==4h), иначе RANGE. Аудит 30.05 (спот-чек 18 сделок): 78%
        RANGE-сделок реально ТРЕНДИЛИ — 15m-шум рассинхронизирует с 4h → тренды
        сваливаются в RANGE → гейты на метке бесполезны.

        v2: 4h-supertrend = ГЛАВНЫЙ (fallback 1h если нет 4h). 15m/1h НЕ требуют
        синхронности и НЕ блокируют тренд. RANGE только если HTF-тренд реально
        затухает (WT-дивергенция мала И ADX слабый).

          Spike (15m, 5 баров) → HIGH_VOL (override)
          HTF trend=1 + (|WT1-WT2|>10 ИЛИ ADX>25) → TREND_UP
          HTF trend=-1 + сила                      → TREND_DOWN
          HTF тренд слабый (нет силы)              → RANGE

        Один калькулятор: trend/wt через те же calculate_trend/calculate_wt, что и
        весь проект (ARCH-118). Shadow mode: use_v2=false → НЕ влияет на торговлю,
        пишется в shadow-поле regime_v2 для сравнения с v1.
        """
        try:
            from core.indicators.indicators import calculate_trend, calculate_wt

            # Слой 1: HIGH_VOL по ATR на 15m (тот же метод, что v1 — устойчивее
            # range-spike: last_atr > 1.8×median_atr. Старый range>3×med давал
            # ложный HIGH_VOL почти всегда в волатильной крипте).
            if (df_15m is not None and len(df_15m) >= _MIN_CANDLES
                    and all(c in df_15m.columns for c in ("high", "low", "close"))):
                _av = _atr(df_15m["high"].tolist(), df_15m["low"].tolist(),
                           df_15m["close"].tolist(), self.atr_period)
                if _av:
                    _last, _med = _av[-1], sorted(_av)[len(_av) // 2]
                    if _med > 0 and _last > _ATR_HIGH_VOL_MULT * _med:
                        return "HIGH_VOL"

            # Слой 2: HTF-доминанта — 4h главный, fallback 1h
            htf = df_4h if (df_4h is not None and len(df_4h) >= _MIN_CANDLES) else df_1h
            if htf is None or len(htf) < _MIN_CANDLES:
                return "RANGE"

            # trend через единый calculate_trend (НЕ требуем синхронности с 15m)
            if "trend" not in htf.columns:
                htf = calculate_trend(htf.copy())
            try:
                t_htf = int(htf["trend"].iloc[-1])  # 1 (UP) / -1 (DOWN)
            except Exception:
                return "RANGE"

            # Сила тренда: WT-дивергенция ИЛИ ADX на HTF
            wt_diff = 0.0
            if "wt1" not in htf.columns or "wt2" not in htf.columns:
                try:
                    htf = calculate_wt(htf)
                except Exception:
                    pass
            if "wt1" in htf.columns and "wt2" in htf.columns:
                try:
                    wt_diff = abs(float(htf["wt1"].iloc[-1]) - float(htf["wt2"].iloc[-1]))
                except Exception:
                    wt_diff = 0.0

            adx_htf = None
            if all(c in htf.columns for c in ("high", "low", "close")):
                try:
                    adx_htf = _adx(htf["high"].tolist(), htf["low"].tolist(),
                                   htf["close"].tolist(), self.adx_period)
                except Exception:
                    adx_htf = None

            strong = (wt_diff > 10) or (adx_htf is not None and adx_htf > _ADX_TREND_THRESHOLD)
            if not strong:
                # HTF-тренд затухает → реально флэт
                return "RANGE"

            return "TREND_UP" if t_htf == 1 else "TREND_DOWN"

        except Exception as e:
            logger.warning("[classify_v2] error: %s", e)
            return "RANGE"
