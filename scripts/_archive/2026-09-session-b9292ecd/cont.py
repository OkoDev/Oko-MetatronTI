# -*- coding: utf-8 -*-
"""Зеркальная проверка: вход ПО импульсу (продолжение) по подтверждению с младшего ТФ.
Геометрия симметрична: стоп = экстремум -/+ 0.5*leg, цель = экстремум +/- 0.5*leg.
Контроль — случайный вход той же геометрии (матч: символ ±30д, квинтиль ATR).
"""
from __future__ import annotations
import os
import sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mtf_lib as L                       # noqa: E402
from run_pass import FAM, BEAR, BULL, _sim, COST  # noqa: E402

K = 3.0
W_H = 4          # ждём подтверждение 4 часа
HOR_H = 48


def one(symbol, ltf, t0, t1):
    tf_ms = L.TF_MS[ltf]
    h1 = L.load(symbol, "1h", t0 - 40 * 24 * 3600_000, t1)
    if len(h1) < 500:
        return None
    lt = L.load(symbol, ltf, t0 - 3600_000, t1 + HOR_H * 3600_000)
    if len(lt) < 5000:
        return None
    F = L.compute_flags(lt)
    t_l = lt["time"].values.astype(np.int64)
    oh, ol, oc = lt["high"].values, lt["low"].values, lt["close"].values
    t_h = h1["time"].values.astype(np.int64)
    a1 = L.atr(h1, 14) / h1["close"].values
    ok = np.isfinite(a1) & (a1 > 0)
    q = np.full(len(h1), -1)
    if ok.sum() > 100:
        q[ok] = pd.qcut(a1[ok], 5, labels=False, duplicates="drop")
    nb_h = HOR_H * 3600_000 // tf_ms
    nb_w = W_H * 3600_000 // tf_ms
    rng = np.random.default_rng(abs(hash(symbol)) % (2 ** 31))
    rows = []
    for im in L.detect_impulses(h1, k=K, m=20):
        ie = im["i_end"]; tc = t_h[ie] + 3600_000
        if tc < t0 or tc > t1:
            continue
        j0 = int(np.searchsorted(t_l, tc))
        if j0 <= 0 or j0 + nb_w + nb_h + 5 >= len(t_l):
            continue
        d = im["dir"]; is_long = d == 1
        pmap = BULL if d == 1 else BEAR
        ext, leg = im["extreme"], im["leg"]
        i1 = min(j0 + nb_w, len(t_l))
        offs = []
        for f in FAM:
            w = np.flatnonzero(F[pmap[f]][j0:i1])
            if w.size:
                offs.append((j0 + w[0], f))
        offs.sort()
        base = dict(sym=symbol, dir=d, year=int(pd.Timestamp(tc, unit="ms").year))
        stop = ext - 0.5 * leg if is_long else ext + 0.5 * leg
        tgt = ext + 0.5 * leg if is_long else ext - 0.5 * leg
        for tag, jj in (("none", j0), ("p1", offs[0][0] if offs else -1),
                        ("p2", offs[1][0] if len(offs) > 1 else -1)):
            if jj < 0:
                continue
            p0 = oc[jj]
            if (is_long and (p0 <= stop or p0 >= tgt)) or \
               (not is_long and (p0 >= stop or p0 <= tgt)):
                continue
            r, res = _sim(oh, ol, oc, jj, p0, stop, tgt, not is_long, nb_h)
            rows.append(dict(base, kind=tag, r=r, out=res,
                             stop_pct=abs(p0 - stop) / p0 * 100,
                             tp_pct=abs(p0 - tgt) / p0 * 100,
                             fam=offs[0][1] if (tag == "p1" and offs) else ""))
        # контроль
        p_ref = oc[j0]
        sp = abs(p_ref - stop) / p_ref * 100; tpp = abs(p_ref - tgt) / p_ref * 100
        cand = np.flatnonzero((np.abs(t_h - t_h[ie]) <= 30 * 24 * 3600_000) & (q == q[ie]))
        cand = cand[(np.abs(cand - ie) > 48) & (cand < len(t_h) - 60)]
        if cand.size:
            for cj in rng.choice(cand, size=min(2, cand.size), replace=False):
                jj = int(np.searchsorted(t_l, t_h[cj] + 3600_000))
                if jj <= 0 or jj + nb_h + 2 >= len(t_l):
                    continue
                p0 = oc[jj]
                st_ = p0 * (1 - sp / 100) if is_long else p0 * (1 + sp / 100)
                tg_ = p0 * (1 + tpp / 100) if is_long else p0 * (1 - tpp / 100)
                r, res = _sim(oh, ol, oc, jj, p0, st_, tg_, not is_long, nb_h)
                rows.append(dict(base, kind="CTL", r=r, out=res,
                                 stop_pct=sp, tp_pct=tpp, fam=""))
    return pd.DataFrame(rows) if rows else None


