# -*- coding: utf-8 -*-
"""Отчёт по замеру лестницы (данные уже в pkl; в прошлом прогоне `R.T` = транспонирование)."""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
R = pd.read_pickle(D + r"\egor_ladder.pkl").rename(columns={"T": "tf"})
B = pd.read_pickle(D + r"\egor_ladder_base.pkl").rename(columns={"T": "tf"})
LADDER = [3, 5, 15, 30, 45, 60, 120, 240]
ENTRIES = sorted(R.tf.unique())
XN = {1: "X1 до зоны", 2: "X2 кросс вне зон"}
bm = B.groupby(["tf", "side", "xv"]).pnl.mean()
print(f"сигналов {len(R):,} · база {len(B):,} · монет {R.sym.nunique()}\n")


def blk(g):
    v = np.sort(g.pnl.values)[::-1]
    per = g.groupby("sym").pnl.mean()
    return v[int(len(v)*.1):].mean(), int((per > 0).sum()), len(per)


print("=== БАЗОВЫЙ УРОВЕНЬ (все пересечения нуля, без фильтров) ===")
print(f"{'T':>4} {'выход':>18} {'стор':>6} {'n':>8} {'нетто':>9} {'база':>9} {'над':>9} "
      f"{'мед':>9} {'баров':>6} {'безтоп10':>9} {'монет+':>7}")
for T in ENTRIES:
    for xv in (1, 2):
        for side, sn in [(1, "long"), (-1, "short")]:
            g = R[(R.tf == T) & (R.xv == xv) & (R.side == side)]
            if len(g) < 200:
                continue
            t10, sp, sn_ = blk(g)
            b = float(bm.get((T, side, xv), np.nan))
            print(f"{T:>4} {XN[xv]:>18} {sn:>6} {len(g):>8,} {g.pnl.mean():+8.3f}% "
                  f"{b:+8.3f}% {g.pnl.mean()-b:+8.3f}% {g.pnl.median():+8.3f}% "
                  f"{g.bars.median():>6.0f} {t10:+8.3f}% {sp}/{sn_}")
    print()

print("=== 🔴 ДИВЕРГЕНЦИЯ НА ТФ ВХОДА (метка R+) ===")
print(f"{'T':>4} {'выход':>18} {'стор':>6} {'R+':>4} {'n':>8} {'доля':>7} {'нетто':>9} "
      f"{'над базой':>10} {'мед':>9} {'безтоп10':>9} {'монет+':>7}")
for T in ENTRIES:
    for xv in (1, 2):
        for side, sn in [(1, "long"), (-1, "short")]:
            tot = len(R[(R.tf == T) & (R.xv == xv) & (R.side == side)])
            if tot < 200:
                continue
            b = float(bm.get((T, side, xv), np.nan))
            for dT in (0, 1):
                g = R[(R.tf == T) & (R.xv == xv) & (R.side == side) & (R.div_T == dT)]
                if len(g) < 150:
                    continue
                t10, sp, sn_ = blk(g)
                print(f"{T:>4} {XN[xv]:>18} {sn:>6} {'да' if dT else 'нет':>4} "
                      f"{len(g):>8,} {len(g)/tot*100:6.1f}% {g.pnl.mean():+8.3f}% "
                      f"{g.pnl.mean()-b:+9.3f}% {g.pnl.median():+8.3f}% {t10:+8.3f}% "
                      f"{sp}/{sn_}")
    print()

print("=== ЛЕСТНИЦА: СКОЛЬКО СЛОЁВ СОГЛАСНЫ (гиперкуб) ===")
for T in ENTRIES:
    for side, sn in [(1, "long"), (-1, "short")]:
        g0 = R[(R.tf == T) & (R.xv == 1) & (R.side == side)]
        if len(g0) < 500:
            continue
        b = float(bm.get((T, side, 1), np.nan))
        print(f"\n  T={T}m {sn} · база {b:+.3f}%")
        print(f"{'слоёв':>6} {'n':>8} {'доля':>7} {'нетто':>9} {'над':>9} {'мед':>9} "
              f"{'WR':>6} {'безтоп10':>9} {'монет+':>7}")
        for a in range(len(LADDER) + 1):
            g = g0[g0.n_agree == a]
            if len(g) < 150:
                continue
            t10, sp, sn_ = blk(g)
            print(f"{a:>6} {len(g):>8,} {len(g)/len(g0)*100:6.1f}% {g.pnl.mean():+8.3f}% "
                  f"{g.pnl.mean()-b:+8.3f}% {g.pnl.median():+8.3f}% "
                  f"{(g.pnl>0).mean()*100:5.1f}% {t10:+8.3f}% {sp}/{sn_}")

