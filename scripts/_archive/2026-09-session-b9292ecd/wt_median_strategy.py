# -*- coding: utf-8 -*-
"""СТРАТЕГИЯ ЕГОРА: вход по пересечению медианы WT, выход в экстремальной зоне.

    ЛОНГ:  вход — wt1 пересекает медиану ВВЕРХ · выход — wt1 > +60 (перекупленность)
    ШОРТ:  вход — wt1 пересекает медиану ВНИЗ  · выход — wt1 < −60 (перепроданность)

Выход по УСЛОВИЮ осциллятора, а не по времени. Меряем:
  · долю сделок, дошедших до выхода (и что с остальными)
  · ход до выхода, время удержания
  · таймаут: если зона не достигнута за N баров — закрытие по рынку
  · MAE по пути: насколько глубоко проседает до выхода
🔴 Зеркальность · IS→OOS · охват монет · медианы · косты.
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
MED_LENS = [21, 34, 55]        # длина медианы по WT — ось, не константа
OS, OB = -60.0, 60.0
TIMEOUT = 200                  # предохранитель: макс. баров в позиции
NSYM = 40
COST = 0.35
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))[:NSYM]
print(f"монет: {len(files)} · ТФ {TFS} · медианы {MED_LENS}\n", flush=True)


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
        if len(d) < 600:
            continue
        w = calculate_wt(d.reset_index(drop=True))
        wt1, wt2 = w["wt1"].values, w["wt2"].values
        # ВЫХОД (уточнение Егора): не касание зоны, а РАЗВОРОТ в ней —
        #   лонг закрывается кроссом ВНИЗ (wt1 через wt2) при wt1 > +60
        #   шорт закрывается кроссом ВВЕРХ при wt1 < −60
        n_ = len(wt1)
        x_dn = np.zeros(n_, bool); x_up = np.zeros(n_, bool)
        x_dn[1:] = (wt1[:-1] >= wt2[:-1]) & (wt1[1:] < wt2[1:]) & (wt1[1:] > OB)
        x_up[1:] = (wt1[:-1] <= wt2[:-1]) & (wt1[1:] > wt2[1:]) & (wt1[1:] < OS)
        c = d["close"].values
        hi, lo = d["high"].values, d["low"].values
        n = len(c)
        for ML in MED_LENS:
            med = pd.Series(wt1).rolling(ML, min_periods=ML // 2).mean().values
            ok = ~np.isnan(med)
            up = np.zeros(n, bool); dn = np.zeros(n, bool)
            up[1:] = ok[1:] & (wt1[:-1] <= med[:-1]) & (wt1[1:] > med[1:])
            dn[1:] = ok[1:] & (wt1[:-1] >= med[:-1]) & (wt1[1:] < med[1:])
            for i in range(ML + 5, n - 5):
                for sig, side, exit_arr in ((up[i], 1, x_dn), (dn[i], -1, x_up)):
                    if not sig:
                        continue
                    e = c[i]
                    # выход: РАЗВОРОТ в экстремальной зоне (кросс wt1×wt2 внутри зоны)
                    j_end, reason = None, "timeout"
                    lim = min(i + TIMEOUT, n - 1)
                    for j in range(i + 1, lim + 1):
                        if exit_arr[j]:
                            j_end, reason = j, "zone"
                            break
                    if j_end is None:
                        j_end = lim
                    seg_h = hi[i + 1:j_end + 1]; seg_l = lo[i + 1:j_end + 1]
                    if len(seg_h) == 0:
                        continue
                    if side == 1:
                        mae = (seg_l.min() - e) / e * 100
                        mfe = (seg_h.max() - e) / e * 100
                    else:
                        mae = (e - seg_h.max()) / e * 100
                        mfe = (e - seg_l.min()) / e * 100
                    rows.append(dict(sym=sym, tf=tf, ml=ML, side=side,
                                     pnl=(c[j_end] - e) / e * 100 * side,
                                     bars=j_end - i, zone=int(reason == "zone"),
                                     mae=mae, mfe=mfe, half=int(i >= n // 2)))
    if fi % 8 == 0:
        print(f"  [{fi}/{len(files)}] сделок {len(rows):,}", flush=True)

R = pd.DataFrame(rows)
R["net"] = R.pnl - COST
R.to_pickle(D + r"\wt_median_strategy.pkl")
print(f"\nсделок: {len(R):,}\n")

print("=== СТРАТЕГИЯ ПО ТФ И ДЛИНЕ МЕДИАНЫ ===")
print(f"{'ТФ':>5} {'мед':>5} {'стор':>6} {'n':>7} {'дошло до зоны':>14} {'баров':>7} "
      f"{'ход':>9} {'мед':>9} {'нетто':>9} {'WR':>6}")
for tf in TFS:
    for ML in MED_LENS:
        for side, sn in [(1, "long"), (-1, "short")]:
            g = R[(R.tf == tf) & (R.ml == ML) & (R.side == side)]
            if len(g) < 200:
                continue
            print(f"{tf:>4}m {ML:>5} {sn:>6} {len(g):>7,} {g.zone.mean()*100:13.1f}% "
                  f"{g.bars.median():>7.0f} {g.pnl.mean():+8.3f}% {g.pnl.median():+8.3f}% "
                  f"{g.net.mean():+8.3f}% {(g.net > 0).mean()*100:5.1f}%")
    print()

print("=== ПОЛНЫЙ ПРОТОКОЛ (лучшая длина медианы по каждому ТФ) ===")
print(f"{'ТФ':>5} {'мед':>5} {'стор':>6} {'n':>7} {'нетто':>9} {'мед':>9} "
      f"{'IS':>9} {'OOS':>9} {'перенос':>8} {'монет+':>9} {'зеркально':>10}")
for tf in TFS:
    best_ml, best_v = None, -9
    for ML in MED_LENS:
        g = R[(R.tf == tf) & (R.ml == ML)]
        if len(g) < 400:
            continue
        v = g.net.mean()
        if v > best_v:
            best_v, best_ml = v, ML
    if best_ml is None:
        continue
    res = {}
    for side, sn in [(1, "long"), (-1, "short")]:
        g = R[(R.tf == tf) & (R.ml == best_ml) & (R.side == side)]
        if len(g) < 200:
            continue
        i_, o_ = g[g.half == 0].net, g[g.half == 1].net
        tag = "✓" if len(i_) > 50 and len(o_) > 50 and i_.mean() * o_.mean() > 0 \
            and i_.mean() > 0 else "✗"
        per = g.groupby("sym").net.mean()
        res[side] = g.net.mean()
        print(f"{tf:>4}m {best_ml:>5} {sn:>6} {len(g):>7,} {g.net.mean():+8.3f}% "
              f"{g.net.median():+8.3f}% {i_.mean():+8.3f}% {o_.mean():+8.3f}% "
              f"{tag:>8} {int((per>0).sum())}/{len(per)} "
              f"{('ДА' if min(res.values()) > 0 else 'нет') if len(res) == 2 else '':>10}")

print("\n=== ГЕОМЕТРИЯ: MFE / MAE до выхода ===")
print(f"{'ТФ':>5} {'стор':>6} {'MFE мед':>9} {'MAE мед':>9} {'MFE/MAE':>8} "
      f"{'баров мед':>10}")
for tf in TFS:
    for side, sn in [(1, "long"), (-1, "short")]:
        g = R[(R.tf == tf) & (R.side == side) & (R.ml == 34)]
        if len(g) < 200:
            continue
        mfe = g.mfe.median(); mae = g.mae.median()
        print(f"{tf:>4}m {sn:>6} {mfe:+8.3f}% {mae:+8.3f}% "
              f"{abs(mfe/mae) if mae else 0:8.2f} {g.bars.median():>10.0f}")

print("\n=== ДОШЛИ ДО ЗОНЫ против ТАЙМАУТА (медиана 34) ===")
for tf in TFS:
    g = R[(R.tf == tf) & (R.ml == 34)]
    if len(g) < 300:
        continue
    z = g[g.zone == 1]; t_ = g[g.zone == 0]
    print(f"  {tf:>4}m: дошли {len(z):>6,} ({len(z)/len(g)*100:.0f}%) нетто "
          f"{z.net.mean():+.3f}% · таймаут {len(t_):>6,} нетто {t_.net.mean():+.3f}%")
