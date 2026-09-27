# -*- coding: utf-8 -*-
"""ПОЛНАЯ ЛЕСТНИЦА + ДИВЕРГЕНЦИЯ (R+) — метод Егора целиком (10.09.2026).

Егор: «у тебя есть все тф — почему используешь только малую часть? у нас гиперкуб
и фрактальности и вложенности и наследование» · «R+ это дивергенция отмечена».

Со скринов BCHUSDT.P: 1h кросс WT в зоне −60 → 15m пересечение нуля + метка R+
(дивергенция) → 3m вход, цена в зелёной зоне у PP. Три слоя, не два.

ЛЕСТНИЦА: 3m 5m 15m 30m 45m 1h 2h 4h (как на его панели TradingView).

Для каждого входа фиксируется СОСТОЯНИЕ ВСЕЙ ЛЕСТНИЦЫ (каузально, по времени
ЗАКРЫТИЯ бара каждого слоя — look-ahead вид 6):
    n_agree     сколько слоёв имеют wt1 по направлению входа (выше/ниже нуля)
    n_zone      сколько слоёв дали кросс в своей зоне OS/OB за последние 12 баров
    n_div       сколько слоёв несут свежую дивергенцию (≤10 баров слоя)
    div_T       есть ли дивергенция на самом ТФ входа  ← метка R+ со скрина
    n_above     сколько слоёв СТАРШЕ входа согласны (наследование вверх)

ВЫХОДЫ (оба варианта Егора):
    X1  touch: wt1 дошёл до противоположной зоны (|wt1| ≥ 60)
    X2  кросс против ВНЕ зон (|wt1| < 60) + перезаход при новом кроссе по направлению

🔴 Вход по OPEN следующего бара · косты 0.35% · контроль = полная база той же геометрии.
"""
import os, sys, glob, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_wt
from core.calculators.combinator_core import _wtx_divergences

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
LADDER = [3, 5, 15, 30, 45, 60, 120, 240]
ENTRIES = [5, 15]            # ТФ входа (3m даёт слишком много шума на костах — проверим 5/15)
OS_, OB_ = -60.0, 60.0
ZONE_MEM, DIV_MEM, TIMEOUT, COST = 12, 10, 300, 0.35
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))
print(f"монет {len(files)} · лестница {LADDER} · входы {ENTRIES}\n", flush=True)


def resample(d1, tf):
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


def layer(d, tf):
    w = calculate_wt(d.reset_index(drop=True))
    w1, w2 = w["wt1"].values, w["wt2"].values
    n = len(w1)
    cu = np.zeros(n, bool); cd = np.zeros(n, bool)
    cu[1:] = (w1[:-1] <= w2[:-1]) & (w1[1:] > w2[1:])
    cd[1:] = (w1[:-1] >= w2[:-1]) & (w1[1:] < w2[1:])
    bull, bear, bull_h, bear_h = _wtx_divergences(w1, d["low"].values,
                                                  d["high"].values)
    def recent(a, k):
        return pd.Series(a).rolling(k, min_periods=1).max().to_numpy() > 0
    return dict(
        w1=w1, cu=cu, cd=cd,
        up_zero=np.concatenate(([False], (w1[:-1] <= 0) & (w1[1:] > 0))),
        dn_zero=np.concatenate(([False], (w1[:-1] >= 0) & (w1[1:] < 0))),
        above=w1 > 0,
        zone_up=recent(cu & (w1 < OS_), ZONE_MEM),     # кросс в OS был недавно
        zone_dn=recent(cd & (w1 > OB_), ZONE_MEM),
        div_up=recent(bull | bull_h, DIV_MEM),
        div_dn=recent(bear | bear_h, DIV_MEM),
        touch_up=w1 >= OB_, touch_dn=w1 <= OS_,
        x_out_up=cd & (np.abs(w1) < OB_),              # кросс вниз ВНЕ зон
        x_out_dn=cu & (np.abs(w1) < OB_),
        close_t=(d.index + pd.Timedelta(minutes=tf)).values,
        cl=d["close"].values, op=d["open"].values, ts=d.index)


