# -*- coding: utf-8 -*-
"""WT + СТРУКТУРА: короткий структурный стоп и вход не «в воздухе» (Егор, 10.09.2026).

Прошлый замер показал: медианы положительны на ВСЕХ шести строках (+0.49…+6.93%),
а средние отрицательны — потому что стопа нет вовсе, MAE доходит до −15%.

Здесь:
  вход   — кросс wt1×wt2 по режиму (wt1 над/под медианой WT)
  фильтр — цена ВБЛИЗИ структуры: рядом swing-уровень или зона OB/FVG
  стоп   — за ближайший swing против направления (структурный ⇒ короткий)
  выход  — разворот в экстремальной зоне (кросс в OB/OS) или стоп

Расстояние до стопа становится ОСЬЮ отбора: берём входы, где структура рядом.
🔴 Зеркальность · IS→OOS · охват монет · медианы · косты 0.35%.
🔴 Детекторы OB/FVG — починенные 10.09 (пороги в долях ATR).
"""
import os, sys, glob, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_wt
from core.smc.oko_sm_engine import _swings
from core.calculators.swing_bridge import etl_order_blocks, etl_fvg

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
TFS = [60, 240]
MED_LEN = 34
SW_LEN = 10
OS, OB = -60.0, 60.0
TIMEOUT = 200
NSYM = 30
COST = 0.35
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))[:NSYM]
print(f"монет: {len(files)} · ТФ {TFS} · swing {SW_LEN} · медиана WT {MED_LEN}\n",
      flush=True)


