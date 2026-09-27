# -*- coding: utf-8 -*-
"""🔬 ПРОВЕРКА 4h→1h (11.09.2026) — лучшая схема вверх по лестнице.

4h→1h (контекст 4h: кросс wt1×wt2 вверх при wt1 < −70; вход 1h: первый кросс вверх в окне
12 баров 4h; выход: wt1 1h ≥ +60): +2.624%, над контролем +2.703, безтоп10 +0.576% без фильтра,
228/291 монета, 3/5 лет. Перед тем как верить:
  1. СЕТКА ПОРОГОВ: вход ±{60,65,70,75} × выход +{50,60,70} — плато или пик?
  2. ТАЙМАУТ: доля сделок, не дошедших до зоны за 400 баров 1h
  3. СЛЕПОЙ ПОРОГ КЛАСТЕРА: выбрать k на 2022-24, проверить на 2025-26
  4. СУРРОГАТ IAAFT без перекрытия (60 монет × 15 рядов), OHLC из 15m close в обеих ветках
Одна позиция на монету · косты 0.35% · контроль — случайный вход без перекрытия.
"""
import os, sys, sqlite3, warnings, time
warnings.filterwarnings("ignore")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_wt

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
LIFE, TIMEOUT, COST = 12, 400, 0.35
CTX, INTF = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) > 2 else (240, 60)
TAG = f"{CTX}m→{INTF}m"
print(f"########## СХЕМА {TAG} ##########\n", flush=True)
IZS, EZS = [60.0, 65.0, 70.0, 75.0], [50.0, 60.0, 70.0]
NSUR_SYM, NSUR = 60, 15
RNG = np.random.default_rng(41)
YR = {2022: "МЕДВ", 2023: "БЫК", 2024: "нейтр", 2025: "МЕДВ", 2026: "МЕДВ"}
con = sqlite3.connect("ohlcv_cache.db")
syms = [r[0] for r in con.execute(
    "select symbol from ohlcv_cache where timeframe='15m' "
    "group by symbol having count(*) > 50000 order by count(*) desc")][:300]
btc_sym = next(s for s in syms if s.upper().startswith("BTC"))


def load(sym):
    d = pd.read_sql("select time,close from ohlcv_cache where symbol=? and timeframe='15m' "
                    "order by time", con, params=(sym,))
    d["ts"] = pd.to_datetime(d.time, unit="ms")
    return d.drop_duplicates("ts").set_index("ts").close


bc = load(btc_sym)
btc30 = (bc / bc.shift(30 * 96) - 1) * 100


def bars(close15, tf):
    r = close15.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r.first(), "high": r.max(), "low": r.min(),
                         "close": r.last()}).dropna()


def wt(d):
    w = calculate_wt(d.reset_index(drop=True))
    w1, w2 = w["wt1"].values, w["wt2"].values
    cu = np.zeros(len(w1), bool); cu[1:] = (w1[:-1] <= w2[:-1]) & (w1[1:] > w2[1:])
    return w1, cu