rows, base = [], []
for fi, f in enumerate(files, 1):
    sym = os.path.basename(f)[:-8]
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    L = {}
    for tf in LADDER:
        dd = resample(d1, tf)
        if len(dd) >= 500:
            L[tf] = layer(dd, tf)
    for T in ENTRIES:
        if T not in L:
            continue
        I_ = L[T]
        n = len(I_["cl"])
        # индексы каждого слоя, каузально сопоставленные барам ТФ входа
        idx = {}
        for tf in LADDER:
            if tf not in L:
                continue
            idx[tf] = np.searchsorted(L[tf]["close_t"], I_["close_t"], "right") - 1
        older = [tf for tf in LADDER if tf > T]

        def state(i, side):
            ag = zo = dv = ab = 0
            for tf in LADDER:
                if tf not in L:
                    continue
                j = idx[tf][i]
                if j < 5:
                    continue
                l = L[tf]
                on = (l["above"][j] if side == 1 else not l["above"][j])
                ag += int(on)
                zo += int((l["zone_up"] if side == 1 else l["zone_dn"])[j])
                dv += int((l["div_up"] if side == 1 else l["div_dn"])[j])
                if tf in older and on:
                    ab += 1
            j = idx[T][i]
            dT = int((L[T]["div_up"] if side == 1 else L[T]["div_dn"])[j])
            zT = int((L[T]["zone_up"] if side == 1 else L[T]["zone_dn"])[j])
            return ag, zo, dv, ab, dT, zT

        def close_x1(ii, side):
            arr = I_["touch_up"] if side == 1 else I_["touch_dn"]
            lim = min(ii + TIMEOUT, n - 1)
            j = np.where(arr[ii + 1:lim + 1])[0]
            return (ii + 1 + int(j[0])) if len(j) else lim

        def close_x2(ii, side):
            arr = I_["x_out_up"] if side == 1 else I_["x_out_dn"]
            tch = I_["touch_up"] if side == 1 else I_["touch_dn"]
            lim = min(ii + TIMEOUT, n - 1)
            j = np.where(arr[ii + 1:lim + 1] | tch[ii + 1:lim + 1])[0]
            return (ii + 1 + int(j[0])) if len(j) else lim

        busy = {(1, 1): -1, (1, -1): -1, (2, 1): -1, (2, -1): -1}
        for i in range(60, n - 5):
            for sig, side in ((I_["up_zero"][i], 1), (I_["dn_zero"][i], -1)):
                if not sig:
                    continue
                ii = i + 1
                if ii >= n - 3:
                    continue
                ag, zo, dv, ab, dT, zT = state(i, side)
                e = I_["op"][ii]
                for xv, fn in ((1, close_x1), (2, close_x2)):
                    if ii <= busy[(xv, side)]:
                        continue
                    jx = fn(ii, side)
                    busy[(xv, side)] = jx
                    rows.append((sym, T, side, xv, ag, zo, dv, ab, dT, zT,
                                 (I_["cl"][jx] - e) / e * 100 * side - COST,
                                 jx - ii, int(I_["ts"][i].year)))
        # контроль: полная база той же геометрии
        for side in (1, -1):
            for xv, fn in ((1, close_x1), (2, close_x2)):
                for ii in range(60, n - 4, 40):
                    jx = fn(ii, side)
                    e = I_["op"][ii]
                    base.append((sym, T, side, xv,
                                 (I_["cl"][jx] - e) / e * 100 * side - COST, jx - ii))
    if fi % 10 == 0:
        print(f"  [{fi}/{len(files)}] сигналов {len(rows):,}", flush=True)

R = pd.DataFrame(rows, columns=["sym", "T", "side", "xv", "n_agree", "n_zone",
                                "n_div", "n_above", "div_T", "zone_T", "pnl",
                                "bars", "year"])
B = pd.DataFrame(base, columns=["sym", "T", "side", "xv", "pnl", "bars"])
R.to_pickle(D + r"\egor_ladder.pkl"); B.to_pickle(D + r"\egor_ladder_base.pkl")
print(f"\nсигналов {len(R):,} · база {len(B):,} · монет {R.sym.nunique()}\n")
bm = B.groupby(["T", "side", "xv"]).pnl.mean()
XN = {1: "X1 до зоны", 2: "X2 кросс вне зон"}


def blk(g):
    v = np.sort(g.pnl.values)[::-1]
    per = g.groupby("sym").pnl.mean()
    return (v[int(len(v)*.1):].mean(), int((per > 0).sum()), len(per))


print("=== БАЗОВЫЙ УРОВЕНЬ (все пересечения нуля, без фильтров) ===")
print(f"{'T':>5} {'выход':>18} {'стор':>6} {'n':>8} {'нетто':>9} {'база':>9} "
      f"{'над':>9} {'мед':>9} {'баров':>7} {'безтоп10':>9} {'монет+':>8}")
for T in ENTRIES:
    for xv in (1, 2):
        for side, sn in [(1, "long"), (-1, "short")]:
            g = R[(R.T == T) & (R.xv == xv) & (R.side == side)]
            if len(g) < 200:
                continue
            t10, sp, sn_ = blk(g)
            b = float(bm.get((T, side, xv), np.nan))
            print(f"{T:>5} {XN[xv]:>18} {sn:>6} {len(g):>8,} {g.pnl.mean():+8.3f}% "
                  f"{b:+8.3f}% {g.pnl.mean()-b:+8.3f}% {g.pnl.median():+8.3f}% "
                  f"{g.bars.median():>7.0f} {t10:+8.3f}% {sp}/{sn_}")