def work(a):
    try:
        return one(*a)
    except Exception as e:
        print("ERR", a[0], e, flush=True)
        return None


if __name__ == "__main__":
    import multiprocessing as mp
    import driver as D
    from analyze import pf_stats
    ltf = sys.argv[1]
    t0 = int(pd.Timestamp(sys.argv[2]).timestamp() * 1000)
    t1 = int(pd.Timestamp(sys.argv[3]).timestamp() * 1000)
    nsym = int(sys.argv[4]); nproc = int(sys.argv[5])
    syms = D.universe(ltf)
    rng = np.random.default_rng(7)
    if nsym < len(syms):
        syms = sorted(rng.choice(syms, nsym, replace=False))
    out = []
    with mp.Pool(nproc) as p:
        for r in p.imap_unordered(work, [(s, ltf, t0, t1) for s in syms]):
            if r is not None:
                out.append(r)
    d = pd.concat(out, ignore_index=True)
    d.to_pickle(os.path.join(HERE, f"cont_{ltf}.pkl"))
    pd.set_option("display.width", 220)
    print(f"=== ПРОДОЛЖЕНИЕ по импульсу, {ltf}, {sys.argv[2]}..{sys.argv[3]}, "
          f"{d.sym.nunique()} монет ===")
    print("медиана stop_pct", round(d.stop_pct.median(), 2),
          " tp_pct", round(d.tp_pct.median(), 2))
    rows = []
    for kd in ("none", "p1", "p2", "CTL"):
        s = pf_stats(d.loc[d.kind == kd, "r"]); s["вход"] = kd; rows.append(s)
    print(pd.DataFrame(rows).set_index("вход").to_string())
    print("\n-- по стороне --")
    rows = []
    for dd, nm in ((1, "long (по росту)"), (-1, "short (по падению)")):
        for kd in ("none", "p1", "p2", "CTL"):
            s = pf_stats(d.loc[(d.kind == kd) & (d.dir == dd), "r"])
            s["side"] = nm; s["вход"] = kd; rows.append(s)
    print(pd.DataFrame(rows).set_index(["side", "вход"]).to_string())
    print("\n-- по году --")
    rows = []
    for y in sorted(d.year.unique()):
        for kd in ("none", "p1", "CTL"):
            s = pf_stats(d.loc[(d.kind == kd) & (d.year == y), "r"])
            s["year"] = y; s["вход"] = kd; rows.append(s)
    print(pd.DataFrame(rows).set_index(["year", "вход"]).to_string())
    print("\n-- по семейству первого подтверждения (p1) --")
    rows = []
    for f in FAM:
        s = pf_stats(d.loc[(d.kind == "p1") & (d.fam == f), "r"]); s["fam"] = f; rows.append(s)
    print(pd.DataFrame(rows).set_index("fam").to_string())
    g = d.loc[d.kind == "p1"].groupby("sym")["r"].sum().sort_values()
    print("\nконцентрация p1: итог", round(g.sum(), 1), "| монет", len(g),
          "| доля монет в плюсе", round(100 * (g > 0).mean(), 1),
          "| топ-5 дают", round(g.tail(5).sum(), 1))
