"""
ATR Change Detector — Куб Метатрона: детектор смены направления supertrend.

Публикует в EventBus:
  - atr_change_15m  (priority=2)
  - atr_change_1h   (priority=1)
  - atr_change_4h   (priority=1)
  - 1d — НЕ публикуется (backtest R8: avgR=-0.4)

Параметры из backtest R6-R8: atr_period=43, factor=1.25.
Debouncing встроен: один event per (symbol, tf) до следующего изменения.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class ATRChangeEvent:
    symbol: str
    tf: str
    side: str               # 'UP' или 'DOWN'
    price: float
    wt1: Optional[float]
    zone: Optional[str]
    trendline: Optional[float] = None   # trendup (LONG SL) или trenddown (SHORT SL)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "tf": self.tf,
            "side": self.side,
            "price": self.price,
            "wt1": self.wt1,
            "zone": self.zone,
            "trendline": self.trendline,
        }


class ATRChangeDetector:
    """Детектирует момент смены supertrend направления (cross supertrend линии).

    Параметры берутся из backtest R6-R8: atr_period=43, factor=1.25.
    Не публикует atr_change_1d (R8: avgR=-0.4).
    """

    def __init__(self, atr_period: int = 43, factor: float = 1.25, history_max_age_s: int = 28800) -> None:
        self.atr_period = atr_period
        self.factor = factor
        self._last_trend: Dict[Tuple[str, str], int] = {}  # (symbol, tf) → +1/-1
        # История кроссов для cascade-проверок (atr_change_15m_pre_1h и т.п.).
        # 28800 = 8 часов — максимальное окно для cascade (TRADER 09.05).
        self._history: Dict[Tuple[str, str], Deque[Tuple[int, str]]] = {}
        self._history_max_age_s = history_max_age_s

    def recent_cross_in_window(self, symbol: str, tf: str, side: str, window_s: int) -> bool:
        """Возвращает True если был cross в данную сторону на (sym, tf) за окно window_s секунд.

        Используется для cascade-confirmations (atr_change_15m_pre_1h: 15m UP за 8h до 1h UP).
        """
        key = (symbol, tf)
        hist = self._history.get(key)
        if not hist:
            return False
        cutoff = int(time.time()) - window_s
        for ts, ev_side in hist:
            if ts >= cutoff and ev_side == side:
                return True
        return False

    def detect(self, symbol: str, tf: str, df_ohlcv: pd.DataFrame) -> Optional[ATRChangeEvent]:
        """Возвращает ATRChangeEvent если произошёл cross, иначе None.

        Debouncing: один event per (symbol, tf) до следующего изменения тренда.

        Args:
            symbol: торговая пара ("BTC/USDT:USDT")
            tf:     таймфрейм ("15m", "1h", "4h")
            df_ohlcv: DataFrame с OHLCV данными (raw, без pre-computed trend)

        Returns:
            ATRChangeEvent если cross произошёл, иначе None.
        """
        try:
            from core.indicators.indicators import calculate_trend, calculate_wt, get_zone

            df = calculate_trend(df_ohlcv, atr_period=self.atr_period, factor=self.factor)
            if df is None or df.empty or "trend" not in df.columns:
                return None

            current = int(df["trend"].iloc[-1])
            key = (symbol, tf)
            prev = self._last_trend.get(key)

            # Горячий старт: при первом вызове после рестарта инициализируем prev
            # из предпоследней свечи. Это позволяет поймать cross на последней закрытой
            # свече сразу, не теряя его до следующего изменения тренда.
            if prev is None and len(df) >= 2:
                _prev_val = df["trend"].iloc[-2]
                if _prev_val is not None and not pd.isna(_prev_val):
                    prev = int(_prev_val)

            self._last_trend[key] = current

            if prev is not None and prev != current:
                side = "UP" if current == 1 else "DOWN"

                # История для cascade (atr_change_15m_pre_1h и т.п.) — добавляем
                # и чистим устаревшие записи.
                _now_s = int(time.time())
                _hist = self._history.setdefault(key, deque(maxlen=50))
                _hist.append((_now_s, side))
                _cutoff = _now_s - self._history_max_age_s
                while _hist and _hist[0][0] < _cutoff:
                    _hist.popleft()

                # wt1 если уже посчитан в df, иначе None
                wt1: Optional[float] = None
                if "wt1" in df.columns:
                    _v = df["wt1"].iloc[-1]
                    if _v is not None and not pd.isna(_v):
                        wt1 = float(_v)

                # zone если есть
                zone: Optional[str] = None
                if "zone" in df.columns:
                    _z = df["zone"].iloc[-1]
                    if _z is not None:
                        zone = str(_z)
                elif wt1 is not None:
                    # fallback: вычислить зону через get_zone
                    try:
                        zone = get_zone(wt1)
                    except Exception:
                        zone = None

                # trendline = SL уровень: trendup для LONG, trenddown для SHORT
                trendline: Optional[float] = None
                if side == "UP" and "trendup" in df.columns:
                    _tl = df["trendup"].iloc[-1]
                    if _tl is not None and not pd.isna(_tl):
                        trendline = float(_tl)
                elif side == "DOWN" and "trenddown" in df.columns:
                    _tl = df["trenddown"].iloc[-1]
                    if _tl is not None and not pd.isna(_tl):
                        trendline = float(_tl)

                return ATRChangeEvent(
                    symbol=symbol,
                    tf=tf,
                    side=side,
                    price=float(df["close"].iloc[-1]),
                    wt1=wt1,
                    zone=zone,
                    trendline=trendline,
                )
        except Exception as e:
            logger.debug("[ATRChangeDetector] %s %s error: %s", symbol, tf, e)
        return None
