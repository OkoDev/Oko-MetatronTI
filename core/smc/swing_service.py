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
    ts: object            # бар пробоя
    idx: int              # бар пробоя (iloc)
    price: float          # пробитый уровень (swing)
    kind: Literal["BOS", "CHoCH"]
    direction: Literal["bull", "bear"]
    has_volume: bool      # объём на пробое выше среднего (критерий настоящего слома)
    from_idx: int = -1    # бар свинга-уровня (откуда тянуть линию до пробоя)


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
    # храним (confirm_idx, swing_idx, price) — swing_idx = откуда тянуть линию
    highs = sorted([(idx + length, idx, price) for idx, price, k in sw if k == "H"])
    lows = sorted([(idx + length, idx, price) for idx, price, k in sw if k == "L"])

    out: List[StructureBreak] = []
    trend = 0
    top_y: Optional[float] = None
    btm_y: Optional[float] = None
    top_from = btm_from = -1
    top_cross = btm_cross = False
    hi_ptr = lo_ptr = 0
    for i in range(n):
        while hi_ptr < len(highs) and highs[hi_ptr][0] <= i:
            top_y = highs[hi_ptr][2]; top_from = highs[hi_ptr][1]; top_cross = True; hi_ptr += 1
        while lo_ptr < len(lows) and lows[lo_ptr][0] <= i:
            btm_y = lows[lo_ptr][2]; btm_from = lows[lo_ptr][1]; btm_cross = True; lo_ptr += 1
        has_vol = bool(vol is not None and not pd.isna(vol_avg[i]) and vol[i] > vol_avg[i] * vol_mult)
        if top_y is not None and top_cross and close[i] > top_y:
            kind = "CHoCH" if trend < 0 else "BOS"
            out.append(StructureBreak(d.index[i], i, float(top_y), kind, "bull", has_vol, top_from))  # type: ignore
            top_cross = False
            trend = 1
        elif btm_y is not None and btm_cross and close[i] < btm_y:
            kind = "CHoCH" if trend > 0 else "BOS"
            out.append(StructureBreak(d.index[i], i, float(btm_y), kind, "bear", has_vol, btm_from))  # type: ignore
            btm_cross = False
            trend = -1
    return out


@dataclass(frozen=True)
class OrderBlock:
    left_idx: int         # бар OB-свечи (левый край бокса)
    top: float
    bottom: float
    kind: Literal["bull", "bear"]
    break_idx: int        # бар слома, при котором OB сформирован
    mitigated_idx: int = -1   # бар пробоя OB (close за боксом) → невалиден; -1 = активен
    is_breaker: bool = False  # пробитый OB сменил роль (breaker block)


