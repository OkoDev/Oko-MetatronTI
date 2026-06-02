"""ARCH-128 — Swing Service: двухуровневые свинги + ZigZag (порт OKO-SM эталона).

Корень "мелких свингов" (DS-311 OTE, точность входа): бот использовал fractal
period=5 без фильтра значимости. Эталон пользователя (OKO-SM Pine) даёт ДВА метода:

1. swings(length) — LuxAlgo: значимый (major, len=50) vs internal (minor, len=5).
   os := high[len] > highest(len) ? 0 : low[len] < lowest(len) ? 1 : os[1]
   Свинг подтверждается СДВИГОМ на `length` баров (не симметричный fractal).

2. ZigZag с ATR-deviation: свинг засчитывается только если разворот ≥ k×ATR%
   (i_dev_thresh = atr(10)/close*100 × dev_mult). Отсекает шум.

Источник формул: memory/reference_oko_sm_indicator.md.
Используется: SMC-структура (BOS/CHoCH на major), OTE (Fib от свинга слома),
магниты, Elliott. Заменяет наивный find_swing_highs/lows для значимой структуры.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal, Optional

import pandas as pd


@dataclass(frozen=True)
class Swing:
    idx: int          # позиция бара (iloc) подтверждённого свинга
    ts: object         # timestamp (index value)
    price: float
    kind: Literal["H", "L"]
    level: Literal["major", "minor"]


def _swings_luxalgo(df: pd.DataFrame, length: int) -> List[tuple]:
    """LuxAlgo swings(length). Возвращает [(idx, price, 'H'/'L')].

    os := 0 (формируется high) когда high[length] > highest(length)
          1 (формируется low)  когда low[length]  < lowest(length)
    top фиксируется при переходе os 1→0, btm при 0→1. Свинг помечается
    на баре (n-length) — там, где экстремум.
    """
    n = len(df)
    if n < length * 2 + 2:
        return []
    high = df["high"].values
    low = df["low"].values
    # rolling highest/lowest за `length` баров (исключая текущий, как в Pine ta.highest)
    upper = df["high"].rolling(length).max().values
    lower = df["low"].rolling(length).min().values

    out = []
    os = 0
    prev_os = 0
    for i in range(length, n):
        h_l = high[i - length]   # high[length] в Pine = бар length назад от текущего
        l_l = low[i - length]
        up = upper[i] if not pd.isna(upper[i]) else h_l
        lo = lower[i] if not pd.isna(lower[i]) else l_l
        prev_os = os
        if h_l > up:
            os = 0
        elif l_l < lo:
            os = 1
        # else os unchanged
        # top при os 1→0, btm при 0→1
        if os == 0 and prev_os != 0:
            out.append((i - length, float(h_l), "H"))
        elif os == 1 and prev_os != 1:
            out.append((i - length, float(l_l), "L"))
    return out


def detect_swings(
    df: pd.DataFrame,
    major_len: int = 50,
    minor_len: int = 5,
) -> List[Swing]:
    """Двухуровневые свинги. df: OHLC (DatetimeIndex желателен).

    major (len=50) — значимая структура (BOS/CHoCH, OTE-свинг слома).
    minor (len=5)  — внутренняя структура (точки входа).
    """
    d = df.copy()
    d.columns = [c.lower() for c in d.columns]
    res: List[Swing] = []
    for length, level in ((major_len, "major"), (minor_len, "minor")):
        for idx, price, kind in _swings_luxalgo(d, length):
            ts = d.index[idx] if idx < len(d.index) else idx
            res.append(Swing(idx=idx, ts=ts, price=price, kind=kind, level=level))  # type: ignore
    res.sort(key=lambda s: s.idx)
    return res


def zigzag_atr(
    df: pd.DataFrame,
    depth: int = 11,
    dev_mult: float = 3.0,
    atr_len: int = 10,
) -> List[tuple]:
    """ZigZag «Waves» — порт OKO-SM Pine 1:1 (depth=11, dev=3 = настройки пользователя).

    Pine-точно:
      • pivot подтверждается ЧЕРЕЗ length=depth//2 баров (НЕ look-ahead): на баре i
        проверяется кандидат src[i-length] против окна [i-2length .. i] (только прошлое).
      • high-pivot имеет приоритет над low на одном баре (Pine: if iH else iL).
      • dev_thresh = atr(10)/close*100 × dev_mult (Wilder RMA, как ta.atr).
      • pivotFound: то же направление → продлить экстремум; разворот → новый свинг
        только если abs(calc_dev) > dev_thresh.
    Возвращает [(ts, price)] подтверждённых точек.
    """
    d = df.copy()
    d.columns = [c.lower() for c in d.columns]
    n = len(d)
    length = max(1, depth // 2)        # Pine: i_depth/2
    l2 = length * 2
    if n < l2 + atr_len + 2:
        return []
    high, low, close = d["high"].values, d["low"].values, d["close"].values
    # ATR Wilder RMA (как ta.atr): ewm alpha=1/period, adjust=False
    tr = pd.concat([
        d["high"] - d["low"],
        (d["high"] - d["close"].shift()).abs(),
        (d["low"] - d["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / atr_len, adjust=False).mean().values

    def pivot_at(i, hi):
        """Pine pivots(): кандидат = src[i-length], окно [i-l2 .. i] (прошлое). None если не pivot."""
        c_idx = i - length
        if c_idx < 0:
            return None
        c = high[c_idx] if hi else low[c_idx]
        for j in range(i - l2, i + 1):
            if j < 0 or j == c_idx:
                continue
            if hi and high[j] > c:
                return None
            if not hi and low[j] < c:
                return None
        return c_idx, float(c)

    pts: List[tuple] = []
    last_is_high: Optional[bool] = None
    last_price = None

    for i in range(l2, n):
        thr = (atr[i] / close[i] * 100 * dev_mult) if (not pd.isna(atr[i]) and close[i]) else 1e9
        # high приоритет (Pine: if not na(iH) ... else if not na(iL))
        ph = pivot_at(i, True)
        pl = pivot_at(i, False) if ph is None else None
        cand = (True, ph) if ph is not None else ((False, pl) if pl is not None else None)
        if cand is None:
            continue
        hi, (c_idx, price) = cand
        if last_is_high is None:
            last_is_high, last_price = hi, price
            pts.append((d.index[c_idx], price))
            continue
        if hi == last_is_high:
            # продлить экстремум в том же направлении
            if (hi and price > last_price) or (not hi and price < last_price):
                last_price = price
                pts[-1] = (d.index[c_idx], price)
        else:
            dev = abs(100 * (price - last_price) / price) if price else 0
            if dev > thr:
                last_is_high, last_price = hi, price
                pts.append((d.index[c_idx], price))
    return pts
