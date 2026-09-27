# -*- coding: utf-8 -*-
"""Один проход по символу: импульсы 1h -> отклик на младшем ТФ -> сделки + контроль."""
from __future__ import annotations

import os
import sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import mtf_lib as L  # noqa: E402

FAM = ["choch_i", "bos_i", "choch_s", "brk_any", "wtdiv", "wtzone", "wtcross", "engulf", "fvg"]
BEAR = {"choch_i": "choch_dn_i", "bos_i": "bos_dn_i", "choch_s": "choch_dn_s",
        "brk_any": "brk_dn_any", "wtdiv": "wt_div_bear_reg", "wtzone": "wt_ob",
        "wtcross": "wt_cross_dn", "engulf": "engulf_bear", "fvg": "fvg_bear"}
BULL = {"choch_i": "choch_up_i", "bos_i": "bos_up_i", "choch_s": "choch_up_s",
        "brk_any": "brk_up_any", "wtdiv": "wt_div_bull_reg", "wtzone": "wt_os",
        "wtcross": "wt_cross_up", "engulf": "engulf_bull", "fvg": "fvg_bull"}

COST = 0.35          # % round-trip
HORIZON_H = 48       # часов на сделку
W_MAX_H = 24         # максимум ожидания подтверждения (часов)
KS = (2.0, 3.0, 5.0)
K_TRADE = 3.0        # на каком K торговый замер
N_CTL = 2


def _first_hits(flag_arr, i0, i1, t_ltf, t0_ms, tf_ms):
    """Минуты до первого срабатывания флага в барах [i0,i1). NaN если нет."""
    if i1 <= i0:
        return np.nan
    seg = flag_arr[i0:i1]
    w = np.flatnonzero(seg)
    if w.size == 0:
        return np.nan
    return (t_ltf[i0 + w[0]] + tf_ms - t0_ms) / 60000.0   # время ЗАКРЫТИЯ бара сигнала


def _sim(o_h, o_l, o_c, j0, p0, stop, tp, is_short, nbars):
    """Симуляция от бара j0+1. Возврат (%, исход)."""
    j1 = min(len(o_c), j0 + 1 + nbars)
    if j0 + 1 >= j1:
        return np.nan, "none"
    hh = o_h[j0 + 1:j1]; ll = o_l[j0 + 1:j1]
    if is_short:
        s_hit = np.flatnonzero(hh >= stop)
        t_hit = np.flatnonzero(ll <= tp)
    else:
        s_hit = np.flatnonzero(ll <= stop)
        t_hit = np.flatnonzero(hh >= tp)
    si = s_hit[0] if s_hit.size else 10**9
    ti = t_hit[0] if t_hit.size else 10**9
    if si == 10**9 and ti == 10**9:
        px, res = o_c[j1 - 1], "TIME"
    elif si <= ti:
        px, res = stop, "SL"
    else:
        px, res = tp, "TP"
    r = (p0 - px) / p0 * 100.0 if is_short else (px - p0) / p0 * 100.0
    return r - COST, res


