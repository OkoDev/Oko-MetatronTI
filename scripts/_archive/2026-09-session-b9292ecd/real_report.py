# -*- coding: utf-8 -*-
"""Отчёт по схеме Егора (данные в pkl; в прогоне снова словил R.T = транспонирование)."""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
R = pd.read_pickle(D + r"\egor_real.pkl").rename(columns={"T": "tf"})
B = pd.read_pickle(D + r"\egor_real_base.pkl").rename(columns={"T": "tf"})
ENTRIES = sorted(R.tf.unique())
print(f"сделок {len(R):,} · контролей {len(B):,} · монет {R.sym.nunique()}\n")


def blk(g):
    v = np.sort(g.pnl.values)[::-1]
    per = g.groupby("sym").pnl.mean()
    return v[int(len(v)*.1):].mean(), int((per > 0).sum()), len(per)


print("=== СХЕМА ПРОТИВ ДВУХ КОНТРОЛЕЙ ===")
print(f"{'T':>4} {'стор':>6} {'что':>24} {'n':>9} {'нетто':>9} {'мед':>9} {'WR':>6} "
      f"{'баров':>6} {'безтоп10':>9} {'монет+':>7}")
for T in ENTRIES:
    for side, sn in [(1, "long"), (-1, "short")]:
        g = R[(R.tf == T) & (R.side == side)]
        if len(g) < 200:
            continue
        t10, sp, sn_ = blk(g)
        print(f"{T:>4} {sn:>6} {'СХЕМА (с разрешением)':>24} {len(g):>9,} "
              f"{g.pnl.mean():+8.3f}% {g.pnl.median():+8.3f}% "
              f"{(g.pnl>0).mean()*100:5.1f}% {g.bars.median():>6.0f} {t10:+8.3f}% "
              f"{sp}/{sn_}")
        for kind, lbl in [("C1_свободный", "C1 кроссы без разреш."),
                          ("C2_база", "C2 полная база")]:
            b = B[(B.kind == kind) & (B.tf == T) & (B.side == side)]
            if len(b) < 200:
                continue
            v = np.sort(b.pnl.values)[::-1]
            per = b.groupby("sym").pnl.mean()
            print(f"{'':>4} {'':>6} {lbl:>24} {len(b):>9,} {b.pnl.mean():+8.3f}% "
                  f"{b.pnl.median():+8.3f}% {(b.pnl>0).mean()*100:5.1f}% "
                  f"{b.bars.median():>6.0f} {v[int(len(v)*.1):].mean():+8.3f}% "
                  f"{int((per>0).sum())}/{len(per)}")
        b1 = B[(B.kind == "C1_свободный") & (B.tf == T) & (B.side == side)].pnl.mean()
        b2 = B[(B.kind == "C2_база") & (B.tf == T) & (B.side == side)].pnl.mean()
        print(f"{'':>4} {'':>6} {'→ над C1 / над C2':>24} "
              f"{g.pnl.mean()-b1:+8.3f} / {g.pnl.mean()-b2:+.3f} п.п.")
        print()

print("=== ПЛЮСЫ ЕГОРА ===")
print(f"{'T':>4} {'стор':>6} {'условие':>26} {'n':>8} {'доля':>7} {'нетто':>9} "
      f"{'мед':>9} {'WR':>6} {'безтоп10':>9} {'монет+':>7}")
for T in ENTRIES:
    for side, sn in [(1, "long"), (-1, "short")]:
        g0 = R[(R.tf == T) & (R.side == side)]
        if len(g0) < 500:
            continue
        for lbl, cond in [
                ("без плюсов", (g0.div1h == 0) & (g0.pivot == 0) & (g0.med == 0)),
                ("P1 дивер на часовике", g0.div1h == 1),
                ("P2 пивот рядом", g0.pivot == 1),
                ("P3 медиана пересечена", g0.med == 1),
                ("P1+P2", (g0.div1h == 1) & (g0.pivot == 1)),
                ("P1+P3", (g0.div1h == 1) & (g0.med == 1)),
                ("P2+P3", (g0.pivot == 1) & (g0.med == 1)),
                ("все три", (g0.div1h == 1) & (g0.pivot == 1) & (g0.med == 1)),
                ("плюсов ≥2", (g0.div1h + g0.pivot + g0.med) >= 2)]:
            g = g0[cond]
            if len(g) < 100:
                continue
            t10, sp, sn_ = blk(g)
            print(f"{T:>4} {sn:>6} {lbl:>26} {len(g):>8,} {len(g)/len(g0)*100:6.1f}% "
                  f"{g.pnl.mean():+8.3f}% {g.pnl.median():+8.3f}% "
                  f"{(g.pnl>0).mean()*100:5.1f}% {t10:+8.3f}% {sp}/{sn_}")
        print()

print("=== СВЕЖЕСТЬ РАЗРЕШЕНИЯ (часов с кросса на часовике) ===")
print(f"{'T':>4} {'стор':>6} {'возраст':>10} {'n':>8} {'нетто':>9} {'мед':>9} "
      f"{'безтоп10':>9} {'монет+':>7}")
for T in ENTRIES:
    for side, sn in [(1, "long"), (-1, "short")]:
        g0 = R[(R.tf == T) & (R.side == side)]
        if len(g0) < 500:
            continue
        for lo, hi_, lbl in [(0, 2, "0-2 ч"), (2, 5, "2-5 ч"), (5, 8, "5-8 ч"),
                             (8, 13, "8-13 ч")]:
            g = g0[(g0.age_h >= lo) & (g0.age_h < hi_)]
            if len(g) < 100:
                continue
            t10, sp, sn_ = blk(g)
            print(f"{T:>4} {sn:>6} {lbl:>10} {len(g):>8,} {g.pnl.mean():+8.3f}% "
                  f"{g.pnl.median():+8.3f}% {t10:+8.3f}% {sp}/{sn_}")
        print()

print("=== ПО ГОДАМ ===")
for T in ENTRIES:
    for side, sn in [(1, "long"), (-1, "short")]:
        g0 = R[(R.tf == T) & (R.side == side)]
        if len(g0) < 500:
            continue
        parts = []
        for y in sorted(g0.year.unique()):
            g = g0[g0.year == y]
            if len(g) < 100:
                continue
            parts.append(f"{y}: {g.pnl.mean():+.3f}% (n={len(g):,})")
        print(f"  T={T}m {sn:>5}: " + " · ".join(parts))
