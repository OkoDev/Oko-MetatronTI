# -*- coding: utf-8 -*-
"""Библиотека для исследования фрактальности: импульс на 1h -> отклик на младших ТФ.

Ничего из проекта не переписываем: структуру берём из core.smc.oko_sm_engine.run_structure,
дивергенции WT из core.calculators.combinator_core._wtx_divergences,
WT из core.indicators.indicators.calculate_wt (10/21/4).
"""
from __future__ import annotations

import os
import sqlite3
import sys

import numpy as np
import pandas as pd

PROJ = r"E:\MTF BOT\CURSOR\crypto_volume_bot"
DB = os.path.join(PROJ, "ohlcv_cache.db")
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)

from core.smc.oko_sm_engine import run_structure          # noqa: E402
from core.calculators.combinator_core import _wtx_divergences  # noqa: E402
from core.indicators.indicators import calculate_wt       # noqa: E402

WT_OS, WT_OB = -60, 60      # из combinator_core
TF_MS = {"1h": 3600_000, "15m": 900_000, "5m": 300_000, "3m": 180_000, "4h": 14400_000}


# ────────────────────────────── данные ──────────────────────────────
def load(symbol: str, tf: str, t0: int | None = None, t1: int | None = None) -> pd.DataFrame:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    q = "select time,open,high,low,close,volume from ohlcv_cache where symbol=? and timeframe=?"
    p = [symbol, tf]
    if t0:
        q += " and time>=?"; p.append(t0)
    if t1:
        q += " and time<=?"; p.append(t1)
    q += " order by time"
    df = pd.read_sql(q, con, params=p)
    con.close()
    return df


def atr(df: pd.DataFrame, period: int = 14) -> np.ndarray:
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).ewm(alpha=1 / period, adjust=False).mean().values


# ─────────────────────── ЭТАП 1: импульсы на 1h ───────────────────────
def detect_impulses(df: pd.DataFrame, k: float = 2.0, m: int = 20, stall: int = 2):
    """Примитивный НЕЗАВИСИМЫЙ детектор импульса. Полностью каузален.

    Импульс вверх на окне [s..t], s = бар минимума за последние m баров:
      leg = max(high[s..t]) - low[s];  leg >= k*ATR14[s];
      просадка от бегущего максимума внутри ноги <= 50% leg  (нет отката глубже 50%);
      длительность t-s <= m.
    ЗАВЕРШЕНИЕ фиксируется на баре t, когда экстремум ноги был поставлен >= stall баров
    назад (импульс заглох). Никакой информации после бара t не используется.
    Дедуп: после срабатывания направление молчит m баров.

    Возвращает список dict: i_end (индекс бара подтверждения), i_ext, i_orig, dir(+1/-1),
    extreme, origin, leg, k_ratio.
    """
    h, l = df["high"].values, df["low"].values
    a = atr(df, 14)
    n = len(df)
    out = []
    last_fire = {1: -10**9, -1: -10**9}
    for t in range(max(m, 20), n):
        w0 = t - m + 1
        # ── вверх ──
        s = w0 + int(np.argmin(l[w0:t + 1]))
        if s < t:
            seg_h = h[s:t + 1]
            i_ext = s + int(np.argmax(seg_h))
            H = h[i_ext]
            leg = H - l[s]
            if leg > 0 and a[s] > 0 and leg >= k * a[s] and i_ext > s and (t - i_ext) >= stall:
                run_max = np.maximum.accumulate(seg_h)
                low_seg = l[s:t + 1]
                # просадка от бегущего максимума (бар-якорь исключён: его тело — часть ноги)
                dd = (run_max[1:] - low_seg[1:]).max()
                if dd <= 0.5 * leg and t - last_fire[1] >= m:
                    out.append(dict(i_end=t, i_ext=i_ext, i_orig=s, dir=1, extreme=float(H),
                                    origin=float(l[s]), leg=float(leg),
                                    k_ratio=float(leg / a[s]), atr=float(a[s])))
                    last_fire[1] = t
        # ── вниз ──
        s = w0 + int(np.argmax(h[w0:t + 1]))
        if s < t:
            seg_l = l[s:t + 1]
            i_ext = s + int(np.argmin(seg_l))
            L = l[i_ext]
            leg = h[s] - L
            if leg > 0 and a[s] > 0 and leg >= k * a[s] and i_ext > s and (t - i_ext) >= stall:
                run_min = np.minimum.accumulate(seg_l)
                high_seg = h[s:t + 1]
                dd = (high_seg[1:] - run_min[1:]).max()
                if dd <= 0.5 * leg and t - last_fire[-1] >= m:
                    out.append(dict(i_end=t, i_ext=i_ext, i_orig=s, dir=-1, extreme=float(L),
                                    origin=float(h[s]), leg=float(leg),
                                    k_ratio=float(leg / a[s]), atr=float(a[s])))
                    last_fire[-1] = t
    return out


