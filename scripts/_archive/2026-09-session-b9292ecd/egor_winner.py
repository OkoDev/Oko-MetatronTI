# -*- coding: utf-8 -*-
"""🏆 ЕДИНСТВЕННАЯ ВЫЖИВШАЯ ЯЧЕЙКА ИЗ 72 — проверка на 5 годах (11.09.2026).

Из 72 политик (18 выходов × 2 ТФ × 2 стороны) положительна нетто ровно одна:
    15m LONG · вход = первый кросс wt1×wt2 вверх внутри разрешения 1h (кросс в OS)
             · выход = wt1 дошёл до противоположной зоны (>= +60)
    нетто +0.168% · контроль −0.420% · НАД +0.588 п.п. · мед +1.065% · WR 63.1%
    · 126 баров · монет+ 14/25 · безтоп10% −0.816% · лет+ 1/2 (данные 1m = 2025-26)

Здесь: 15m-кэш 2022-2026, 314 монет ⇒ появляются МЕДВЕДЬ 2022, БЫК 2023, нейтраль 2024.

🔴 Вариации параметров считаются СРАЗУ — если знак меняется внутри разумного диапазона,
   это шум, а не эффект (закон сессии). Варьируются:
     LIFE   жизнь разрешения: 6 / 12 / 24 бара часовика
     ZONE   порог зоны: ±50 / ±60 / ±70
     MA_LEN медиана: 21 / 43 / 89 (влияет только на «плюс», не на вход)
🔴 Контроль — случайный вход той же монеты с той же политикой выхода.
🔴 Обе стороны обязательно (зеркальность).
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
TIMEOUT, COST = 400, 0.35
LIFES, ZONES = [6, 12, 24], [50.0, 60.0, 70.0]
RNG = np.random.default_rng(777)
RG = {2022: "МЕДВ", 2023: "БЫК", 2024: "нейтр", 2025: "МЕДВ", 2026: "МЕДВ"}
con = sqlite3.connect("ohlcv_cache.db")
syms = [r[0] for r in con.execute(
    "select symbol from ohlcv_cache where timeframe='15m' "
    "group by symbol having count(*) > 50000 order by count(*) desc")][:314]
print(f"символов {len(syms)} · LIFE {LIFES} · ZONE {ZONES}\n", flush=True)

rows = []
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

    for ZONE in ZONES:
        zu, zd = w1 >= ZONE, w1 <= -ZONE
        czu, czd = ccu & (c1 < -ZONE), ccd & (c1 > ZONE)
        for LIFE in LIFES:
            ctx = []
            for arr, sd in ((czu, 1), (czd, -1)):
                for k in np.where(arr)[0]:
                    if k + LIFE < nc:
                        ctx.append((ct_c[k], ct_c[k + LIFE], sd))
            if not ctx:
                continue
            ctx.sort(key=lambda x: x[0])
            for (t0, t1, side) in ctx:
                i0 = int(np.searchsorted(ct_i, t0, "left"))
                i1 = int(np.searchsorted(ct_i, t1, "right")) - 1
                if i0 < 60 or i1 >= n - 5 or i1 <= i0 + 1:
                    continue
                up = cu if side == 1 else cd
                ins = [k for k in range(i0, i1 + 1) if up[k]]
                if not ins:
                    continue
                ii = ins[0] + 1
                if ii >= n - 5:
                    continue
                zone = zu if side == 1 else zd
                lim = min(ii + TIMEOUT, n - 1)
                jz = np.where(zone[ii + 1:lim + 1])[0]
                jx = ii + 1 + int(jz[0]) if len(jz) else lim
                e = op[ii]
                rows.append((sym, side, LIFE, ZONE, "sig",
                             (cl[jx] - e) / e * 100 * side - COST, jx - ii,
                             int(yr[ii]), int(len(jz) > 0)))
                rs = int(RNG.integers(60, max(61, n - TIMEOUT - 5)))
                jr = np.where(zone[rs + 1:min(rs + TIMEOUT, n - 1) + 1])[0]
                jrx = rs + 1 + int(jr[0]) if len(jr) else min(rs + TIMEOUT, n - 1)
                rows.append((sym, side, LIFE, ZONE, "ctl",
                             (cl[jrx] - op[rs]) / op[rs] * 100 * side - COST,
                             jrx - rs, int(yr[rs]), int(len(jr) > 0)))
    if fi % 40 == 0:
        print(f"  [{fi}/{len(syms)}] {len(rows):,}", flush=True)

R = pd.DataFrame(rows, columns=["sym", "side", "life", "zone", "kind", "pnl",
                                "bars", "year", "reached"])
R.to_pickle(D + r"\egor_winner.pkl")
print(f"\nзаписей {len(R):,} · монет {R.sym.nunique()}\n")


def blk(g):
    v = np.sort(g.pnl.values)[::-1]
    per = g.groupby("sym").pnl.mean()
    return v[int(len(v)*.1):].mean(), v[int(len(v)*.25):].mean(), \
        int((per > 0).sum()), len(per)


print("=== БАЗОВАЯ КОНФИГУРАЦИЯ (LIFE=12, ZONE=60) НА 5 ГОДАХ ===")
print(f"{'стор':>6} {'n':>7} {'нетто':>9} {'контр':>8} {'НАД':>8} {'мед':>9} {'WR':>6} "
      f"{'бар':>5} {'долёт':>7} {'безтоп10':>9} {'безтоп25':>9} {'монет+':>9}")
for side, sn in [(1, "long"), (-1, "short")]:
    g = R[(R["side"] == side) & (R["life"] == 12) & (R["zone"] == 60.0) &
          (R["kind"] == "sig")]
    c = R[(R["side"] == side) & (R["life"] == 12) & (R["zone"] == 60.0) &
          (R["kind"] == "ctl")]
    if len(g) < 300:
        continue
    t10, t25, sp, sn_ = blk(g)
    print(f"{sn:>6} {len(g):>7,} {g.pnl.mean():+8.3f}% {c.pnl.mean():+7.3f}% "
          f"{g.pnl.mean()-c.pnl.mean():+7.3f}% {g.pnl.median():+8.3f}% "
          f"{(g.pnl>0).mean()*100:5.1f}% {g.bars.median():>5.0f} "
          f"{g.reached.mean()*100:6.1f}% {t10:+8.3f}% {t25:+8.3f}% {sp}/{sn_}")

print("\n=== ПО ГОДАМ И РЕЖИМАМ (LIFE=12, ZONE=60) ===")
print(f"{'стор':>6} {'год':>5} {'режим':>6} {'n':>6} {'нетто':>9} {'контр':>8} "
      f"{'НАД':>8} {'мед':>9} {'безтоп10':>9} {'монет+':>9}")
for side, sn in [(1, "long"), (-1, "short")]:
    for y in sorted(R.year.unique()):
        g = R[(R["side"] == side) & (R["life"] == 12) & (R["zone"] == 60.0) &
              (R["kind"] == "sig") & (R["year"] == y)]
        c = R[(R["side"] == side) & (R["life"] == 12) & (R["zone"] == 60.0) &
              (R["kind"] == "ctl") & (R["year"] == y)]
        if len(g) < 100 or len(c) < 50:
            continue
        t10, _, sp, sn_ = blk(g)
        print(f"{sn:>6} {y:>5} {RG.get(y,'?'):>6} {len(g):>6,} {g.pnl.mean():+8.3f}% "
              f"{c.pnl.mean():+7.3f}% {g.pnl.mean()-c.pnl.mean():+7.3f}% "
              f"{g.pnl.median():+8.3f}% {t10:+8.3f}% {sp}/{sn_}")
    print()

print("=== 🔴 УСТОЙЧИВОСТЬ: ПЛАТО ИЛИ ПИК ===")
print(f"{'стор':>6} {'LIFE':>5} {'ZONE':>5} {'n':>7} {'нетто':>9} {'НАД':>8} "
      f"{'мед':>9} {'безтоп10':>9} {'монет+':>9}")
for side, sn in [(1, "long"), (-1, "short")]:
    for LIFE in LIFES:
        for ZONE in ZONES:
            g = R[(R["side"] == side) & (R["life"] == LIFE) & (R["zone"] == ZONE) &
                  (R["kind"] == "sig")]
            c = R[(R["side"] == side) & (R["life"] == LIFE) & (R["zone"] == ZONE) &
                  (R["kind"] == "ctl")]
            if len(g) < 300:
                continue
            t10, _, sp, sn_ = blk(g)
            print(f"{sn:>6} {LIFE:>5} {ZONE:>5.0f} {len(g):>7,} {g.pnl.mean():+8.3f}% "
                  f"{g.pnl.mean()-c.pnl.mean():+7.3f}% {g.pnl.median():+8.3f}% "
                  f"{t10:+8.3f}% {sp}/{sn_}")
    print()

print("=== ЗЕРКАЛЬНОСТЬ И РАЗБРОС ПО СЕТКЕ ===")
for side, sn in [(1, "long"), (-1, "short")]:
    vals = []
    for LIFE in LIFES:
        for ZONE in ZONES:
            g = R[(R["side"] == side) & (R["life"] == LIFE) & (R["zone"] == ZONE) &
                  (R["kind"] == "sig")]
            if len(g) > 300:
                vals.append(g.pnl.mean())
    if vals:
        v = np.array(vals)
        print(f"  {sn:>5}: сетка 9 конфигураций — мин {v.min():+.3f}% · "
              f"медиана {np.median(v):+.3f}% · макс {v.max():+.3f}% · "
              f"знак одинаков: {'ДА' if (v > 0).all() or (v < 0).all() else '🔴 НЕТ'}")
