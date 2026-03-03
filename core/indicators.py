import pandas as pd
import numpy as np

def calculate_wt(df: pd.DataFrame, n1=10, n2=21) -> pd.DataFrame:
    """Вычисляет wt1 и wt2, добавляет в df"""
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


def calculate_trend(df: pd.DataFrame, atr_period=43, factor=1.0) -> pd.DataFrame:
    """
    Расчет тренда по алгоритму из Pine Script
    
    Аналог:
    float factor = 1.0
    int pd = 43
    float up = hl2 - (factor * ta.atr(pd))
    dn = hl2 + (factor * ta.atr(pd))
    
    trendup := hl2[1] > trendup[1] ? math.max(up, trendup[1]) : up
    trenddown := hl2[1] < trenddown[1] ? math.min(dn, trenddown[1]) : dn
    trendX := hl2 > trenddown[1] ? 1 : hl2 < trendup[1] ? -1 : nz(trendX[1], 1)
    """
    df = df.copy().reset_index(drop=True)
    
    high = df["high"]
    low = df["low"]
    close = df["close"]
    
    # Расчет ATR
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=atr_period, min_periods=1).mean()
    
    # hl2 (средняя цена high-low)
    hl2 = (high + low) / 2.0
    
    # Базовые уровни up и dn
    up = hl2 - (factor * atr)
    dn = hl2 + (factor * atr)
    
    # Инициализация массивов
    trendup = np.zeros(len(df))
    trenddown = np.zeros(len(df))
    trend = np.zeros(len(df))
    
    # Первая строка
    trendup[0] = up.iloc[0]
    trenddown[0] = dn.iloc[0]
    trend[0] = 1  # По умолчанию восходящий тренд
    
    # Итеративный расчет (как в Pine Script)
    for i in range(1, len(df)):
        # trendup := hl2[1] > trendup[1] ? math.max(up, trendup[1]) : up
        if hl2.iloc[i-1] > trendup[i-1]:
            trendup[i] = max(up.iloc[i], trendup[i-1])
        else:
            trendup[i] = up.iloc[i]
        
        # trenddown := hl2[1] < trenddown[1] ? math.min(dn, trenddown[1]) : dn
        if hl2.iloc[i-1] < trenddown[i-1]:
            trenddown[i] = min(dn.iloc[i], trenddown[i-1])
        else:
            trenddown[i] = dn.iloc[i]
        
        # trendX := hl2 > trenddown[1] ? 1 : hl2 < trendup[1] ? -1 : nz(trendX[1], 1)
        if hl2.iloc[i] > trenddown[i-1]:
            trend[i] = 1  # Восходящий тренд
        elif hl2.iloc[i] < trendup[i-1]:
            trend[i] = -1  # Нисходящий тренд
        else:
            trend[i] = trend[i-1]  # Сохраняем предыдущий тренд
    
    # Добавляем в DataFrame
    df["trend"] = trend.astype(int)
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