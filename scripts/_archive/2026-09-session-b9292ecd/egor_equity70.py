# -*- coding: utf-8 -*-
"""💰 ЭКВИТИ ЛУЧШЕЙ КОНФИГУРАЦИИ БЕЗ ПЕРЕКРЫТИЯ (11.09.2026).

Конфигурация прошла суррогат (перцентиль 100% по нетто и превышению над контролем):
    LONG · вход: кросс WT вверх при wt1 < −70 на 1h → первый кросс вверх на 15m в окне 12 баров
         · выход: wt1 на 15m дошёл до +60
    среднее по сделкам +1.037% · над контролем +1.339 · 5/5 лет в плюсе

🔴 НО эквити для входа ±70 НЕ считалась, а для ±60 показала провал перекрытия:
   среднее по сделкам +0.155%, при одной позиции на монету −0.045% на сделку.
   Долгая перепроданность рождает несколько разрешений подряд ⇒ одно движение
   засчитывается несколько раз, и это как раз хорошие движения.

Здесь:
  · ОДНА позиция на монету, новые сигналы игнорируются, пока позиция открыта
  · сделки помечены: первое разрешение в серии или повтор внутри уже открытой позиции
  · контроль: случайные входы БЕЗ перекрытия, та же политика выхода, то же число сделок
  · по годам, просадка эквити, охват монет, хрупкость
  · сетка вход {60, 65, 70, 75} × выход {60, 70} — чтобы видеть, плато это или пик
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
ENTRY_Z, EXIT_Z = [60.0, 65.0, 70.0, 75.0], [60.0, 70.0]
RNG = np.random.default_rng(90210)
RG = {2022: "МЕДВ", 2023: "БЫК", 2024: "нейтр", 2025: "МЕДВ", 2026: "МЕДВ"}
con = sqlite3.connect("ohlcv_cache.db")
syms = [r[0] for r in con.execute(
    "select symbol from ohlcv_cache where timeframe='15m' "
    "group by symbol having count(*) > 50000 order by count(*) desc")][:300]
print(f"символов {len(syms)} · вход {ENTRY_Z} · выход {EXIT_Z} · только LONG\n", flush=True)

trades, eq_rows = [], []
for fi, sym in enumerate(syms, 1):
    d = pd.read_sql("select time,open,high,low,close from ohlcv_cache "
                    "where symbol=? and timeframe='15m' order by time",
                    con, params=(sym,))
    if len(d) < 50000:
        continue
    d["ts"] = pd.to_datetime(d.time, unit="ms")
    di = d.drop_duplicates("ts").set_index("ts")
    dc = di.resample("60min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    if len(dc) < 500 or len(di) < 2000:
        continue
    wc = calculate_wt(dc.reset_index(drop=True))
    c1, c2 = wc["wt1"].values, wc["wt2"].values
    nc = len(c1)
    ccu = np.zeros(nc, bool)
    ccu[1:] = (c1[:-1] <= c2[:-1]) & (c1[1:] > c2[1:])
    ct_c = (dc.index + pd.Timedelta(minutes=60)).values
    wi = calculate_wt(di.reset_index(drop=True))
    w1, w2 = wi["wt1"].values, wi["wt2"].values
    n = len(w1)
    cu = np.zeros(n, bool)
    cu[1:] = (w1[:-1] <= w2[:-1]) & (w1[1:] > w2[1:])
    cl, op, lo = di.close.values, di.open.values, di.low.values
    ct_i = (di.index + pd.Timedelta(minutes=15)).values
    yr = di.index.year.values

    for IZ in ENTRY_Z:
        ctx = [(ct_c[k], ct_c[k + LIFE]) for k in np.where(ccu & (c1 < -IZ))[0]
               if k + LIFE < nc]
        entries = []
        for (t0, t1) in ctx:
            i0 = int(np.searchsorted(ct_i, t0, "left"))
            i1 = int(np.searchsorted(ct_i, t1, "right")) - 1
            if i0 < 60 or i1 >= n - 5 or i1 <= i0:
                continue
            ins = np.where(cu[i0:i1 + 1])[0]
            if len(ins):
                ii = i0 + int(ins[0]) + 1
                if ii < n - 5:
                    entries.append(ii)
        entries = sorted(set(entries))
        for EZ in EXIT_Z:
            zone = w1 >= EZ

            def exit_at(ii):
                lim = min(ii + TIMEOUT, n - 1)
                j = np.where(zone[ii + 1:lim + 1])[0]
                return (ii + 1 + int(j[0])) if len(j) else lim

            busy, total, taken, occ, curve = -1, 0.0, 0, 0, []
            for ii in entries:
                jx = exit_at(ii)
                pnl = (cl[jx] - op[ii]) / op[ii] * 100 - COST
                repeat = int(ii <= busy)
                mae = (lo[ii:jx + 1].min() - op[ii]) / op[ii] * 100
                trades.append((sym, IZ, EZ, pnl, jx - ii, int(yr[ii]), repeat, mae))
                if not repeat:
                    total += pnl; taken += 1; occ += jx - ii; busy = jx
                    curve.append(total)
            # контроль: столько же случайных неперекрывающихся входов
            ctl_total, ctl_n, cb = 0.0, 0, -1
            cand = np.sort(RNG.integers(60, max(61, n - TIMEOUT - 5), size=taken * 4))
            for ii in cand:
                if ctl_n >= taken:
                    break
                if ii <= cb:
                    continue
                jx = exit_at(int(ii))
                ctl_total += (cl[jx] - op[ii]) / op[ii] * 100 - COST
                ctl_n += 1; cb = jx
            if curve:
                cv = np.array(curve)
                dd = float((cv - np.maximum.accumulate(cv)).min())
            else:
                dd = 0.0
            eq_rows.append((sym, IZ, EZ, total, taken, occ / n, dd, ctl_total, ctl_n))
    if fi % 50 == 0:
        print(f"  [{fi}/{len(syms)}] сделок {len(trades):,}", flush=True)

T = pd.DataFrame(trades, columns=["sym", "iz", "ez", "pnl", "bars", "year", "repeat", "mae"])
E = pd.DataFrame(eq_rows, columns=["sym", "iz", "ez", "total", "taken", "occ", "dd",
                                   "ctl_total", "ctl_n"])
T.to_pickle(D + r"\egor_eq70_trades.pkl"); E.to_pickle(D + r"\egor_eq70_equity.pkl")
print(f"\nсделок {len(T):,} · монет {T.sym.nunique()}\n")

print("=== ПЕРЕКРЫТИЕ: сколько сделок — повторы внутри уже открытой позиции ===")
print(f"{'вход':>5} {'выход':>6} {'всего':>7} {'повторы':>8} {'первые: нетто':>14} "
      f"{'повторы: нетто':>15} {'всё среднее':>12}")
for IZ in ENTRY_Z:
    for EZ in EXIT_Z:
        g = T[(T["iz"] == IZ) & (T["ez"] == EZ)]
        if len(g) < 100:
            continue
        f_ = g[g["repeat"] == 0]; r_ = g[g["repeat"] == 1]
        print(f"{IZ:>5.0f} {EZ:>6.0f} {len(g):>7,} {len(r_)/len(g)*100:7.1f}% "
              f"{f_.pnl.mean():+13.3f}% "
              f"{(r_.pnl.mean() if len(r_) else float('nan')):+14.3f}% "
              f"{g.pnl.mean():+11.3f}%")

print("\n=== 💰 ЭКВИТИ: ОДНА ПОЗИЦИЯ НА МОНЕТУ (без перекрытия) против КОНТРОЛЯ ===")
print(f"{'вход':>5} {'выход':>6} {'монет':>6} {'сделок/мон':>11} {'сумма%/мон':>11} "
      f"{'на сделку':>10} {'контроль/сд':>12} {'НАД':>8} {'в рынке':>8} "
      f"{'мед DD':>8} {'монет+':>9}")
for IZ in ENTRY_Z:
    for EZ in EXIT_Z:
        g = E[(E["iz"] == IZ) & (E["ez"] == EZ) & (E["taken"] > 0)]
        if len(g) < 30:
            continue
        per_trade = g.total.sum() / g.taken.sum()
        ctl_trade = g.ctl_total.sum() / max(g.ctl_n.sum(), 1)
        print(f"{IZ:>5.0f} {EZ:>6.0f} {len(g):>6} {g.taken.mean():>11.1f} "
              f"{g.total.mean():+10.1f}% {per_trade:+9.3f}% {ctl_trade:+11.3f}% "
              f"{per_trade-ctl_trade:+7.3f}% {g.occ.mean()*100:7.1f}% "
              f"{g.dd.median():+7.1f}% {int((g.total>0).sum())}/{len(g)}")

print("\n=== ЛУЧШАЯ ПО ЭКВИТИ: ПО ГОДАМ (только первые, без повторов) ===")
best = None
for IZ in ENTRY_Z:
    for EZ in EXIT_Z:
        g = E[(E["iz"] == IZ) & (E["ez"] == EZ) & (E["taken"] > 0)]
        if len(g) < 30:
            continue
        pt = g.total.sum() / g.taken.sum()
        if best is None or pt > best[0]:
            best = (pt, IZ, EZ)
_, biz, bez = best
print(f"  вход ±{biz:.0f} · выход +{bez:.0f}")
g0 = T[(T["iz"] == biz) & (T["ez"] == bez) & (T["repeat"] == 0)]
print(f"{'год':>7} {'режим':>6} {'n':>6} {'нетто':>9} {'мед':>9} {'WR':>6} "
      f"{'безтоп10':>9} {'медиана MAE':>12} {'монет+':>9}")
for y in sorted(g0.year.unique()):
    g = g0[g0.year == y]
    if len(g) < 30:
        continue
    v = np.sort(g.pnl.values)[::-1]
    per = g.groupby("sym").pnl.mean()
    print(f"{y:>7} {RG.get(y,'?'):>6} {len(g):>6,} {g.pnl.mean():+8.3f}% "
          f"{g.pnl.median():+8.3f}% {(g.pnl>0).mean()*100:5.1f}% "
          f"{v[int(len(v)*.1):].mean():+8.3f}% {g.mae.median():+11.2f}% "
          f"{int((per>0).sum())}/{len(per)}")
v = np.sort(g0.pnl.values)[::-1]
print(f"\n  всё окно (первые): n={len(g0):,} · нетто {g0.pnl.mean():+.3f}% · "
      f"мед {g0.pnl.median():+.3f}% · безтоп10 {v[int(len(v)*.1):].mean():+.3f}% · "
      f"безтоп25 {v[int(len(v)*.25):].mean():+.3f}% · медиана MAE {g0.mae.median():+.2f}% · "
      f"худший MAE 5% {np.percentile(g0.mae, 5):+.2f}%")
