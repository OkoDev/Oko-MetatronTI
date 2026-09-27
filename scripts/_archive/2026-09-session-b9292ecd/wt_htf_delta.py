# -*- coding: utf-8 -*-
"""ДЕЛЬТА НА СТАРШЕМ ТФ КАК СОСТОЯНИЕ (Егор, 10.09.2026).

Дельта |wt1−wt2| на ТФ ВХОДА (60m) работает обратно: слабые кроссы лучше сильных.
Гипотеза Егора о другом — дельта на ТФ РЕЖИМА (240m):
    расширяется → импульс старшего усиливается → входы на LTF по нему надёжнее
    сужается    → старший выдыхается           → входы рискованнее

Меряем три величины старшего ТФ в момент входа:
    A  величина дельты (квинтили)
    B  расширение: дельта растёт или падает (производная)
    C  знак: расширяется ли в сторону режима (wt1 уходит от wt2 в нужную сторону)

🔴 Всё каузально: состояние 240m берётся по ЗАКРЫТОМУ бару.
🔴 Вход по OPEN следующего бара (проверено: утечки нет), одна позиция за раз.
"""
import os, sys, glob, bisect, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_wt

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
TF_REG, TF_IN = 240, 60
MED_LEN = 34
OS, OB = -60.0, 60.0
TIMEOUT = 200
COST = 0.35
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))
print(f"монет: {len(files)} · режим {TF_REG}m → вход {TF_IN}m\n", flush=True)


def resample(d1, tf):
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