print("\n=== СЛОЁВ С ДИВЕРГЕНЦИЕЙ ПО ВСЕЙ ЛЕСТНИЦЕ ===")
for T in ENTRIES:
    for side, sn in [(1, "long"), (-1, "short")]:
        g0 = R[(R.tf == T) & (R.xv == 1) & (R.side == side)]
        if len(g0) < 500:
            continue
        b = float(bm.get((T, side, 1), np.nan))
        print(f"\n  T={T}m {sn} · база {b:+.3f}%")
        print(f"{'слоёв':>6} {'n':>8} {'доля':>7} {'нетто':>9} {'над':>9} {'мед':>9} "
              f"{'безтоп10':>9} {'монет+':>7}")
        for a in sorted(g0.n_div.unique()):
            g = g0[g0.n_div == a]
            if len(g) < 150:
                continue
            t10, sp, sn_ = blk(g)
            print(f"{int(a):>6} {len(g):>8,} {len(g)/len(g0)*100:6.1f}% "
                  f"{g.pnl.mean():+8.3f}% {g.pnl.mean()-b:+8.3f}% {g.pnl.median():+8.3f}% "
                  f"{t10:+8.3f}% {sp}/{sn_}")

print("\n=== НАСЛЕДОВАНИЕ ВВЕРХ: согласны слои СТАРШЕ входа ===")
for T in ENTRIES:
    for side, sn in [(1, "long"), (-1, "short")]:
        g0 = R[(R.tf == T) & (R.xv == 1) & (R.side == side)]
        if len(g0) < 500:
            continue
        b = float(bm.get((T, side, 1), np.nan))
        print(f"\n  T={T}m {sn} · база {b:+.3f}%")
        print(f"{'старших':>8} {'n':>8} {'доля':>7} {'нетто':>9} {'над':>9} {'мед':>9} "
              f"{'безтоп10':>9} {'монет+':>7}")
        for a in sorted(g0.n_above.unique()):
            g = g0[g0.n_above == a]
            if len(g) < 150:
                continue
            t10, sp, sn_ = blk(g)
            print(f"{int(a):>8} {len(g):>8,} {len(g)/len(g0)*100:6.1f}% "
                  f"{g.pnl.mean():+8.3f}% {g.pnl.mean()-b:+8.3f}% {g.pnl.median():+8.3f}% "
                  f"{t10:+8.3f}% {sp}/{sn_}")

print("\n=== КОМБИНАЦИИ (метод Егора целиком) ===")
print(f"{'T':>4} {'вых':>4} {'стор':>6} {'условие':>32} {'n':>7} {'доля':>7} {'нетто':>9} "
      f"{'над базой':>10} {'мед':>9} {'безтоп10':>9} {'монет+':>7}")
for T in ENTRIES:
    for xv in (1, 2):
        for side, sn in [(1, "long"), (-1, "short")]:
            g0 = R[(R.tf == T) & (R.xv == xv) & (R.side == side)]
            if len(g0) < 500:
                continue
            b = float(bm.get((T, side, xv), np.nan))
            hi = g0.n_agree >= 6
            for lbl, cond in [
                    ("все входы", g0.n_agree >= 0),
                    ("R+ на входе", g0.div_T == 1),
                    ("лестница ≥6 слоёв", hi),
                    ("зона на старших ≥2", g0.n_zone >= 2),
                    ("R+ и лестница ≥6", (g0.div_T == 1) & hi),
                    ("R+ и зона старших ≥2", (g0.div_T == 1) & (g0.n_zone >= 2)),
                    ("R+ и ≥6 и зона ≥2", (g0.div_T == 1) & hi & (g0.n_zone >= 2)),
                    ("R+ и все старшие согласны",
                     (g0.div_T == 1) & (g0.n_above == g0.n_above.max()))]:
                g = g0[cond]
                if len(g) < 100:
                    continue
                t10, sp, sn_ = blk(g)
                print(f"{T:>4} {xv:>4} {sn:>6} {lbl:>32} {len(g):>7,} "
                      f"{len(g)/len(g0)*100:6.1f}% {g.pnl.mean():+8.3f}% "
                      f"{g.pnl.mean()-b:+9.3f}% {g.pnl.median():+8.3f}% {t10:+8.3f}% "
                      f"{sp}/{sn_}")
            print()
