# -*- coding: utf-8 -*-
"""🎯 ГДЕ ТЕРЯЕТСЯ: ДРОБЛЕНИЕ НА КРОССЫ (11.09.2026).

Замер схемы Егора дословно дал −0.34% при костах 0.35% (грязными ≈ 0), плюсы не работают.
Но разрез по ЖИЗНИ сделки монотонен на всех ТФ:
    1-2 бара −0.694% · 3-5 −0.562% · 6-11 −0.211% · 12-29 +0.225% (грязн +0.575%)
⇒ вход не виноват, выход по ВСТРЕЧНОМУ КРОССУ режет половину сделок за 1-5 баров.

Егор берёт ВСЕ кроссы вверх И закрывает по встречному ⇒ он ПЕРЕОТКРЫВАЕТСЯ, то есть
держит направление почти всё разрешение, но платит косты на каждом дроблении.
Проверяем, сколько стоит дробление и что даёт удержание без него.

ПЯТЬ ПОЛИТИК на ОДНОМ И ТОМ ЖЕ входе (первый кросс вверх внутри разрешения):
  A  до встречного кросса на МЛАДШЕМ            (как есть сейчас, базовая)
  B  серия: вход по каждому кроссу, выход по встречному — косты за каждое дробление
  C  ОДИН вход, держать до конца разрешения (LIFE баров часовика) — косты один раз
  D  до встречного кросса на СТАРШЕМ (1h), а не на младшем
  E  до встречного кросса на младшем, НО игнорировать его пока wt1 ниже нуля
     (не выходить, пока осциллятор не поднялся)

🔴 Все политики на одних входах, косты 0.35% за каждое открытие, вход по OPEN следующего.
🔴 Контроль: те же политики от случайного бара той же монеты.
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
TF_CTX, ENTRIES = 60, [3, 15]
OS_, OB_, LIFE, COST, NSYM = -60.0, 60.0, 12, 0.35, 25
RNG = np.random.default_rng(11)
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))[:NSYM]
POL = {"A": "A встречный кросс", "B": "B серия дроблений", "C": "C до конца разрешения",
       "D": "D встречный на 1h", "E": "E кросс выше нуля"}
print(f"монет {len(files)} · входы {ENTRIES} · политики {list(POL.values())}\n", flush=True)


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
    dc = resample(d1, TF_CTX)
    if len(dc) < 500:
        continue
    wc = calculate_wt(dc.reset_index(drop=True))
    c1, c2 = wc["wt1"].values, wc["wt2"].values
    nc = len(c1)
    ccu = np.zeros(nc, bool); ccd = np.zeros(nc, bool)
    ccu[1:] = (c1[:-1] <= c2[:-1]) & (c1[1:] > c2[1:])
    ccd[1:] = (c1[:-1] >= c2[:-1]) & (c1[1:] < c2[1:])
    ct_c = (dc.index + pd.Timedelta(minutes=TF_CTX)).values
    ctx = []
    for arr, sd in ((ccu & (c1 < OS_), 1), (ccd & (c1 > OB_), -1)):
        for k in np.where(arr)[0]:
            if k + LIFE < nc:
                ctx.append((ct_c[k], ct_c[k + LIFE], sd, k))
    if not ctx:
        continue
    ctx.sort(key=lambda x: x[0])
    for T in ENTRIES:
        di = resample(d1, T)
        if len(di) < 2000:
            continue
        wi = calculate_wt(di.reset_index(drop=True))
        w1, w2 = wi["wt1"].values, wi["wt2"].values
        n = len(w1)
        cu = np.zeros(n, bool); cd = np.zeros(n, bool)
        cu[1:] = (w1[:-1] <= w2[:-1]) & (w1[1:] > w2[1:])
        cd[1:] = (w1[:-1] >= w2[:-1]) & (w1[1:] < w2[1:])
        cl, op = di.close.values, di.open.values
        ct_i = (di.index + pd.Timedelta(minutes=T)).values
        # встречный кросс СТАРШЕГО, спроецированный на бары младшего
        opp_htf = np.zeros(n, bool)
        for k in np.where(ccd if True else ccu)[0]:
            pass
        idx_c = np.clip(np.searchsorted(ct_c, ct_i, "right") - 1, 0, nc - 1)

        def first_after(arr, ii, lim):
            j = np.where(arr[ii + 1:lim + 1])[0]
            return (ii + 1 + int(j[0])) if len(j) else None

        for (t0, t1, side, kc) in ctx:
            i0 = int(np.searchsorted(ct_i, t0, "left"))
            i1 = int(np.searchsorted(ct_i, t1, "right")) - 1
            if i0 < 60 or i1 >= n - 3 or i1 <= i0 + 2:
                continue
            up = cu if side == 1 else cd
            dn = cd if side == 1 else cu
            ins = [k for k in range(i0, i1) if up[k]]
            if not ins:
                continue
            first = ins[0] + 1
            if first >= n - 3:
                continue
            e0 = op[first]
            year = int(di.index[first].year)

            def rec(pol, pnl, bars, ntr):
                rows.append((sym, T, side, pol, pnl, bars, ntr, year))

            # A: один вход, выход по первому встречному на младшем
            jx = first_after(dn, first, min(i1 + 200, n - 1)) or min(i1, n - 2)
            rec("A", (cl[jx] - e0) / e0 * 100 * side - COST, jx - first, 1)
            # B: серия — каждый кросс вверх внутри разрешения
            tot, ntr, busy, bsum = 0.0, 0, -1, 0
            for k in ins:
                ii = k + 1
                if ii >= n - 3 or ii <= busy:
                    continue
                jj = first_after(dn, ii, min(i1 + 200, n - 1)) or min(i1, n - 2)
                tot += (cl[jj] - op[ii]) / op[ii] * 100 * side - COST
                bsum += jj - ii; ntr += 1; busy = jj
            if ntr:
                rec("B", tot, bsum, ntr)
            # C: один вход, держать до конца разрешения
            rec("C", (cl[i1] - e0) / e0 * 100 * side - COST, i1 - first, 1)
            # D: выход по встречному кроссу СТАРШЕГО
            opp_c = ccd if side == 1 else ccu
            kk = np.where(opp_c[kc + 1:])[0]
            if len(kk):
                t_end = ct_c[kc + 1 + int(kk[0])]
                jd = int(np.searchsorted(ct_i, t_end, "left"))
                jd = min(max(jd, first + 1), n - 2)
            else:
                jd = min(i1, n - 2)
            rec("D", (cl[jd] - e0) / e0 * 100 * side - COST, jd - first, 1)
            # E: выход по встречному кроссу, но только когда wt1 по нужную сторону нуля
            lim = min(i1 + 200, n - 1)
            je = None
            for k in range(first + 1, lim + 1):
                if dn[k] and ((w1[k] > 0) if side == 1 else (w1[k] < 0)):
                    je = k; break
            je = je or min(i1, n - 2)
            rec("E", (cl[je] - e0) / e0 * 100 * side - COST, je - first, 1)
            # контроль: те же политики от случайного бара
            rs = int(RNG.integers(60, n - 300))
            jr = first_after(dn, rs, min(rs + 200, n - 1)) or min(rs + 100, n - 2)
            rows.append((sym, T, side, "ctlA",
                         (cl[jr] - op[rs]) / op[rs] * 100 * side - COST, jr - rs, 1, year))
            jc = min(rs + (i1 - first), n - 2)
            rows.append((sym, T, side, "ctlC",
                         (cl[jc] - op[rs]) / op[rs] * 100 * side - COST, jc - rs, 1, year))
    if fi % 5 == 0:
        print(f"  [{fi}/{len(files)}] {len(rows):,}", flush=True)

R = pd.DataFrame(rows, columns=["sym", "tf", "side", "pol", "pnl", "bars", "ntr", "year"])
R.to_pickle(D + r"\egor_hold3.pkl")
print(f"\nзаписей {len(R):,} · монет {R.sym.nunique()}\n")


def blk(g):
    v = np.sort(g.pnl.values)[::-1]
    per = g.groupby("sym").pnl.mean()
    return v[int(len(v)*.1):].mean(), int((per > 0).sum()), len(per)


print("=== ПОЛИТИКИ УДЕРЖАНИЯ НА ОДНИХ ВХОДАХ ===")
print(f"{'T':>4} {'стор':>6} {'политика':>24} {'n':>7} {'нетто':>9} {'грязн':>8} "
      f"{'мед':>9} {'WR':>6} {'баров':>7} {'сделок':>7} {'безтоп10':>9} {'монет+':>7}")
for T in ENTRIES:
    for side, sn in [(1, "long"), (-1, "short")]:
        for pol in ["A", "B", "C", "D", "E", "ctlA", "ctlC"]:
            g = R[(R["tf"] == T) & (R["side"] == side) & (R["pol"] == pol)]
            if len(g) < 100:
                continue
            t10, sp, sn_ = blk(g)
            nm = POL.get(pol, "контроль " + pol[-1])
            ntr = g.ntr.mean()
            print(f"{T:>4} {sn:>6} {nm:>24} {len(g):>7,} {g.pnl.mean():+8.3f}% "
                  f"{g.pnl.mean()+COST*ntr:+7.3f}% {g.pnl.median():+8.3f}% "
                  f"{(g.pnl>0).mean()*100:5.1f}% {g.bars.median():>7.0f} {ntr:>7.1f} "
                  f"{t10:+8.3f}% {sp}/{sn_}")
        print()

print("=== ЦЕНА ДРОБЛЕНИЯ: B против C на одних разрешениях ===")
for T in ENTRIES:
    for side, sn in [(1, "long"), (-1, "short")]:
        b = R[(R["tf"] == T) & (R["side"] == side) & (R["pol"] == "B")]
        c = R[(R["tf"] == T) & (R["side"] == side) & (R["pol"] == "C")]
        if len(b) < 100 or len(c) < 100:
            continue
        print(f"  T={T}m {sn:>5}: серия {b.pnl.mean():+.3f}% ({b.ntr.mean():.1f} сделок, "
              f"косты {COST*b.ntr.mean():.2f}%) · один вход {c.pnl.mean():+.3f}% "
              f"(косты {COST:.2f}%) · разница {c.pnl.mean()-b.pnl.mean():+.3f} п.п.")

print("\n=== ПО ГОДАМ (лучшая политика) ===")
best = R[~R["pol"].str.startswith("ctl")].groupby("pol").pnl.mean().idxmax()
print(f"  лучшая политика: {POL.get(best, best)}")
for T in ENTRIES:
    for side, sn in [(1, "long"), (-1, "short")]:
        g0 = R[(R["tf"] == T) & (R["side"] == side) & (R["pol"] == best)]
        if len(g0) < 200:
            continue
        parts = []
        for y in sorted(g0.year.unique()):
            g = g0[g0.year == y]
            if len(g) < 50:
                continue
            parts.append(f"{y}: {g.pnl.mean():+.3f}%")
        print(f"  T={T}m {sn:>5}: " + " · ".join(parts))
