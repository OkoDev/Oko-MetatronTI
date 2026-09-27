# -*- coding: utf-8 -*-
"""Разбор результатов: ЭТАП 2 (частоты) и ЭТАП 3 (торговля)."""
import os
import sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = ["choch_i", "bos_i", "choch_s", "brk_any", "wtdiv", "wtzone", "wtcross", "engulf", "fvg"]
WINS = [4, 12, 24]


def pf_stats(r: pd.Series) -> dict:
    r = r.dropna()
    n = len(r)
    if n < 10:
        return dict(n=n)
    pos = r[r > 0].sum(); neg = -r[r < 0].sum()
    pf = pos / neg if neg > 0 else np.inf
    q = r.quantile(0.90)
    r_nt = r[r <= q]
    pos2 = r_nt[r_nt > 0].sum(); neg2 = -r_nt[r_nt < 0].sum()
    return dict(n=n, pf=round(pf, 3), wr=round((r > 0).mean() * 100, 1),
                mean=round(r.mean(), 4), med=round(r.median(), 4),
                sum=round(r.sum(), 1),
                mean_no_top10=round(r_nt.mean(), 4),
                pf_no_top10=round(pos2 / neg2, 3) if neg2 > 0 else np.inf)


def freq_table(imp, ctl, ks=None, dirs=None, extra=""):
    rows = []
    a = imp if ks is None else imp[imp.k.isin(ks)]
    b = ctl
    if dirs is not None:
        a = a[a.dir.isin(dirs)]; b = b[b.dir.isin(dirs)]
    for side in ("c", "p"):
        for f in FAM + (["vol"] if side == "c" else []):
            col = f"{side}_{f}"
            if col not in a.columns:
                continue
            for w in WINS:
                pi = (a[col] <= w * 60).mean()
                pc = (b[col] <= w * 60).mean()
                na, nb = len(a), len(b)
                se = np.sqrt(pi * (1 - pi) / max(na, 1) + pc * (1 - pc) / max(nb, 1))
                z = (pi - pc) / se if se > 0 else 0
                rows.append(dict(side=side, fam=f, W=w, n_imp=na, n_ctl=nb,
                                 p_imp=round(pi * 100, 2), p_ctl=round(pc * 100, 2),
                                 lift=round(pi / pc, 3) if pc > 0 else np.inf,
                                 z=round(z, 1), cut=extra))
    return pd.DataFrame(rows)
