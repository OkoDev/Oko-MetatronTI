# -*- coding: utf-8 -*-
"""🎯 СХЕМА ЕГОРА ДОСЛОВНО (11.09.2026, третья формулировка — теперь однозначная).

«часовик дал кросс в OS — на трёх минутках беру ВСЕ кроссы вверх и работаю от лонга.
 закрываю при ВСТРЕЧНОМ КРОССЕ. не жду прямо сейчас перехода от OS в OB за один проход.
 если на часовике дивер появляется — усиливает гипотезу, продолжаю работать.
 если пивот рядом — это +. если медиану пересекли вверх — это тоже +»

Чем это отличается от всего, что я мерил сегодня:
  · ВХОД  — кросс wt1×wt2 на МЛАДШЕМ (я делал вход по пересечению медианы);
  · ВЫХОД — ВСТРЕЧНЫЙ КРОСС на том же младшем (я держал до противоположной ЗОНЫ,
            таймаут 200-400 баров ⇒ сделки на дни вместо минут);
  · МЕДИАНА — «плюс», а не триггер (я сделал её основным входом);
  · серия коротких сделок внутри одного разрешения старшего.

Оси «плюсов» Егора, каждая мерится отдельно и в комбинации:
  P1 дивергенция (regular bull/bear) на ЧАСОВИКЕ, свежая
  P2 пивот рядом — цена входа близко к последнему ПОДТВЕРЖДЁННОМУ swing (OKO-SM)
  P3 медиана на младшем пересечена в сторону входа недавно

Контроли (оба обязательны):
  C1 те же кроссы младшего БЕЗ разрешения старшего  → что добавляет разрешение
  C2 полная база: вход каждые N баров, выход тем же встречным кроссом
"""
import os, sys, glob, bisect, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_wt
from core.calculators.combinator_core import _wtx_divergences
from core.smc.oko_sm_engine import _swings

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
TF_CTX = 60
ENTRIES = [3, 5, 15]
MA_LEN, SW_LEN = 43, 5
OS_, OB_ = -60.0, 60.0
LIFE = 12          # жизнь разрешения, баров ЧАСОВИКА
DIV_MEM, MED_MEM = 10, 5
PIVOT_ATR = 0.5    # «пивот рядом» = ближе 0.5·ATR
TIMEOUT = 400
COST = 0.35
NSYM = 25
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))[:NSYM]
print(f"монет {len(files)} · разрешение {TF_CTX}m · входы {ENTRIES} · "
      f"выход = встречный кросс\n", flush=True)


def resample(d1, tf):
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


def atr_pct(h, l, c, period=14):
    prev = np.concatenate(([c[0]], c[:-1]))
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev), np.abs(l - prev)))
    return pd.Series(np.where(c > 0, tr / c * 100, np.nan)).rolling(
        period, min_periods=5).mean().to_numpy(float)


def recent(a, k):
    return pd.Series(a).rolling(k, min_periods=1).max().to_numpy() > 0


