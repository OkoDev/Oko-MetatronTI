# -*- coding: utf-8 -*-
"""УДЕРЖАНИЕ ПО ПАДЕНИЮ СОГЛАСИЯ ОТ МАКСИМУМА + R+ В ОКНЕ (11.09.2026).

Прошлый замер провалил буквальную реализацию: «держать пока согласных ≥4» выбрасывает
за 1 бар, потому что на входе согласия ещё НЕТ — оно набирается позже. Мысль Егора
(«согласие нужно для удержания») требует другой формы:

  ДЕРЖАТЬ, ПОКА СОГЛАСИЕ НЕ РАССЫПАЛОСЬ ПОСЛЕ ТОГО, КАК СОБРАЛОСЬ.
  → следим за максимумом согласия ВНУТРИ сделки, выходим при падении от него на K слоёв.

И R+ теперь ищется В ОКНЕ до входа (эталонный детектор даёт 0.74% баров — на самом
баре входа почти не совпадает).

Оси:
  удержание:  H0 до зоны · D1/D2/D3 падение от максимума на 1/2/3 слоя ·
              M1 падение от максимума на 2 + выход по зоне (что раньше)
  вход:       R+ в окне {0 (нет фильтра), 5, 10, 20} баров 15m
"""
import os, sys, glob, bisect, warnings
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
TF_CTX, TF_IN, MA_LEN = 60, 15, 43
OS_, OB_, LIFE, TIMEOUT, COST = -60.0, 60.0, 12, 300, 0.35
HOLDS = {0: "H0 до зоны", 1: "D1 падение −1", 2: "D2 падение −2",
         3: "D3 падение −3", 4: "M1 зона или −2"}
WINS = [0, 5, 10, 20]
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))
print(f"монет {len(files)} · удержания {list(HOLDS.values())} · окна R+ {WINS}\n",
      flush=True)


def resample(d1, tf):
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


rows, base = [], []
for fi, f in enumerate(files, 1):
    sym = os.path.basename(f)[:-8]
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    L = {}
    for tf in LADDER:
        dd = resample(d1, tf)
        if len(dd) < 600:
            continue
        w = calculate_wt(dd.reset_index(drop=True))
        w1, w2 = w["wt1"].values, w["wt2"].values
        n_ = len(w1)
        cu = np.zeros(n_, bool); cd = np.zeros(n_, bool)
        cu[1:] = (w1[:-1] <= w2[:-1]) & (w1[1:] > w2[1:])
        cd[1:] = (w1[:-1] >= w2[:-1]) & (w1[1:] < w2[1:])
        ma = pd.Series(w1).ewm(span=MA_LEN, adjust=False).mean().to_numpy()
        bull, bear, _, _ = _wtx_divergences(w1, dd["low"].values, dd["high"].values)
        L[tf] = dict(w1=w1, above=w1 > ma,
                     arrow_up=cu & (w1 < OS_), arrow_dn=cd & (w1 > OB_),
                     up=np.concatenate(([False], (w1[:-1] <= ma[:-1]) & (w1[1:] > ma[1:]))),
                     dn=np.concatenate(([False], (w1[:-1] >= ma[:-1]) & (w1[1:] < ma[1:]))),
                     touch_up=w1 >= OB_, touch_dn=w1 <= OS_,
                     div_up=bull, div_dn=bear,
                     ct=(dd.index + pd.Timedelta(minutes=tf)).values,
                     cl=dd.close.values, op=dd.open.values, ts=dd.index)
    if TF_IN not in L or TF_CTX not in L:
        continue
    I_, C_ = L[TF_IN], L[TF_CTX]
    n = len(I_["cl"])
    idx = {tf: np.searchsorted(L[tf]["ct"], I_["ct"], "right") - 1
           for tf in LADDER if tf in L}
    agree_up = np.zeros(n, np.int16)
    for tf in LADDER:
        if tf not in L:
            continue
        j = np.clip(idx[tf], 0, len(L[tf]["above"]) - 1)
        agree_up += L[tf]["above"][j].astype(np.int16)
    nlad = sum(1 for tf in LADDER if tf in L)
    # R+ в окне: максимум флага за последние W баров ТФ входа
    divw = {}
    for W in WINS:
        if W == 0:
            continue
        divw[(W, 1)] = pd.Series(I_["div_up"]).rolling(W, min_periods=1).max().to_numpy() > 0
        divw[(W, -1)] = pd.Series(I_["div_dn"]).rolling(W, min_periods=1).max().to_numpy() > 0

    def exit_at(ii, side, mode):
        lim = min(ii + TIMEOUT, n - 1)
        zone = I_["touch_up"] if side == 1 else I_["touch_dn"]
        ag = agree_up if side == 1 else (nlad - agree_up)
        peak = int(ag[ii])
        for k in range(ii + 1, lim + 1):
            a = int(ag[k])
            if a > peak:
                peak = a
            if mode == 0 and zone[k]:
                return k
            if mode in (1, 2, 3) and peak - a >= mode:
                return k
            if mode == 4 and (zone[k] or peak - a >= 2):
                return k
        return lim

    ctx = []
    for arr, sd in ((C_["arrow_up"], 1), (C_["arrow_dn"], -1)):
        for k in np.where(arr)[0]:
            if k + LIFE < len(C_["ct"]):
                ctx.append((C_["ct"][k], C_["ct"][k + LIFE], sd))
    if not ctx:
        continue
    ctx.sort(); st = [x[0] for x in ctx]
    busy = {(m, s): -1 for m in HOLDS for s in (1, -1)}
    for i in range(max(120, MA_LEN + 5), n - 5):
        for sig, side in ((I_["up"][i], 1), (I_["dn"][i], -1)):
            if not sig:
                continue
            t_now = I_["ct"][i]
            q = bisect.bisect_right(st, t_now) - 1
            if not any(ctx[z][2] == side and ctx[z][0] <= t_now <= ctx[z][1]
                       for z in range(max(0, q - 4), q + 1) if 0 <= z < len(ctx)):
                continue
            ii = i + 1
            if ii >= n - 3:
                continue
            dw = tuple(int(divw[(W, side)][i]) for W in WINS if W)
            ag0 = int(agree_up[i] if side == 1 else nlad - agree_up[i])
            e = I_["op"][ii]
            for m in HOLDS:
                if ii <= busy[(m, side)]:
                    continue
                jx = exit_at(ii, side, m)
                busy[(m, side)] = jx
                rows.append((sym, side, m, ag0, *dw,
                             (I_["cl"][jx] - e) / e * 100 * side - COST, jx - ii,
                             int(I_["ts"][i].year)))
    for side in (1, -1):
        for m in HOLDS:
            for ii in range(120, n - 4, 60):
                jx = exit_at(ii, side, m)
                e = I_["op"][ii]
                base.append((sym, side, m,
                             (I_["cl"][jx] - e) / e * 100 * side - COST, jx - ii))
    if fi % 10 == 0:
        print(f"  [{fi}/{len(files)}] {len(rows):,}", flush=True)

