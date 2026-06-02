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
    """ZigZag с ATR-deviation порогом (OKO-SM "Waves").

    Свинг = pivot (выше/ниже всех ±depth/2) И разворот от пред. пивота ≥ dev_thresh,
    где dev_thresh = atr(atr_len)/close*100 × dev_mult. Возвращает [(ts, price)].
    """
    d = df.copy()
    d.columns = [c.lower() for c in d.columns]
    n = len(d)
    half = max(1, depth // 2)
    if n < depth + atr_len + 2:
        return []
    high, low, close = d["high"].values, d["low"].values, d["close"].values
    # ATR (Wilder упрощённо через TR rolling mean)
    tr = pd.concat([
        d["high"] - d["low"],
        (d["high"] - d["close"].shift()).abs(),
        (d["low"] - d["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(atr_len).mean().values

    def is_pivot(i, hi):
        c = high[i] if hi else low[i]
        for j in range(max(0, i - half), min(n, i + half + 1)):
            if j == i:
                continue
            if hi and high[j] > c:
                return False
            if not hi and low[j] < c:
                return False
        return True

    pts: List[tuple] = []
    last_price = close[half]
    for i in range(half, n - half):
        thr = (atr[i] / close[i] * 100 * dev_mult) if (not pd.isna(atr[i]) and close[i]) else 1e9
        for hi in (True, False):
            if is_pivot(i, hi):
                price = high[i] if hi else low[i]
                dev = abs(100 * (price - last_price) / price) if price else 0
                if not pts or dev > thr:
                    pts.append((d.index[i], float(price)))
                    last_price = price
                break
    return pts