rows = []
for fi, f in enumerate(files, 1):
    sym = os.path.basename(f)[:-8]
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    dr = resample(d1, TF_REG); di = resample(d1, TF_IN)
    if len(dr) < 200 or len(di) < 600:
        continue
    wr_ = calculate_wt(dr.reset_index(drop=True))
    r1, r2 = wr_["wt1"].values, wr_["wt2"].values
    medr = pd.Series(r1).rolling(MED_LEN, min_periods=MED_LEN // 2).mean().values
    above = r1 > medr
    dlt_r = r1 - r2                       # СО ЗНАКОМ: направление расхождения
    adlt_r = np.abs(dlt_r)                # величина
    exp_r = np.concatenate(([0.0], np.diff(adlt_r)))   # расширение/сужение
    ct_r = list(dr.index + pd.Timedelta(minutes=TF_REG))
    wi = calculate_wt(di.reset_index(drop=True))
    w1, w2 = wi["wt1"].values, wi["wt2"].values
    c = di["close"].values; o = di["open"].values
    n = len(c)
    cu = np.zeros(n, bool); cd = np.zeros(n, bool)
    cu[1:] = (w1[:-1] <= w2[:-1]) & (w1[1:] > w2[1:])
    cd[1:] = (w1[:-1] >= w2[:-1]) & (w1[1:] < w2[1:])
    x_up = cd & (w1 > OB); x_dn = cu & (w1 < OS)
    d_in = np.abs(w1 - w2)

    def exit_bar(i, side):
        arr = x_up if side == 1 else x_dn
        opp = cd if side == 1 else cu
        lim = min(i + TIMEOUT, n - 1)
        jz = np.where(arr[i + 1:lim + 1])[0]
        jo = np.where(opp[i + 1:lim + 1])[0]
        if len(jz):
            return i + 1 + int(jz[0])
        if len(jo):
            return i + 1 + int(jo[0])
        return lim

    busy = -1
    for i in range(MED_LEN + 5, n - 5):
        for sig, side in ((cu[i], 1), (cd[i], -1)):
            if not sig:
                continue
            j = bisect.bisect_right(ct_r, di.index[i] + pd.Timedelta(minutes=TF_IN)) - 1
            if j < 5 or np.isnan(medr[j]):
                continue
            if (1 if above[j] else -1) != side:
                continue
            ii = i + 1
            if ii >= n - 3 or ii <= busy:
                continue
            jx = exit_bar(ii, side)
            e = o[ii]
            r_ = (c[jx] - e) / e * 100 * side - COST
            busy = jx
            rows.append(dict(sym=sym, side=side,
                             htf_d=float(adlt_r[j]),          # величина дельты HTF
                             htf_exp=float(exp_r[j]),         # расширение HTF
                             htf_dir=float(dlt_r[j] * side),  # расхождение В СТОРОНУ входа
                             ltf_d=float(d_in[i]),            # сила кросса на LTF
                             pnl=r_, bars=jx - ii, half=int(i >= n // 2)))
    if fi % 10 == 0:
        print(f"  [{fi}/{len(files)}] {sym}", flush=True)

R = pd.DataFrame(rows)
R.to_pickle(D + r"\wt_htf_delta.pkl")
print(f"\nсделок: {len(R):,} · монет {R.sym.nunique()}\n")
base = R.pnl.mean()
print(f"база (все входы): {base:+.3f}% на сделку\n")

print("=== A. ВЕЛИЧИНА ДЕЛЬТЫ НА СТАРШЕМ ТФ ===")
R["q_d"] = pd.qcut(R.htf_d, 5, labels=False, duplicates="drop")
print(f"{'квинтиль':>9} {'|Δ| HTF':>9} {'n':>8} {'нетто':>9} {'мед':>9} {'WR':>6}")
for q in sorted(R.q_d.dropna().unique()):
    g = R[R.q_d == q]
    print(f"{int(q)+1:>9} {g.htf_d.median():8.2f} {len(g):>8,} {g.pnl.mean():+8.3f}% "
          f"{g.pnl.median():+8.3f}% {(g.pnl>0).mean()*100:5.1f}%")

print("\n=== B. РАСШИРЕНИЕ ДЕЛЬТЫ HTF (производная) ===")
print(f"{'состояние':>18} {'n':>8} {'доля':>7} {'нетто':>9} {'мед':>9} {'WR':>6} "
      f"{'IS':>9} {'OOS':>9} {'перенос':>8}")
for lbl, cond in [("сужается", R.htf_exp < -0.05),
                  ("плоско", (R.htf_exp >= -0.05) & (R.htf_exp <= 0.05)),
                  ("расширяется", R.htf_exp > 0.05)]:
    g = R[cond]
    if len(g) < 300:
        continue
    i_, o_ = g[g.half == 0].pnl, g[g.half == 1].pnl
    tag = "✓" if i_.mean() * o_.mean() > 0 and i_.mean() > 0 else "✗"
    print(f"{lbl:>18} {len(g):>8,} {len(g)/len(R)*100:6.1f}% {g.pnl.mean():+8.3f}% "
          f"{g.pnl.median():+8.3f}% {(g.pnl>0).mean()*100:5.1f}% {i_.mean():+8.3f}% "
          f"{o_.mean():+8.3f}% {tag:>8}")

print("\n=== C. РАСХОЖДЕНИЕ В СТОРОНУ ВХОДА (знак Δ × сторона) ===")
R["q_dir"] = pd.qcut(R.htf_dir, 5, labels=False, duplicates="drop")
print(f"{'квинтиль':>9} {'Δ·сторона':>11} {'n':>8} {'нетто':>9} {'мед':>9} {'WR':>6}")
for q in sorted(R.q_dir.dropna().unique()):
    g = R[R.q_dir == q]
    print(f"{int(q)+1:>9} {g.htf_dir.median():10.2f} {len(g):>8,} {g.pnl.mean():+8.3f}% "
          f"{g.pnl.median():+8.3f}% {(g.pnl>0).mean()*100:5.1f}%")

print("\n=== D. КОМБИНАЦИЯ: расширение HTF × слабый кросс LTF ===")
print(f"{'условие':>34} {'n':>8} {'доля':>7} {'нетто':>9} {'мед':>9} {'монет+':>9}")
lo_ltf = R.ltf_d <= R.ltf_d.quantile(.4)
for lbl, cond in [("все входы", R.pnl == R.pnl),
                  ("расширение HTF", R.htf_exp > 0.05),
                  ("слабый кросс LTF", lo_ltf),
                  ("расширение HTF + слабый LTF", (R.htf_exp > 0.05) & lo_ltf)]:
    g = R[cond]
    if len(g) < 200:
        continue
    per = g.groupby("sym").pnl.mean()
    print(f"{lbl:>34} {len(g):>8,} {len(g)/len(R)*100:6.1f}% {g.pnl.mean():+8.3f}% "
          f"{g.pnl.median():+8.3f}% {int((per>0).sum())}/{len(per)}")

print("\n=== ЗЕРКАЛЬНОСТЬ ЛУЧШЕГО УСЛОВИЯ ===")
best = R[(R.htf_exp > 0.05)]
for side, sn in [(1, "long"), (-1, "short")]:
    g = best[best.side == side]
    if len(g) < 150:
        continue
    per = g.groupby("sym").pnl.mean()
    print(f"  {sn:>5}: n={len(g):>6,} нетто {g.pnl.mean():+.3f}% мед {g.pnl.median():+.3f}% "
          f"монет+ {int((per>0).sum())}/{len(per)}")