rows, base = [], []
for fi, f in enumerate(files, 1):
    sym = os.path.basename(f)[:-8]
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    # ── ЧАСОВИК: разрешение + дивергенция
    dc = resample(d1, TF_CTX)
    if len(dc) < 500:
        continue
    wc = calculate_wt(dc.reset_index(drop=True))
    c1, c2 = wc["wt1"].values, wc["wt2"].values
    nc = len(c1)
    ccu = np.zeros(nc, bool); ccd = np.zeros(nc, bool)
    ccu[1:] = (c1[:-1] <= c2[:-1]) & (c1[1:] > c2[1:])
    ccd[1:] = (c1[:-1] >= c2[:-1]) & (c1[1:] < c2[1:])
    cbull, cbear, _, _ = _wtx_divergences(c1, dc.low.values, dc.high.values)
    cdiv_up = recent(cbull, DIV_MEM); cdiv_dn = recent(cbear, DIV_MEM)
    ct_c = (dc.index + pd.Timedelta(minutes=TF_CTX)).values
    ctx = []
    for arr, sd in ((ccu & (c1 < OS_), 1), (ccd & (c1 > OB_), -1)):
        for k in np.where(arr)[0]:
            if k + LIFE < nc:
                ctx.append((ct_c[k], ct_c[k + LIFE], sd, k))
    if not ctx:
        continue
    ctx.sort(key=lambda x: x[0]); st = [x[0] for x in ctx]

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
        ma = pd.Series(w1).ewm(span=MA_LEN, adjust=False).mean().to_numpy()
        med_up = recent(np.concatenate(([False], (w1[:-1] <= ma[:-1]) & (w1[1:] > ma[1:]))),
                        MED_MEM)
        med_dn = recent(np.concatenate(([False], (w1[:-1] >= ma[:-1]) & (w1[1:] < ma[1:]))),
                        MED_MEM)
        hi, lo, cl, op = di.high.values, di.low.values, di.close.values, di.open.values
        A = atr_pct(hi, lo, cl)
        # пивоты OKO-SM, каузально (цена с бара ПОДТВЕРЖДЕНИЯ)
        ptop = np.full(n, np.nan); pbtm = np.full(n, np.nan)
        for conf_i, sw_i, price, is_top in _swings(di["high"], di["low"], SW_LEN):
            (ptop if is_top else pbtm)[conf_i] = price
        ptop = pd.Series(ptop).ffill().to_numpy(float)
        pbtm = pd.Series(pbtm).ffill().to_numpy(float)
        ct_i = (di.index + pd.Timedelta(minutes=T)).values

        def exit_at(ii, side):
            """ВСТРЕЧНЫЙ КРОСС на том же ТФ."""
            arr = cd if side == 1 else cu
            lim = min(ii + TIMEOUT, n - 1)
            j = np.where(arr[ii + 1:lim + 1])[0]
            return (ii + 1 + int(j[0])) if len(j) else lim

        busy = {1: -1, -1: -1}
        busy_free = {1: -1, -1: -1}
        for i in range(60, n - 5):
            for sig, side in ((cu[i], 1), (cd[i], -1)):
                if not sig:
                    continue
                ii = i + 1
                if ii >= n - 3:
                    continue
                t_now = ct_i[i]
                q = bisect.bisect_right(st, t_now) - 1
                live, kc = False, -1
                for z in range(max(0, q - 4), q + 1):
                    if 0 <= z < len(ctx) and ctx[z][2] == side and \
                       ctx[z][0] <= t_now <= ctx[z][1]:
                        live, kc = True, ctx[z][3]; break
                jx = exit_at(ii, side)
                e = op[ii]
                pnl = (cl[jx] - e) / e * 100 * side - COST
                a = A[i]
                lvl = pbtm[i] if side == 1 else ptop[i]
                near = int(np.isfinite(lvl) and np.isfinite(a) and a > 0 and
                           abs(e - lvl) / e * 100 <= PIVOT_ATR * a)
                med = int((med_up if side == 1 else med_dn)[i])
                # C1: тот же кросс БЕЗ разрешения старшего
                if ii > busy_free[side]:
                    busy_free[side] = jx
                    base.append(("C1_свободный", sym, T, side, pnl, jx - ii))
                if not live or ii <= busy[side]:
                    continue
                busy[side] = jx
                j_c = bisect.bisect_right(ct_c, t_now) - 1
                dv = int((cdiv_up if side == 1 else cdiv_dn)[j_c]) if j_c >= 0 else 0
                age = (t_now - ctx[q][0]) / np.timedelta64(1, "h") if q >= 0 else np.nan
                rows.append((sym, T, side, dv, near, med, pnl, jx - ii, float(age),
                             int(di.index[i].year)))
        # C2: полная база той же геометрии
        for side in (1, -1):
            for ii in range(60, n - 4, 200):
                jx = exit_at(ii, side)
                e = op[ii]
                base.append(("C2_база", sym, T, side,
                             (cl[jx] - e) / e * 100 * side - COST, jx - ii))
    if fi % 5 == 0:
        print(f"  [{fi}/{len(files)}] сделок {len(rows):,}", flush=True)

R = pd.DataFrame(rows, columns=["sym", "T", "side", "div1h", "pivot", "med",
                                "pnl", "bars", "age_h", "year"])
B = pd.DataFrame(base, columns=["kind", "sym", "T", "side", "pnl", "bars"])
R.to_pickle(D + r"\egor_real.pkl"); B.to_pickle(D + r"\egor_real_base.pkl")
print(f"\nсделок {len(R):,} · контролей {len(B):,} · монет {R.sym.nunique()}\n")
bm = B.groupby(["kind", "T", "side"]).pnl.mean()


def blk(g):
    v = np.sort(g.pnl.values)[::-1]
    per = g.groupby("sym").pnl.mean()
    return v[int(len(v)*.1):].mean(), int((per > 0).sum()), len(per)


print("=== СХЕМА ПРОТИВ ДВУХ КОНТРОЛЕЙ ===")
print(f"{'T':>4} {'стор':>6} {'что':>22} {'n':>8} {'нетто':>9} {'мед':>9} {'WR':>6} "
      f"{'баров':>6} {'безтоп10':>9} {'монет+':>7}")
