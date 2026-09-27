# -*- coding: utf-8 -*-
"""ВАРИАНТ 3 (Егор): все кроссы вверх, пока НАД медианой + MTF-переход LTF↔HTF.

Режим:  wt1 > медиана на ТФ_РЕЖИМА  → разрешены только лонги (и наоборот)
Входы:  каждый кросс wt1×wt2 вверх на ТФ_ВХОДА, пока режим держится
Выходы: четыре варианта на одних и тех же входах —
    А  разворот в перекупленности (кросс вниз при wt1 > +60)
    Б  любой кросс вниз
    В  возврат под медиану на ТФ режима
    Г  таймаут
Вопрос Егора: «не всегда в экстремум сразу прилетаем» — доля долетевших и цена ожидания.

MTF: режим на 60m/240m, входы на 5m/15m/60m — старший даёт направление, младший точки.
🔴 Каузально: состояние режима берётся по ЗАКРЫТОМУ бару старшего ТФ (ошибка вида 6).
"""
import os, sys, glob, bisect
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_wt

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
PAIRS = [(60, 5), (60, 15), (60, 60), (240, 15), (240, 60)]   # (режим, вход)
MED_LEN = 34
OS, OB = -60.0, 60.0
TIMEOUT = 200
NSYM = 30
COST = 0.35
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))[:NSYM]
print(f"монет: {len(files)} · пары (режим→вход): {PAIRS}\n", flush=True)


def resample(d1, tf):
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


