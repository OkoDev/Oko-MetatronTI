# -*- coding: utf-8 -*-
"""🏆 ГРАДИЕНТ ПО ПОРОГУ ВЫХОДА + СУРРОГАТ + ЭКВИТИ (11.09.2026).

На 291 монете и 5 годах выжила одна конфигурация и появился МОНОТОННЫЙ градиент:
    ZONE=50 −0.279% (над контролем +0.094) · ZONE=60 +0.142% (+0.570) ·
    ZONE=70 +1.157% (+1.608), монет+ 231/291
LIFE (6/12/24) не влияет ⇒ дело не в разрешении часовика, а в ВЫХОДЕ по глубокой зоне.

Три вопроса, закрывающие находку:
  1. ПРОДОЛЖАЕТСЯ ЛИ ГРАДИЕНТ: зоны 60…95 + отдельно порог ВХОДНОЙ зоны часовика
  2. ЭКВИТИ: удержание 119 баров ⇒ сделки ПЕРЕКРЫВАЮТСЯ, среднее по сделкам завышает.
     Считается портфельная эквити с одной позицией на монету
  3. СУРРОГАТ: та же конструкция на фазово-рандомизированном ряде

🔴 Контроль для каждой конфигурации · обе стороны · разрез по годам и режимам.
"""
import os, sys, sqlite3, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_wt

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
TIMEOUT, COST, LIFE = 400, 0.35, 12
EXIT_Z = [60.0, 70.0, 75.0, 80.0, 85.0, 95.0]    # порог зоны ВЫХОДА
ENTRY_Z = [50.0, 60.0, 70.0]                      # порог зоны ВХОДА на часовике
NSYM, NSUR = 200, 12
RNG = np.random.default_rng(4242)
RG = {2022: "МЕДВ", 2023: "БЫК", 2024: "нейтр", 2025: "МЕДВ", 2026: "МЕДВ"}
con = sqlite3.connect("ohlcv_cache.db")
syms = [r[0] for r in con.execute(
    "select symbol from ohlcv_cache where timeframe='15m' "
    "group by symbol having count(*) > 50000 order by count(*) desc")][:NSYM]
print(f"символов {len(syms)} · зоны выхода {EXIT_Z} · зоны входа {ENTRY_Z} · "
      f"суррогатов {NSUR}\n", flush=True)


def iaaft(x, iters=10, rng=RNG):
    n = len(x); xs = np.sort(x); amp = np.abs(np.fft.rfft(x))
    y = rng.permutation(x)
    for _ in range(iters):
        Y = np.fft.rfft(y)
        y = np.fft.irfft(amp * np.exp(1j * np.angle(Y)), n)
        y = xs[np.argsort(np.argsort(y))]
    return y