for T in ENTRIES:
    for side, sn in [(1, "long"), (-1, "short")]:
        g = R[(R.T == T) & (R.side == side)]
        if len(g) < 200:
            continue
        t10, sp, sn_ = blk(g)
        print(f"{T:>4} {sn:>6} {'СХЕМА (с разрешением)':>22} {len(g):>8,} "
              f"{g.pnl.mean():+8.3f}% {g.pnl.median():+8.3f}% "
              f"{(g.pnl>0).mean()*100:5.1f}% {g.bars.median():>6.0f} {t10:+8.3f}% "
              f"{sp}/{sn_}")
        for kind, lbl in [("C1_свободный", "C1 кроссы без разреш."),
                          ("C2_база", "C2 полная база")]:
            b = B[(B.kind == kind) & (B.T == T) & (B.side == side)]
            if len(b) < 200:
                continue
            v = np.sort(b.pnl.values)[::-1]
            per = b.groupby("sym").pnl.mean()
            print(f"{'':>4} {'':>6} {lbl:>22} {len(b):>8,} {b.pnl.mean():+8.3f}% "
                  f"{b.pnl.median():+8.3f}% {(b.pnl>0).mean()*100:5.1f}% "
                  f"{b.bars.median():>6.0f} {v[int(len(v)*.1):].mean():+8.3f}% "
                  f"{int((per>0).sum())}/{len(per)}")
        b1 = B[(B.kind == "C1_свободный") & (B.T == T) & (B.side == side)].pnl.mean()
        print(f"{'':>4} {'':>6} {'→ вклад разрешения':>22} {g.pnl.mean()-b1:+8.3f} п.п.")
        print()

print("=== ПЛЮСЫ ЕГОРА: дивергенция 1h · пивот рядом · медиана ===")
print(f"{'T':>4} {'стор':>6} {'условие':>34} {'n':>8} {'доля':>7} {'нетто':>9} "
      f"{'мед':>9} {'WR':>6} {'безтоп10':>9} {'монет+':>7}")
for T in ENTRIES:
    for side, sn in [(1, "long"), (-1, "short")]:
        g0 = R[(R.T == T) & (R.side == side)]
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
                ("все три плюса", (g0.div1h == 1) & (g0.pivot == 1) & (g0.med == 1)),
                ("сумма плюсов ≥2",
                 (g0.div1h + g0.pivot + g0.med) >= 2)]:
            g = g0[cond]
            if len(g) < 100:
                continue
            t10, sp, sn_ = blk(g)
            print(f"{T:>4} {sn:>6} {lbl:>34} {len(g):>8,} "
                  f"{len(g)/len(g0)*100:6.1f}% {g.pnl.mean():+8.3f}% "
                  f"{g.pnl.median():+8.3f}% {(g.pnl>0).mean()*100:5.1f}% {t10:+8.3f}% "
                  f"{sp}/{sn_}")
        print()

print("=== СВЕЖЕСТЬ РАЗРЕШЕНИЯ (часов с кросса на часовике) ===")
print(f"{'T':>4} {'стор':>6} {'возраст':>12} {'n':>8} {'нетто':>9} {'мед':>9} "
      f"{'безтоп10':>9} {'монет+':>7}")
for T in ENTRIES:
    for side, sn in [(1, "long"), (-1, "short")]:
        g0 = R[(R.T == T) & (R.side == side)]
        if len(g0) < 500:
            continue
        for lo, hi_, lbl in [(0, 2, "0-2 ч"), (2, 5, "2-5 ч"), (5, 8, "5-8 ч"),
                             (8, 13, "8-13 ч")]:
            g = g0[(g0.age_h >= lo) & (g0.age_h < hi_)]
            if len(g) < 100:
                continue
            t10, sp, sn_ = blk(g)
            print(f"{T:>4} {sn:>6} {lbl:>12} {len(g):>8,} {g.pnl.mean():+8.3f}% "
                  f"{g.pnl.median():+8.3f}% {t10:+8.3f}% {sp}/{sn_}")
        print()

print("=== ПО ГОДАМ (лучший ТФ входа) ===")
best_T = R.groupby("T").pnl.mean().idxmax()
for side, sn in [(1, "long"), (-1, "short")]:
    g0 = R[(R.T == best_T) & (R.side == side)]
    if len(g0) < 300:
        continue
    print(f"\n  T={best_T}m {sn}")
    for y in sorted(g0.year.unique()):
        g = g0[g0.year == y]
        if len(g) < 100:
            continue
        t10, sp, sn_ = blk(g)
        print(f"    {y}: n={len(g):>6,} {g.pnl.mean():+.3f}% мед {g.pnl.median():+.3f}% "
              f"безтоп10 {t10:+.3f}% монет+ {sp}/{sn_}")
