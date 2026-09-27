# -*- coding: utf-8 -*-
"""🛡️ ЧАСТОТА И БЕЗОПАСНОСТЬ: БУ · встречный кросс · TSL · частичная фиксация · стоп по времени
· ПОРТФЕЛЬ С ЛИМИТОМ СЛОТОВ (Егор, 11.09.2026).

Схемы (одна позиция на монету, 291 монета, 15m-кэш 2022-01…2026-07):
  4h→1h   контекст 4h: кросс вверх при wt1<−70 → вход 1h (первый кросс вверх в окне 12 баров 4h)
  1h→15m  контекст 1h → вход 15m
  базовый выход: wt1 на ТФ входа ≥ +60, таймаут 400 баров.
Политики управления позицией симулируются по барам ТФ входа (high/low); внутри бара стоп раньше
цели (консервативно). Косты 0.35% на круг; у частичной фиксации — 0.35% на каждую половину
(половина кост при выходе, ×2 выхода ⇒ итого те же 0.35% на весь объём + ничего лишнего).

Портфель: сделки обеих схем по времени входа; лимит S слотов (каждый = 1/S счёта); если слоты
заняты — сделка пропускается; лимит новых входов в сутки L. Эквити по времени ВЫХОДА.
"""
import sys, os, sqlite3, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_wt

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
IZ, EZ, LIFE, TIMEOUT, COST = 70.0, 60.0, 12, 400, 0.35
SCHEMES = [(240, 60, "4h→1h"), (60, 15, "1h→15m")]
POL = ["база (зона +60)", "жёсткий стоп ATR×12",
       "БУ после +1%", "БУ после +2%", "БУ после +3%", "БУ после +5%",
       "БУ после 1 ATR", "БУ после 2 ATR", "БУ после 3 ATR",
       "БУ по встречному кроссу", "TSL 2ATR с +2%", "TSL 3ATR с +2%", "TSL 5ATR с +2%",
       "½ на +2%, остаток БУ", "½ на +3%, остаток БУ",
       "время: 12 баров", "время: 24 бара", "время: 48 баров"]
con = sqlite3.connect("ohlcv_cache.db")
syms = [r[0] for r in con.execute(
    "select symbol from ohlcv_cache where timeframe='15m' "
    "group by symbol having count(*) > 50000 order by count(*) desc")][:300]


def load(sym):
    d = pd.read_sql("select time,open,high,low,close from ohlcv_cache where symbol=? "
                    "and timeframe='15m' order by time", con, params=(sym,))
    d["ts"] = pd.to_datetime(d.time, unit="ms")
    return d.drop_duplicates("ts").set_index("ts")[["open", "high", "low", "close"]]


def rs(d, tf):
    if tf == 15:
        return d
    return d.resample(f"{tf}min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()


def wt(d):
    w = calculate_wt(d.reset_index(drop=True))
    w1, w2 = w["wt1"].values, w["wt2"].values
    cu = np.zeros(len(w1), bool); cd = np.zeros(len(w1), bool)
    cu[1:] = (w1[:-1] <= w2[:-1]) & (w1[1:] > w2[1:])
    cd[1:] = (w1[:-1] >= w2[:-1]) & (w1[1:] < w2[1:])
    return w1, cu, cd


def atr_pct(h, l, c, p=14):
    prev = np.concatenate(([c[0]], c[:-1]))
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev), np.abs(l - prev)))
    return pd.Series(tr / c * 100).rolling(p, min_periods=5).mean().to_numpy()


