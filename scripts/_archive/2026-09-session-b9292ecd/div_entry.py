# -*- coding: utf-8 -*-
"""👁️ ГИПОТЕЗА С ГРАФИКОВ: крупные ходы начинаются после R+/H+ в перепроданности на 1h (11.09).

Глазами на BTC/GRT/SOL (1h, 15.08-11.09): рост начинался после R+ или H+ в зоне OS;
на ETH (боковик) чётких R+ нет — и крупного хода нет. Правило Егора «каждый кросс → встречный»
дало ноль грязными на всех LTF (10.5 млн отрезков) ⇒ деньги не в отрезке до встречного кросса.

ВХОД   на 1h: бычья дивергенция OkoTrend (эталон: фрактал 2/2 на wt1 против ОДНОГО предыдущего)
       варианты: R+ (регулярная) · H+ (скрытая) · любая; условие зоны: wt1 фрактала < −60 / < −30 / любая
       вход по open бара ПОСЛЕ подтверждения фрактала (флаг ставится на баре подтверждения).
ВЫХОД  a) wt1 1h ≥ +60 (зона OB) · b) встречный кросс 1h · c) медвежья дивергенция R− на 1h
       предохранитель 400 баров.
Зеркало: R−/H− в OB → шорт.
Контроль: случайный бар той же монеты, та же политика выхода. Одна позиция на монету.
Данные: 15m-кэш 2022-2026 → 1h, 291 монета. Разрез по годам.
"""
import sys, os, sqlite3, warnings
warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_wt
from core.calculators.combinator_core import _wtx_divergences

D = os.path.dirname(os.path.abspath(__file__))
COST, TIMEOUT = 0.35, 400
RNG = np.random.default_rng(99)
YR = {2022: "МЕДВ", 2023: "БЫК", 2024: "нейтр", 2025: "МЕДВ", 2026: "МЕДВ"}
con = sqlite3.connect("ohlcv_cache.db")
syms = [r[0] for r in con.execute(
    "select symbol from ohlcv_cache where timeframe='15m' "
    "group by symbol having count(*) > 50000 order by count(*) desc")][:300]

