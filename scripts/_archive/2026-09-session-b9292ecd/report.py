# -*- coding: utf-8 -*-
"""Печать отчёта по одному тегу (ltf)."""
import os
import sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from analyze import pf_stats, freq_table, FAM, WINS  # noqa: E402

pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 400)
pd.set_option("display.max_columns", 50)

tag = sys.argv[1]
imp = pd.read_pickle(os.path.join(HERE, f"imp_{tag}.pkl"))
ctl = pd.read_pickle(os.path.join(HERE, f"ctl_{tag}.pkl"))
print(f"===== {tag}: импульсов {len(imp)}, контролей {len(ctl)}, символов {imp.sym.nunique()}")
print(imp.groupby(["k", "dir"]).size())
print("годы:", imp.groupby("year").size().to_dict())
print("режим (BTC 30д):", imp.groupby("reg").size().to_dict())
print("медиана kr:", round(imp.kr.median(), 2), " медиана длит.(1h баров):", imp.dur.median())

print("\n########## ЭТАП 2. ЧАСТОТЫ: импульс vs контроль (матч: символ ±30д, квинтиль ATR) ##########")
f = freq_table(imp, ctl)
print(f.pivot_table(index=["side", "fam"], columns="W",
                    values=["p_imp", "p_ctl", "lift", "z"]).round(2))

print("\n--- только против импульса (c_), по K ---")
for k in sorted(imp.k.unique()):
    t = freq_table(imp[imp.k == k], ctl, extra=f"K={k}")
    t = t[(t.side == "c") & (t.W == 12)]
    print(f"K={k}", t[["fam", "n_imp", "p_imp", "p_ctl", "lift", "z"]].to_string(index=False))

print("\n--- по стороне (K=3, W=12) ---")
for d, nm in ((1, "импульс ВВЕРХ (фейд=short)"), (-1, "импульс ВНИЗ (фейд=long)")):
    t = freq_table(imp[imp.k == 3], ctl, dirs=[d])
    t = t[(t.W == 12)]
    print(nm)
    print(t.pivot_table(index="fam", columns="side", values=["p_imp", "p_ctl", "lift", "z"]).round(2))

print("\n--- ЧИСЛО РАЗНЫХ ПОДТВЕРЖДЕНИЙ в окне (K=3) ---")
for w in WINS:
    cols = [f"c_{f}" for f in FAM]
    ni = (imp[imp.k == 3][cols] <= w * 60).sum(axis=1)
    nc = (ctl[cols] <= w * 60).sum(axis=1)
    print(f"W={w}ч: импульс среднее {ni.mean():.2f} медиана {ni.median():.0f} | "
          f"контроль среднее {nc.mean():.2f} медиана {nc.median():.0f} | "
          f"P(>=1) {100*(ni>=1).mean():.1f}/{100*(nc>=1).mean():.1f} "
          f"P(>=2) {100*(ni>=2).mean():.1f}/{100*(nc>=2).mean():.1f} "
          f"P(>=3) {100*(ni>=3).mean():.1f}/{100*(nc>=3).mean():.1f}")

print("\n########## ЭТАП 3. ТОРГОВЛЯ (K=3, стоп=экстремум, цели 0.382/0.618, косты 0.35%) ##########")
k3 = imp[imp.k == 3].copy()
print("геометрия: медиана stop_pct", round(k3.stop_pct.median(), 3),
      "медиана tp1_pct", round(k3.tp1_pct.median(), 3),
      " -> медиана RR(tp1)", round((k3.tp1_pct / k3.stop_pct).median(), 3))

for tn, nm in (("1", "цель 0.382"), ("2", "цель 0.618")):
    print(f"\n--- {nm} ---")
    rows = []
    for tag2, lbl in (("none", "без подтверждения (вход сразу)"),
                      ("c1", "1 подтверждение"), ("c2", "2 разных"), ("c3", "3 разных")):
        for w in WINS:
            col = f"r{tn}_{tag2}"
            if col not in k3.columns:
                continue
            m = k3[f"wait_{tag2}"] <= w if tag2 != "none" else pd.Series(True, index=k3.index)
            s = pf_stats(k3.loc[m, col])
            s.update(вход=lbl, W=w)
            rows.append(s)
    s = pf_stats(ctl[f"r{tn}"]); s.update(вход="КОНТРОЛЬ (случайный вход, та же геометрия)", W=0)
    rows.append(s)
    print(pd.DataFrame(rows).set_index(["вход", "W"]).to_string())

