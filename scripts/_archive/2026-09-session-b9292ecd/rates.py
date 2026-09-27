# -*- coding: utf-8 -*-
"""ЭТАП 2, честная версия: ЧАСТОТА событий (шт/бар) в окне после импульса 1h
против матчированного случайного окна. Плюс контроль на тавтологию CHoCH:
контрольные окна дополнительно матчатся по знаку структурного тренда LTF.
"""
from __future__ import annotations
import os
import sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mtf_lib as L        # noqa: E402
from run_pass import FAM, BEAR, BULL  # noqa: E402
from core.smc.oko_sm_engine import run_structure  # noqa: E402

WINS = [1, 2, 4, 12, 24]
K = 3.0
NCTL = 3


def swing_trend(df):
    st = run_structure(df[["open", "high", "low", "close"]].reset_index(drop=True), 50, 5)
    tr = np.zeros(len(df), dtype=np.int8)
    cur = 0
    idx = 0
    ev = [e for e in st.events if not e.internal]
    for i in range(len(df)):
        while idx < len(ev) and ev[idx].i <= i:
            cur = 1 if ev[idx].bull else -1
            idx += 1
        tr[i] = cur
    return tr


def one(symbol, ltf, t0, t1):
    tf_ms = L.TF_MS[ltf]
    h1 = L.load(symbol, "1h", t0 - 40 * 24 * 3600_000, t1)
    if len(h1) < 500:
        return None
    lt = L.load(symbol, ltf, t0 - 3600_000, t1 + 30 * 3600_000)
    if len(lt) < 5000:
        return None
    F = L.compute_flags(lt)
    tr = swing_trend(lt)
    CS = {k: np.concatenate([[0], np.cumsum(v)]) for k, v in F.items()}
    t_l = lt["time"].values.astype(np.int64)
    t_h = h1["time"].values.astype(np.int64)
    a1 = L.atr(h1, 14) / h1["close"].values
    ok = np.isfinite(a1) & (a1 > 0)
    q = np.full(len(h1), -1)
    if ok.sum() > 100:
        q[ok] = pd.qcut(a1[ok], 5, labels=False, duplicates="drop")
    rng = np.random.default_rng(abs(hash(symbol)) % (2 ** 31))
    rows = []

    def rec(j0, d, kind, t_anchor):
        cmap = BEAR if d == 1 else BULL
        pmap = BULL if d == 1 else BEAR
        r = dict(sym=symbol, dir=d, kind=kind, ltrend=int(tr[max(j0 - 1, 0)]),
                 year=int(pd.Timestamp(t_anchor, unit="ms").year))
        for w in WINS:
            nb = int(w * 3600_000 // tf_ms)
            j1 = min(j0 + nb, len(t_l))
            r[f"nb{w}"] = j1 - j0
            for f in FAM:
                r[f"c_{f}_{w}"] = int(CS[cmap[f]][j1] - CS[cmap[f]][j0])
                r[f"p_{f}_{w}"] = int(CS[pmap[f]][j1] - CS[pmap[f]][j0])
            r[f"c_vol_{w}"] = int(CS["vol_spike"][j1] - CS["vol_spike"][j0])
        return r

    for im in L.detect_impulses(h1, k=K, m=20):
        ie = im["i_end"]
        tc = t_h[ie] + 3600_000
        if tc < t0 or tc > t1:
            continue
        j0 = int(np.searchsorted(t_l, tc))
        if j0 <= 0 or j0 + 300 >= len(t_l):
            continue
        rows.append(rec(j0, im["dir"], "IMP", tc))
        cand = np.flatnonzero((np.abs(t_h - t_h[ie]) <= 30 * 24 * 3600_000) & (q == q[ie]))
        cand = cand[(np.abs(cand - ie) > 48) & (cand < len(t_h) - 60)]
        if cand.size:
            for cj in rng.choice(cand, size=min(NCTL, cand.size), replace=False):
                tcc = t_h[cj] + 3600_000
                jj = int(np.searchsorted(t_l, tcc))
                if jj <= 0 or jj + 300 >= len(t_l):
                    continue
                rows.append(rec(jj, im["dir"], "CTL", tcc))
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
    ltf = sys.argv[1]
    t0 = int(pd.Timestamp(sys.argv[2]).timestamp() * 1000)
    t1 = int(pd.Timestamp(sys.argv[3]).timestamp() * 1000)
    nsym = int(sys.argv[4]); nproc = int(sys.argv[5])
    syms = D.universe(ltf)
    rng = np.random.default_rng(7)
    if nsym < len(syms):
        syms = sorted(rng.choice(syms, nsym, replace=False))
    print(f"rates {ltf}: {len(syms)} syms", flush=True)
    out = []
    with mp.Pool(nproc) as p:
        for n, r in enumerate(p.imap_unordered(work, [(s, ltf, t0, t1) for s in syms]), 1):
            if r is not None:
                out.append(r)
            if n % 25 == 0:
                print("  ", n, flush=True)
    d = pd.concat(out, ignore_index=True)
    d.to_pickle(os.path.join(HERE, f"rates2_{ltf}.pkl"))
    print("ROWS", d.shape, d.kind.value_counts().to_dict(), flush=True)
