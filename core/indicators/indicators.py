import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Union

def calculate_wt(df: pd.DataFrame, n1=10, n2=21) -> pd.DataFrame:
    """Вычисляет wt1 и wt2, добавляет в df.
    ARCH-18: если колонки уже есть и параметры дефолтные — пропускаем пересчёт.
    """
    if n1 == 10 and n2 == 21 and "wt1" in df.columns and "wt2" in df.columns:
        return df
    df = df.copy().reset_index(drop=True)
    hlc3 = (df["high"] + df["low"] + df["close"]) / 3.0
    esa = hlc3.ewm(span=n1, adjust=False).mean()
    d = (abs(hlc3 - esa)).ewm(span=n1, adjust=False).mean()
    # предотвращаем деление на 0
    denom = (0.015 * d).replace(0, np.nan)
    ci = (hlc3 - esa) / denom
    tci = ci.ewm(span=n2, adjust=False).mean()
    df["wt1"] = tci.fillna(0)
    df["wt2"] = df["wt1"].rolling(window=4, min_periods=1).mean()
    return df


# def calculate_trend(df: pd.DataFrame, atr_period=43, factor=1.0) -> pd.DataFrame:
#     """
#     Расчет тренда по алгоритму из Pine Script
    
#     Аналог:
#     float factor = 1.0
#     int pd = 43
#     float up = hl2 - (factor * ta.atr(pd))
#     dn = hl2 + (factor * ta.atr(pd))
    
#     trendup := hl2[1] > trendup[1] ? math.max(up, trendup[1]) : up
#     trenddown := hl2[1] < trenddown[1] ? math.min(dn, trenddown[1]) : dn
#     trendX := hl2 > trenddown[1] ? 1 : hl2 < trendup[1] ? -1 : nz(trendX[1], 1)
#     """
#     df = df.copy().reset_index(drop=True)
    
#     high = df["high"]
#     low = df["low"]
#     close = df["close"]
    
#     # Расчет ATR
#     tr1 = high - low
#     tr2 = (high - close.shift(1)).abs()
#     tr3 = (low - close.shift(1)).abs()
#     tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
#     atr = tr.rolling(window=atr_period, min_periods=1).mean()
    
#     # hl2 (средняя цена high-low)
#     hl2 = (high + low) / 2.0
    
#     # Базовые уровни up и dn
#     up = hl2 - (factor * atr)
#     dn = hl2 + (factor * atr)
    
#     # Инициализация массивов
#     trendup = np.zeros(len(df))
#     trenddown = np.zeros(len(df))
#     trend = np.zeros(len(df))
    
#     # Первая строка
#     trendup[0] = up.iloc[0]
#     trenddown[0] = dn.iloc[0]
#     trend[0] = 1  # По умолчанию восходящий тренд
    
#     # Итеративный расчет (как в Pine Script)
#     for i in range(1, len(df)):
#         # trendup := hl2[1] > trendup[1] ? math.max(up, trendup[1]) : up
#         if hl2.iloc[i-1] > trendup[i-1]:
#             trendup[i] = max(up.iloc[i], trendup[i-1])
#         else:
#             trendup[i] = up.iloc[i]
        
#         # trenddown := hl2[1] < trenddown[1] ? math.min(dn, trenddown[1]) : dn
#         if hl2.iloc[i-1] < trenddown[i-1]:
#             trenddown[i] = min(dn.iloc[i], trenddown[i-1])
#         else:
#             trenddown[i] = dn.iloc[i]
        
#         # trendX := hl2 > trenddown[1] ? 1 : hl2 < trendup[1] ? -1 : nz(trendX[1], 1)
#         if hl2.iloc[i] > trenddown[i-1]:
#             trend[i] = 1  # Восходящий тренд
#         elif hl2.iloc[i] < trendup[i-1]:
#             trend[i] = -1  # Нисходящий тренд
#         else:
#             trend[i] = trend[i-1]  # Сохраняем предыдущий тренд
    
#     # Добавляем в DataFrame
#     df["trend"] = trend.astype(int)
#     df["trendup"] = trendup
#     df["trenddown"] = trenddown
#     df["tsl"] = np.where(df["trend"] == 1, trendup, trenddown)
    
#     return df

