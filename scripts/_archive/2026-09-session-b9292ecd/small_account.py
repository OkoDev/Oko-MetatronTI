# -*- coding: utf-8 -*-
"""💼 МАЛЕНЬКИЙ СЧЁТ НА ФЬЮЧЕРСАХ: плечо · ликвидации · 1-5 позиций · лонг И шорт (Егор, 11.09).

«ты предлагаешь схемы под большой депозит и только в лонг, а у нас деп маленький и фьючи»

ЧАСТЬ 1 — сделки (291 монета, 15m-кэш 2022-2026, одна позиция на монету):
  LONG   контекст: кросс wt1×wt2 ВВЕРХ при wt1 < −Z на ТФ контекста → вход: первый кросс ВВЕРХ на ТФ входа
         в окне 12 баров контекста → выход: wt1 ТФ входа ≥ +60
  SHORT  зеркало: кросс ВНИЗ при wt1 > +Z → первый кросс ВНИЗ → выход wt1 ≤ −60
  схемы 4h→1h · 2h→15m · 1h→15m · Z = 70 / 75 · таймаут 400 баров
  для каждой сделки: доход, MAE (худший ход против позиции до выхода), время входа/выхода.
ЧАСТЬ 2 — счёт (сложный процент, изолированная маржа):
  K слотов (1,2,3,5): маржа сделки = текущий счёт / K; объём = маржа × L (L = 1,2,3,5)
  ЛИКВИДАЦИЯ: если MAE ≤ −(1/L − 0.5%) → потеря всей маржи сделки
  СТОП s (нет, 10%, 15%): если MAE ≤ −s → выход по −s (стоп раньше ликвидации, только если s < 1/L)
  комиссия 0.35% ОТ ОБЪЁМА (с плечом — ×L от маржи); занятые слоты → сигнал пропускается («кто первый»)
Выход: годовая доходность, макс. просадка счёта, худший месяц, ликвидаций, сделок взято.
"""
import sys, os, sqlite3, warnings, itertools
warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_wt

D = os.path.dirname(os.path.abspath(__file__))
LIFE, TIMEOUT, EZ, FEE = 12, 400, 60.0, 0.35
SCHEMES = [(240, 60, "4h→1h"), (120, 15, "2h→15m"), (60, 15, "1h→15m")]
ZS = [70.0, 75.0]
PKL = os.path.join(D, "small_account_trades.pkl")

