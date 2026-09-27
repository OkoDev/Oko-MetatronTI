# -*- coding: utf-8 -*-
"""Отчёт по сохранённому pkl замера дельты HTF (вывод прошлого запуска потерян)."""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
R = pd.read_pickle(D + r"\wt_htf_delta.pkl")
print(f"сделок: {len(R):,} · монет {R.sym.nunique()} · база {R.pnl.mean():+.3f}%\n")

print("=== A. ВЕЛИЧИНА |Δ| НА СТАРШЕМ (240m) ===")
R["q_d"] = pd.qcut(R.htf_d, 5, labels=False, duplicates="drop")
print(f"{'квинт':>6} {'|Δ|HTF':>8} {'n':>8} {'нетто':>9} {'мед':>9} {'WR':>6}")
for q in sorted(R.q_d.dropna().unique()):
    g = R[R.q_d == q]
    print(f"{int(q)+1:>6} {g.htf_d.median():7.2f} {len(g):>8,} {g.pnl.mean():+8.3f}% "
          f"{g.pnl.median():+8.3f}% {(g.pnl>0).mean()*100:5.1f}%")

print("\n=== B. РАСШИРЕНИЕ |Δ| HTF (гипотеза Егора) ===")
print(f"{'состояние':>14} {'n':>8} {'доля':>7} {'нетто':>9} {'мед':>9} {'IS':>9} "
      f"{'OOS':>9} {'перенос':>8} {'монет+':>8}")
for lbl, cond in [("сужается", R.htf_exp < -0.05),
                  ("плоско", (R.htf_exp >= -0.05) & (R.htf_exp <= 0.05)),
                  ("расширяется", R.htf_exp > 0.05)]:
    g = R[cond]
    if len(g) < 300:
        continue
    i_, o_ = g[g.half == 0].pnl, g[g.half == 1].pnl
    tag = "✓" if i_.mean() * o_.mean() > 0 and i_.mean() > 0 else "✗"
    per = g.groupby("sym").pnl.mean()
    print(f"{lbl:>14} {len(g):>8,} {len(g)/len(R)*100:6.1f}% {g.pnl.mean():+8.3f}% "
          f"{g.pnl.median():+8.3f}% {i_.mean():+8.3f}% {o_.mean():+8.3f}% {tag:>8} "
          f"{int((per>0).sum())}/{len(per)}")

print("\n  по сторонам:")
for lbl, cond in [("сужается", R.htf_exp < -0.05), ("расширяется", R.htf_exp > 0.05)]:
    for side, sn in [(1, "long"), (-1, "short")]:
        g = R[cond & (R.side == side)]
        if len(g) < 200:
            continue
        print(f"    {lbl:>12} {sn:>5}: n={len(g):>6,} {g.pnl.mean():+.3f}% "
              f"мед {g.pnl.median():+.3f}%")

print("\n=== C. Δ В СТОРОНУ ВХОДА (знак × сторона) ===")
R["q_dir"] = pd.qcut(R.htf_dir, 5, labels=False, duplicates="drop")
for q in sorted(R.q_dir.dropna().unique()):
    g = R[R.q_dir == q]
    print(f"{int(q)+1:>6} {g.htf_dir.median():8.2f} {len(g):>8,} {g.pnl.mean():+8.3f}% "
          f"{g.pnl.median():+8.3f}%")

print("\n=== D. КОМБИНАЦИЯ ===")
lo = R.ltf_d <= R.ltf_d.quantile(.4)
print(f"{'условие':>30} {'n':>8} {'доля':>7} {'нетто':>9} {'мед':>9} {'монет+':>8}")
for lbl, cond in [("все входы", R.pnl == R.pnl),
                  ("расширение HTF", R.htf_exp > 0.05),
                  ("слабый кросс LTF", lo),
                  ("расширение + слабый LTF", (R.htf_exp > 0.05) & lo)]:
    g = R[cond]
    per = g.groupby("sym").pnl.mean()
    print(f"{lbl:>30} {len(g):>8,} {len(g)/len(R)*100:6.1f}% {g.pnl.mean():+8.3f}% "
          f"{g.pnl.median():+8.3f}% {int((per>0).sum())}/{len(per)}")
