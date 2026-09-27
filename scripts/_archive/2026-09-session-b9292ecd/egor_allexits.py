# -*- coding: utf-8 -*-
"""🔬 ВСЕ ВОЗМОЖНЫЕ ВЫХОДЫ НА ОДНОМ ВХОДЕ (Егор: «пробуй все варианты», 11.09.2026).

ВХОД фиксирован и один для всех политик: первый кросс wt1×wt2 в сторону разрешения
внутри живого разрешения часовика (кросс в зоне OS/OB на 1h, жив 12 баров).
Дробление НЕ используется — измерено, что 16.5 кроссов стоят 5.79% костов и дают
столько же грязными, сколько один вход.

18 ПОЛИТИК ВЫХОДА, четыре семейства:
  ВОЗВРАТ К СРЕДНЕМУ   встречный кросс LTF · встречный кросс HTF · конец разрешения ·
                       противоположная зона
  ТРЕНДОВЫЕ            трейлинг по структуре (swing) · chandelier 2/3·ATR ·
                       wt1 ушёл под медиану · разворот наклона медианы
  ФИКСИРОВАННЫЕ ЦЕЛИ   RR-сетка TP/SL в ATR: 1/1 · 2/1 · 3/1.5 · 4/2 ·
                       геометрия стенда: TP ближайший swing, SL широкий структурный
  ВРЕМЕННЫЕ            10 · 30 · 60 · 120 баров

🔴 Для КАЖДОЙ политики свой контроль — случайный бар той же монеты, та же политика.
   Метрика отбора — ПРЕВЫШЕНИЕ над контролем, не абсолют: лучший из 18 будет хорош
   просто от перебора, это учтено.
🔴 Вход по OPEN следующего бара · косты 0.35% на круг · внутрибарно стоп раньше цели.
"""
import os, sys, glob, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_wt
from core.smc.oko_sm_engine import _swings

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
TF_CTX, ENTRIES = 60, [3, 15]
MA_LEN, SW_LEN = 43, 5
OS_, OB_, LIFE, TIMEOUT, COST, NSYM = -60.0, 60.0, 12, 400, 0.35, 25
RNG = np.random.default_rng(2026)
POL = ["MR встречный кросс LTF", "MR встречный кросс HTF", "MR конец разрешения",
       "MR противоположная зона",
       "TR трейл по структуре", "TR chandelier 2ATR", "TR chandelier 3ATR",
       "TR wt1 под медиану", "TR разворот наклона MA",
       "FX TP1/SL1 ATR", "FX TP2/SL1 ATR", "FX TP3/SL1.5 ATR", "FX TP4/SL2 ATR",
       "FX геометрия стенда",
       "TM 10 баров", "TM 30 баров", "TM 60 баров", "TM 120 баров"]
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))[:NSYM]
print(f"монет {len(files)} · входы {ENTRIES} · политик выхода {len(POL)}\n", flush=True)


def resample(d1, tf):
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