if not os.path.exists(PKL):
    con = sqlite3.connect("ohlcv_cache.db")
    syms = [r[0] for r in con.execute(
        "select symbol from ohlcv_cache where timeframe='15m' "
        "group by symbol having count(*) > 50000 order by count(*) desc")][:300]

    def rs(d, tf):
        if tf == 15:
            return d
        return d.resample(f"{tf}min", label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()

    def wt(d):
        w = calculate_wt(d.reset_index(drop=True))
        w1, w2 = w.wt1.values, w.wt2.values
        cu = np.concatenate(([False], (w1[:-1] <= w2[:-1]) & (w1[1:] > w2[1:])))
        cd = np.concatenate(([False], (w1[:-1] >= w2[:-1]) & (w1[1:] < w2[1:])))
        return w1, cu, cd

    rows = []
    for fi, sym in enumerate(syms, 1):
        d15 = pd.read_sql("select time,open,high,low,close from ohlcv_cache where symbol=? "
                          "and timeframe='15m' order by time", con, params=(sym,))
        d15["ts"] = pd.to_datetime(d15.time, unit="ms")
        d15 = d15.drop_duplicates("ts").set_index("ts")[["open", "high", "low", "close"]]
        if len(d15) < 50000:
            continue
        for ctx_tf, in_tf, nm in SCHEMES:
            dc, di = rs(d15, ctx_tf), rs(d15, in_tf)
            if len(dc) < 800 or len(di) < 2000:
                continue
            c1, ccu, ccd = wt(dc)
            w1, cu, cd = wt(di)
            nc, n = len(c1), len(w1)
            ctc = (dc.index + pd.Timedelta(minutes=ctx_tf)).values
            cti = (di.index + pd.Timedelta(minutes=in_tf)).values
            hi, lo, cl, op = di.high.values, di.low.values, di.close.values, di.open.values
            for side in (1, -1):
                ctx_sig = ccu if side == 1 else ccd
                in_sig = cu if side == 1 else cd
                zone = (w1 >= EZ) if side == 1 else (w1 <= -EZ)
                for Z in ZS:
                    mask = ctx_sig & ((c1 < -Z) if side == 1 else (c1 > Z))
                    ents = []
                    for k in np.where(mask)[0]:
                        if k < 300 or k + LIFE >= nc:
                            continue
                        i0 = int(np.searchsorted(cti, ctc[k], "left"))
                        i1 = int(np.searchsorted(cti, ctc[k + LIFE], "right")) - 1
                        if i0 < 300 or i1 >= n - 3 or i1 <= i0:
                            continue
                        ins = np.where(in_sig[i0:i1 + 1])[0]
                        if len(ins):
                            ents.append(i0 + int(ins[0]) + 1)
                    busy = -1
                    for ii in sorted(set(ents)):
                        if ii <= busy or ii >= n - 3:
                            continue
                        lim = min(ii + TIMEOUT, n - 1)
                        j = np.where(zone[ii + 1:lim + 1])[0]
                        jx = ii + 1 + int(j[0]) if len(j) else lim
                        busy = jx
                        e = op[ii]
                        pnl = (cl[jx] - e) / e * 100 * side
                        mae = ((lo[ii:jx + 1].min() - e) / e * 100) if side == 1 else \
                              ((e - hi[ii:jx + 1].max()) / e * 100)
                        rows.append((nm, sym, side, Z, di.index[ii],
                                     pd.Timestamp(cti[jx]), pnl, mae))
        if fi % 50 == 0:
            print(f"  [{fi}/{len(syms)}] сделок {len(rows):,}", flush=True)
    T = pd.DataFrame(rows, columns=["scheme", "sym", "side", "z", "t_in", "t_out", "pnl", "mae"])
    T.to_pickle(PKL)
T = pd.read_pickle(PKL)
span = (T.t_in.max() - T.t_in.min()).days / 365.25
print(f"\nсделок {len(T):,} · лет {span:.1f}\n")

print("=== ЧАСТЬ 1: СДЕЛКИ (без плеча, косты 0.35%) ===")
print(f"{'схема':>7} {'сторона':>7} {'порог':>6} {'n/год':>7} {'нетто':>9} {'мед':>8} {'WR':>6} "
      f"{'безтоп10':>9} {'MAE мед':>8} {'MAE 5%':>8} {'MAE 1%':>8}")
for (nm, side, Z), g in T.groupby(["scheme", "side", "z"]):
    net = g.pnl - FEE
    v = np.sort(net.values)[::-1]
    print(f"{nm:>7} {'LONG' if side==1 else 'SHORT':>7} {('−' if side==1 else '+')+str(int(Z)):>6} "
          f"{len(g)/span:7.0f} {net.mean():+8.3f}% {net.median():+7.3f}% {(net>0).mean()*100:5.1f}% "
          f"{v[int(len(v)*.1):].mean():+8.3f}% {g.mae.median():+7.1f}% {np.percentile(g.mae,5):+7.1f}% "
          f"{np.percentile(g.mae,1):+7.1f}%")


def account(g, K, L, stop):
    """сложный процент, изолированная маржа, K слотов, плечо L, стоп stop% (None — нет)."""
    g = g.sort_values("t_in")
    eq, peak, maxdd = 1.0, 1.0, 0.0
    open_pos, taken, liq = [], 0, 0            # (t_out, margin, result_pct_of_margin)
    month_eq = {}
    liq_edge = -(100.0 / L - 0.5)
    events = []
    for r in g.itertuples():
        # закрыть позиции, вышедшие до этого входа
        still = []
        for p in open_pos:
            if p[0] <= r.t_in:
                eq += p[1] * p[2] / 100
                peak = max(peak, eq); maxdd = min(maxdd, eq / peak - 1)
                month_eq[p[0].to_period("M")] = eq
            else:
                still.append(p)
        open_pos = still
        if len(open_pos) >= K or eq <= 0.02:
            continue
        margin = eq / K
        if stop is not None and r.mae <= -stop and -stop > liq_edge:
            res = -stop * L - FEE * L
        elif r.mae <= liq_edge:
            res = -100.0; liq += 1
        else:
            res = r.pnl * L - FEE * L
        res = max(res, -100.0)
        open_pos.append((r.t_out, margin, res)); taken += 1
    for p in sorted(open_pos):
        eq += p[1] * p[2] / 100
        peak = max(peak, eq); maxdd = min(maxdd, eq / peak - 1)
        month_eq[p[0].to_period("M")] = eq
    if not month_eq:
        return None
    me = pd.Series(month_eq).sort_index()
    mret = me.pct_change().dropna()
    cagr = (max(eq, 1e-9)) ** (1 / span) - 1
    return cagr * 100, maxdd * 100, (mret.min() * 100 if len(mret) else np.nan), liq, taken, eq


print("\n=== ЧАСТЬ 2: СЧЁТ (сложный процент; итог — во сколько раз вырос счёт за период) ===")
print(f"{'схема':>7} {'сторона':>7} {'порог':>5} {'K':>2} {'L':>2} {'стоп':>5} {'годовых':>9} "
      f"{'макс DD':>8} {'худш.мес':>9} {'ликвид.':>8} {'сделок':>7} {'итог ×':>8}")
best = []
for (nm, side, Z), g in T.groupby(["scheme", "side", "z"]):
    for K, L, stop in itertools.product([1, 2, 3, 5], [1, 2, 3, 5], [None, 10, 15]):
        r = account(g, K, L, stop)
        if not r:
            continue
        best.append((nm, side, Z, K, L, stop) + r)
B = pd.DataFrame(best, columns=["scheme", "side", "z", "K", "L", "stop", "cagr", "dd", "wm", "liq",
                                "taken", "mult"])
B.to_pickle(os.path.join(D, "small_account_grid.pkl"))
for (nm, side, Z), g in B.groupby(["scheme", "side", "z"]):
    g = g.copy()
    g["score"] = g.cagr / g.dd.abs().clip(lower=5)
    top = g.sort_values("score", ascending=False).head(4)
    safe = g[g.dd > -30].sort_values("cagr", ascending=False).head(2)
    for _, r in pd.concat([top, safe]).drop_duplicates().iterrows():
        print(f"{nm:>7} {'LONG' if side==1 else 'SHORT':>7} {('−' if side==1 else '+')+str(int(Z)):>5} "
              f"{int(r.K):>2} {int(r.L):>2} {('нет' if pd.isna(r.stop) else str(int(r.stop))+'%'):>5} "
              f"{r.cagr:+8.1f}% {r.dd:+7.1f}% {r.wm:+8.1f}% {int(r.liq):>8} {int(r.taken):>7} "
              f"{r.mult:>7.2f}×")
    print()
print("=== ПЛЕЧО И ЛИКВИДАЦИИ: 4h→1h LONG −75, K=2, без стопа ===")
g = B[(B.scheme == "4h→1h") & (B.side == 1) & (B.z == 75) & (B.K == 2) & (B.stop.isna())]
for _, r in g.sort_values("L").iterrows():
    print(f"  плечо ×{int(r.L)}: годовых {r.cagr:+.1f}% · DD {r.dd:+.1f}% · ликвидаций {int(r.liq)} · итог {r.mult:.2f}×")
