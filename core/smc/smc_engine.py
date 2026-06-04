"""ARCH-128 — SMC Engine: эталонный движок SMC (порт OKO-SM Pine, единый калькулятор).

Воспроизводит индикатор пользователя OKO-SM слой-в-слой. НЕ только свинги (имя
swing_service устарело 03.06 → smc_engine): ZigZag · structure HH/HL/LH/LL · BOS/CHoCH
(защищённые уровни) · Order Blocks (+mitigation) · Premium/Discount · OTE (0.5-0.79) ·
EQH/EQL · FVG (+overlap) · Эллиотт (5-волн +extension, мульти-масштаб).

Базис значимости свингов (корень «мелких свингов» DS-311 OTE):
1. swings(length) — LuxAlgo: значимый (major, len=50) vs internal (minor, len=5).
2. ZigZag с ATR-deviation: разворот ≥ k×ATR% (dev=3, depth=11). Отсекает шум.

ЕДИНЫЙ КАЛЬКУЛЯТОР (ARCH-118): combinator/features_json/сферы Bus вызывают ЭТОТ модуль,
не дублируют формулы. Источник: memory/reference_oko_sm_indicator.md, docs/PRICE_PATTERNS_LIBRARY.md.
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
    # Зона входа = 0.5-0.79 (уточнение пользователя 02.06: вход в диапазоне discount/premium,
    # не только глубокий 0.705-0.79; 0.705/0.79 — наиболее вероятные точки отскока внутри).
    o1, o2 = levels[0.5], levels[0.79]
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


def _pivots(df: "pd.DataFrame", length: int, is_high: bool) -> List[tuple]:
    """Pivot-точки (строгий left, нестрогий right — анти-дубль плато, как zigzag_atr).

    Кандидат на баре c — экстремум окна [c-length .. c+length]. Возвращает [(idx, price)].
    Используется для EQH/EQL (eq_len=3) и любой fixed-pivot разметки.
    """
    d = df
    src = d["high"].values if is_high else d["low"].values
    n = len(d)
    out: List[tuple] = []
    for c in range(length, n - length):
        val = src[c]
        ok = True
        for j in range(c - length, c + length + 1):
            if j == c:
                continue
            left = j < c
            if is_high:
                if (left and src[j] >= val) or (not left and src[j] > val):
                    ok = False; break
            else:
                if (left and src[j] <= val) or (not left and src[j] < val):
                    ok = False; break
        if ok:
            out.append((c, float(val)))
    return out


def detect_equal_levels(
    df: "pd.DataFrame",
    eq_len: int = 3,
    threshold: float = 0.1,
    atr_len: int = 200,
) -> List[tuple]:
    """EQH/EQL (LuxAlgo) — равные хаи/лоу = зоны ликвидности (скопления стопов).

    Два СОСЕДНИХ pivot(eq_len) того же типа «равны», если |Δцены| < threshold×ATR.
    EQH = равные вершины (ликвидность сверху, цель для свипа вверх); EQL = равные донья.
    Возвращает [(ts1, p1, ts2, p2, 'EQH'/'EQL')] — пары уровней.
    """
    d = df.copy()
    d.columns = [c.lower() for c in d.columns]
    tr = pd.concat([
        d["high"] - d["low"],
        (d["high"] - d["close"].shift()).abs(),
        (d["low"] - d["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / atr_len, adjust=False).mean().values
    out: List[tuple] = []
    for is_high, lab in ((True, "EQH"), (False, "EQL")):
        pv = _pivots(d, eq_len, is_high)
        for (i1, p1), (i2, p2) in zip(pv, pv[1:]):
            thr = threshold * atr[i2] if not pd.isna(atr[i2]) else 0.0
            if abs(p2 - p1) < thr:
                out.append((d.index[i1], p1, d.index[i2], p2, lab))
    return out


@dataclass(frozen=True)
class SponsoredCandle:
    ts: object               # бар SC
    idx: int                 # iloc
    top: float               # верх box (bull: max(o,c); bear: high-фитиль)
    bottom: float            # низ box (bull: low-фитиль; bear: min(o,c))
    direction: Literal["bull", "bear"]
    mt: float                # Mean Threshold = 0.5 box (крупный капитал тестит середину)
    open_level: float        # уровень открытия SC (первичная поддержка/сопротивление)
    swept: float             # пробитый экстремум (снятая ликвидность)
    broke_structure: bool    # критерий 2: импульс после = BOS (обновил экстремум)
    has_imbalance: bool      # критерий 3: FVG сразу после
    confirmed: bool          # ИСТИННЫЙ SC = свип+разворот + BOS + FVG (все 3 критерия)


def detect_sponsored_candle(
    df: "pd.DataFrame",
    lookback: int = 10,
    atr_len: int = 14,
    min_body_atr: float = 0.5,
    min_wick_frac: float = 0.3,
    confirm_bars: int = 5,
) -> List[SponsoredCandle]:
    """SC (Sponsored Candle) — свеча, СНИМАЮЩАЯ ликвидность + РАЗВОРОТ (эталон пользователя/ICT).

    Свеча-кандидат (2 условия):
      1. Снятие ликвидности: фитиль обновляет пред. экстремум (lookback), снимая стопы.
      2. Импульс-разворот: close против фитиля.
    ИСТИННЫЙ SC (confirmed) — + ещё 2 критерия (как у истинного OB):
      3. Ломает структуру: импульс после = CHoCH (для разворотной SC слом ПРОТИВ тренда =
         смена характера, НЕ BOS; пробивает противотрендовый защитный экстремум).
      4. Оставляет имбаланс: FVG сразу после свечи.

    Разметка box:
      • Bull SC (свип МИНИМУМА → вверх): top=max(o,c) [тело], bottom=low [фитиль].
      • Bear SC (свип МАКСИМУМА → вниз): top=high [фитиль], bottom=min(o,c) [тело].
    Уровни: MT (0.5 box), open_level. Поля broke_structure/has_imbalance/confirmed = критерии 3-4.
    """
    d = df.copy()
    d.columns = [c.lower() for c in d.columns]
    o, h, l, c = d["open"].values, d["high"].values, d["low"].values, d["close"].values
    n = len(d)
    tr = pd.concat([
        d["high"] - d["low"],
        (d["high"] - d["close"].shift()).abs(),
        (d["low"] - d["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / atr_len, adjust=False).mean().values

    def _confirm(i: int, bull: bool):
        """Критерии 3-4: CHoCH (слом ПРОТИВ тренда = смена характера) + FVG в окне после."""
        w_end = min(i + 1 + confirm_bars, n)
        if w_end <= i + 1:
            return False, False
        if bull:
            # bull SC свипнул МИНИМУМ (тренд был вниз) → пробой пред. HIGH вверх = CHoCH bull
            choch = h[i + 1:w_end].max() > h[i - lookback:i + 1].max()
        else:
            # bear SC свипнул МАКСИМУМ (тренд был вверх) → пробой пред. LOW вниз = CHoCH bear
            choch = l[i + 1:w_end].min() < l[i - lookback:i + 1].min()
        fvg = False                                                    # трёхсвечный имбаланс после
        for j in range(i + 1, min(i + confirm_bars, n - 1)):
            if bull and l[j + 1] > h[j - 1]:
                fvg = True; break
            if (not bull) and h[j + 1] < l[j - 1]:
                fvg = True; break
        return bool(choch), bool(fvg)

    out: List[SponsoredCandle] = []
    for i in range(lookback, n):
        if pd.isna(atr[i]) or atr[i] <= 0:
            continue
        body = abs(c[i] - o[i])
        if body < min_body_atr * atr[i]:
            continue
        prev_min = l[i - lookback:i].min()
        prev_max = h[i - lookback:i].max()
        lower_wick = min(o[i], c[i]) - l[i]
        upper_wick = h[i] - max(o[i], c[i])
        # Bull SC: фитиль снял МИНИМУМ + закрытие вверх
        if l[i] < prev_min and c[i] > o[i] and lower_wick > min_wick_frac * body:
            bos, fvg = _confirm(i, True)
            top = float(max(o[i], c[i])); bot = float(l[i])
            out.append(SponsoredCandle(d.index[i], i, top, bot, "bull",
                round((top + bot) / 2, 8), float(o[i]), float(prev_min), bos, fvg, bos and fvg))
        # Bear SC: фитиль снял МАКСИМУМ + закрытие вниз
        elif h[i] > prev_max and c[i] < o[i] and upper_wick > min_wick_frac * body:
            bos, fvg = _confirm(i, False)
            top = float(h[i]); bot = float(min(o[i], c[i]))
            out.append(SponsoredCandle(d.index[i], i, top, bot, "bear",
                round((top + bot) / 2, 8), float(o[i]), float(prev_max), bos, fvg, bos and fvg))
    return out


def detect_fvg(
    df: "pd.DataFrame",
    threshold: Optional[float] = None,
) -> List[tuple]:
    """FVG / Fair Value Gap (LuxAlgo) — трёхсвечный имбаланс (незаполненный гэп).

    bull-FVG: low[i] > high[i-2] и close[i-1] > high[i-2] → гэп ВВЕРХ (бокс high[i-2]..low[i]).
    bear-FVG: high[i] < low[i-2] и close[i-1] < low[i-2] → гэп ВНИЗ (бокс high[i]..low[i-2]).
    Фильтр значимости: Δ% > threshold (auto = средний |Δ%| × 2 — отсекает мелкие гэпы).
    mitigated = бар, где цена ЗАКРЫЛА гэп (вошла насквозь); -1 = активен.
    Возвращает [(ts_left, top, bottom, kind, ts_i, mitigated_ts_or_None)].
    Конфлюенция: FVG внутри OTE-зоны = усиление сигнала («+»).
    """
    d = df.copy()
    d.columns = [c.lower() for c in d.columns]
    high, low, close = d["high"].values, d["low"].values, d["close"].values
    n = len(d)
    raw = []
    for i in range(2, n):
        if low[i] > high[i - 2] and close[i - 1] > high[i - 2]:
            dper = (low[i] - high[i - 2]) / high[i - 2] * 100
            raw.append((i, "bull", float(low[i]), float(high[i - 2]), dper))
        elif high[i] < low[i - 2] and close[i - 1] < low[i - 2]:
            dper = (low[i - 2] - high[i]) / high[i] * 100
            raw.append((i, "bear", float(low[i - 2]), float(high[i]), dper))
    if threshold is None:
        # LuxAlgo auto: средний |gap%| по ВСЕМ барам (gap=0 где нет) × 2. Считать
        # только по FVG-барам НЕЛЬЗЯ — редкие крупные гэпы задирают порог и режут валидные.
        allgaps = [max(0.0, low[i] - high[i - 2], low[i - 2] - high[i]) / close[i] * 100
                   for i in range(2, n)]
        threshold = (sum(allgaps) / len(allgaps)) * 2 if allgaps else 0.0
    out = []
    for i, kind, top, bottom, dper in raw:
        if dper <= threshold:
            continue
        mit = None
        for j in range(i + 1, n):
            # mitigation по CLOSE за противоположной границей (полное закрытие гэпа),
            # НЕ касание фитилём — иначе тренд закрывает валидные FVG откатами.
            if kind == "bull" and close[j] < bottom:
                mit = d.index[j]; break
            if kind == "bear" and close[j] > top:
                mit = d.index[j]; break
        out.append((d.index[i - 2], top, bottom, kind, d.index[i], mit))
    return out


def detect_fvg_overlap(
    df: "pd.DataFrame",
    threshold: Optional[float] = None,
) -> List[dict]:
    """Перекрытие bull×bear FVG = ПОТЕНЦИАЛЬНЫЙ разворот (НЕ гарантия — наблюдать).

    bull-FVG перекрывает bear-FVG (bull сформирован ПОЗЖЕ, зоны пересекаются) → bull-импульс
    снял bear-сопротивление → возможный разворот ВВЕРХ. Bear часто уже mitigated (его и
    закрыл этот bull). Зеркально: bear перекрыл bull → разворот ВНИЗ.
    held = зона перекрытия удержалась (после формирования цена не закрылась за противоположной
    границей зоны) — подтверждение, что разворот пока в силе. Правило пользователя 03.06:
    сигнал вероятностный, требует наблюдения за откатом, не вход «вслепую».
    Возвращает [dict(lo, hi, direction 'up'/'down', since_ts, held, bull, bear)].
    """
    fvgs = detect_fvg(df, threshold)
    close = df["close"].values
    n = len(df)
    pos = {ts: i for i, ts in enumerate(df.index)}
    def lohi(f):
        return min(f[1], f[2]), max(f[1], f[2])
    bulls = [f for f in fvgs if f[3] == "bull"]
    bears = [f for f in fvgs if f[3] == "bear"]
    out: List[dict] = []
    # bull(активный) перекрыл bear(любой) → разворот вверх
    for bu in [f for f in bulls if f[5] is None]:
        bl, bh = lohi(bu)
        for be in bears:
            rl, rh = lohi(be)
            if bl <= rh and rl <= bh and bu[4] > be[4]:
                lo, hi = max(bl, rl), min(bh, rh)
                i0 = pos[bu[4]]
                held = all(close[j] >= lo for j in range(i0 + 1, n)) if i0 + 1 < n else True
                out.append(dict(lo=lo, hi=hi, direction="up", since=bu[4], held=held, bull=bu, bear=be))
    # bear(активный) перекрыл bull(любой) → разворот вниз
    for be in [f for f in bears if f[5] is None]:
        rl, rh = lohi(be)
        for bu in bulls:
            bl, bh = lohi(bu)
            if bl <= rh and rl <= bh and be[4] > bu[4]:
                lo, hi = max(bl, rl), min(bh, rh)
                i0 = pos[be[4]]
                held = all(close[j] <= hi for j in range(i0 + 1, n)) if i0 + 1 < n else True
                out.append(dict(lo=lo, hi=hi, direction="down", since=be[4], held=held, bull=bu, bear=be))
    return out


def detect_elliott_impulse(zz: List[tuple]) -> List[dict]:
    """ARCH-128 — Эллиотт: 5-волновой импульс на ZigZag (1-3-5 импульсные, 2-4 коррекции).

    Окно из 6 ZigZag-точек = 5 волн. Hard-правила Эллиотта (обязательные):
      R1. Волна 2 не откатывает ЗА начало волны 1.
      R2. Волна 3 НЕ самая короткая из (1,3,5).
      R3. Волна 4 не заходит в территорию волны 1 (не перекрывает её конец).
    bull-импульс (вверх): точки L,H,L,H,L,H; bear (вниз): H,L,H,L,H,L.
    Большая волновая фибо строится на всём импульсе (точка0 → точка5) → откат к OTE.
    Возвращает [dict(waves=[(ts,price)×6], direction, lens=(w1,w3,w5))]. Самый свежий — последний.
    """
    typed = _zz_typed(zz)
    out: List[dict] = []
    for i in range(len(typed) - 5):
        seg = typed[i:i + 6]
        kinds = [t for _, _, t in seg]
        ps = [p for _, p, _ in seg]
        ts = [t for t, _, _ in seg]
        p0, p1, p2, p3, p4, p5 = ps
        if kinds == ["L", "H", "L", "H", "L", "H"]:
            # bull: w2 выше старта (R1), w3 новый max + не перекрытие w1 (R3), w5 новый max
            if not (p1 > p0 and p2 > p0 and p3 > p1 and p4 > p1 and p5 > p3):
                continue
            l1, l3, l5 = p1 - p0, p3 - p2, p5 - p4
            direction = "up"
        elif kinds == ["H", "L", "H", "L", "H", "L"]:
            if not (p1 < p0 and p2 < p0 and p3 < p1 and p4 < p1 and p5 < p3):
                continue
            l1, l3, l5 = p0 - p1, p2 - p3, p4 - p5
            direction = "down"
        else:
            continue
        if l3 < l1 and l3 < l5:        # R2: волна 3 не самая короткая
            continue
        # EXTENSION волны 5: продлить до финального экстремума. Волна 5 часто расширяется
        # под-волнами (GRT 15m: 19:30 → откат 21:30 → новое дно 23:15). Тянем точку 5 до
        # последнего low(bear)/high(bull), пока цена не развернулась ЗА волну 4 (конец импульса).
        w5_ts, w5_p = ts[5], ps[5]
        k = i + 6
        while k < len(typed):
            kt, kp, kk = typed[k]
            if direction == "down":
                if kk == "H" and kp > p4:        # разворот вверх за волну 4 = импульс закончен
                    break
                if kk == "L" and kp < w5_p:       # новое дно — продлеваем волну 5
                    w5_ts, w5_p = kt, kp
            else:
                if kk == "L" and kp < p4:
                    break
                if kk == "H" and kp > w5_p:
                    w5_ts, w5_p = kt, kp
            k += 1
        l5 = abs(w5_p - p4)
        # Фибо-соотношения волн (docs/ENCYCLOPEDIA.md «Волновая теория Эллиотта»):
        #   w2 откат 0.618-0.786 волны 1 = классика (OTE SHORT/LONG); w4 откат ~0.382 волны 3;
        #   w3 расширение ≥1.618 волны 1 = сильный импульс. textbook = все три в норме.
        w2_retr = abs(p2 - p1) / l1 if l1 else 0.0
        w4_retr = abs(p4 - p3) / l3 if l3 else 0.0
        w3_ext = l3 / l1 if l1 else 0.0
        textbook = (0.5 <= w2_retr <= 0.886) and (0.236 <= w4_retr <= 0.618) and w3_ext >= 1.3
        waves = [(ts[k2], ps[k2]) for k2 in range(5)] + [(w5_ts, w5_p)]
        out.append(dict(waves=waves, direction=direction,
                        lens=(l1, l3, l5), w2_retr=round(w2_retr, 3), w4_retr=round(w4_retr, 3),
                        w3_ext=round(w3_ext, 3), textbook=textbook))
    return out


def detect_elliott_mtf(df: "pd.DataFrame", devs: tuple = (3.0, 5.0, 8.0)) -> List[dict]:
    """Эллиотт на НЕСКОЛЬКИХ масштабах ZigZag — волновой мульти-масштаб (фрактальность).

    Одно движение на мелком dev = под-волны (не проходит правила), на крупном = чистый
    импульс. Перебираем dev → собираем импульсы с пометкой scale. GRT 02.06: на 1m dev=3
    импульса нет (под-волны), на 15m — есть. Каждый импульс несёт 'scale'=dev (масштаб волны).
    Возвращает [dict(... + scale)], от мелкого масштаба к крупному.
    """
    res: List[dict] = []
    for dev in devs:
        zz = zigzag_atr(df, 11, float(dev))
        for imp in detect_elliott_impulse(zz):
            imp = dict(imp); imp["scale"] = dev
            res.append(imp)
    return res


def _zz_typed(zz: List[tuple]) -> List[tuple]:
    """ZigZag-точки с типом H/L (строгое чередование). [(ts, price, 'H'/'L')].

    ZigZag по построению чередует вершины/донья. Тип первой определяется сравнением
    со второй, дальше чередование. Нужен для структурного анализа (HH/HL/LH/LL, слом).
    """
    if not zz:
        return []
    if len(zz) == 1:
        return [(zz[0][0], zz[0][1], "H")]
    first_is_high = zz[0][1] > zz[1][1]
    out = []
    for k, (ts, p) in enumerate(zz):
        is_high = first_is_high == (k % 2 == 0)
        out.append((ts, p, "H" if is_high else "L"))
    return out


def find_setups_zz(zz: List[tuple], df: "pd.DataFrame") -> List[dict]:
    """ARCH-128 ЯДРО АВТОПОИСКА — сетапы на ZigZag-структуре (точные вершины LuxAlgo пропускает).

    Перебирает ВСЕ значимые сломы (не «последний CHoCH»). Слом структуры на ZigZag:
      • новый zz-high > предыдущего zz-high → пробой хая вверх (bull).
          trend<0 (была нисходящая LL/LH) → CHoCH (смена характера); иначе BOS (продолжение).
      • новый zz-low < предыдущего zz-low → пробой лоу вниз (bear). Симметрично.
    ИМПУЛЬС СЛОМА (для фибо) = тот, что пробил структуру: от zz-экстремума-начала
    (low перед bull-сломом / high перед bear-сломом) до zz-вершины слома. На GRT 02.06:
    LL 19:33(0.02284) → H 19:53(0.02348) пробил LH 19:00(0.02342) = bull-CHoCH, OTE near low.

    Логика BOS/CHoCH/trend — LuxAlgo; источник свингов — ZigZag (точнее swings(50)).
    Возвращает [dict] (build_ote + from/to/kind/struct/choch_ts/broken_level), хронологически.
    """
    typed = _zz_typed(zz)
    if len(typed) < 3:
        return []
    setups: List[dict] = []
    trend = 0
    # ЗАЩИТНЫЕ структурные уровни (держатся, пока тренд жив — НЕ сосед):
    #   prot_high — пробой вверх = bull-слом; prot_low — пробой вниз = bear-слом.
    # cand_* — последний swing того же типа (кандидат: начало импульса слома + новый защитный).
    prot_high: Optional[tuple] = None   # (ts, price)
    prot_low: Optional[tuple] = None
    cand_high: Optional[tuple] = None
    cand_low: Optional[tuple] = None
    for ts, p, t in typed:
        if t == "H":
            if prot_high is not None and p > prot_high[1]:
                # пробой защитного high → bull-слом. CHoCH если был нисходящий тренд, иначе BOS.
                kind = "CHoCH" if trend < 0 else "BOS"
                if cand_low is not None:
                    lp, hp = cand_low[1], p
                    ote = build_ote(hp, lp)                 # 0=high(конец), 1=low(начало) → long, near low
                    ote["from"], ote["to"] = (cand_low[0], lp), (ts, hp)
                    ote.update(kind=kind, struct="bull", choch_ts=ts,
                               broken_level=prot_high[1], broken_ts=prot_high[0])
                    setups.append(ote)
                trend = 1
                prot_high = (ts, p)
                if cand_low is not None:
                    prot_low = cand_low      # защитный low поднят на HL подтверждённой структуры
            elif prot_high is None:
                prot_high = (ts, p)
            cand_high = (ts, p)
        else:
            if prot_low is not None and p < prot_low[1]:
                kind = "CHoCH" if trend > 0 else "BOS"
                if cand_high is not None:
                    hp, lp = cand_high[1], p
                    ote = build_ote(lp, hp)                 # 0=low(конец), 1=high(начало) → short, near high
                    ote["from"], ote["to"] = (cand_high[0], hp), (ts, lp)
                    ote.update(kind=kind, struct="bear", choch_ts=ts,
                               broken_level=prot_low[1], broken_ts=prot_low[0])
                    setups.append(ote)
                trend = -1
                prot_low = (ts, p)
                if cand_high is not None:
                    prot_high = cand_high
            elif prot_low is None:
                prot_low = (ts, p)
            cand_low = (ts, p)
    return setups


def append_provisional_leg(zz: List[tuple], df: "pd.DataFrame") -> tuple:
    """LIVE: дорисовывает ТЕКУЩУЮ формирующуюся ногу как НЕПОДТВЕРЖДЁННЫЙ pivot.

    Решает критичный лаг zigzag (zigzag_lag_live_critical): последняя нога подтверждается
    только через depth//2 баров (4h=20ч!), поэтому live-движок СЛЕП к свежему слому.
    Provisional = текущий rolling-экстремум после последней zz-точки = то, что трейдер
    рисует ГЛАЗОМ+рукой, не дожидаясь индикатора. Проверено XLM 1h: воспроизводит
    ручную SHORT-OTE пользователя до фибо (все 6 уровней совпали).

    Возвращает (zz_extended, provisional_ts | None). Если новой ноги нет — (zz, None).
    """
    if not zz:
        return zz, None
    typed = _zz_typed(zz)
    if not typed:
        return zz, None
    last_ts, last_p, last_t = typed[-1]
    pos = {ts: i for i, ts in enumerate(df.index)}
    li = pos.get(last_ts)
    if li is None or li >= len(df) - 1:
        return zz, None
    after = df.iloc[li + 1:]
    if last_t == "H":                                   # формируется LOW
        pi = li + 1 + int(after["low"].values.argmin()); pp = float(after["low"].min())
        if pp >= last_p:
            return zz, None                             # не ниже последней H → нет новой ноги
    else:                                               # формируется HIGH
        pi = li + 1 + int(after["high"].values.argmax()); pp = float(after["high"].max())
        if pp <= last_p:
            return zz, None
    prov_ts = df.index[pi]
    return list(zz) + [(prov_ts, pp)], prov_ts


def ote_retest_setups(
    df: "pd.DataFrame",
    *,
    dev_mult: float = 3.0,
    retest_bars: int = 60,
    only_choch: bool = True,
    depth: int = 11,
    provisional: bool = False,
) -> List[dict]:
    """ARCH-128 — OTE-Retest Engine (ядро): слом → импульс → OTE → РЕТЕСТ → вход+стоп+конфлюенция.

    Логика входа (метод пользователя):
      1. Значимый слом структуры (CHoCH) — `find_setups_zz`.
      2. Импульс слома → OTE-зона 0.5-0.79 (`build_ote`).
      3. РЕТЕСТ: первый бар ПОСЛЕ слома, где цена вернулась в OTE-зону (откат).
      4. КОНФЛЮЕНЦИЯ: OB/FVG той же стороны внутри OTE = усиление (+/++).
      5. ВХОД = середина OTE (0.645), СТОП за 1.0 (начало импульса) + буфер.
    direction: long (bull-CHoCH, OTE near low) / short (bear-CHoCH, near high).
    Возвращает [dict(choch_ts, entry_ts, entry, sl, risk, direction, ote, confluence, from, to)].
    TP не считается здесь — отдельный слой (магниты/фибо/пивоты).
    """
    zz = zigzag_atr(df, depth, dev_mult)
    prov_ts = None
    if provisional:
        zz, prov_ts = append_provisional_leg(zz, df)   # live: дорисовать текущую ногу
    setups = find_setups_zz(zz, df)
    breaks = detect_structure_breaks(df)
    obs = detect_order_blocks(df, breaks)
    fvgs = detect_fvg(df)
    pos = {ts: i for i, ts in enumerate(df.index)}
    low_a, high_a = df["low"].values, df["high"].values
    n = len(df)
    out: List[dict] = []

    for s in setups:
        if only_choch and s.get("kind") != "CHoCH":
            continue
        ote_lo, ote_hi = s["ote"]
        direction = s["direction"]            # long / short
        ci = pos.get(s["choch_ts"])
        if ci is None:
            continue
        # 3. РЕТЕСТ — первый бар после слома, коснувшийся OTE-зоны
        entry_i = None
        for j in range(ci + 1, min(ci + 1 + retest_bars, n)):
            if low_a[j] <= ote_hi and high_a[j] >= ote_lo:
                entry_i = j
                break
        if entry_i is None:
            continue
        entry = (ote_lo + ote_hi) / 2.0       # середина зоны (~0.645)
        # 4. КОНФЛЮЕНЦИЯ — OB/FVG той же стороны в OTE-зоне
        want = "bull" if direction == "long" else "bear"
        confl = 0
        for ob in obs:
            if ob.kind == want and min(ob.top, ob.bottom) <= ote_hi and max(ob.top, ob.bottom) >= ote_lo:
                confl += 1
        for fv in fvgs:
            ftop, fbot = max(fv[1], fv[2]), min(fv[1], fv[2])
            if fv[3] == want and fbot <= ote_hi and ftop >= ote_lo:
                confl += 1
        # 5. СТОП за 1.0 (начало импульса = s['to'] для long(низ)? — точка 1.0 build_ote)
        one_level = s["levels"][1.0]          # 1.0 = начало импульса
        sl = one_level
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        out.append(dict(
            choch_ts=s["choch_ts"], entry_ts=df.index[entry_i], entry=round(entry, 8),
            sl=round(sl, 8), risk=round(risk, 8), direction=direction,
            ote=(ote_lo, ote_hi), confluence=confl, **{"from": s["from"], "to": s["to"]},
            unconfirmed=bool(prov_ts is not None and s["to"][0] == prov_ts),  # provisional нога
        ))
    return out


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
            # Анти-дубль плато: слева СТРОГО (>=/<=  отменяет), справа нестрого (>/<).
            # На ровном плато проходит только ПЕРВЫЙ бар; если слева есть равный —
            # не пивот (убирает лишние zz-точки 18:06/18:36 GRT 02.06, сохраняя значимые).
            left = j < c_idx
            if hi:
                if left and high[j] >= c:
                    return None
                if not left and high[j] > c:
                    return None
            else:
                if left and low[j] <= c:
                    return None
                if not left and low[j] < c:
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