print("\n=== 🔴 ГЛАВНОЕ: ДИВЕРГЕНЦИЯ НА ТФ ВХОДА (метка R+) ===")
print(f"{'T':>5} {'выход':>18} {'стор':>6} {'R+':>4} {'n':>8} {'доля':>7} "
      f"{'нетто':>9} {'над базой':>10} {'мед':>9} {'безтоп10':>9} {'монет+':>8}")
for T in ENTRIES:
    for xv in (1, 2):
        for side, sn in [(1, "long"), (-1, "short")]:
            tot = len(R[(R.T == T) & (R.xv == xv) & (R.side == side)])
            for dT in (0, 1):
                g = R[(R.T == T) & (R.xv == xv) & (R.side == side) & (R.div_T == dT)]
                if len(g) < 150:
                    continue
                t10, sp, sn_ = blk(g)
                b = float(bm.get((T, side, xv), np.nan))
                print(f"{T:>5} {XN[xv]:>18} {sn:>6} {'да' if dT else 'нет':>4} "
                      f"{len(g):>8,} {len(g)/tot*100:6.1f}% {g.pnl.mean():+8.3f}% "
                      f"{g.pnl.mean()-b:+9.3f}% {g.pnl.median():+8.3f}% {t10:+8.3f}% "
                      f"{sp}/{sn_}")
            print()

print("=== ЛЕСТНИЦА: СКОЛЬКО СЛОЁВ СОГЛАСНЫ (гиперкуб) ===")
for T in ENTRIES:
    for side, sn in [(1, "long"), (-1, "short")]:
        g0 = R[(R.T == T) & (R.xv == 1) & (R.side == side)]
        if len(g0) < 500:
            continue
        print(f"\n  T={T}m {sn} (выход X1, база {float(bm.get((T,side,1),np.nan)):+.3f}%)")
        print(f"{'слоёв':>7} {'n':>8} {'доля':>7} {'нетто':>9} {'мед':>9} {'WR':>6} "
              f"{'безтоп10':>9} {'монет+':>8}")
        for a in range(0, len(LADDER) + 1):
            g = g0[g0.n_agree == a]
            if len(g) < 150:
                continue
            t10, sp, sn_ = blk(g)
            print(f"{a:>7} {len(g):>8,} {len(g)/len(g0)*100:6.1f}% {g.pnl.mean():+8.3f}% "
                  f"{g.pnl.median():+8.3f}% {(g.pnl>0).mean()*100:5.1f}% {t10:+8.3f}% "
                  f"{sp}/{sn_}")

print("\n=== СЛОЁВ С ДИВЕРГЕНЦИЕЙ ПО ВСЕЙ ЛЕСТНИЦЕ ===")
for T in ENTRIES:
    for side, sn in [(1, "long"), (-1, "short")]:
        g0 = R[(R.T == T) & (R.xv == 1) & (R.side == side)]
        if len(g0) < 500:
            continue
        print(f"\n  T={T}m {sn}")
        print(f"{'слоёв':>7} {'n':>8} {'доля':>7} {'нетто':>9} {'мед':>9} "
              f"{'безтоп10':>9} {'монет+':>8}")
        for a in sorted(g0.n_div.unique()):
            g = g0[g0.n_div == a]
            if len(g) < 150:
                continue
            t10, sp, sn_ = blk(g)
            print(f"{int(a):>7} {len(g):>8,} {len(g)/len(g0)*100:6.1f}% "
                  f"{g.pnl.mean():+8.3f}% {g.pnl.median():+8.3f}% {t10:+8.3f}% {sp}/{sn_}")

print("\n=== КОМБИНАЦИЯ: R+ на входе × согласие лестницы ===")
print(f"{'T':>5} {'стор':>6} {'условие':>34} {'n':>7} {'нетто':>9} {'над базой':>10} "
      f"{'мед':>9} {'безтоп10':>9} {'монет+':>8}")
for T in ENTRIES:
    for side, sn in [(1, "long"), (-1, "short")]:
        g0 = R[(R.T == T) & (R.xv == 1) & (R.side == side)]
        if len(g0) < 500:
            continue
        b = float(bm.get((T, side, 1), np.nan))
        hi = g0.n_agree >= 6
        for lbl, cond in [("все входы", g0.n_agree >= 0),
                          ("R+ на входе", g0.div_T == 1),
                          ("лестница ≥6 слоёв", hi),
                          ("R+ и лестница ≥6", (g0.div_T == 1) & hi),
                          ("R+ и лестница ≥6 и зона старших", (g0.div_T == 1) & hi &
                           (g0.n_zone >= 2))]:
            g = g0[cond]
            if len(g) < 100:
                continue
            t10, sp, sn_ = blk(g)
            print(f"{T:>5} {sn:>6} {lbl:>34} {len(g):>7,} {g.pnl.mean():+8.3f}% "
                  f"{g.pnl.mean()-b:+9.3f}% {g.pnl.median():+8.3f}% {t10:+8.3f}% "
                  f"{sp}/{sn_}")
        print()