def calculate_trend(df: pd.DataFrame, atr_period=43, factor=1.0) -> pd.DataFrame:
    """
    ЕДИНЫЙ источник тренда и TSL-линий для всего проекта.
    ARCH-18: если колонки уже есть и параметры дефолтные — пропускаем пересчёт.

    Расчет по алгоритму Pine Script (точная реализация):
      up = hl2 - factor * ta.atr(atr_period)
      dn = hl2 + factor * ta.atr(atr_period)
      trendup  := prev_hl2 > prev_trendup  ? max(up, prev_trendup)  : up
      trenddown:= prev_hl2 < prev_trenddown? min(dn, prev_trenddown): dn
      trend    := hl2 > prev_trenddown ? 1 : hl2 < prev_trendup ? -1 : prev_trend

    Добавляет колонки: trend (+1/-1), trendup, trenddown, tsl.
    tsl = trendup  (для LONG, SL снизу)
    tsl = trenddown(для SHORT, SL сверху)

    Используется везде: check_trend_signals, TSL check_open_trades,
    _calculate_levels в trading_intelligence, trade_simulator TSL-трекинг.
    """
    _trend_cols = ("trend", "trendup", "trenddown", "tsl")
    if atr_period == 43 and factor == 1.0 and all(c in df.columns for c in _trend_cols):
        return df
    df = df.copy().reset_index(drop=True)

    # --- 1. True Range — через единую функцию проекта ---
    tr = true_range_series(df)

    # --- 2. ATR методом RMA (Wilder's smoothing), как в Pine Script ---
    atr = pd.Series(index=tr.index, dtype=float)
    if len(tr) >= atr_period:
        # Первый период: простое среднее
        atr.iloc[atr_period-1] = tr.iloc[:atr_period].mean()
        # Рекуррентное сглаживание для остальных
        for i in range(atr_period, len(tr)):
            atr.iloc[i] = (atr.iloc[i-1] * (atr_period - 1) + tr.iloc[i]) / atr_period
    # Остальные значения остаются NaN (как в Pine до накопления period баров)
    
    # --- 3. hl2 и базовые уровни up/dn ---
    high = df["high"]
    low = df["low"]
    hl2 = (high + low) / 2.0
    up = hl2 - factor * atr
    dn = hl2 + factor * atr
    
    # --- 4. Инициализация выходных массивов (NaN для trendup/trenddown) ---
    trendup = np.full(len(df), np.nan, dtype=float)
    trenddown = np.full(len(df), np.nan, dtype=float)
    trend = np.full(len(df), np.nan, dtype=float)
    
    # --- 5. Первый бар (i=0) ---
    # trendup[0] = up[0] (скорее всего NaN), trenddown[0] = dn[0] (NaN), trend[0] = 1 (как nz(...,1))
    trendup[0] = up.iloc[0]
    trenddown[0] = dn.iloc[0]
    trend[0] = 1.0
    
    # --- 6. Основной цикл (точная логика Pine Script) ---
    for i in range(1, len(df)):
        prev_hl2 = hl2.iloc[i-1]
        prev_trendup = trendup[i-1]
        prev_trenddown = trenddown[i-1]
        prev_trend = trend[i-1]
        
        up_i = up.iloc[i]
        dn_i = dn.iloc[i]
        
        # --- trendup ---
        # Если предыдущий trendup существует и условие выполняется, берём максимум,
        # иначе просто up_i (даже если up_i NaN – результат будет NaN)
        if not np.isnan(prev_trendup) and prev_hl2 > prev_trendup:
            trendup[i] = max(up_i, prev_trendup) if not np.isnan(up_i) else prev_trendup
        else:
            trendup[i] = up_i
        
        # --- trenddown ---
        if not np.isnan(prev_trenddown) and prev_hl2 < prev_trenddown:
            trenddown[i] = min(dn_i, prev_trenddown) if not np.isnan(dn_i) else prev_trenddown
        else:
            trenddown[i] = dn_i
        
        # --- trendX ---
        if not np.isnan(prev_trenddown) and hl2.iloc[i] > prev_trenddown:
            trend[i] = 1.0
        elif not np.isnan(prev_trendup) and hl2.iloc[i] < prev_trendup:
            trend[i] = -1.0
        else:
            trend[i] = prev_trend if not np.isnan(prev_trend) else 1.0
    
    # --- 7. Добавление результатов в DataFrame ---
    df["trend"] = trend.astype(int)   # trend теперь целые значения (1 или -1)
    df["trendup"] = trendup
    df["trenddown"] = trenddown
    df["tsl"] = np.where(df["trend"] == 1, trendup, trenddown)
    
    return df


def get_zone(wt_value: float, ob1=60, os1=-60) -> str:
    """OB / OS / N"""
    try:
        if wt_value >= ob1:
            return "OB"
        if wt_value <= os1:
            return "OS"
    except Exception:
        pass
    return "N"


