# -*- coding: utf-8 -*-
"""СХЕМА ЕГОРА: медиана WT → кросс в зоне OS/OB (10.09.2026, скрин BCH 1h).

Двухступенчатый триггер:
  1. wt1 пересекает МЕДИАНУ (длинная скользящая по самому WT — зелёная на панели)
     → смена режима осциллятора
  2. ПОСЛЕ этого — кросс wt1×wt2 в зоне перепроданности (<-60) или перекупленности (>+60)
     → точка входа

Проверяются обе ступени по отдельности и вместе, чтобы видеть вклад каждой.
🔴 Зеркальность обязательна · IS→OOS · охват монет · медианы.
"""
import os, sys, glob
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_wt

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
TFS = [15, 60, 240]
MED_LEN = 34            # длина медианы по WT (зелёная линия)
OS, OB = -60.0, 60.0
MAX_WAIT = 24           # сколько баров ждём кросс после пересечения медианы
FWD = [8, 24, 72]       # горизонты в барах ТФ
NSYM = 40
COST = 0.35
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))[:NSYM]
print(f"монет: {len(files)} · ТФ {TFS} · медиана WT({MED_LEN}) · ожидание {MAX_WAIT} баров\n",
      flush=True)


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
    for tf in TFS:
        d = resample(d1, tf)
        if len(d) < 500:
            continue
        w = calculate_wt(d.reset_index(drop=True))
        wt1, wt2 = w["wt1"].values, w["wt2"].values
        med = pd.Series(wt1).rolling(MED_LEN, min_periods=MED_LEN // 2).mean().values
        c = d["close"].values
        n = len(c)
        # ступень 1: пересечение медианы
        cross_med_up = np.zeros(n, bool); cross_med_dn = np.zeros(n, bool)
        m_ok = ~np.isnan(med)
        cross_med_up[1:] = m_ok[1:] & (wt1[:-1] <= med[:-1]) & (wt1[1:] > med[1:])
        cross_med_dn[1:] = m_ok[1:] & (wt1[:-1] >= med[:-1]) & (wt1[1:] < med[1:])
        # ступень 2: кросс wt1×wt2 в зоне
        cu = np.zeros(n, bool); cd = np.zeros(n, bool)
        cu[1:] = (wt1[:-1] <= wt2[:-1]) & (wt1[1:] > wt2[1:]) & (wt1[:-1] < OS)
        cd[1:] = (wt1[:-1] >= wt2[:-1]) & (wt1[1:] < wt2[1:]) & (wt1[:-1] > OB)
        # давность пересечения медианы
        last_up = np.full(n, -10**9); last_dn = np.full(n, -10**9)
        lu = ld = -10**9
        for i in range(n):
            if cross_med_up[i]:
                lu = i
            if cross_med_dn[i]:
                ld = i
            last_up[i] = lu; last_dn[i] = ld
        for i in range(MED_LEN + 5, n - max(FWD) - 1):
            for sig, side, med_age in ((cu[i], 1, i - last_up[i]),
                                       (cd[i], -1, i - last_dn[i])):
                if not sig:
                    continue
                rec = dict(sym=sym, tf=tf, side=side,
                           after_med=int(0 <= med_age <= MAX_WAIT),
                           med_age=int(med_age) if med_age < 10**8 else -1,
                           half=int(i >= n // 2))
                for h in FWD:
                    rec[f"f{h}"] = (c[i + h] - c[i]) / c[i] * 100 * side
                rows.append(rec)
    if fi % 8 == 0:
        print(f"  [{fi}/{len(files)}] сигналов {len(rows):,}", flush=True)

R = pd.DataFrame(rows)
R.to_pickle(D + r"\wt_median_cross.pkl")
print(f"\nсигналов: {len(R):,}\n")

print("=== ВКЛАД СТУПЕНЕЙ: кросс в зоне · и он же ПОСЛЕ пересечения медианы ===")
print(f"{'ТФ':>5} {'фильтр':>22} {'стор':>6} {'n':>7} "
      + " ".join(f"{h:>9}" for h in FWD) + f" {'мед 24':>9}")
for tf in TFS:
    for nm, sub in [("кросс в зоне", R[R.tf == tf]),
                    ("+ после медианы", R[(R.tf == tf) & (R.after_med == 1)])]:
        for side, sn in [(1, "long"), (-1, "short")]:
            g = sub[sub.side == side]
            if len(g) < 150:
                continue
            vals = " ".join(f"{g[f'f{h}'].mean():+9.3f}" for h in FWD)
            print(f"{tf:>4}m {nm:>22} {sn:>6} {len(g):>7,} {vals} "
                  f"{g['f24'].median():+9.3f}")
    print()

print("=== ПОЛНЫЙ ПРОТОКОЛ: обе ступени, горизонт 24 бара ===")
print(f"{'ТФ':>5} {'стор':>6} {'n':>7} {'ход':>9} {'мед':>9} {'нетто':>9} "
      f"{'IS':>9} {'OOS':>9} {'перенос':>8} {'монет+':>9}")
for tf in TFS:
    for side, sn in [(1, "long"), (-1, "short")]:
        g = R[(R.tf == tf) & (R.after_med == 1) & (R.side == side)]
        if len(g) < 150:
            continue
        v = g["f24"]
        i_, o_ = v[g.half == 0], v[g.half == 1]
        tag = "✓" if len(i_) > 40 and len(o_) > 40 and i_.mean() * o_.mean() > 0 \
            and i_.mean() > 0 else "✗"
        per = g.groupby("sym").f24.mean()
        print(f"{tf:>4}m {sn:>6} {len(g):>7,} {v.mean():+8.3f}% {v.median():+8.3f}% "
              f"{v.mean()-COST:+8.3f}% {i_.mean():+8.3f}% {o_.mean():+8.3f}% "
              f"{tag:>8} {int((per>0).sum())}/{len(per)}")
    print()

print("=== ЗЕРКАЛЬНОСТЬ (обе ступени) ===")
for tf in TFS:
    g = R[(R.tf == tf) & (R.after_med == 1)]
    l = g[g.side == 1]["f24"]; s = g[g.side == -1]["f24"]
    if len(l) < 100 or len(s) < 100:
        continue
    print(f"  {tf:>4}m: long {l.mean():+.3f}% (мед {l.median():+.3f}%) · "
          f"short {s.mean():+.3f}% (мед {s.median():+.3f}%) · "
          f"{'ЗЕРКАЛЬНО' if l.mean() > 0 and s.mean() > 0 else 'нет'}")

print("\n=== ДАВНОСТЬ ПЕРЕСЕЧЕНИЯ МЕДИАНЫ → результат (24 бара) ===")
print(f"{'давность':>12} {'n':>8} {'ход':>9} {'мед':>9}")
for lo, hi in [(0, 3), (3, 8), (8, 16), (16, 25), (25, 10**9)]:
    g = R[(R.med_age >= lo) & (R.med_age < hi) & (R.med_age >= 0)]
    if len(g) < 300:
        continue
    lbl = f"{lo}-{hi}" if hi < 10**8 else f"{lo}+"
    print(f"{lbl:>12} {len(g):>8,} {g['f24'].mean():+8.3f}% {g['f24'].median():+8.3f}%")
