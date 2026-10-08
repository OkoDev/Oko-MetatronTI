"""
SMC Specialist — Сфера 4 / CUBE-08.

Быстрый SMC классификатор на уже загруженных df (без дополнительных API запросов).
Вызывается в scan_one() после расчёта индикаторов — данные уже есть в памяти.

Вердикты (🔴 08.10: это ATR-тренд `calculate_trend` на 1h и 4h, BOS/CHoCH здесь НЕ смотрятся — старый
docstring врал; с ML-вердиктом `mtf_smc_specialist` (качество сетапа STRONG_SETUP/WEAK_SETUP) не путать).
09.10 (Егор): метки переименованы из STRONG_BULL_ZONE/… в ATR_TREND_* — имя говорит, что внутри. Слова
BULL/BEAR/STRONG/WEAK сохранены: дашборд oko-dashboard разбирает метку по этим подстрокам.
  ATR_TREND_BULL_STRONG  — тренд UP на 1h и на 4h          (было STRONG_BULL_ZONE)
  ATR_TREND_BULL_WEAK    — тренд UP на 1h, 4h нет или против (было WEAK_BULL_ZONE)
  ATR_TREND_BEAR_STRONG  — тренд DOWN на 1h и на 4h        (было STRONG_BEAR_ZONE)
  ATR_TREND_BEAR_WEAK    — тренд DOWN на 1h, 4h нет или против (было WEAK_BEAR_ZONE)
  ATR_TREND_NONE         — тренда на 1h нет                 (было NEUTRAL)
В `features_json` сделок до 09.10 лежат старые имена.
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger("SMCSpecialist")

# Минимум баров для анализа
_MIN_BARS = 30


def fast_smc_verdict(
    df_1h: Optional[pd.DataFrame],
    df_4h: Optional[pd.DataFrame],
) -> Optional[str]:
    """
    Быстрый SMC вердикт на основе уже вычисленных trend/WT колонок.
    Не делает API запросов. Использует trendup/trenddown/trend из calculate_trend().

    Args:
        df_1h: DataFrame 1h с колонками trend, trendup, trenddown (calculate_trend applied)
        df_4h: DataFrame 4h с колонками trend, trendup, trenddown

    Returns:
        Вердикт или None если нет данных
    """
    if df_1h is None or df_1h.empty or len(df_1h) < _MIN_BARS:
        return None

    # ── 1h тренд: основная структура ──────────────────────────────────────
    trend_1h = _get_trend(df_1h)
    if trend_1h == 0:
        return "ATR_TREND_NONE"

    # ── 4h подтверждение ─────────────────────────────────────────────────
    if df_4h is None or df_4h.empty or len(df_4h) < _MIN_BARS:
        # Только 1h — слабый сигнал
        if trend_1h == 1:
            return "ATR_TREND_BULL_WEAK"
        return "ATR_TREND_BEAR_WEAK"

    trend_4h = _get_trend(df_4h)

    # Оба TF совпадают → сильный сигнал
    if trend_4h == trend_1h:
        if trend_1h == 1:
            return "ATR_TREND_BULL_STRONG"
        return "ATR_TREND_BEAR_STRONG"

    # 4h против 1h (или 4h без тренда) → слабый сигнал
    if trend_1h == 1:
        return "ATR_TREND_BULL_WEAK"
    return "ATR_TREND_BEAR_WEAK"


def _get_trend(df: pd.DataFrame) -> int:
    """
    Читает направление тренда из колонки 'trend' (output calculate_trend).
    Возвращает: 1 (UP), -1 (DOWN), 0 (нет данных).
    """
    try:
        if "trend" not in df.columns:
            # Fallback: trendup/trenddown
            if "trendup" in df.columns and "trenddown" in df.columns:
                last = df.iloc[-1]
                if last.get("trendup", 0) and float(last.get("trendup", 0)) > 0:
                    return 1
                if last.get("trenddown", 0) and float(last.get("trenddown", 0)) > 0:
                    return -1
            return 0
        t = df["trend"].iloc[-1]
        if t == 1:
            return 1
        if t == -1:
            return -1
    except Exception:
        pass
    return 0
