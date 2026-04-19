"""
HTF Detectors — Куб Метатрона: детекторы на старших таймфреймах.

Детекторы, которые публикуют в EventBus для запуска Full CALL:
  - trend_change_1h:  смена тренда (trenddown→trendup / trendup→trenddown) на 1h
  - wt_cross_4h:      кросс WT1/WT2 в зонах OB/OS на 4h (редкий, мощный сетап)
  - wt_cross_1d:      кросс WT1/WT2 в зонах OB/OS на 1d (ещё реже, ещё мощнее)

Каждый детектор:
  - Получает df с уже рассчитанными индикаторами (wt1, wt2, trendup, trenddown)
  - Хранит предыдущее состояние per-symbol (для detect "change")
  - Возвращает (fired: bool, event_data: dict | None)
"""
from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple

import pandas as pd

logger = logging.getLogger("htf_detectors")


class TrendChangeDetector:
    """
    Сфера 7 → EventBus: обнаруживает смену тренда на 1h.

    Логика:
      - Хранит последний известный тренд per symbol (UP/DOWN)
      - Если тренд изменился → fired=True + event_data
      - Кулдаун: один fire per symbol per change (не повторяет)
    """

    def __init__(self) -> None:
        self._prev_trend: Dict[str, str] = {}   # symbol → "UP" / "DOWN"

    def check(self, symbol: str, df_1h: pd.DataFrame) -> Tuple[bool, Optional[dict]]:
        """
        Проверяет смену тренда на 1h.

        Args:
            df_1h: DataFrame с колонками trendup/trenddown (из calculate_trend)

        Returns:
            (fired, event_data) — fired=True если тренд сменился
        """
        if df_1h is None or df_1h.empty or len(df_1h) < 3:
            return False, None

        if "trendup" not in df_1h.columns or "trenddown" not in df_1h.columns:
            return False, None

        last = df_1h.iloc[-1]
        tu = last.get("trendup", 0)
        td = last.get("trenddown", 0)

        # Определяем текущий тренд
        if tu and tu > 0 and (not td or td == 0):
            current_trend = "UP"
        elif td and td > 0 and (not tu or tu == 0):
            current_trend = "DOWN"
        else:
            return False, None

        prev = self._prev_trend.get(symbol)
        self._prev_trend[symbol] = current_trend

        # Первая проверка — запоминаем, не стреляем
        if prev is None:
            return False, None

        # Тренд изменился
        if current_trend != prev:
            # Дополнительно: WT 1h для контекста
            wt1_1h = float(df_1h["wt1"].iloc[-1]) if "wt1" in df_1h.columns else None

            event_data = {
                "old_trend": prev,
                "new_trend": current_trend,
                "wt1_1h": wt1_1h,
                "close": float(last.get("close", 0)),
            }
            logger.info(
                "[HTF] %s trend_change_1h: %s → %s (wt1=%.1f)",
                symbol, prev, current_trend, wt1_1h or 0,
            )
            return True, event_data

        return False, None


class WTCrossHTFDetector:
    """
    Сфера 7 → EventBus: обнаруживает кросс WT1/WT2 в зонах OB/OS на 4h и 1d.

    Логика:
      - Кросс UP в OS (<-60): бычий разворот на старшем TF → LONG setup
      - Кросс DOWN в OB (>60): медвежий разворот на старшем TF → SHORT setup
      - Хранит предыдущий кросс per symbol per tf (не повторяет)
    """

    def __init__(self, ob_threshold: float = 60.0, os_threshold: float = -60.0) -> None:
        self._ob = ob_threshold
        self._os = os_threshold
        self._prev_cross: Dict[str, int] = {}   # f"{symbol}:{tf}" → last cross direction

    def check(self, symbol: str, df: pd.DataFrame, tf: str) -> Tuple[bool, Optional[dict]]:
        """
        Проверяет кросс WT в OB/OS зоне на заданном TF.

        Args:
            df: DataFrame с wt1/wt2 (из calculate_wt)
            tf: таймфрейм ("4h", "1d")

        Returns:
            (fired, event_data)
        """
        if df is None or df.empty or len(df) < 3:
            return False, None

        if "wt1" not in df.columns or "wt2" not in df.columns:
            return False, None

        wt1 = float(df["wt1"].iloc[-1])
        wt2 = float(df["wt2"].iloc[-1])
        wt1_prev = float(df["wt1"].iloc[-2])
        wt2_prev = float(df["wt2"].iloc[-2])

        cross = 0
        direction = None
        zone = None

        # Кросс UP в OS зоне
        if wt1_prev <= wt2_prev and wt1 > wt2 and wt1 < self._os:
            cross = 1
            direction = "LONG"
            zone = "OS"

        # Кросс DOWN в OB зоне
        elif wt1_prev >= wt2_prev and wt1 < wt2 and wt1 > self._ob:
            cross = -1
            direction = "SHORT"
            zone = "OB"

        if cross == 0:
            return False, None

        # Дедупликация: не повторяем один и тот же кросс
        key = f"{symbol}:{tf}"
        if self._prev_cross.get(key) == cross:
            return False, None
        self._prev_cross[key] = cross

        gap = abs(wt1 - wt2)
        event_data = {
            "tf": tf,
            "direction": direction,
            "zone": zone,
            "wt1": round(wt1, 2),
            "wt2": round(wt2, 2),
            "gap": round(gap, 2),
            "close": float(df["close"].iloc[-1]) if "close" in df.columns else 0,
        }
        logger.info(
            "[HTF] %s wt_cross_%s: %s in %s zone (wt1=%.1f wt2=%.1f gap=%.1f)",
            symbol, tf, direction, zone, wt1, wt2, gap,
        )
        return True, event_data