# ─────────────────── ЭТАП 2: признаки разворота на ТФ ───────────────────
FLAGS_BEAR = ["choch_dn_i", "bos_dn_i", "choch_dn_s", "brk_dn_any",
              "wt_div_bear_reg", "wt_ob", "wt_cross_dn", "engulf_bear", "fvg_bear", "vol_spike"]
FLAGS_BULL = ["choch_up_i", "bos_up_i", "choch_up_s", "brk_up_any",
              "wt_div_bull_reg", "wt_os", "wt_cross_up", "engulf_bull", "fvg_bull", "vol_spike"]


def compute_flags(df: pd.DataFrame, swing_len: int = 50, internal_len: int = 5) -> dict:
    """Побарные булевы признаки разворота. Все каузальны (флаг на баре подтверждения)."""
    n = len(df)
    o, h, l, c, v = (df[x].values.astype(float) for x in ("open", "high", "low", "close", "volume"))
    F = {k: np.zeros(n, dtype=bool) for k in set(FLAGS_BEAR + FLAGS_BULL)}

    # ── структура OKO-SM ──
    st = run_structure(df[["open", "high", "low", "close"]].reset_index(drop=True),
                       swing_len=swing_len, internal_len=internal_len)
    for e in st.events:
        if e.internal:
            key = ("choch" if e.kind == "CHoCH" else "bos") + ("_up_i" if e.bull else "_dn_i")
        else:
            if e.kind != "CHoCH":
                # swing-BOS не считаем разворотным
                F["brk_up_any" if e.bull else "brk_dn_any"][e.i] = True
                continue
            key = "choch_up_s" if e.bull else "choch_dn_s"
        F[key][e.i] = True
        F["brk_up_any" if e.bull else "brk_dn_any"][e.i] = True

    # ── WT ──
    d = calculate_wt(df[["high", "low", "close"]].copy(), 10, 21)
    wt = d["wt1"].values; wt2 = d["wt2"].values
    F["wt_ob"] = wt > WT_OB
    F["wt_os"] = wt < WT_OS
    cu = np.zeros(n, bool); cd = np.zeros(n, bool)
    prev_up = wt[:-1] <= wt2[:-1]; now_up = wt[1:] > wt2[1:]
    cu[1:] = prev_up & now_up & (wt[:-1] < WT_OS)
    cd[1:] = (~prev_up) & (wt[1:] < wt2[1:]) & (wt[:-1] > WT_OB)
    F["wt_cross_up"] = cu; F["wt_cross_dn"] = cd
    br, ber, bh, beh = _wtx_divergences(wt, l, h)
    F["wt_div_bull_reg"] = br; F["wt_div_bear_reg"] = ber

    # ── свечной разворот: поглощение ──
    body = c - o
    pb = np.roll(body, 1); po = np.roll(o, 1); pc = np.roll(c, 1)
    eb = np.zeros(n, bool); el = np.zeros(n, bool)
    eb[1:] = (pb[1:] > 0) & (body[1:] < 0) & (o[1:] >= pc[1:]) & (c[1:] <= po[1:])
    el[1:] = (pb[1:] < 0) & (body[1:] > 0) & (o[1:] <= pc[1:]) & (c[1:] >= po[1:])
    F["engulf_bear"] = eb; F["engulf_bull"] = el

    # ── FVG (3 бара, флаг на баре i — момент, когда гэп виден) ──
    fb = np.zeros(n, bool); fl = np.zeros(n, bool)
    fl[2:] = l[2:] > h[:-2]                     # бычий разрыв
    fb[2:] = h[2:] < l[:-2]                     # медвежий разрыв
    F["fvg_bull"] = fl; F["fvg_bear"] = fb

    # ── всплеск объёма ──
    med = pd.Series(v).rolling(96, min_periods=20).median().values
    with np.errstate(invalid="ignore", divide="ignore"):
        F["vol_spike"] = np.nan_to_num(v / med, nan=0.0) > 3.0
    return F