def detect_fvg(df: pd.DataFrame):
    """Detect FVG on last 3 bars. Return ('BULL'|'BEAR'|None, entry_price)"""
    if df is None or len(df) < 3:
        return None, None
    last3 = df.iloc[-3:].reset_index(drop=True)
    # Bull gap: low of last > high of first
    if last3.loc[2, "low"] > last3.loc[0, "high"]:
        entry = (last3.loc[2, "low"] + last3.loc[0, "high"]) / 2.0
        return "BULL", entry
    # Bear gap:
    if last3.loc[2, "high"] < last3.loc[0, "low"]:
        entry = (last3.loc[2, "high"] + last3.loc[0, "low"]) / 2.0
        return "BEAR", entry
    return None, None


def calculate_trend_strength(df: pd.DataFrame) -> pd.DataFrame:
    """
    Дополнительно: расчет силы тренда на основе последовательных баров
    """
    if "trend" not in df.columns:
        df = calculate_trend(df)
    
    # Подсчитываем последовательные бары одного направления
    df["trend_strength"] = 0
    current_strength = 0
    
    for i in range(1, len(df)):
        if df["trend"].iloc[i] == df["trend"].iloc[i-1]:
            current_strength += 1
        else:
            current_strength = 1
        df.loc[df.index[i], "trend_strength"] = current_strength
    
    return df


def get_trend_info(df: pd.DataFrame) -> dict:
    """
    Возвращает подробную информацию о текущем тренде
    """
    if df is None or df.empty or "trend" not in df.columns:
        return None
    
    last_row = df.iloc[-1]
    
    # Считаем длину текущего тренда
    trend_length = 1
    for i in range(len(df)-2, -1, -1):
        if df["trend"].iloc[i] == last_row["trend"]:
            trend_length += 1
        else:
            break
    
    # Расстояние до TSL (Trailing Stop Loss)
    current_price = last_row["close"]
    tsl = last_row.get("tsl", 0)
    distance_to_tsl = abs(current_price - tsl) / current_price * 100 if tsl else 0
    
    return {
        "direction": "UP" if last_row["trend"] == 1 else "DOWN",
        "trend_value": int(last_row["trend"]),
        "length": trend_length,
        "tsl": tsl,
        "distance_to_tsl_percent": distance_to_tsl,
        "trendup": last_row.get("trendup", 0),
        "trenddown": last_row.get("trenddown", 0),
        "is_strong": trend_length >= 5  # Тренд считается сильным если 5+ баров
    }


# ═══════════════════════════════════════════════════════════════════════════
# ЕДИНЫЕ БАЗОВЫЕ ВЫЧИСЛЕНИЯ — используйте только эти функции во всём проекте
#
# TREND / TSL  → calculate_trend(df, atr_period=43, factor=1.0)
#                → колонки: trend (+1/-1), trendup, trenddown, tsl
# ATR          → compute_atr(df, period) / compute_atr_values(h, l, c, period)
# EMA          → compute_ema(values, period) / compute_ema_values(values, period)
# SMA          → compute_sma(values, period)
# Volatility   → compute_volatility(closes, period=20) → ПРОЦЕНТЫ (1.5 = 1.5%)
#                  Для ML нормализовать: / 100.0
# ADX          → compute_adx(highs, lows, closes, period=14) → 0-100
# RSI          → compute_rsi(closes, period=14) → 0-100
# Volume Ratio → compute_volume_ratio(volumes, period=20) → current/SMA
# Swing H/L    → find_swing_highs(series, period) / find_swing_lows(series, period)
# Pivot Points → calculate_pivot_points(high, low, close) → {PP, S1-S5, R1-R5}
# True Range   → true_range_series(df)
# ═══════════════════════════════════════════════════════════════════════════

def true_range_series(df: pd.DataFrame) -> pd.Series:
    """True Range для pandas DataFrame с колонками high/low/close."""
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - df["close"].shift(1)).abs()
    tr3 = (df["low"] - df["close"].shift(1)).abs()
    return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)


def compute_atr_values(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14,
) -> List[float]:
    """ATR серия (Wilder's RMA) из списков. Возвращает список всех значений.
    Используется когда нужна медиана или история ATR (например market_regime).
    """
    n = len(closes)
    if n < period + 1:
        return []
    tr = []
    for i in range(1, n):
        h, l, pc = highs[i], lows[i], closes[i - 1]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(tr) < period:
        return []
    atr_val = sum(tr[:period]) / period
    result = [atr_val]
    for v in tr[period:]:
        atr_val = (atr_val * (period - 1) + v) / period
        result.append(atr_val)
    return result