def detect_order_blocks(
    df: pd.DataFrame,
    breaks: List["StructureBreak"],
    atr_len: int = 200,
) -> List[OrderBlock]:
    """Order Blocks (LuxAlgo ob_coord): при сломе структуры — последняя «спокойная»
    свеча (размер < 2×ATR) с экстремумом в интервале [свинг..пробой].

    bull-слом → bullish OB = lowest-свеча (поддержка, институционал покупал).
    bear-слом → bearish OB = highest-свеча (сопротивление).
    OB-бокс = (high, low) той свечи. Фильтр Atr (ta.atr(200)).
    """
    d = df.copy()
    d.columns = [c.lower() for c in d.columns]
    high, low = d["high"].values, d["low"].values
    tr = pd.concat([
        d["high"] - d["low"],
        (d["high"] - d["close"].shift()).abs(),
        (d["low"] - d["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / atr_len, adjust=False).mean().values

    out: List[OrderBlock] = []
    for b in breaks:
        loc = b.from_idx if b.from_idx >= 0 else b.idx
        a, z = min(loc, b.idx), max(loc, b.idx)
        if z - a < 1:
            continue
        best_idx = None
        best_val = None
        for i in range(a, z + 1):
            if (high[i] - low[i]) >= (atr[i] if not pd.isna(atr[i]) else 1e9) * 2:
                continue   # волатильная свеча — пропуск (фильтр Atr)
            if b.direction == "bull":
                if best_val is None or low[i] < best_val:
                    best_val = low[i]; best_idx = i
            else:
                if best_val is None or high[i] > best_val:
                    best_val = high[i]; best_idx = i
        if best_idx is None:
            continue
        ob_top, ob_btm = float(high[best_idx]), float(low[best_idx])
        # mitigation: первый бар ПОСЛЕ слома, где close пробивает OB (LuxAlgo remove)
        close_arr = d["close"].values
        mit = -1
        for j in range(b.idx + 1, len(d)):
            if b.direction == "bull" and close_arr[j] < ob_btm:
                mit = j; break
            if b.direction == "bear" and close_arr[j] > ob_top:
                mit = j; break
        out.append(OrderBlock(best_idx, ob_top, ob_btm, b.direction, b.idx, mit))  # type: ignore
    return out


def active_order_blocks(obs: List[OrderBlock], n_bars: int, per_side: int = 5) -> List[OrderBlock]:
    """Только ВАЛИДНЫЕ OB к концу данных (непробитые), последние per_side каждого типа.

    Как LuxAlgo: пробитый OB удаляется (mitigated_idx != -1 и < n_bars). Показываем
    активные (mitigated_idx == -1) — последние per_side bull + per_side bear.
    """
    active = [o for o in obs if o.mitigated_idx == -1]
    bull = [o for o in active if o.kind == "bull"][-per_side:]
    bear = [o for o in active if o.kind == "bear"][-per_side:]
    return sorted(bull + bear, key=lambda o: o.left_idx)


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


def premium_discount(top: float, btm: float) -> dict:
    """Premium/Discount/Equilibrium зоны (LuxAlgo) — упрощённое Фибо-деление диапазона.

    top = Strong High (trail_up), btm = Weak Low (trail_dn). Связь с Фибо:
      equilibrium ≈ 0.5; discount = нижняя зона (где OTE-LONG 0.705-0.786);
      premium = верхняя (где OTE-SHORT). Грубая рамка «где торговать»:
      покупать в discount, продавать в premium.
    """
    return {
        "premium": (0.95 * top + 0.05 * btm, top),                       # верх
        "equilibrium": (0.475 * top + 0.525 * btm, 0.525 * top + 0.475 * btm),  # ~0.5
        "discount": (btm, 0.95 * btm + 0.05 * top),                      # низ
        "eq_mid": (top + btm) / 2,
    }


def build_ote(swing_a: float, swing_b: float) -> dict:
    """OTE/Fib от импульса swing_a → swing_b (как разметка пользователя на XLM).

    Fib: 0 = swing_a (начало импульса), 1 = swing_b (конец). Уровни между.
    OTE-зона = 0.705-0.786 (Optimal Trade Entry — глубокий откат к началу).
    Пример пользователя (импульс вниз high 0.22928→low 0.21478):
      0.382=0.22127, 0.5=0.22003, 0.618=0.21879, 0.705=0.21787, 0.786=0.21702.

    direction вычисляется из знака: swing_a>swing_b → импульс ВНИЗ → откат вверх (LONG-сетап,
    OTE снизу). swing_a<swing_b → импульс ВВЕРХ → SHORT-сетап.
    Возвращает {'levels': {fib: price}, 'ote': (low, high), 'direction': 'long'/'short'}.
    """
    rng = swing_b - swing_a
    # Набор уровней пользователя (TradingView OTE): 0.5/0.62/0.705/0.79
    fibs = [0.0, 0.5, 0.62, 0.705, 0.79, 1.0]
    levels = {f: swing_a + f * rng for f in fibs}
    # OTE-зона = 0.705-0.79 (как разметка пользователя)
    o1, o2 = levels[0.705], levels[0.79]
    ote = (min(o1, o2), max(o1, o2))
    direction = "long" if swing_a > swing_b else "short"   # импульс вниз → ждём LONG из OTE
    return {"levels": levels, "ote": ote, "direction": direction}


def find_choch_ote(
    breaks: List["StructureBreak"],
    df_for_swings: Optional["pd.DataFrame"] = None,
    swing_len: int = 20,
) -> Optional[dict]:
    """OTE на ЗНАЧИМОМ импульсе, что ВЫЗВАЛ последний CHoCH (механика пользователя).

    bull-CHoCH: импульс ВВЕРХ (последний swing low → swing high, что пробил структуру)
        → OTE near low → LONG (ждём откат вниз в OTE для покупки).
    bear-CHoCH: импульс ВНИЗ (swing high → swing low) → OTE near high → SHORT.
    Импульс = «первый левый от низа до верха» (значимая нога, не последняя мелкая).
    0=КОНЕЦ импульса, 1=НАЧАЛО. Торговля вероятностей — цена может НЕ зайти в OTE.
    """
    chochs = [b for b in breaks if b.kind == "CHoCH"]
    if not chochs:
        return None
    b = chochs[-1]
    # ЗНАЧИМЫЙ импульс, что вызвал CHoCH: структурные swing-точки ДО слома.
    sw = _swings_luxalgo(df_for_swings, swing_len) if (df_for_swings is not None) else []
    pts = [(i, p, k) for i, p, k in sw if df_for_swings.index[i] <= b.ts]
    if len(pts) < 2:
        return None
    highs = [(i, p) for i, p, k in pts if k == "H"]
    lows = [(i, p) for i, p, k in pts if k == "L"]
    low_arr = df_for_swings["low"].values
    high_arr = df_for_swings["high"].values
    if b.direction == "bull":
        # bull-CHoCH: импульс = ПОСЛЕДНЯЯ восходящая волна (дно→вершина).
        # вершина = последний swing high перед сломом; дно = минимум low от предыдущей
        # вершины до этой (самый глубокий LL, с которого начался рост — «от низа до верха»).
        if not highs:
            return None
        hi, hp = highs[-1]
        prev_hi = highs[-2][0] if len(highs) >= 2 else 0
        seg_lows = low_arr[prev_hi:hi + 1]
        if len(seg_lows) == 0:
            return None
        rel = int(seg_lows.argmin()); li = prev_hi + rel; lp = float(low_arr[li])
        ote = build_ote(hp, lp)               # 0=high(конец), 1=low(начало) → long, OTE near low
        ote["from"], ote["to"] = (df_for_swings.index[li], lp), (df_for_swings.index[hi], hp)
    else:
        # bear-CHoCH: импульс = последняя нисходящая волна (вершина→дно).
        if not lows:
            return None
        li, lp = lows[-1]
        prev_lo = lows[-2][0] if len(lows) >= 2 else 0
        seg_highs = high_arr[prev_lo:li + 1]
        if len(seg_highs) == 0:
            return None
        rel = int(seg_highs.argmax()); hi = prev_lo + rel; hp = float(high_arr[hi])
        ote = build_ote(lp, hp)               # 0=low(конец), 1=high(начало) → short, OTE near high
        ote["from"], ote["to"] = (df_for_swings.index[hi], hp), (df_for_swings.index[li], lp)
    ote["choch"] = b
    return ote


def last_swing_leg_ote(df: pd.DataFrame, length: int = 20) -> Optional[dict]:
    """OTE от последней ЗНАЧИМОЙ последовательной ноги структуры (привязка к swing H/L).

    Импульс = две последние СОСЕДНИЕ swing-точки (swings(length)) — реальная нога
    high→low или low→high, привязанная к экстремумам (не глобальный поиск, не мелкая
    ZigZag-нога). bull (нога вниз high→low) → OTE near low; bear (вверх) → near high.
    """
    sw = _swings_luxalgo(df, length)   # [(idx, price, 'H'/'L')] в порядке времени
    if len(sw) < 2:
        return None
    (ai, ap, ak), (ci, cp, ck) = sw[-2], sw[-1]   # последняя нога: ap=начало, cp=конец
    a_ts, c_ts = df.index[ai], df.index[ci]
    # Правило пользователя: 0 = КОНЕЦ импульса (cp), 1 = НАЧАЛО (ap). Откат к началу.
    #   нога low→high (импульс ВВЕРХ) → 0=high, 1=low → OTE near low → LONG (откат вниз)
    #   нога high→low (импульс ВНИЗ)  → 0=low, 1=high → OTE near high → SHORT (откат вверх)
    ote = build_ote(cp, ap)
    ote["from"], ote["to"] = (a_ts, ap), (c_ts, cp)   # наклонная: начало→конец (реальное направление)
    ote["leg"] = f"{ak}->{ck}"
    return ote


def last_impulse_ote(zz: List[tuple]) -> Optional[dict]:
    """Авто-OTE от последнего завершённого импульса ZigZag (нога high→low или low→high).

    zz = точки ZigZag [(ts, price)]. Берёт последнюю ногу (zz[-2]→zz[-1]) как импульс,
    строит OTE. direction='long' если нога вниз (откат вверх = LONG-сетап).
    Возвращает dict build_ote + {'from': (ts,price), 'to': (ts,price)} или None.
    """
    if not zz or len(zz) < 2:
        return None
    (a_ts, a), (b_ts, b) = zz[-2], zz[-1]
    res = build_ote(a, b)
    res["from"] = (a_ts, a)
    res["to"] = (b_ts, b)
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