def resample(d1, tf):
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last(),
                         "volume": r["volume"].sum()}).dropna()


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
        dd = d.reset_index(drop=True)
        w = calculate_wt(dd)
        wt1, wt2 = w["wt1"].values, w["wt2"].values
        med = pd.Series(wt1).rolling(MED_LEN, min_periods=MED_LEN // 2).mean().values
        c = d["close"].values; hi = d["high"].values; lo = d["low"].values
        n = len(c)
        atr = ((d["high"] - d["low"]) / d["close"]).rolling(14,
                                                            min_periods=7).mean().values * 100
        cu = np.zeros(n, bool); cd = np.zeros(n, bool)
        cu[1:] = (wt1[:-1] <= wt2[:-1]) & (wt1[1:] > wt2[1:])
        cd[1:] = (wt1[:-1] >= wt2[:-1]) & (wt1[1:] < wt2[1:])
        x_up = cd & (wt1 > OB)          # выход лонга
        x_dn = cu & (wt1 < OS)          # выход шорта
        # структура: подтверждённые swing-уровни (каузально — с бара подтверждения)
        sw = _swings(d["high"], d["low"], SW_LEN)
        low_lvl = np.full(n, np.nan); high_lvl = np.full(n, np.nan)
        cur_lo = cur_hi = np.nan
        by_conf = {}
        for conf_i, sw_i, price, is_top in sw:
            by_conf.setdefault(conf_i, []).append((price, is_top))
        for i in range(n):
            for price, is_top in by_conf.get(i, []):
                if is_top:
                    cur_hi = price
                else:
                    cur_lo = price
            low_lvl[i] = cur_lo; high_lvl[i] = cur_hi
        # зоны OB/FVG (починенные пороги)
        try:
            ob = etl_order_blocks(dd); fv = etl_fvg(dd)
            in_bull_zone = (np.asarray(ob["bull_ob_near"], bool) |
                            np.asarray(fv["bull_fvg_in"], bool))
            in_bear_zone = (np.asarray(ob["bear_ob_near"], bool) |
                            np.asarray(fv["bear_fvg_in"], bool))
        except Exception:
            in_bull_zone = in_bear_zone = np.zeros(n, bool)
        for i in range(MED_LEN + SW_LEN + 5, n - 5):
            if np.isnan(med[i]) or np.isnan(atr[i]) or atr[i] <= 0:
                continue
            reg = 1 if wt1[i] > med[i] else -1
            for sig, side in ((cu[i], 1), (cd[i], -1)):
                if not sig or side != reg:
                    continue
                e = c[i]
                # СТРУКТУРНЫЙ СТОП: ближайший swing против направления
                lvl = low_lvl[i] if side == 1 else high_lvl[i]
                if np.isnan(lvl):
                    continue
                stop_pct = (e - lvl) / e * 100 if side == 1 else (lvl - e) / e * 100
                if stop_pct <= 0.05:
                    continue
                in_zone = in_bull_zone[i] if side == 1 else in_bear_zone[i]
                exit_arr = x_up if side == 1 else x_dn
                lim = min(i + TIMEOUT, n - 1)
                res, bars, how = None, 0, "timeout"
                for j in range(i + 1, lim + 1):
                    bars = j - i
                    if side == 1:
                        if lo[j] <= lvl:
                            res, how = -stop_pct, "stop"; break
                    else:
                        if hi[j] >= lvl:
                            res, how = -stop_pct, "stop"; break
                    if exit_arr[j]:
                        res = (c[j] - e) / e * 100 * side; how = "zone"; break
                if res is None:
                    res = (c[lim] - e) / e * 100 * side
                rows.append(dict(sym=sym, tf=tf, side=side, stop=stop_pct,
                                 stop_atr=stop_pct / atr[i], zone=int(in_zone),
                                 pnl=res, bars=bars, how=how,
                                 half=int(i >= n // 2)))
    if fi % 6 == 0:
        print(f"  [{fi}/{len(files)}] сделок {len(rows):,}", flush=True)

R = pd.DataFrame(rows)
R["net"] = R.pnl - COST
R.to_pickle(D + r"\wt_struct_stop.pkl")
print(f"\nсделок: {len(R):,}\n")

print("=== ЭФФЕКТ СТРУКТУРНОГО СТОПА (против прошлого замера без стопа) ===")
print(f"{'ТФ':>5} {'стор':>6} {'n':>7} {'стоп%':>7} {'стоп/ATR':>9} {'нетто':>9} "
      f"{'мед':>9} {'WR':>6} {'по стопу':>9} {'по зоне':>8}")
for tf in TFS:
    for side, sn in [(1, "long"), (-1, "short")]:
        g = R[(R.tf == tf) & (R.side == side)]
        if len(g) < 200:
            continue
        print(f"{tf:>4}m {sn:>6} {len(g):>7,} {g.stop.median():6.2f}% "
              f"{g.stop_atr.median():8.2f} {g.net.mean():+8.3f}% {g.net.median():+8.3f}% "
              f"{(g.net > 0).mean()*100:5.1f}% {(g.how=='stop').mean()*100:8.1f}% "
              f"{(g.how=='zone').mean()*100:7.1f}%")
    print()

print("=== ФИЛЬТР «НЕ В ВОЗДУХЕ»: вход в зоне OB/FVG ===")
print(f"{'ТФ':>5} {'стор':>6} {'фильтр':>12} {'n':>7} {'нетто':>9} {'мед':>9} "
      f"{'WR':>6} {'IS':>9} {'OOS':>9} {'перенос':>8} {'монет+':>9}")
for tf in TFS:
    for side, sn in [(1, "long"), (-1, "short")]:
        for lbl, sub in [("все", R[(R.tf == tf) & (R.side == side)]),
                         ("в зоне", R[(R.tf == tf) & (R.side == side) & (R.zone == 1)])]:
            if len(sub) < 150:
                continue
            i_, o_ = sub[sub.half == 0].net, sub[sub.half == 1].net
            tag = "✓" if len(i_) > 40 and len(o_) > 40 and i_.mean() * o_.mean() > 0 \
                and i_.mean() > 0 else "✗"
            per = sub.groupby("sym").net.mean()
            print(f"{tf:>4}m {sn:>6} {lbl:>12} {len(sub):>7,} {sub.net.mean():+8.3f}% "
                  f"{sub.net.median():+8.3f}% {(sub.net>0).mean()*100:5.1f}% "
                  f"{i_.mean():+8.3f}% {o_.mean():+8.3f}% {tag:>8} "
                  f"{int((per>0).sum())}/{len(per)}")
    print()

print("=== ДЛИНА СТОПА КАК ОСЬ ОТБОРА (квинтили стоп/ATR) ===")
print(f"{'ТФ':>5} {'квинтиль':>9} {'стоп/ATR':>9} {'n':>7} {'нетто':>9} {'мед':>9} "
      f"{'WR':>6}")
for tf in TFS:
    g = R[R.tf == tf].copy()
    if len(g) < 500:
        continue
    g["q"] = pd.qcut(g.stop_atr, 5, labels=False, duplicates="drop")
    for q in sorted(g.q.dropna().unique()):
        s = g[g.q == q]
        print(f"{tf:>4}m {int(q)+1:>9} {s.stop_atr.median():8.2f} {len(s):>7,} "
              f"{s.net.mean():+8.3f}% {s.net.median():+8.3f}% {(s.net>0).mean()*100:5.1f}%")
    print()