cols = ["sym", "side", "hold", "agree"] + [f"d{W}" for W in WINS if W] + \
       ["pnl", "bars", "year"]
R = pd.DataFrame(rows, columns=cols)
B = pd.DataFrame(base, columns=["sym", "side", "hold", "pnl", "bars"])
R.to_pickle(D + r"\egor_hold2.pkl"); B.to_pickle(D + r"\egor_hold2_base.pkl")
bm = B.groupby(["side", "hold"]).pnl.mean()
print(f"\nсигналов {len(R):,} · монет {R.sym.nunique()}\n")


def blk(g):
    v = np.sort(g.pnl.values)[::-1]
    per = g.groupby("sym").pnl.mean()
    return v[int(len(v)*.1):].mean(), int((per > 0).sum()), len(per)


print("=== УДЕРЖАНИЕ ПО ПАДЕНИЮ СОГЛАСИЯ ОТ МАКСИМУМА ===")
print(f"{'удержание':>16} {'стор':>6} {'n':>7} {'нетто':>9} {'база':>9} {'над':>9} "
      f"{'мед':>9} {'WR':>6} {'баров':>6} {'безтоп10':>9} {'монет+':>7}")
for m in HOLDS:
    for side, sn in [(1, "long"), (-1, "short")]:
        g = R[(R.hold == m) & (R.side == side)]
        if len(g) < 150:
            continue
        t10, sp, sn_ = blk(g)
        b = float(bm.get((side, m), np.nan))
        print(f"{HOLDS[m]:>16} {sn:>6} {len(g):>7,} {g.pnl.mean():+8.3f}% {b:+8.3f}% "
              f"{g.pnl.mean()-b:+8.3f}% {g.pnl.median():+8.3f}% "
              f"{(g.pnl>0).mean()*100:5.1f}% {g.bars.median():>6.0f} {t10:+8.3f}% "
              f"{sp}/{sn_}")
    print()

print("=== R+ В ОКНЕ ПЕРЕД ВХОДОМ (эталонный детектор) ===")
print(f"{'удержание':>16} {'стор':>6} {'окно':>6} {'n':>7} {'доля':>7} {'нетто':>9} "
      f"{'над базой':>10} {'мед':>9} {'безтоп10':>9} {'монет+':>7}")
for m in (0, 4):
    for side, sn in [(1, "long"), (-1, "short")]:
        g0 = R[(R.hold == m) & (R.side == side)]
        if len(g0) < 300:
            continue
        b = float(bm.get((side, m), np.nan))
        for W in WINS:
            g = g0 if W == 0 else g0[g0[f"d{W}"] == 1]
            if len(g) < 80:
                continue
            t10, sp, sn_ = blk(g)
            lbl = "все" if W == 0 else f"R+ ≤{W}"
            print(f"{HOLDS[m]:>16} {sn:>6} {lbl:>6} {len(g):>7,} "
                  f"{len(g)/len(g0)*100:6.1f}% {g.pnl.mean():+8.3f}% "
                  f"{g.pnl.mean()-b:+9.3f}% {g.pnl.median():+8.3f}% {t10:+8.3f}% "
                  f"{sp}/{sn_}")
        print()

print("=== СОГЛАСИЕ НА ВХОДЕ (проверка прошлой находки на большем n) ===")
print(f"{'удержание':>16} {'стор':>6} {'согласных':>12} {'n':>7} {'нетто':>9} "
      f"{'над базой':>10} {'мед':>9} {'безтоп10':>9} {'монет+':>7}")
for m in (0, 4):
    for side, sn in [(1, "long"), (-1, "short")]:
        g0 = R[(R.hold == m) & (R.side == side)]
        if len(g0) < 300:
            continue
        b = float(bm.get((side, m), np.nan))
        for lo, hi, lbl in [(0, 3, "мало ≤3"), (4, 5, "средне 4-5"), (6, 8, "много ≥6")]:
            g = g0[g0.agree.between(lo, hi)]
            if len(g) < 80:
                continue
            t10, sp, sn_ = blk(g)
            print(f"{HOLDS[m]:>16} {sn:>6} {lbl:>12} {len(g):>7,} {g.pnl.mean():+8.3f}% "
                  f"{g.pnl.mean()-b:+9.3f}% {g.pnl.median():+8.3f}% {t10:+8.3f}% "
                  f"{sp}/{sn_}")
        print()