def process(symbol: str, ltf: str, t0: int, t1: int, btc_t: np.ndarray, btc_reg: np.ndarray):
    tf_ms = L.TF_MS[ltf]
    h1 = L.load(symbol, "1h", t0 - 40 * 24 * 3600_000, t1)
    if len(h1) < 500:
        return None, None
    lt = L.load(symbol, ltf, t0 - 3600_000, t1 + HORIZON_H * 3600_000)
    if len(lt) < 5000:
        return None, None
    F = L.compute_flags(lt)
    t_l = lt["time"].values.astype(np.int64)
    o_h = lt["high"].values; o_l = lt["low"].values; o_c = lt["close"].values
    t_h = h1["time"].values.astype(np.int64)
    a1 = L.atr(h1, 14)
    atr_pct = a1 / h1["close"].values
    ok = np.isfinite(atr_pct) & (atr_pct > 0)
    q = np.full(len(h1), -1)
    if ok.sum() > 100:
        q[ok] = pd.qcut(atr_pct[ok], 5, labels=False, duplicates="drop")
    nb_h = HORIZON_H * 3600_000 // tf_ms
    nb_w = W_MAX_H * 3600_000 // tf_ms

    rows, ctls = [], []
    rng = np.random.default_rng(abs(hash(symbol)) % (2**31))
    for k in KS:
        imps = L.detect_impulses(h1, k=k, m=20)
        for im in imps:
            ie = im["i_end"]
            t_close = t_h[ie] + 3600_000            # момент, когда завершение ИЗВЕСТНО
            if t_close < t0 or t_close > t1:
                continue
            j0 = int(np.searchsorted(t_l, t_close))  # первый LTF-бар, открывшийся после
            if j0 <= 0 or j0 + nb_w + 5 >= len(t_l):
                continue
            d = im["dir"]
            cmap = BEAR if d == 1 else BULL
            pmap = BULL if d == 1 else BEAR
            i1 = min(j0 + nb_w, len(t_l))
            rec = dict(sym=symbol, ltf=ltf, k=k, dir=d, t=t_close,
                       kr=im["k_ratio"], leg=im["leg"], extreme=im["extreme"],
                       origin=im["origin"], dur=ie - im["i_orig"],
                       year=int(pd.Timestamp(t_close, unit="ms").year),
                       reg=int(btc_reg[np.searchsorted(btc_t, t_close, "right") - 1]))
            offs = []
            for f in FAM:
                a = _first_hits(F[cmap[f]], j0, i1, t_l, t_close, tf_ms)
                b = _first_hits(F[pmap[f]], j0, i1, t_l, t_close, tf_ms)
                rec["c_" + f] = a; rec["p_" + f] = b
                offs.append(a)
            rec["c_vol"] = _first_hits(F["vol_spike"], j0, i1, t_l, t_close, tf_ms)
            offs = np.sort(np.array([x for x in offs if np.isfinite(x)]))
            rec["n_conf"] = len(offs)
            for m_ in (1, 2, 3):
                rec[f"off{m_}"] = offs[m_ - 1] if len(offs) >= m_ else np.nan

            # ── торговый замер (только на K_TRADE) ──
            if k == K_TRADE:
                is_short = d == 1
                ext = im["extreme"]; leg = im["leg"]
                tp1 = ext - 0.382 * leg if is_short else ext + 0.382 * leg
                tp2 = ext - 0.618 * leg if is_short else ext + 0.618 * leg
                p_none = o_c[j0]
                gsp = abs(ext - p_none) / p_none * 100.0
                rec["stop_pct"] = gsp
                rec["tp1_pct"] = abs(p_none - tp1) / p_none * 100.0
                for tag, jj in [("none", j0)] + [
                        (f"c{m_}", (j0 + int(np.ceil(rec[f'off{m_}'] * 60000 / tf_ms)) - 1)
                         if np.isfinite(rec[f"off{m_}"]) else -1) for m_ in (1, 2, 3)]:
                    if jj < 0 or jj >= len(o_c) - 2:
                        continue
                    p0 = o_c[jj]
                    if (is_short and p0 >= ext) or ((not is_short) and p0 <= ext):
                        rec[f"r1_{tag}"] = np.nan; continue     # стоп уже пробит
                    for tn, tpx in (("1", tp1), ("2", tp2)):
                        if (is_short and p0 <= tpx) or ((not is_short) and p0 >= tpx):
                            rec[f"r{tn}_{tag}"] = np.nan; continue
                        r, res = _sim(o_h, o_l, o_c, jj, p0, ext, tpx, is_short, nb_h)
                        rec[f"r{tn}_{tag}"] = r
                        rec[f"o{tn}_{tag}"] = res
                    rec[f"wait_{tag}"] = (t_l[jj] + tf_ms - t_close) / 3600000.0

                # ── КОНТРОЛЬ: случайный вход той же геометрии ──
                cand = np.flatnonzero((np.abs(t_h - t_h[ie]) <= 30 * 24 * 3600_000) &
                                      (q == q[ie]) & (np.arange(len(t_h)) < len(t_h) - 60))
                cand = cand[np.abs(cand - ie) > 48]
                if cand.size:
                    for cj in rng.choice(cand, size=min(N_CTL, cand.size), replace=False):
                        tc = t_h[cj] + 3600_000
                        jj = int(np.searchsorted(t_l, tc))
                        if jj <= 0 or jj >= len(o_c) - nb_h - 2:
                            continue
                        p0 = o_c[jj]
                        st_ = p0 * (1 + gsp / 100) if is_short else p0 * (1 - gsp / 100)
                        c = dict(sym=symbol, ltf=ltf, dir=d, t=tc,
                                 year=int(pd.Timestamp(tc, unit="ms").year),
                                 reg=int(btc_reg[np.searchsorted(btc_t, tc, "right") - 1]))
                        for tn in ("1", "2"):
                            # цель в тех же % от входа, что и у боевой сделки (та же геометрия)
                            tp_pct = abs(p_none - (tp1 if tn == "1" else tp2)) / p_none * 100
                            tgt = p0 * (1 - tp_pct / 100) if is_short else p0 * (1 + tp_pct / 100)
                            r, res = _sim(o_h, o_l, o_c, jj, p0, st_, tgt, is_short, nb_h)
                            c[f"r{tn}"] = r; c[f"o{tn}"] = res
                        # частотный контроль: те же признаки в случайном окне
                        i1c = min(jj + nb_w, len(t_l))
                        for f in FAM:
                            c["c_" + f] = _first_hits(F[cmap[f]], jj, i1c, t_l, tc, tf_ms)
                            c["p_" + f] = _first_hits(F[pmap[f]], jj, i1c, t_l, tc, tf_ms)
                        c["c_vol"] = _first_hits(F["vol_spike"], jj, i1c, t_l, tc, tf_ms)
                        ctls.append(c)
            rows.append(rec)
    return (pd.DataFrame(rows) if rows else None,
            pd.DataFrame(ctls) if ctls else None)