def pipeline(di, collect_equity=False):
    """вернуть список записей (side, ez, iz, pnl, bars, year, kind) + эквити."""
    dc = di.resample("60min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    if len(dc) < 500 or len(di) < 2000:
        return [], {}
    wc = calculate_wt(dc.reset_index(drop=True))
    c1, c2 = wc["wt1"].values, wc["wt2"].values
    nc = len(c1)
    ccu = np.zeros(nc, bool); ccd = np.zeros(nc, bool)
    ccu[1:] = (c1[:-1] <= c2[:-1]) & (c1[1:] > c2[1:])
    ccd[1:] = (c1[:-1] >= c2[:-1]) & (c1[1:] < c2[1:])
    ct_c = (dc.index + pd.Timedelta(minutes=60)).values
    wi = calculate_wt(di.reset_index(drop=True))
    w1, w2 = wi["wt1"].values, wi["wt2"].values
    n = len(w1)
    cu = np.zeros(n, bool); cd = np.zeros(n, bool)
    cu[1:] = (w1[:-1] <= w2[:-1]) & (w1[1:] > w2[1:])
    cd[1:] = (w1[:-1] >= w2[:-1]) & (w1[1:] < w2[1:])
    cl, op = di.close.values, di.open.values
    ct_i = (di.index + pd.Timedelta(minutes=15)).values
    yr = di.index.year.values
    out, eq = [], {}
    for IZ in ENTRY_Z:
        for side, czone in ((1, ccu & (c1 < -IZ)), (-1, ccd & (c1 > IZ))):
            ctx = []
            for k in np.where(czone)[0]:
                if k + LIFE < nc:
                    ctx.append((ct_c[k], ct_c[k + LIFE]))
            if not ctx:
                continue
            ctx.sort()
            for EZ in EXIT_Z:
                zone = (w1 >= EZ) if side == 1 else (w1 <= -EZ)
                busy, tot, cnt, occ = -1, 0.0, 0, 0
                for (t0, t1) in ctx:
                    i0 = int(np.searchsorted(ct_i, t0, "left"))
                    i1 = int(np.searchsorted(ct_i, t1, "right")) - 1
                    if i0 < 60 or i1 >= n - 5 or i1 <= i0:
                        continue
                    up = cu if side == 1 else cd
                    ins = [k for k in range(i0, i1 + 1) if up[k]]
                    if not ins:
                        continue
                    ii = ins[0] + 1
                    if ii >= n - 5:
                        continue
                    lim = min(ii + TIMEOUT, n - 1)
                    jz = np.where(zone[ii + 1:lim + 1])[0]
                    jx = ii + 1 + int(jz[0]) if len(jz) else lim
                    e = op[ii]
                    pnl = (cl[jx] - e) / e * 100 * side - COST
                    out.append((side, EZ, IZ, pnl, jx - ii, int(yr[ii]), "sig"))
                    if collect_equity and ii > busy:
                        tot += pnl; cnt += 1; occ += jx - ii; busy = jx
                    rs = int(RNG.integers(60, max(61, n - TIMEOUT - 5)))
                    jr = np.where(zone[rs + 1:min(rs + TIMEOUT, n - 1) + 1])[0]
                    jrx = rs + 1 + int(jr[0]) if len(jr) else min(rs + TIMEOUT, n - 1)
                    out.append((side, EZ, IZ,
                                (cl[jrx] - op[rs]) / op[rs] * 100 * side - COST,
                                jrx - rs, int(yr[rs]), "ctl"))
                if collect_equity and cnt:
                    eq[(side, EZ, IZ)] = (tot, cnt, occ / n)
    return out, eq


rows, eqs = [], []
data = []
for fi, sym in enumerate(syms, 1):
    d = pd.read_sql("select time,open,high,low,close from ohlcv_cache "
                    "where symbol=? and timeframe='15m' order by time",
                    con, params=(sym,))
    if len(d) < 50000:
        continue
    d["ts"] = pd.to_datetime(d.time, unit="ms")
    di = d.drop_duplicates("ts").set_index("ts")
    o, e = pipeline(di, collect_equity=True)
    for r in o:
        rows.append((sym,) + r)
    for k, v in e.items():
        eqs.append((sym,) + k + v)
    if fi <= 40:
        data.append((sym, di))
    if fi % 40 == 0:
        print(f"  [{fi}/{len(syms)}] {len(rows):,}", flush=True)

R = pd.DataFrame(rows, columns=["sym", "side", "ez", "iz", "pnl", "bars", "year", "kind"])
E = pd.DataFrame(eqs, columns=["sym", "side", "ez", "iz", "total", "trades", "occ"])
R.to_pickle(D + r"\egor_zone_grid.pkl"); E.to_pickle(D + r"\egor_zone_eq.pkl")
print(f"\nзаписей {len(R):,} · монет {R.sym.nunique()}\n")


def blk(g):
    v = np.sort(g.pnl.values)[::-1]
    per = g.groupby("sym").pnl.mean()
    return v[int(len(v)*.1):].mean(), v[int(len(v)*.25):].mean(), \
        int((per > 0).sum()), len(per)


print("=== ГРАДИЕНТ ПО ПОРОГУ ВЫХОДА (вход IZ=60) ===")
print(f"{'стор':>6} {'выход':>6} {'n':>7} {'нетто':>9} {'контр':>8} {'НАД':>8} "
      f"{'мед':>9} {'WR':>6} {'бар':>5} {'безтоп10':>9} {'безтоп25':>9} {'монет+':>9}")
for side, sn in [(1, "long"), (-1, "short")]:
    for EZ in EXIT_Z:
        g = R[(R["side"] == side) & (R["ez"] == EZ) & (R["iz"] == 60.0) &
              (R["kind"] == "sig")]
        c = R[(R["side"] == side) & (R["ez"] == EZ) & (R["iz"] == 60.0) &
              (R["kind"] == "ctl")]
        if len(g) < 200:
            continue
        t10, t25, sp, sn_ = blk(g)
        print(f"{sn:>6} {EZ:>6.0f} {len(g):>7,} {g.pnl.mean():+8.3f}% "
              f"{c.pnl.mean():+7.3f}% {g.pnl.mean()-c.pnl.mean():+7.3f}% "
              f"{g.pnl.median():+8.3f}% {(g.pnl>0).mean()*100:5.1f}% "
              f"{g.bars.median():>5.0f} {t10:+8.3f}% {t25:+8.3f}% {sp}/{sn_}")
    print()

print("=== ПОРОГ ВХОДНОЙ ЗОНЫ ЧАСОВИКА (выход EZ=80) ===")
for side, sn in [(1, "long"), (-1, "short")]:
    for IZ in ENTRY_Z:
        g = R[(R["side"] == side) & (R["ez"] == 80.0) & (R["iz"] == IZ) &
              (R["kind"] == "sig")]
        c = R[(R["side"] == side) & (R["ez"] == 80.0) & (R["iz"] == IZ) &
              (R["kind"] == "ctl")]
        if len(g) < 200:
            continue
        t10, _, sp, sn_ = blk(g)
        print(f"  {sn:>5} вход±{IZ:.0f}: n={len(g):>6,} нетто {g.pnl.mean():+.3f}% · "
              f"над {g.pnl.mean()-c.pnl.mean():+.3f}% · мед {g.pnl.median():+.3f}% · "
              f"безтоп10 {t10:+.3f}% · монет+ {sp}/{sn_}")

print("\n=== ЛУЧШАЯ КОНФИГУРАЦИЯ ПО ГОДАМ ===")
best = None
for side in (1, -1):
    for EZ in EXIT_Z:
        for IZ in ENTRY_Z:
            g = R[(R["side"] == side) & (R["ez"] == EZ) & (R["iz"] == IZ) &
                  (R["kind"] == "sig")]
            if len(g) < 2000:
                continue
            v = np.sort(g.pnl.values)[::-1]
            t10 = v[int(len(v)*.1):].mean()
            if best is None or t10 > best[0]:
                best = (t10, side, EZ, IZ)
_, bs, bez, biz = best
print(f"  выбрана по безтоп10%: {'long' if bs==1 else 'short'} · выход ±{bez:.0f} · "
      f"вход ±{biz:.0f}")
for y in sorted(R.year.unique()):
    g = R[(R["side"] == bs) & (R["ez"] == bez) & (R["iz"] == biz) &
          (R["kind"] == "sig") & (R["year"] == y)]
    c = R[(R["side"] == bs) & (R["ez"] == bez) & (R["iz"] == biz) &
          (R["kind"] == "ctl") & (R["year"] == y)]
    if len(g) < 50:
        continue
    t10, _, sp, sn_ = blk(g)
    print(f"    {y} {RG.get(y,'?'):>6}: n={len(g):>6,} нетто {g.pnl.mean():+.3f}% "
          f"контр {c.pnl.mean():+.3f}% над {g.pnl.mean()-c.pnl.mean():+.3f}% "
          f"мед {g.pnl.median():+.3f}% безтоп10 {t10:+.3f}% монет+ {sp}/{sn_}")

print("\n=== ЭКВИТИ (одна позиция на монету; сделки перекрываются!) ===")
print(f"{'стор':>6} {'выход':>6} {'вход':>5} {'монет':>6} {'сумма%':>9} {'на сделку':>10} "
      f"{'сделок':>7} {'в рынке':>8} {'монет+':>9}")
for side, sn in [(1, "long"), (-1, "short")]:
    for EZ in EXIT_Z:
        g = E[(E["side"] == side) & (E["ez"] == EZ) & (E["iz"] == 60.0)]
        if len(g) < 50:
            continue
        print(f"{sn:>6} {EZ:>6.0f} {60:>5} {len(g):>6} {g.total.mean():+8.1f}% "
              f"{g.total.sum()/max(g.trades.sum(),1):+9.3f}% {g.trades.mean():>7.1f} "
              f"{g.occ.mean()*100:7.1f}% {int((g.total>0).sum())}/{len(g)}")
    print()

# ── СУРРОГАТ на лучшей конфигурации
print("=== СУРРОГАТ (IAAFT) НА ЛУЧШЕЙ КОНФИГУРАЦИИ ===", flush=True)
g = R[(R["side"] == bs) & (R["ez"] == bez) & (R["iz"] == biz) & (R["kind"] == "sig")]
c = R[(R["side"] == bs) & (R["ez"] == bez) & (R["iz"] == biz) & (R["kind"] == "ctl")]
real_over = g.pnl.mean() - c.pnl.mean()
real_net = g.pnl.mean()
print(f"  реальное: нетто {real_net:+.3f}% · над контролем {real_over:+.3f} п.п. "
      f"(на {len(data)} монетах суррогат)", flush=True)
S_net, S_over = [], []
for s in range(NSUR):
    rows_s = []
    for sym, di in data:
        cclose = di.close.to_numpy(float)
        lr = np.diff(np.log(cclose))
        sur = iaaft(lr)
        cs = np.empty(len(cclose)); cs[0] = cclose[0]
        cs[1:] = cclose[0] * np.exp(np.cumsum(sur))
        ds = pd.DataFrame({"open": cs, "high": cs, "low": cs, "close": cs},
                          index=di.index)
        o, _ = pipeline(ds)
        rows_s += [(sym,) + r for r in o]
    if len(rows_s) < 200:
        continue
    RS = pd.DataFrame(rows_s, columns=["sym", "side", "ez", "iz", "pnl", "bars",
                                       "year", "kind"])
    gs = RS[(RS["side"] == bs) & (RS["ez"] == bez) & (RS["iz"] == biz) &
            (RS["kind"] == "sig")]
    cs_ = RS[(RS["side"] == bs) & (RS["ez"] == bez) & (RS["iz"] == biz) &
             (RS["kind"] == "ctl")]
    if len(gs) < 100 or len(cs_) < 100:
        continue
    S_net.append(gs.pnl.mean()); S_over.append(gs.pnl.mean() - cs_.pnl.mean())
    print(f"    суррогат {s+1:>2}/{NSUR}: нетто {gs.pnl.mean():+.3f}% · "
          f"над {gs.pnl.mean()-cs_.pnl.mean():+.3f}", flush=True)

# реальное на тех же монетах, что суррогат
sub = [s for s, _ in data]
gr = g[g.sym.isin(sub)]; cr = c[c.sym.isin(sub)]
rn, ro = gr.pnl.mean(), gr.pnl.mean() - cr.pnl.mean()
for nm, real, sur in [("нетто", rn, S_net), ("над контролем", ro, S_over)]:
    if not sur:
        continue
    a = np.array(sur)
    pct = (a < real).mean() * 100
    p95 = np.percentile(a, 95)
    print(f"\n  {nm}: реальное {real:+.3f} · суррогаты медиана {np.median(a):+.3f} "
          f"[{a.min():+.3f} … {a.max():+.3f}] · 95й {p95:+.3f} · "
          f"перцентиль {pct:.0f}% → "
          f"{'✅ БЬЁТ' if real > p95 else '🔴 НЕ БЬЁТ'}")