rows = []
for fi, sym in enumerate(syms, 1):
    d = pd.read_sql("select time,open,high,low,close from ohlcv_cache where symbol=? "
                    "and timeframe='15m' order by time", con, params=(sym,))
    d["ts"] = pd.to_datetime(d.time, unit="ms")
    d = d.drop_duplicates("ts").set_index("ts")
    h = d.resample("60min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    if len(h) < 2000:
        continue
    w = calculate_wt(h.reset_index(drop=True))
    w1, w2 = w.wt1.values, w.wt2.values
    n = len(w1)
    x = w1 - w2
    cu = np.concatenate(([False], (x[:-1] <= 0) & (x[1:] > 0)))
    cd = np.concatenate(([False], (x[:-1] >= 0) & (x[1:] < 0)))
    br, sr, bh, sh = _wtx_divergences(w1, h.low.values, h.high.values)
    op, cl = h.open.values, h.close.values
    yr = h.index.year.values
    fr_wt = np.concatenate(([np.nan, np.nan], w1[:-2]))     # wt1 на центре фрактала (i-2)

    def exit_at(ii, side, mode):
        lim = min(ii + TIMEOUT, n - 1)
        if mode == "zone":
            arr = (w1 >= 60) if side == 1 else (w1 <= -60)
        elif mode == "cross":
            arr = cd if side == 1 else cu
        else:
            arr = sr if side == 1 else br
        j = np.where(arr[ii + 1:lim + 1])[0]
        return ii + 1 + int(j[0]) if len(j) else lim

    for side in (1, -1):
        for kind in ("R", "H", "any"):
            if side == 1:
                sig = br if kind == "R" else (bh if kind == "H" else (br | bh))
            else:
                sig = sr if kind == "R" else (sh if kind == "H" else (sr | sh))
            for zone in (60, 30, 0):
                if zone:
                    zc = (fr_wt < -zone) if side == 1 else (fr_wt > zone)
                else:
                    zc = np.ones(n, bool)
                ents = np.where(sig & zc)[0]
                ents = ents[(ents > 400) & (ents < n - 3)]
                for mode in ("zone", "cross", "div"):
                    busy, taken = -1, 0
                    for i in ents:
                        ii = i + 1
                        if ii <= busy:
                            continue
                        jx = exit_at(ii, side, mode)
                        busy = jx; taken += 1
                        rows.append((sym, side, kind, zone, mode, "sig",
                                     (cl[jx] - op[ii]) / op[ii] * 100 * side - COST,
                                     jx - ii, int(yr[ii])))
                    cb, cn = -1, 0
                    for ii in np.sort(RNG.integers(401, n - 3, size=max(taken, 1) * 3)):
                        if cn >= taken:
                            break
                        if ii <= cb:
                            continue
                        jx = exit_at(int(ii), side, mode)
                        cb = jx; cn += 1
                        rows.append((sym, side, kind, zone, mode, "ctl",
                                     (cl[jx] - op[ii]) / op[ii] * 100 * side - COST,
                                     jx - ii, int(yr[ii])))
    if fi % 50 == 0:
        print(f"  [{fi}/{len(syms)}] {len(rows):,}", flush=True)

R = pd.DataFrame(rows, columns=["sym", "side", "kind", "zone", "mode", "k", "pnl", "bars", "year"])
R.to_pickle(os.path.join(D, "div_entry.pkl"))
print(f"\nзаписей {len(R):,} · монет {R.sym.nunique()}\n")
MN = {"zone": "до зоны ±60", "cross": "до встречного кросса", "div": "до встречной дивергенции"}
KN = {"R": "R", "H": "H", "any": "R или H"}
print(f"{'сторона':>7} {'див':>7} {'зона':>6} {'выход':>24} {'n':>6} {'нетто':>9} {'контр':>8} "
      f"{'НАД':>8} {'мед':>8} {'WR':>6} {'бар':>5} {'безтоп10':>9} {'монет+':>9} {'лет+':>5}")
for side, sn in [(1, "LONG"), (-1, "SHORT")]:
    for kind in ("R", "H", "any"):
        for zone in (60, 30, 0):
            for mode in ("zone", "cross", "div"):
                g = R[(R.side == side) & (R.kind == kind) & (R.zone == zone) & (R["mode"] == mode) & (R.k == "sig")]
                c = R[(R.side == side) & (R.kind == kind) & (R.zone == zone) & (R["mode"] == mode) & (R.k == "ctl")]
                if len(g) < 100:
                    continue
                v = np.sort(g.pnl.values)[::-1]
                per = g.groupby("sym").pnl.mean(); yrs = g.groupby("year").pnl.mean()
                zl = f"<−{zone}" if side == 1 and zone else (f">+{zone}" if zone else "любая")
                print(f"{sn:>7} {KN[kind]+('+' if side==1 else '−'):>7} {zl:>6} {MN[mode]:>24} {len(g):>6,} "
                      f"{g.pnl.mean():+8.3f}% {c.pnl.mean():+7.3f}% {g.pnl.mean()-c.pnl.mean():+7.3f}% "
                      f"{g.pnl.median():+7.3f}% {(g.pnl>0).mean()*100:5.1f}% {g.bars.median():>5.0f} "
                      f"{v[int(len(v)*.1):].mean():+8.3f}% {int((per>0).sum())}/{len(per)} "
                      f"{int((yrs>0).sum())}/{len(yrs)}")
        print()
print("=== ПО ГОДАМ: LONG R+/H+ в OS (<−60), выход до зоны ===")
for kind in ("R", "H", "any"):
    g = R[(R.side == 1) & (R.kind == kind) & (R.zone == 60) & (R["mode"] == "zone") & (R.k == "sig")]
    print(f"  {KN[kind]}+: " + " · ".join(f"{y} {YR.get(y,'?')} {g[g.year==y].pnl.mean():+.2f}% (n={int((g.year==y).sum())})"
                                      for y in sorted(g.year.unique())))
