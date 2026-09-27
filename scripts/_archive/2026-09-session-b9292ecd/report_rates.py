# -*- coding: utf-8 -*-
import os
import sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from run_pass import FAM  # noqa: E402

pd.set_option("display.width", 250); pd.set_option("display.max_rows", 300)
ltf = sys.argv[1]
d = pd.read_pickle(os.path.join(HERE, f"rates2_{ltf}.pkl"))
I = d[d.kind == "IMP"]; C = d[d.kind == "CTL"]
print(f"===== rates {ltf}: IMP {len(I)}  CTL {len(C)}  символов {d.sym.nunique()}  "
      f"годы {sorted(d.year.unique())}")

print("\n--- состояние структурного тренда LTF на входе в окно (доли, %) ---")
print(pd.crosstab(I.dir, I.ltrend, normalize="index").round(3) * 100, "\n(импульс)")
print(pd.crosstab(C.dir, C.ltrend, normalize="index").round(3) * 100, "\n(контроль)")


def rate_tbl(I, C, note=""):
    rows = []
    for w in (1, 2, 4, 12, 24):
        for side in ("c", "p"):
            fams = FAM + (["vol"] if side == "c" else [])
            for f in fams:
                col = f"{side}_{f}_{w}"
                if col not in I.columns:
                    continue
                ri = I[col].sum() / I[f"nb{w}"].sum()
                rc = C[col].sum() / C[f"nb{w}"].sum()
                # пуассоновский z по суммам событий
                ni, nc = I[col].sum(), C[col].sum()
                bi, bc = I[f"nb{w}"].sum(), C[f"nb{w}"].sum()
                lam = (ni + nc) / (bi + bc)
                se = np.sqrt(lam * (1 / bi + 1 / bc))
                z = (ri - rc) / se if se > 0 else 0
                rows.append(dict(W=w, side=side, fam=f, ev_imp=int(ni), ev_ctl=int(nc),
                                 rate_imp=round(ri * 1000, 3), rate_ctl=round(rc * 1000, 3),
                                 lift=round(ri / rc, 3) if rc > 0 else np.inf, z=round(z, 1),
                                 note=note))
    return pd.DataFrame(rows)


print("\n########## ЧАСТОТА СОБЫТИЙ (шт на 1000 баров LTF), импульс vs матч-контроль ##########")
t = rate_tbl(I, C)
print(t[t.W == 1].pivot_table(index="fam", columns="side",
                              values=["rate_imp", "rate_ctl", "lift", "z"]).round(2))
print("\nW=12ч:")
print(t[t.W == 4].pivot_table(index="fam", columns="side",
                               values=["rate_imp", "rate_ctl", "lift", "z"]).round(2))

print("\n########## ТО ЖЕ, но контроль МАТЧИТСЯ ПО СТРУКТУРНОМУ ТРЕНДУ LTF ##########")
print("(снимает тавтологию «после роста следующий CHoCH может быть только вниз»)")
out = []
for dd in (1, -1):
    Ii = I[(I.dir == dd) & (I.ltrend == dd)]
    Cc = C[(C.dir == dd) & (C.ltrend == dd)]
    if len(Ii) < 200 or len(Cc) < 200:
        print("мало данных для dir", dd, len(Ii), len(Cc)); continue
    tt = rate_tbl(Ii, Cc, note=f"dir={dd} trend-matched n_imp={len(Ii)} n_ctl={len(Cc)}")
    out.append(tt)
    print(f"\ndir={dd}  n_imp={len(Ii)} n_ctl={len(Cc)}   W=1ч:")
    print(tt[tt.W == 1].pivot_table(index="fam", columns="side",
                                    values=["rate_imp", "rate_ctl", "lift", "z"]).round(2))

print("\n########## ЗАТУХАНИЕ ОТКЛИКА: lift по окнам (counter, trend-matched dir=1) ##########")
if out:
    a = pd.concat(out)
    print(a[(a.side == "c") & (a.note.str.contains("dir=1"))]
          .pivot_table(index="fam", columns="W", values="lift").round(3))
    print("\nz:")
    print(a[(a.side == "c") & (a.note.str.contains("dir=1"))]
          .pivot_table(index="fam", columns="W", values="z").round(1))
