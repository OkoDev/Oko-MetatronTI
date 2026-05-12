"""
ATR Change Detector — Куб Метатрона: детектор смены направления supertrend.

Публикует в EventBus:
  - atr_change_15m  (priority=2)
  - atr_change_1h   (priority=1)
  - atr_change_4h   (priority=1)
  - 1d — НЕ публикуется (backtest R8: avgR=-0.4)

Параметры из backtest R6-R8: atr_period=43, factor=1.25.

Принцип «закрытая свеча» (как симуляционный TSL в trade_simulator):
  scan_loop уже считает df['trend'] через _calc_trend → берём готовое значение.
  current = trend.iloc[-2] (последняя ЗАКРЫТАЯ свеча), prev = trend.iloc[-3].
  Это исключает flip-flop из-за пересчёта ATR на открытой свече.
  Биржевой TSL остаётся отдельной нерешённой задачей.

Debouncing: один event per (symbol, tf) до следующего изменения тренда (через _last_trend).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

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
    """Детектирует подтверждённую (на закрытой свече) смену supertrend направления.

    Параметры atr_period=43, factor=1.25 нужны только для fallback-пересчёта,
    когда вызывающий код не передал df с готовой колонкой 'trend'.
    Штатный путь — scan_loop уже посчитал trend → детектор просто читает.
    """

    def __init__(self, atr_period: int = 43, factor: float = 1.25) -> None:
        self.atr_period = atr_period
        self.factor = factor
        self._last_trend: Dict[Tuple[str, str], int] = {}  # (symbol, tf) → +1/-1

    def detect(self, symbol: str, tf: str, df_ohlcv: pd.DataFrame) -> Optional[ATRChangeEvent]:
        """Возвращает ATRChangeEvent если на закрытой свече произошёл cross, иначе None."""
        try:
            if df_ohlcv is None or df_ohlcv.empty or len(df_ohlcv) < 3:
                return None

            # Используем уже посчитанный trend из scan_loop, чтобы не плодить дубль calculate_trend.
            # Fallback на пересчёт — только если колонки нет (старый вызывающий код).
            if "trend" in df_ohlcv.columns:
                df = df_ohlcv
            else:
                from core.indicators.indicators import calculate_trend
                df = calculate_trend(df_ohlcv, atr_period=self.atr_period, factor=self.factor)
                if df is None or df.empty or "trend" not in df.columns:
                    return None

            # iloc[-2] = последняя ЗАКРЫТАЯ свеча, iloc[-1] = открытая (или только что закрытая, но
            # её trend ещё мог flip-flop'ить между сканами). Принцип симуляционного TSL.
            _c = df["trend"].iloc[-2]
            _p = df["trend"].iloc[-3]
            if pd.isna(_c) or pd.isna(_p):
                return None
            current = int(_c)
            prev_closed = int(_p)

            key = (symbol, tf)
            last_emitted = self._last_trend.get(key)

            # Debouncing: запоминаем current → один event per смену тренда.
            self._last_trend[key] = current

            # Cross детектируется когда (а) две соседние закрытые свечи имеют разный trend
            # и (б) мы ещё не выпускали event для этого направления (last_emitted != current).
            if prev_closed == current:
                return None
            if last_emitted == current:
                return None

            side = "UP" if current == 1 else "DOWN"

            # Все значения берём с той же закрытой свечи [-2], чтобы snapshot был согласован.
            row_closed = df.iloc[-2]

            wt1: Optional[float] = None
            if "wt1" in df.columns:
                _v = row_closed.get("wt1")
                if _v is not None and not pd.isna(_v):
                    wt1 = float(_v)

            zone: Optional[str] = None
            if "zone" in df.columns:
                _z = row_closed.get("zone")
                if _z is not None and not pd.isna(_z):
                    zone = str(_z)
            elif wt1 is not None:
                try:
                    from core.indicators.indicators import get_zone
                    zone = get_zone(wt1)
                except Exception:
                    zone = None

            trendline: Optional[float] = None
            _col = "trendup" if side == "UP" else "trenddown"
            if _col in df.columns:
                _tl = row_closed.get(_col)
                if _tl is not None and not pd.isna(_tl):
                    trendline = float(_tl)

            price = float(row_closed["close"])

            return ATRChangeEvent(
                symbol=symbol,
                tf=tf,
                side=side,
                price=price,
                wt1=wt1,
                zone=zone,
                trendline=trendline,
            )
        except Exception as e:
            logger.debug("[ATRChangeDetector] %s %s error: %s", symbol, tf, e)
        return None