def compute_atr(
    df: Optional[pd.DataFrame] = None,
    period: int = 14,
    *,
    highs: Optional[List[float]] = None,
    lows: Optional[List[float]] = None,
    closes: Optional[List[float]] = None,
) -> Optional[float]:
    """Единый ATR (Wilder's RMA) для всего проекта — как в Pine Script ta.atr().

    Принимает либо pandas DataFrame (df=...), либо три списка (highs/lows/closes=...).
    Возвращает последнее значение ATR или None если данных недостаточно.
    """
    if df is not None:
        if len(df) < period + 1:
            return None
        h = df["high"].tolist()
        l = df["low"].tolist()
        c = df["close"].tolist()
    elif highs is not None and lows is not None and closes is not None:
        h, l, c = highs, lows, closes
    else:
        return None
    vals = compute_atr_values(h, l, c, period)
    return float(vals[-1]) if vals else None


def compute_ema_values(
    prices: Union[List[float], pd.Series],
    period: int,
) -> List[float]:
    """EMA серия. k = 2/(period+1). Возвращает список всех значений.
    Используется когда нужен slope или история EMA (например market_regime).
    """
    if isinstance(prices, pd.Series):
        lst = prices.dropna().tolist()
    else:
        lst = [v for v in prices if v == v]
    if len(lst) < period:
        return []
    k = 2.0 / (period + 1)
    ema = sum(lst[:period]) / period
    result = [ema]
    for v in lst[period:]:
        ema = v * k + ema * (1 - k)
        result.append(ema)
    return result


def compute_ema(
    values: Union[List[float], pd.Series],
    period: int,
) -> Optional[float]:
    """Единая EMA для всего проекта. Возвращает последнее значение."""
    vals = compute_ema_values(values, period)
    return float(vals[-1]) if vals else None


def compute_sma(
    values: Union[List[float], pd.Series],
    period: int,
) -> Optional[float]:
    """Единая SMA для всего проекта. Возвращает последнее значение."""
    if isinstance(values, pd.Series):
        lst = values.dropna().tolist()
    else:
        lst = [v for v in values if v == v]
    if len(lst) < period:
        return None
    return float(sum(lst[-period:]) / period)


def compute_volatility(
    closes: Union[List[float], pd.Series],
    period: int = 20,
) -> Optional[float]:
    """Волатильность цены (Единый источник) — std процентных изменений за period баров.

    Возвращает значение в ПРОЦЕНТАХ (например 1.5 означает 1.5%).
    Используется в: market_context.volatility, SL-расчётах, ML-фичах.

    При передаче в ML нормализовать: compute_volatility(...) / 100.0
    """
    if isinstance(closes, pd.Series):
        lst = closes.dropna().tolist()
    else:
        lst = [v for v in closes if v == v]
    if len(lst) < period + 1:
        return None
    pct = [(lst[i] - lst[i - 1]) / lst[i - 1] for i in range(1, len(lst)) if lst[i - 1] != 0]
    if len(pct) < period:
        return None
    window = pct[-period:]
    mean = sum(window) / len(window)
    variance = sum((x - mean) ** 2 for x in window) / len(window)
    return float(variance ** 0.5 * 100)  # в процентах


def _wilder_smooth(values: List[float], period: int) -> List[float]:
    """Wilder's smoothing (RMA) — вспомогательная функция для ADX."""
    if len(values) < period:
        return []
    s = [sum(values[:period])]
    for v in values[period:]:
        s.append(s[-1] - s[-1] / period + v)
    return s


def compute_adx(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14,
) -> Optional[float]:
    """ADX (Average Directional Index) — Единый источник для всего проекта.

    Алгоритм:
      - Wilder's accumulated smoothing (sum→rma) для TR/DM+/DM-
      - RMA (SMA init) для DX→ADX (как compute_atr_values)
    Возвращает последнее значение ADX (0-100) или None если данных недостаточно.
    Используется в: market_regime.py (TREND_UP/TREND_DOWN классификация).
    """
    n = len(closes)
    if n < period * 2:
        return None
    dm_plus, dm_minus, tr = [], [], []
    for i in range(1, n):
        up   = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        dm_plus.append(max(up, 0) if up > down else 0)
        dm_minus.append(max(down, 0) if down > up else 0)
        h, l, pc = highs[i], lows[i], closes[i - 1]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))

    # Wilder's накопленное сглаживание (Σ → рекуррентно) для TR/DM
    str_      = _wilder_smooth(tr, period)
    sdm_plus  = _wilder_smooth(dm_plus, period)
    sdm_minus = _wilder_smooth(dm_minus, period)

    di_plus  = [100 * p / t if t else 0 for p, t in zip(sdm_plus, str_)]
    di_minus = [100 * m / t if t else 0 for m, t in zip(sdm_minus, str_)]
    dx = [100 * abs(p - m) / (p + m) if (p + m) else 0 for p, m in zip(di_plus, di_minus)]

    # ADX = RMA(DX, period) — SMA-инициализация (как compute_atr_values)
    if len(dx) < period:
        return None
    adx = sum(dx[:period]) / period
    for v in dx[period:]:
        adx = (adx * (period - 1) + v) / period
    return float(adx)


