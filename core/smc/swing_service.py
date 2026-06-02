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


@dataclass(frozen=True)
class StructureBreak:
    ts: object
    idx: int
    price: float          # пробитый уровень (swing)
    kind: Literal["BOS", "CHoCH"]
    direction: Literal["bull", "bear"]
    has_volume: bool      # объём на пробое выше среднего (критерий настоящего слома)


def detect_structure_breaks(
    df: pd.DataFrame,
    length: int = 50,
    vol_len: int = 20,
    vol_mult: float = 1.2,
) -> List[StructureBreak]:
    """BOS/CHoCH (LuxAlgo) + критерий пользователя: пробой + ОБЪЁМ + закрепление.

    LuxAlgo: close пробивает последний swing high (bull) / low (bear).
      BOS   = пробой ПО тренду (продолжение)
      CHoCH = первый пробой ПРОТИВ тренда (смена характера)
    Критерий пользователя (настоящий слом): закрепление = пробой по CLOSE (тело, не
    фитиль — уже в LuxAlgo) + объём на баре пробоя > среднего (has_volume=True).
    """
    d = df.copy()
    d.columns = [c.lower() for c in d.columns]
    n = len(d)
    close = d["close"].values
    vol = d["volume"].values if "volume" in d.columns else None
    vol_avg = (pd.Series(vol).rolling(vol_len).mean().values if vol is not None else None)
    sw = _swings_luxalgo(d, length)   # [(idx, price, 'H'/'L')], idx = экстремум
    # активируем уровень с бара (idx + length) — момент подтверждения свинга (как Pine)
    highs = sorted([(idx + length, price) for idx, price, k in sw if k == "H"])
    lows = sorted([(idx + length, price) for idx, price, k in sw if k == "L"])

    out: List[StructureBreak] = []
    trend = 0
    top_y: Optional[float] = None
    btm_y: Optional[float] = None
    top_cross = btm_cross = False
    hi_ptr = lo_ptr = 0
    for i in range(n):
        # обновить активные swing-уровни, подтверждённые к бару i
        while hi_ptr < len(highs) and highs[hi_ptr][0] <= i:
            top_y = highs[hi_ptr][1]; top_cross = True; hi_ptr += 1
        while lo_ptr < len(lows) and lows[lo_ptr][0] <= i:
            btm_y = lows[lo_ptr][1]; btm_cross = True; lo_ptr += 1
        has_vol = bool(vol is not None and not pd.isna(vol_avg[i]) and vol[i] > vol_avg[i] * vol_mult)
        # bull break: close пробил swing high
        if top_y is not None and top_cross and close[i] > top_y:
            kind = "CHoCH" if trend < 0 else "BOS"
            out.append(StructureBreak(d.index[i], i, float(top_y), kind, "bull", has_vol))  # type: ignore
            top_cross = False
            trend = 1
        # bear break: close пробил swing low
        elif btm_y is not None and btm_cross and close[i] < btm_y:
            kind = "CHoCH" if trend > 0 else "BOS"
            out.append(StructureBreak(d.index[i], i, float(btm_y), kind, "bear", has_vol))  # type: ignore
            btm_cross = False
            trend = -1
    return out


def classify_structure(df: pd.DataFrame, length: int = 50) -> List[tuple]:
    """Swing Structure HH/HL/LH/LL (LuxAlgo, «Show Swings Points = length»).

    swings(length) → классификация по предыдущему экстремуму того же типа:
      swing-high: HH если > пред. high, иначе LH
      swing-low:  LL если < пред. low,  иначе HL
    Возвращает [(ts, price, label)] где label ∈ {HH,HL,LH,LL}. Отдельный слой
    от ZigZag (структурные точки, не волновая линия).
    """
    raw = _swings_luxalgo(df, length)   # [(idx, price, 'H'/'L')]
    out: List[tuple] = []
    prev_high: Optional[float] = None
    prev_low: Optional[float] = None
    for idx, price, kind in raw:
        if kind == "H":
            label = "HH" if (prev_high is not None and price > prev_high) else ("LH" if prev_high is not None else "HH")
            prev_high = price
        else:
            label = "LL" if (prev_low is not None and price < prev_low) else ("HL" if prev_low is not None else "LL")
            prev_low = price
        ts = df.index[idx] if idx < len(df.index) else idx
        out.append((ts, float(price), label))
    return out


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