def simulate(e, a, hi, lo, cl, w1, cd, ii, lim, zone_j):
    """вернуть список (pnl%, bar_exit) по политикам POL. zone_j — бар выхода по зоне или lim."""
    out = []
    ret = lambda px: (px - e) / e * 100
    base_j = zone_j
    out.append((ret(cl[base_j]) - COST, base_j))                              # база
    # жёсткий стоп ATR×12
    sp = e * (1 - 12 * a / 100)
    h = np.where(lo[ii:base_j + 1] <= sp)[0]
    out.append(((ret(sp) if len(h) else ret(cl[base_j])) - COST,
                ii + int(h[0]) if len(h) else base_j))
    # БУ по ходу в % и в ATR
    for trig in [e * 1.01, e * 1.02, e * 1.03, e * 1.05,
                 e * (1 + a / 100), e * (1 + 2 * a / 100), e * (1 + 3 * a / 100)]:
        armed, res = False, None
        for k in range(ii, base_j + 1):
            if armed and lo[k] <= e:
                res = (0.0 - COST, k); break
            if hi[k] >= trig:
                armed = True
        out.append(res if res else (ret(cl[base_j]) - COST, base_j))
    # БУ по встречному кроссу (если в этот момент в плюсе)
    armed, res = False, None
    for k in range(ii + 1, base_j + 1):
        if armed and lo[k] <= e:
            res = (0.0 - COST, k); break
        if cd[k] and cl[k] > e:
            armed = True
    out.append(res if res else (ret(cl[base_j]) - COST, base_j))
    # TSL chandelier k·ATR, включается после +2%
    for m in (2, 3, 5):
        act, ext, res = False, e, None
        for k in range(ii, base_j + 1):
            if act and lo[k] <= ext * (1 - m * a / 100):
                res = (ret(ext * (1 - m * a / 100)) - COST, k); break   # чистый TSL, без БУ
            if hi[k] >= e * 1.02:
                act = True
            ext = max(ext, hi[k])
        out.append(res if res else (ret(cl[base_j]) - COST, base_j))
    # половина на +x%, остаток в БУ до зоны
    for x in (2, 3):
        tp, half, res = e * (1 + x / 100), None, None
        for k in range(ii, base_j + 1):
            if half is None:
                if hi[k] >= tp:
                    half = k
                continue
            if lo[k] <= e:
                res = (0.5 * x + 0.5 * 0.0 - COST, k); break
        if half is None:
            out.append((ret(cl[base_j]) - COST, base_j))
        elif res:
            out.append(res)
        else:
            out.append((0.5 * x + 0.5 * ret(cl[base_j]) - COST, base_j))
    # стоп по времени: если через N баров не в плюсе — выход
    for nb in (12, 24, 48):
        k = ii + nb
        if k < base_j and cl[k] <= e:
            out.append((ret(cl[k]) - COST, k))
        else:
            out.append((ret(cl[base_j]) - COST, base_j))
    return out


trades = []
for fi, sym in enumerate(syms, 1):
    d15 = load(sym)
    if len(d15) < 50000:
        continue
    for ctx_tf, in_tf, nm in SCHEMES:
        dc, di = rs(d15, ctx_tf), rs(d15, in_tf)
        if len(dc) < 200 or len(di) < 800:
            continue
        c1, ccu, _ = wt(dc)
        w1, cu, cd = wt(di)
        nc, n = len(c1), len(w1)
        ctc = (dc.index + pd.Timedelta(minutes=ctx_tf)).values
        cti = (di.index + pd.Timedelta(minutes=in_tf)).values
        hi, lo, cl, op = di.high.values, di.low.values, di.close.values, di.open.values
        A = atr_pct(hi, lo, cl)
        ents = []
        for k in np.where(ccu & (c1 < -IZ))[0]:
            if k + LIFE >= nc:
                continue
            i0 = int(np.searchsorted(cti, ctc[k], "left"))
            i1 = int(np.searchsorted(cti, ctc[k + LIFE], "right")) - 1
            if i0 < 60 or i1 >= n - 3 or i1 <= i0:
                continue
            ins = np.where(cu[i0:i1 + 1])[0]
            if len(ins):
                ents.append(i0 + int(ins[0]) + 1)
        busy = -1
        for ii in sorted(set(x for x in ents if x < n - 3)):
            if ii <= busy or not np.isfinite(A[ii - 1]):
                continue
            lim = min(ii + TIMEOUT, n - 1)
            j = np.where(w1[ii + 1:lim + 1] >= EZ)[0]
            zj = ii + 1 + int(j[0]) if len(j) else lim
            busy = zj
            res = simulate(op[ii], A[ii - 1], hi, lo, cl, w1, cd, ii, lim, zj)
            t_in = di.index[ii]
            for pi, (pnl, jx) in enumerate(res):
                trades.append((nm, sym, pi, float(pnl), t_in, pd.Timestamp(cti[jx])))
    if fi % 50 == 0:
        print(f"  [{fi}/{len(syms)}] {len(trades):,}", flush=True)

