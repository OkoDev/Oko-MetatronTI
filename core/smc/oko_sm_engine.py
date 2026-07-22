# -*- coding: utf-8 -*-
"""OKO-SM ENGINE — точный порт структурного ядра индикатора Егора «OKO - SM» v163 (23.07).

Источник: docs/reference/OkoSM_v163.pine (Pine v5, LuxAlgo SMC-архитектура, калибровка Егора).
Портировано 1:1:
  swings(len)        — свинг-детекция: os-машина по ta.highest/lowest, точка = bar len назад;
  структурная машина — swing(len=50) + internal(len=5), CHoCH/BOS на crossover(close, level),
                       trend/itrend, trail_up/trail_dn (Strong High / Weak Low).
Нога (импульс) для OTE: trend=1 → (последний len50-btm ИЛИ Weak Low) → Strong High;
                        trend=-1 → (последний len50-top ИЛИ Strong High) → Weak Low.

Верификация: события CHoCH/BOS обязаны совпадать с метками OKO-SM на графике Егора
(data_get_pine_labels) — глаз Егора = машиночитаемый эталон. Чистые функции, без IO.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


@dataclass
class SMEvent:
    i: int              # индекс бара события (подтверждение слома)
    kind: str           # 'CHoCH' | 'BOS'
    bull: bool          # бычий (пробой вверх) / медвежий
    level: float        # сломанный уровень (цена свинга)
    internal: bool      # internal(len5) или swing(len50)


@dataclass
class SMState:
    trend: int = 0                  # swing-тренд: 1 бычий / -1 медвежий / 0 не определён
    itrend: int = 0
    top_y: Optional[float] = None   # последний подтверждённый swing-top (len50)
    top_x: Optional[int] = None
    btm_y: Optional[float] = None
    btm_x: Optional[int] = None
    trail_up: Optional[float] = None    # Strong High (бегущий экстремум)
    trail_up_x: Optional[int] = None
    trail_dn: Optional[float] = None    # Weak Low
    trail_dn_x: Optional[int] = None
    events: list = field(default_factory=list)


def _swings(high: pd.Series, low: pd.Series, length: int):
    """Порт swings(len): os := high[len] > ta.highest(len) ? 0 : low[len] < ta.lowest(len) ? 1 : os[1].
    top появляется при os 1→0 (значение high[len]), btm при os 0→1 (low[len]).
    → список (bar_подтверждения, bar_свинга, цена, is_top)."""
    n = len(high)
    hh = high.rolling(length).max().values   # ta.highest(len) = max последних len баров (текущий вкл.)
    ll = low.rolling(length).min().values
    hv, lv = high.values, low.values
    out = []
    os_ = 0
    for t in range(length, n):
        prev = os_
        if hv[t - length] > hh[t]:
            os_ = 0
        elif lv[t - length] < ll[t]:
            os_ = 1
        if os_ == 0 and prev != 0:
            out.append((t, t - length, float(hv[t - length]), True))
        elif os_ == 1 and prev != 1:
            out.append((t, t - length, float(lv[t - length]), False))
    return out


def run_structure(df: pd.DataFrame, swing_len: int = 50, internal_len: int = 5) -> SMState:
    """Прогон структурной машины OKO-SM по df (columns: open/high/low/close, RangeIndex).
    Возвращает состояние: trend, свинги, trail (Strong/Weak), события CHoCH/BOS."""
    st = SMState()
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    n = len(df)

    sw = {i: [] for i in range(n)}
    for conf_i, sw_i, price, is_top in _swings(df["high"], df["low"], swing_len):
        sw[conf_i].append((sw_i, price, is_top, False))
    for conf_i, sw_i, price, is_top in _swings(df["high"], df["low"], internal_len):
        sw[conf_i].append((sw_i, price, is_top, True))

    itop_y = itop_x = ibtm_y = ibtm_x = None
    top_cross = btm_cross = itop_cross = ibtm_cross = False

    for t in range(n):
        # новые подтверждённые свинги этого бара
        for sw_i, price, is_top, internal in sw[t]:
            if internal:
                if is_top:
                    itop_y, itop_x, itop_cross = price, sw_i, True
                else:
                    ibtm_y, ibtm_x, ibtm_cross = price, sw_i, True
            else:
                if is_top:
                    st.top_y, st.top_x, top_cross = price, sw_i, True
                    st.trail_up, st.trail_up_x = price, sw_i     # top → reset trail (Pine :1679)
                else:
                    st.btm_y, st.btm_x, btm_cross = price, sw_i, True
                    st.trail_dn, st.trail_dn_x = price, sw_i

        # trail_up/dn — бегущие экстремумы (Pine :1689-1745)
        if st.trail_up is None or high[t] > st.trail_up:
            st.trail_up, st.trail_up_x = float(high[t]), t
        if st.trail_dn is None or low[t] < st.trail_dn:
            st.trail_dn, st.trail_dn_x = float(low[t]), t

        if t == 0:
            continue
        pc, cc = close[t - 1], close[t]

        # internal сломы (crossover close vs itop_y/ibtm_y; фильтр top_y!=itop_y как в Pine)
        if (itop_y is not None and itop_cross and cc > itop_y and pc <= itop_y
                and (st.top_y is None or st.top_y != itop_y)):
            st.events.append(SMEvent(t, "CHoCH" if st.itrend < 0 else "BOS", True, itop_y, True))
            itop_cross = False
            st.itrend = 1
        if (ibtm_y is not None and ibtm_cross and cc < ibtm_y and pc >= ibtm_y
                and (st.btm_y is None or st.btm_y != ibtm_y)):
            st.events.append(SMEvent(t, "CHoCH" if st.itrend > 0 else "BOS", False, ibtm_y, True))
            ibtm_cross = False
            st.itrend = -1

        # swing сломы
        if st.top_y is not None and top_cross and cc > st.top_y and pc <= st.top_y:
            st.events.append(SMEvent(t, "CHoCH" if st.trend < 0 else "BOS", True, st.top_y, False))
            top_cross = False
            st.trend = 1
        if st.btm_y is not None and btm_cross and cc < st.btm_y and pc >= st.btm_y:
            st.events.append(SMEvent(t, "CHoCH" if st.trend > 0 else "BOS", False, st.btm_y, False))
            btm_cross = False
            st.trend = -1

    return st


def current_leg(st: SMState) -> Optional[dict]:
    """НОГА (импульс) для OTE по состоянию структуры — как размечает Егор:
    trend=1: origin = последний len50-btm (HL) или Weak Low → extreme = Strong High.
    trend=-1: origin = последний len50-top (LH) или Strong High → extreme = Weak Low."""
    if st.trend == 1 and st.trail_up is not None:
        o, ox = (st.btm_y, st.btm_x) if st.btm_y is not None else (st.trail_dn, st.trail_dn_x)
        if o is None or o >= st.trail_up:
            return None
        return {"trend": "long", "origin": o, "origin_i": ox,
                "extreme": st.trail_up, "extreme_i": st.trail_up_x}
    if st.trend == -1 and st.trail_dn is not None:
        o, ox = (st.top_y, st.top_x) if st.top_y is not None else (st.trail_up, st.trail_up_x)
        if o is None or o <= st.trail_dn:
            return None
        return {"trend": "short", "origin": o, "origin_i": ox,
                "extreme": st.trail_dn, "extreme_i": st.trail_dn_x}
    return None