def compute_rsi(
    closes: Union[List[float], pd.Series],
    period: int = 14,
) -> Optional[float]:
    """RSI (Relative Strength Index) — Единый источник для всего проекта.

    Алгоритм: SMA gain/loss за первые period баров, затем RMA (Wilder's).
    Возвращает значение 0-100 или None если данных недостаточно.
    Используется в: ml_predictor.py (feature extraction).
    """
    if isinstance(closes, pd.Series):
        lst = closes.dropna().tolist()
    else:
        lst = [v for v in closes if v == v]
    if len(lst) < period + 1:
        return None
    deltas = [lst[i] - lst[i - 1] for i in range(1, len(lst))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [abs(min(d, 0.0)) for d in deltas]
    # Первый период: SMA
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    # RMA (Wilder's)
    for g, l in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100.0 - 100.0 / (1.0 + rs))


def compute_volume_ratio(
    volumes: Union[List[float], pd.Series],
    period: int = 20,
) -> Optional[float]:
    """Относительный объём (volume ratio) — Единый источник для всего проекта.

    Возвращает current_volume / SMA(volume, period).
    Значение > 1.0 означает объём выше среднего (например 3.0 = тройной объём).
    Используется в: signal_checkers.py, ml_predictor.py, trading_intelligence.py.
    """
    if isinstance(volumes, pd.Series):
        lst = volumes.dropna().tolist()
    else:
        lst = [v for v in volumes if v == v]
    if len(lst) < period + 1:
        return None
    ma = sum(lst[-period - 1:-1]) / period  # SMA за предыдущие period баров
    current = lst[-1]
    return float(current / ma) if ma > 0 else None


def find_swing_highs(
    series: pd.Series,
    period: int = 5,
) -> List[dict]:
    """Swing Highs (pivot highs) — Единый источник для всего проекта.

    Pivot high = значение выше ВСЕХ соседей на расстоянии period баров с каждой стороны.
    Аналог ta.pivothigh() в Pine Script.

    Возвращает список dict: {'index': int, 'value': float}
    Используется в: divergence_detector.py, trading_intelligence.py (swing_high SL).
    """
    pivots = []
    n = len(series)
    for i in range(period, n - period):
        val = series.iloc[i]
        if all(val > series.iloc[j] for j in range(i - period, i + period + 1) if j != i):
            pivots.append({"index": i, "value": float(val)})
    return pivots


def find_swing_lows(
    series: pd.Series,
    period: int = 5,
) -> List[dict]:
    """Swing Lows (pivot lows) — Единый источник для всего проекта.

    Pivot low = значение ниже ВСЕХ соседей на расстоянии period баров с каждой стороны.
    Аналог ta.pivotlow() в Pine Script.

    Возвращает список dict: {'index': int, 'value': float}
    Используется в: divergence_detector.py, trading_intelligence.py (swing_low SL).
    """
    pivots = []
    n = len(series)
    for i in range(period, n - period):
        val = series.iloc[i]
        if all(val < series.iloc[j] for j in range(i - period, i + period + 1) if j != i):
            pivots.append({"index": i, "value": float(val)})
    return pivots


def calculate_pivot_points(high: float, low: float, close: float) -> Dict[str, float]:
    """Traditional Pivot Points — Единый источник формул для всего проекта.

    Формулы Pine Script: PP = (H+L+C)/3, S1..S5, R1..R5.
    Используется в: pivot_levels.PivotLevels и pivot_calculator_fixed.PivotCalculatorFixed.
    """
    pp = (high + low + close) / 3.0
    hl = high - low
    return {
        "PP": pp,
        "S1": pp * 2.003 - high,
        "S2": pp - hl,
        "S3": pp * 2 - (2 * high - low),
        "S4": pp * 3 - (3 * high - low),
        "S5": pp * 4 - (4 * high - low),
        "R1": pp * 1.997 - low,
        "R2": pp + hl,
        "R3": pp * 2 + (high - 2 * low),
        "R4": pp * 3 + (high - 3 * low),
        "R5": pp * 4 + (high - 4 * low),
    }