def wt_pack(d, tf):
    w = calculate_wt(d.reset_index(drop=True))
    wt1, wt2 = w["wt1"].values, w["wt2"].values
    med = pd.Series(wt1).rolling(MED_LEN, min_periods=MED_LEN // 2).mean().values
    n = len(wt1)
    cu = np.zeros(n, bool); cd = np.zeros(n, bool)
    cu[1:] = (wt1[:-1] <= wt2[:-1]) & (wt1[1:] > wt2[1:])
    cd[1:] = (wt1[:-1] >= wt2[:-1]) & (wt1[1:] < wt2[1:])
    xa_up = cd & (wt1 > OB)          # разворот в перекупленности → выход лонга
    xa_dn = cu & (wt1 < OS)          # разворот в перепроданности → выход шорта
    above = np.where(np.isnan(med), np.nan, (wt1 > med).astype(float))
    ct = list(d.index + pd.Timedelta(minutes=tf))
    return dict(wt1=wt1, cu=cu, cd=cd, xa_up=xa_up, xa_dn=xa_dn,
                above=above, ct=ct, idx=d.index, close=d["close"].values)


rows = []
for fi, f in enumerate(files, 1):
    sym = os.path.basename(f)[:-8]
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    cache = {}
    for tf in sorted({t for p in PAIRS for t in p}):
        d = resample(d1, tf)
        if len(d) < 600:
            continue
        cache[tf] = wt_pack(d, tf)
    for tf_reg, tf_in in PAIRS:
        if tf_reg not in cache or tf_in not in cache:
            continue
        Rg, In = cache[tf_reg], cache[tf_in]
        c = In["close"]; n = len(c)
        for i in range(MED_LEN + 5, n - 5):
            for sig, side in ((In["cu"][i], 1), (In["cd"][i], -1)):
                if not sig:
                    continue
                # режим старшего ТФ по ЗАКРЫТОМУ бару
                j = bisect.bisect_right(Rg["ct"], In["ct"][i]) - 1
                if j < 5 or np.isnan(Rg["above"][j]):
                    continue
                reg = 1 if Rg["above"][j] > 0.5 else -1
                if reg != side:
                    continue                   # торгуем только ПО режиму
                e = c[i]
                lim = min(i + TIMEOUT, n - 1)
                exits = {}
                # А: разворот в экстремальной зоне
                arr = In["xa_up"] if side == 1 else In["xa_dn"]
                w = np.where(arr[i + 1:lim + 1])[0]
                exits["A"] = i + 1 + int(w[0]) if len(w) else None
                # Б: любой кросс против
                arr2 = In["cd"] if side == 1 else In["cu"]
                w = np.where(arr2[i + 1:lim + 1])[0]
                exits["B"] = i + 1 + int(w[0]) if len(w) else None
                # В: возврат под/над медиану на ТФ режима
                jj = j
                vend = None
                while jj + 1 < len(Rg["above"]) and Rg["ct"][jj] <= In["ct"][lim]:
                    jj += 1
                    a = Rg["above"][jj]
                    if np.isnan(a):
                        continue
                    if (side == 1 and a < 0.5) or (side == -1 and a > 0.5):
                        k = bisect.bisect_left(In["ct"], Rg["ct"][jj])
                        if i < k <= lim:
                            vend = k
                        break
                exits["V"] = vend
                exits["G"] = lim
                rec = dict(sym=sym, reg=tf_reg, tin=tf_in, side=side,
                           half=int(i >= n // 2))
                for k_, jx in exits.items():
                    if jx is None or jx <= i or jx >= n:
                        rec[f"p{k_}"] = np.nan; rec[f"b{k_}"] = np.nan
                    else:
                        rec[f"p{k_}"] = (c[jx] - e) / e * 100 * side
                        rec[f"b{k_}"] = jx - i
                rows.append(rec)
    if fi % 6 == 0:
        print(f"  [{fi}/{len(files)}] сделок {len(rows):,}", flush=True)

R = pd.DataFrame(rows)
R.to_pickle(D + r"\wt_regime_mtf.pkl")
print(f"\nсделок: {len(R):,}\n")

NAMES = {"A": "разворот в зоне", "B": "кросс против", "V": "возврат за медиану",
         "G": "таймаут"}
print("=== ВАРИАНТЫ ВЫХОДА НА ОДНИХ И ТЕХ ЖЕ ВХОДАХ ===")
print(f"{'выход':>20} {'дошло':>8} {'баров':>7} {'ход':>9} {'мед':>9} {'нетто':>9} "
      f"{'WR':>6}")
for k_ in ["A", "B", "V", "G"]:
    g = R[R[f"p{k_}"].notna()]
    if len(g) < 200:
        continue
    v = g[f"p{k_}"]
    print(f"{NAMES[k_]:>20} {len(g)/len(R)*100:7.1f}% {g[f'b{k_}'].median():>7.0f} "
          f"{v.mean():+8.3f}% {v.median():+8.3f}% {v.mean()-COST:+8.3f}% "
          f"{(v > COST).mean()*100:5.1f}%")

print("\n=== MTF: режим → вход (лучший выход по каждой паре) ===")
print(f"{'режим':>7} {'вход':>6} {'стор':>6} {'n':>7} {'лучший выход':>18} "
      f"{'нетто':>9} {'мед':>9} {'IS':>9} {'OOS':>9} {'перенос':>8} {'монет+':>9}")
for tf_reg, tf_in in PAIRS:
    for side, sn in [(1, "long"), (-1, "short")]:
        g = R[(R.reg == tf_reg) & (R.tin == tf_in) & (R.side == side)]
        if len(g) < 200:
            continue
        best, bv = None, -9
        for k_ in ["A", "B", "V", "G"]:
            gg = g[g[f"p{k_}"].notna()]
            if len(gg) < 100:
                continue
            v = gg[f"p{k_}"].mean() - COST
            if v > bv:
                bv, best = v, k_
        if best is None:
            continue
        gg = g[g[f"p{best}"].notna()]
        v = gg[f"p{best}"] - COST
        i_, o_ = v[gg.half == 0], v[gg.half == 1]
        tag = "✓" if len(i_) > 40 and len(o_) > 40 and i_.mean() * o_.mean() > 0 \
            and i_.mean() > 0 else "✗"
        per = gg.assign(v=v).groupby("sym").v.mean()
        print(f"{tf_reg:>6}m {tf_in:>5}m {sn:>6} {len(gg):>7,} {NAMES[best]:>18} "
              f"{v.mean():+8.3f}% {v.median():+8.3f}% {i_.mean():+8.3f}% "
              f"{o_.mean():+8.3f}% {tag:>8} {int((per>0).sum())}/{len(per)}")
    print()

print("=== ЦЕНА ОЖИДАНИЯ ЭКСТРЕМУМА: долетевшие против недолетевших ===")
for tf_reg, tf_in in PAIRS:
    g = R[(R.reg == tf_reg) & (R.tin == tf_in)]
    if len(g) < 300:
        continue
    reach = g[g.pA.notna()]
    miss = g[g.pA.isna()]
    if len(reach) < 50 or len(miss) < 50:
        continue
    mb = miss[miss.pB.notna()].pB.mean() if miss.pB.notna().any() else np.nan
    print(f"  {tf_reg:>4}m→{tf_in:<4}m: долетели {len(reach)/len(g)*100:4.1f}% "
          f"(нетто {reach.pA.mean()-COST:+.3f}%) · не долетели "
          f"{len(miss)/len(g)*100:4.1f}% (по кроссу против {mb-COST:+.3f}%)")