def run(close15, confs, want_ctl=True):
    """вернуть список (iz, ez, kind, pnl, t_entry, timeout_flag)."""
    d4, d1 = bars(close15, CTX), bars(close15, INTF)
    if len(d4) < 200 or len(d1) < 800:
        return []
    c1, ccu = wt(d4); w1, cu = wt(d1)
    nc, n = len(c1), len(w1)
    ct4 = (d4.index + pd.Timedelta(minutes=CTX)).values
    ct1 = (d1.index + pd.Timedelta(minutes=INTF)).values
    op, cl = d1.open.values, d1.close.values
    out = []
    for iz, ez in confs:
        ents = []
        for k in np.where(ccu & (c1 < -iz))[0]:
            if k + LIFE >= nc:
                continue
            i0 = int(np.searchsorted(ct1, ct4[k], "left"))
            i1 = int(np.searchsorted(ct1, ct4[k + LIFE], "right")) - 1
            if i0 < 60 or i1 >= n - 3 or i1 <= i0:
                continue
            ins = np.where(cu[i0:i1 + 1])[0]
            if len(ins):
                ents.append(i0 + int(ins[0]) + 1)
        zone = w1 >= ez

        def ex(ii):
            lim = min(ii + TIMEOUT, n - 1)
            j = np.where(zone[ii + 1:lim + 1])[0]
            return (ii + 1 + int(j[0]), 0) if len(j) else (lim, 1)

        busy, taken = -1, 0
        for ii in sorted(set(e for e in ents if e < n - 3)):
            if ii <= busy:
                continue
            jx, to = ex(ii); busy = jx; taken += 1
            out.append((iz, ez, "sig", (cl[jx] - op[ii]) / op[ii] * 100 - COST,
                        d1.index[ii], to))
        if want_ctl:
            cb, cn = -1, 0
            for ii in np.sort(RNG.integers(60, max(61, n - TIMEOUT - 3), size=max(taken, 1) * 4)):
                if cn >= taken:
                    break
                if ii <= cb:
                    continue
                jx, to = ex(int(ii)); cb = jx; cn += 1
                out.append((iz, ez, "ctl", (cl[jx] - op[ii]) / op[ii] * 100 - COST,
                            d1.index[int(ii)], to))
    return out


ALL = [(iz, ez) for iz in IZS for ez in EZS]
rows, closes = [], []
t0 = time.time()
for fi, sym in enumerate(syms, 1):
    c = load(sym)
    if len(c) < 50000:
        continue
    for r in run(c, ALL):
        rows.append((sym,) + r)
    if len(closes) < NSUR_SYM:
        closes.append((sym, c))
    if fi % 60 == 0:
        print(f"  [{fi}/{len(syms)}] {len(rows):,} · {time.time()-t0:.0f}с", flush=True)

R = pd.DataFrame(rows, columns=["sym", "iz", "ez", "kind", "pnl", "ts", "to"])
R["ts"] = pd.to_datetime(R["ts"]); R["year"] = R.ts.dt.year; R["day"] = R.ts.dt.normalize()
R["btc30"] = btc30.reindex(R.ts, method="ffill").values
R.to_pickle(D + rf"\verify_{CTX}_{INTF}.pkl")
S = R[R.kind == "sig"]; C = R[R.kind == "ctl"]
print(f"\nзаписей {len(R):,} · монет {R.sym.nunique()}\n")


def st(g):
    v = np.sort(g.pnl.values)[::-1]
    per = g.groupby("sym").pnl.sum()
    return len(g), g.pnl.mean(), v[int(len(v) * .1):].mean(), int((per > 0).sum()), len(per)


print("=== 1-2. СЕТКА ПОРОГОВ (плато или пик) + доля таймаута ===")
print(f"{'вход':>5} {'выход':>6} {'n':>6} {'нетто':>9} {'контр':>8} {'НАД':>8} {'безтоп10':>9} "
      f"{'таймаут':>8} {'монет+':>9} {'лет+':>5}")
for iz in IZS:
    for ez in EZS:
        g = S[(S.iz == iz) & (S.ez == ez)]; c = C[(C.iz == iz) & (C.ez == ez)]
        if len(g) < 50:
            continue
        s = st(g); yrs = g.groupby("year").pnl.mean()
        print(f"{iz:>5.0f} {ez:>6.0f} {s[0]:>6,} {s[1]:+8.3f}% {c.pnl.mean():+7.3f}% "
              f"{s[1]-c.pnl.mean():+7.3f}% {s[2]:+8.3f}% {g.to.mean()*100:7.1f}% "
              f"{s[3]}/{s[4]} {int((yrs>0).sum())}/{len(yrs)}")

G = S[(S.iz == 70.0) & (S.ez == 60.0)].copy()
G = G.join(G.groupby("day").sym.nunique().rename("k"), on="day")
print(f"\n=== 3. СЛЕПОЙ ПОРОГ КЛАСТЕРА (4h→1h, ±70/+60): IS 2022-24 → OOS 2025-26 ===")
IS, OOS = G[G.year <= 2024], G[G.year >= 2025]
best = None
print(f"{'k≥':>4} {'IS n':>5} {'IS нетто':>9} {'IS безтоп10':>12} {'OOS n':>6} {'OOS нетто':>10} "
      f"{'OOS безтоп10':>13}")