T = pd.DataFrame(trades, columns=["scheme", "sym", "pol", "pnl", "t_in", "t_out"])
T.to_pickle(D + r"\safety.pkl")
span_y = (T.t_in.max() - T.t_in.min()).days / 365.25
print(f"\nзаписей {len(T):,} · лет {span_y:.1f}\n")


def pstats(g):
    v = np.sort(g.pnl.values)[::-1]
    return len(g), g.pnl.mean(), g.pnl.median(), (g.pnl > 0).mean(), v[int(len(v) * .1):].mean()


print("=== НА УРОВНЕ СДЕЛКИ ===")
for nm in [s[2] for s in SCHEMES]:
    print(f"\n  ── {nm} ──")
    print(f"{'политика':>26} {'n':>6} {'%/сделка':>9} {'мед':>8} {'WR':>6} {'безтоп10':>9} "
          f"{'удерж ч (мед)':>14}")
    for pi, pn in enumerate(POL):
        g = T[(T.scheme == nm) & (T.pol == pi)]
        if not len(g):
            continue
        s = pstats(g)
        hold = ((g.t_out - g.t_in).dt.total_seconds() / 3600).median()
        print(f"{pn:>26} {s[0]:>6,} {s[1]:+8.3f}% {s[2]:+7.3f}% {s[3]*100:5.1f}% {s[4]:+8.3f}% "
              f"{hold:>14.0f}")


def portfolio(g, S, L):
    """g: сделки (одна политика, одна или обе схемы). Возврат: год. доходность, макс DD, худший
    месяц, взято сделок, доля пропущенных."""
    g = g.sort_values("t_in")
    open_ends, eq_events, taken, day_cnt = [], [], 0, {}
    for r in g.itertuples():
        open_ends = [t for t in open_ends if t > r.t_in]
        dkey = r.t_in.normalize()
        if len(open_ends) >= S or day_cnt.get(dkey, 0) >= L:
            continue
        open_ends.append(r.t_out); day_cnt[dkey] = day_cnt.get(dkey, 0) + 1
        eq_events.append((r.t_out, r.pnl / S)); taken += 1
    if not eq_events:
        return None
    e = pd.Series([x[1] for x in eq_events], index=[x[0] for x in eq_events]).sort_index()
    cum = e.cumsum()
    dd = (cum - cum.cummax()).min()
    mon = e.resample("ME").sum()
    return cum.iloc[-1] / span_y, dd, mon.min(), taken, 1 - taken / len(g), (mon > 0).mean()


print("\n=== ПОРТФЕЛЬ: лимит слотов S и новых входов в сутки L (эквити по времени выхода) ===")
print(f"{'схема':>14} {'политика':>26} {'S':>4} {'L':>4} {'годовых':>9} {'макс DD':>9} "
      f"{'худш. мес':>10} {'взято':>7} {'пропущено':>10} {'мес+':>6}")
key_pols = [0, 1, 3, 5, 8, 9, 11, 13, 16]
for scope in ["4h→1h", "1h→15m", "обе"]:
    G0 = T if scope == "обе" else T[T.scheme == scope]
    for pi in key_pols:
        g = G0[G0.pol == pi]
        for S, L in [(20, 10**9), (30, 10**9), (50, 10**9), (30, 10), (30, 5), (20, 5)]:
            r = portfolio(g, S, L)
            if not r:
                continue
            print(f"{scope:>14} {POL[pi]:>26} {S:>4} {'∞' if L > 10**8 else L:>4} "
                  f"{r[0]:+8.1f}% {r[1]:+8.1f}% {r[2]:+9.1f}% {r[3]:>7,} {r[4]*100:9.0f}% "
                  f"{r[5]*100:5.0f}%")
        print()