def atr_pct(h, l, c, period=14):
    prev = np.concatenate(([c[0]], c[:-1]))
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev), np.abs(l - prev)))
    return pd.Series(np.where(c > 0, tr / c * 100, np.nan)).rolling(
        period, min_periods=5).mean().to_numpy(float)


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
        ma = pd.Series(w1).ewm(span=MA_LEN, adjust=False).mean().to_numpy()
        ma_rise = np.concatenate(([False], ma[1:] > ma[:-1]))
        hi, lo, cl, op = di.high.values, di.low.values, di.close.values, di.open.values
        A = atr_pct(hi, lo, cl)
        ptop = np.full(n, np.nan); pbtm = np.full(n, np.nan)
        for conf_i, sw_i, price, is_top in _swings(di["high"], di["low"], SW_LEN):
            (ptop if is_top else pbtm)[conf_i] = price
        ptop = pd.Series(ptop).ffill().to_numpy(float)
        pbtm = pd.Series(pbtm).ffill().to_numpy(float)
        ct_i = (di.index + pd.Timedelta(minutes=T)).values
        zone_up, zone_dn = w1 >= OB_, w1 <= OS_

        def all_exits(ii, side, i_ctx_end, kc):
            """вернуть список (pnl, bars) длины len(POL) для входа на баре ii."""
            e = op[ii]
            a = A[ii - 1] if np.isfinite(A[ii - 1]) else np.nan
            lim = min(ii + TIMEOUT, n - 1)
            out = []

            def px(j):
                return (cl[j] - e) / e * 100 * side - COST

            dn = cd if side == 1 else cu
            j = np.where(dn[ii + 1:lim + 1])[0]
            j1 = ii + 1 + int(j[0]) if len(j) else lim
            out.append((px(j1), j1 - ii))                       # 0 MR кросс LTF
            opp_c = ccd if side == 1 else ccu
            kk = np.where(opp_c[kc + 1:])[0]
            j2 = (min(max(int(np.searchsorted(ct_i, ct_c[kc + 1 + int(kk[0])], "left")),
                          ii + 1), lim) if len(kk) else lim)
            out.append((px(j2), j2 - ii))                       # 1 MR кросс HTF
            j3 = min(max(i_ctx_end, ii + 1), lim)
            out.append((px(j3), j3 - ii))                       # 2 MR конец разрешения
            z = zone_up if side == 1 else zone_dn
            jz = np.where(z[ii + 1:lim + 1])[0]
            j4 = ii + 1 + int(jz[0]) if len(jz) else lim
            out.append((px(j4), j4 - ii))                       # 3 MR зона
            # ── трендовые (побарный проход один раз)
            trail_sw = trail_a2 = trail_a3 = None
            wt_med = ma_flip = None
            ext = hi[ii] if side == 1 else lo[ii]
            for k in range(ii, lim + 1):
                ext = max(ext, hi[k]) if side == 1 else min(ext, lo[k])
                if trail_sw is None:
                    lvl = pbtm[k] if side == 1 else ptop[k]
                    if np.isfinite(lvl) and k > ii and (
                            (side == 1 and cl[k] < lvl) or (side == -1 and cl[k] > lvl)):
                        trail_sw = k
                if np.isfinite(a):
                    if trail_a2 is None and k > ii:
                        stop = ext * (1 - 2 * a / 100) if side == 1 else ext * (1 + 2 * a / 100)
                        if (side == 1 and lo[k] <= stop) or (side == -1 and hi[k] >= stop):
                            trail_a2 = k
                    if trail_a3 is None and k > ii:
                        stop = ext * (1 - 3 * a / 100) if side == 1 else ext * (1 + 3 * a / 100)
                        if (side == 1 and lo[k] <= stop) or (side == -1 and hi[k] >= stop):
                            trail_a3 = k
                if wt_med is None and k > ii and (
                        (side == 1 and w1[k] < ma[k]) or (side == -1 and w1[k] > ma[k])):
                    wt_med = k
                if ma_flip is None and k > ii and (
                        (side == 1 and not ma_rise[k]) or (side == -1 and ma_rise[k])):
                    ma_flip = k
                if all(x is not None for x in (trail_sw, trail_a2, trail_a3,
                                               wt_med, ma_flip)):
                    break
            for jj in (trail_sw, trail_a2, trail_a3, wt_med, ma_flip):
                jj = jj if jj is not None else lim
                out.append((px(jj), jj - ii))                   # 4..8 трендовые
            # ── фиксированные цели
            for tp_m, sl_m in ((1, 1), (2, 1), (3, 1.5), (4, 2)):
                if not np.isfinite(a) or a <= 0:
                    out.append((px(lim), lim - ii)); continue
                tp = e * (1 + tp_m * a / 100) if side == 1 else e * (1 - tp_m * a / 100)
                sl = e * (1 - sl_m * a / 100) if side == 1 else e * (1 + sl_m * a / 100)
                jj, pnl = lim, None
                for k in range(ii, lim + 1):
                    if (side == 1 and lo[k] <= sl) or (side == -1 and hi[k] >= sl):
                        jj, pnl = k, (sl - e) / e * 100 * side - COST; break
                    if (side == 1 and hi[k] >= tp) or (side == -1 and lo[k] <= tp):
                        jj, pnl = k, (tp - e) / e * 100 * side - COST; break
                out.append((pnl if pnl is not None else px(jj), jj - ii))  # 9..12
            # геометрия стенда: TP ближайший swing, SL широкий структурный
            tgt = ptop[ii - 1] if side == 1 else pbtm[ii - 1]
            stp = pbtm[ii - 1] if side == 1 else ptop[ii - 1]
            if np.isfinite(tgt) and np.isfinite(stp) and np.isfinite(a):
                stp = stp * (1 - 0.5 * a / 100) if side == 1 else stp * (1 + 0.5 * a / 100)
                jj, pnl = lim, None
                for k in range(ii, lim + 1):
                    if (side == 1 and lo[k] <= stp) or (side == -1 and hi[k] >= stp):
                        jj, pnl = k, (stp - e) / e * 100 * side - COST; break
                    if (side == 1 and hi[k] >= tgt) or (side == -1 and lo[k] <= tgt):
                        jj, pnl = k, (tgt - e) / e * 100 * side - COST; break
                out.append((pnl if pnl is not None else px(jj), jj - ii))
            else:
                out.append((px(lim), lim - ii))                 # 13
            for nb in (10, 30, 60, 120):
                jj = min(ii + nb, n - 1)
                out.append((px(jj), jj - ii))                   # 14..17
            return out

        for (t0, t1, side, kc) in ctx:
            i0 = int(np.searchsorted(ct_i, t0, "left"))
            i1 = int(np.searchsorted(ct_i, t1, "right")) - 1
            if i0 < 60 or i1 >= n - 5 or i1 <= i0 + 2:
                continue
            up = cu if side == 1 else cd
            ins = [k for k in range(i0, i1) if up[k]]
            if not ins:
                continue
            ii = ins[0] + 1
            if ii >= n - 5:
                continue
            year = int(di.index[ii].year)
            for pi, (pnl, bars) in enumerate(all_exits(ii, side, i1, kc)):
                rows.append((sym, T, side, pi, "sig", pnl, bars, year))
            rs = int(RNG.integers(60, max(61, n - TIMEOUT - 5)))
            kr = int(np.clip(np.searchsorted(ct_c, ct_i[rs], "right") - 1, 0, nc - 2))
            for pi, (pnl, bars) in enumerate(
                    all_exits(rs, side, min(rs + (i1 - ii), n - 2), kr)):
                rows.append((sym, T, side, pi, "ctl", pnl, bars, year))
    if fi % 5 == 0:
        print(f"  [{fi}/{len(files)}] {len(rows):,}", flush=True)