for k in [2, 3, 5, 8, 10, 15, 20, 30]:
    a, b = IS[IS.k >= k], OOS[OOS.k >= k]
    if len(a) < 30 or len(b) < 30:
        continue
    sa, sb = st(a), st(b)
    print(f"{k:>4} {sa[0]:>5,} {sa[1]:+8.3f}% {sa[2]:+11.3f}% {sb[0]:>6,} {sb[1]:+9.3f}% "
          f"{sb[2]:+12.3f}%")
    if best is None or sa[2] > best[1]:
        best = (k, sa[2])
if best:
    k = best[0]
    b0, b1 = st(OOS), st(OOS[OOS.k >= k])
    b2 = OOS[(OOS.k >= k) & (OOS.btc30 < -10)]
    print(f"  выбран на IS k≥{k} → OOS: без фильтра {b0[1]:+.3f}% → кластер {b1[1]:+.3f}% "
          f"(безтоп10 {b1[2]:+.3f})" +
          (f" · кластер+BTC↓ {b2.pnl.mean():+.3f}% (n={len(b2)})" if len(b2) >= 20 else ""))
print("\n  по годам (±70/+60, все входы):")
for y in sorted(G.year.unique()):
    g = G[G.year == y]
    if len(g) >= 20:
        s = st(g)
        print(f"    {y} {YR.get(y,'?'):>6}: n={s[0]:>5,} · {s[1]:+.3f}% · безтоп10 {s[2]:+.3f}% · "
              f"монет+ {s[3]}/{s[4]}")

print(f"\n=== 4. СУРРОГАТ IAAFT без перекрытия ({len(closes)} монет × {NSUR}) ===", flush=True)


def iaaft(x, iters=10):
    n = len(x); xs = np.sort(x); amp = np.abs(np.fft.rfft(x))
    y = RNG.permutation(x)
    for _ in range(iters):
        Y = np.fft.rfft(y)
        y = np.fft.irfft(amp * np.exp(1j * np.angle(Y)), n)
        y = xs[np.argsort(np.argsort(y))]
    return y


def agg(rs):
    df = pd.DataFrame(rs, columns=["iz", "ez", "kind", "pnl", "ts", "to"])
    s = df[df.kind == "sig"].pnl; c = df[df.kind == "ctl"].pnl
    return s.mean(), s.mean() - c.mean(), len(s)


real = []
for sym, c in closes:
    real += run(c, [(70.0, 60.0)])
rn, ro, rk = agg(real)
print(f"  реальное (те же монеты): на сделку {rn:+.3f}% · над контролем {ro:+.3f} · n={rk}")
SN, SO = [], []
for s in range(NSUR):
    ts_ = time.time(); rs_ = []
    for sym, c in closes:
        v = c.to_numpy(float)
        y = iaaft(np.diff(np.log(v)))
        cs = np.empty(len(v)); cs[0] = v[0]; cs[1:] = v[0] * np.exp(np.cumsum(y))
        rs_ += run(pd.Series(cs, index=c.index), [(70.0, 60.0)])
    a, b, nn = agg(rs_)
    SN.append(a); SO.append(b)
    print(f"    суррогат {s+1:>2}/{NSUR} ({time.time()-ts_:.0f}с): {a:+.3f}% / над {b:+.3f} (n={nn})",
          flush=True)
for nm, rv, arr in [("на сделку", rn, SN), ("над контролем", ro, SO)]:
    a = np.array(arr); p95 = np.percentile(a, 95)
    print(f"  {nm}: реальное {rv:+.3f} · суррогаты мед {np.median(a):+.3f} "
          f"[{a.min():+.3f} … {a.max():+.3f}] · 95й {p95:+.3f} · перцентиль "
          f"{(a < rv).mean()*100:.0f}% → {'✅ БЬЁТ' if rv > p95 else '🔴 НЕ БЬЁТ'}")