print("\n--- разрез: сторона × вход (цель 0.618, W=12) ---")
rows = []
for d, dn in ((1, "short (фейд роста)"), (-1, "long (фейд падения)")):
    for tag2 in ("none", "c1", "c2", "c3"):
        m = (k3.dir == d) & ((k3[f"wait_{tag2}"] <= 12) if tag2 != "none" else True)
        s = pf_stats(k3.loc[m, f"r2_{tag2}"]); s.update(side=dn, вход=tag2); rows.append(s)
    s = pf_stats(ctl.loc[ctl.dir == d, "r2"]); s.update(side=dn, вход="КОНТРОЛЬ"); rows.append(s)
print(pd.DataFrame(rows).set_index(["side", "вход"]).to_string())

print("\n--- разрез: год × вход (цель 0.618, W=12) ---")
rows = []
for y in sorted(k3.year.unique()):
    for tag2 in ("none", "c2"):
        m = (k3.year == y) & ((k3[f"wait_{tag2}"] <= 12) if tag2 != "none" else True)
        s = pf_stats(k3.loc[m, f"r2_{tag2}"]); s.update(year=y, вход=tag2); rows.append(s)
    s = pf_stats(ctl.loc[ctl.year == y, "r2"]); s.update(year=y, вход="КОНТРОЛЬ"); rows.append(s)
print(pd.DataFrame(rows).set_index(["year", "вход"]).to_string())

print("\n--- разрез: режим BTC × вход (цель 0.618, W=12) ---")
rows = []
for g, gn in ((1, "бык"), (0, "флэт"), (-1, "медведь")):
    for tag2 in ("none", "c2"):
        m = (k3.reg == g) & ((k3[f"wait_{tag2}"] <= 12) if tag2 != "none" else True)
        s = pf_stats(k3.loc[m, f"r2_{tag2}"]); s.update(reg=gn, вход=tag2); rows.append(s)
    s = pf_stats(ctl.loc[ctl.reg == g, "r2"]); s.update(reg=gn, вход="КОНТРОЛЬ"); rows.append(s)
print(pd.DataFrame(rows).set_index(["reg", "вход"]).to_string())

print("\n--- по типу первого подтверждения (цель 0.618, W=12, вход c1) ---")
rows = []
for f in FAM:
    m = (k3[f"c_{f}"] <= 12 * 60) & (k3[f"c_{f}"] == k3["off1"])
    s = pf_stats(k3.loc[m, "r2_c1"]); s.update(fam=f); rows.append(s)
print(pd.DataFrame(rows).set_index("fam").to_string())

print("\n--- концентрация по монетам (цель 0.618, вход c2, W=12) ---")
m = k3[f"wait_c2"] <= 12
g = k3.loc[m].groupby("sym")["r2_c2"].agg(["count", "sum"]).sort_values("sum")
tot = g["sum"].sum()
print("итог %:", round(tot, 1), "| монет:", len(g))
print("топ-5 доноров:", g.tail(5)[["count", "sum"]].round(1).to_dict("index"))
print("топ-5 доноров дают от итога:", round(g["sum"].tail(5).sum(), 1))
print("медиана по монете:", round(g["sum"].median(), 3))
print("доля монет в плюсе:", round(100 * (g["sum"] > 0).mean(), 1), "%")

print("\n--- сколько ждать: распределение времени до подтверждения (часы, K=3) ---")
print(k3[["off1", "off2", "off3"]].div(60).describe(percentiles=[.25, .5, .75, .9]).round(2))
print("доля импульсов БЕЗ 1/2/3 подтверждений в 24ч:",
      [round(100 * k3[f"off{i}"].isna().mean(), 1) for i in (1, 2, 3)])