R = pd.DataFrame(rows, columns=["sym", "tf", "side", "pol", "kind", "pnl", "bars", "year"])
R.to_pickle(D + r"\egor_allexits.pkl")
print(f"\nзаписей {len(R):,} · монет {R.sym.nunique()}\n")

res = []
for T in ENTRIES:
    for side in (1, -1):
        for pi in range(len(POL)):
            g = R[(R["tf"] == T) & (R["side"] == side) & (R["pol"] == pi) &
                  (R["kind"] == "sig")]
            c = R[(R["tf"] == T) & (R["side"] == side) & (R["pol"] == pi) &
                  (R["kind"] == "ctl")]
            if len(g) < 300 or len(c) < 300:
                continue
            v = np.sort(g.pnl.values)[::-1]
            per = g.groupby("sym").pnl.mean()
            yrs = g.groupby("year").pnl.mean()
            res.append(dict(tf=T, side=side, pol=pi, n=len(g), net=g.pnl.mean(),
                            ctl=c.pnl.mean(), over=g.pnl.mean() - c.pnl.mean(),
                            med=g.pnl.median(), wr=(g.pnl > 0).mean(),
                            bars=g.bars.median(), top10=v[int(len(v)*.1):].mean(),
                            sp=int((per > 0).sum()), sn=len(per),
                            yp=int((yrs > 0).sum()), yn=len(yrs)))
O = pd.DataFrame(res)
O.to_pickle(D + r"\egor_allexits_summary.pkl")

print("=== ВСЕ ПОЛИТИКИ, СОРТИРОВКА ПО ПРЕВЫШЕНИЮ НАД КОНТРОЛЕМ ===")
print(f"{'T':>4} {'стор':>6} {'политика':>24} {'n':>6} {'нетто':>9} {'контр':>8} "
      f"{'НАД':>8} {'мед':>8} {'WR':>6} {'бар':>5} {'безтоп10':>9} {'монет+':>7} {'лет+':>5}")
for _, r in O.sort_values("over", ascending=False).iterrows():
    print(f"{int(r.tf):>4} {'long' if r.side==1 else 'short':>6} {POL[int(r.pol)]:>24} "
          f"{int(r.n):>6,} {r.net:+8.3f}% {r.ctl:+7.3f}% {r.over:+7.3f}% "
          f"{r.med:+7.3f}% {r.wr*100:5.1f}% {r.bars:>5.0f} {r.top10:+8.3f}% "
          f"{int(r.sp)}/{int(r.sn)} {int(r.yp)}/{int(r.yn)}")

print("\n=== ТОЛЬКО ТЕ, ЧТО ПОЛОЖИТЕЛЬНЫ НЕТТО ===")
pos = O[O.net > 0].sort_values("net", ascending=False)
if len(pos):
    for _, r in pos.iterrows():
        print(f"  {int(r.tf)}m {'long' if r.side==1 else 'short':>5} "
              f"{POL[int(r.pol)]:>24}: нетто {r.net:+.3f}% · над контролем {r.over:+.3f}% · "
              f"мед {r.med:+.3f}% · безтоп10 {r.top10:+.3f}% · монет+ {int(r.sp)}/{int(r.sn)} "
              f"· лет+ {int(r.yp)}/{int(r.yn)}")
else:
    print("  нет ни одной политики с положительным нетто")

print("\n=== ПО СЕМЕЙСТВАМ (среднее превышение над контролем) ===")
fam = {"MR": "возврат к среднему", "TR": "трендовые", "FX": "фикс. цели",
       "TM": "временные"}
O["fam"] = O.pol.apply(lambda p: POL[p][:2])
for k, nm in fam.items():
    g = O[O.fam == k]
    if not len(g):
        continue
    print(f"  {nm:>20}: над контролем {g.over.mean():+.3f} п.п. · нетто "
          f"{g.net.mean():+.3f}% · лучшая {g.over.max():+.3f}")
