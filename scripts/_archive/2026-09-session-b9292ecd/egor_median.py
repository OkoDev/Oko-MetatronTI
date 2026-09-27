# -*- coding: utf-8 -*-
"""ТИП И ПЕРИОД МЕДИАНЫ (скрин настроек Егора: EMA / 43 / реакция 1) — 11.09.2026.

Егор: «с длиной медианы можно поиграть, она сейчас фикс; если я её меняю на 43,
результат меняется». На скрине: Тип медианы = EMA, Период = 43, Реакция = 1.
Я мерил SMA(34) и ноль — ни то, ни другое.

🔴 Правильный вопрос не «какой период лучший» (это выбор максимума из 20 = подгонка),
а ЕСТЬ ЛИ ПЛАТО: соседние периоды обязаны давать близкий результат. Если 43 хорошо,
а 39 и 47 плохо — параметр шумовой, и «результат меняется» означает подгонку.

Оси: тип {EMA, SMA} × период {8,13,21,26,34,39,43,47,55,68,89} × сторона.
Схема: контекст 1h (кросс WT в зоне OS/OB, жив 12 баров) → вход 15m по пересечению
медианы → выход: wt1 дошёл до противоположной зоны (touch), таймаут 300.
Контроль: полная база той же геометрии. Косты 0.35%, вход по OPEN следующего бара.
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
TF_CTX, TF_IN = 60, 15
PERIODS = [8, 13, 21, 26, 34, 39, 43, 47, 55, 68, 89]
KINDS = ["ema", "sma"]
OS_, OB_, LIFE, TIMEOUT, COST = -60.0, 60.0, 12, 300, 0.35
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))
print(f"монет {len(files)} · {TF_CTX}m→{TF_IN}m · типы {KINDS} · периоды {PERIODS}\n",
      flush=True)


def resample(d1, tf):
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


rows, base = [], []
for fi, f in enumerate(files, 1):
    sym = os.path.basename(f)[:-8]
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    dc, di = resample(d1, TF_CTX), resample(d1, TF_IN)
    if len(dc) < 500 or len(di) < 2000:
        continue
    wc = calculate_wt(dc.reset_index(drop=True))
    c1, c2 = wc["wt1"].values, wc["wt2"].values
    ccu = np.zeros(len(c1), bool); ccd = np.zeros(len(c1), bool)
    ccu[1:] = (c1[:-1] <= c2[:-1]) & (c1[1:] > c2[1:])
    ccd[1:] = (c1[:-1] >= c2[:-1]) & (c1[1:] < c2[1:])
    ct = list(dc.index + pd.Timedelta(minutes=TF_CTX))
    wi = calculate_wt(di.reset_index(drop=True))
    w1 = wi["wt1"].values
    n = len(w1)
    cl, op, ts = di.close.values, di.open.values, di.index
    touch_up, touch_dn = w1 >= OB_, w1 <= OS_

    def close_at(ii, side):
        arr = touch_up if side == 1 else touch_dn
        lim = min(ii + TIMEOUT, n - 1)
        j = np.where(arr[ii + 1:lim + 1])[0]
        return (ii + 1 + int(j[0])) if len(j) else lim

    ctx = []
    for arr, sd in ((ccu & (c1 < OS_), 1), (ccd & (c1 > OB_), -1)):
        for k in np.where(arr)[0]:
            if k + LIFE < len(ct):
                ctx.append((ct[k], ct[k + LIFE], sd))
    if not ctx:
        continue
    ctx.sort(); st = [x[0] for x in ctx]
    live_cache = {}
    for kind in KINDS:
        for p in PERIODS:
            s = pd.Series(w1)
            m = (s.ewm(span=p, adjust=False).mean() if kind == "ema"
                 else s.rolling(p, min_periods=max(2, p // 3)).mean()).to_numpy()
            up = np.concatenate(([False], (w1[:-1] <= m[:-1]) & (w1[1:] > m[1:])))
            dn = np.concatenate(([False], (w1[:-1] >= m[:-1]) & (w1[1:] < m[1:])))
            busy = {1: -1, -1: -1}
            for i in range(max(90, p + 5), n - 5):
                for sig, side in ((up[i], 1), (dn[i], -1)):
                    if not sig:
                        continue
                    key = (i, side)
                    if key not in live_cache:
                        t_now = ts[i] + pd.Timedelta(minutes=TF_IN)
                        q = bisect.bisect_right(st, t_now) - 1
                        live_cache[key] = any(
                            ctx[z][2] == side and ctx[z][0] <= t_now <= ctx[z][1]
                            for z in range(max(0, q - 4), q + 1) if 0 <= z < len(ctx))
                    if not live_cache[key]:
                        continue
                    ii = i + 1
                    if ii >= n - 3 or ii <= busy[side]:
                        continue
                    jx = close_at(ii, side)
                    busy[side] = jx
                    e = op[ii]
                    rows.append((sym, kind, p, side,
                                 (cl[jx] - e) / e * 100 * side - COST, jx - ii,
                                 int(ts[i].year)))
    for side in (1, -1):
        for ii in range(90, n - 4, 40):
            jx = close_at(ii, side)
            e = op[ii]
            base.append((sym, side, (cl[jx] - e) / e * 100 * side - COST))
    if fi % 10 == 0:
        print(f"  [{fi}/{len(files)}] {len(rows):,}", flush=True)

R = pd.DataFrame(rows, columns=["sym", "kind", "p", "side", "pnl", "bars", "year"])
B = pd.DataFrame(base, columns=["sym", "side", "pnl"])
R.to_pickle(D + r"\egor_median.pkl")
bm = B.groupby("side").pnl.mean()
print(f"\nсигналов {len(R):,} · монет {R.sym.nunique()}")
print(f"база: long {bm[1]:+.3f}% · short {bm[-1]:+.3f}%\n")

print("=== ЕСТЬ ЛИ ПЛАТО ПО ПЕРИОДУ (главный тест) ===")
for side, sn in [(1, "long"), (-1, "short")]:
    b = float(bm[side])
    print(f"\n  ── {sn} · база {b:+.3f}% ──")
    print(f"{'тип':>5} {'период':>7} {'n':>7} {'нетто':>9} {'над базой':>10} {'мед':>9} "
          f"{'WR':>6} {'баров':>6} {'безтоп10':>9} {'монет+':>7} {'лет+':>5}")
    for kind in KINDS:
        for p in PERIODS:
            g = R[(R.kind == kind) & (R.p == p) & (R.side == side)]
            if len(g) < 200:
                continue
            v = np.sort(g.pnl.values)[::-1]
            per = g.groupby("sym").pnl.mean(); yrs = g.groupby("year").pnl.mean()
            print(f"{kind:>5} {p:>7} {len(g):>7,} {g.pnl.mean():+8.3f}% "
                  f"{g.pnl.mean()-b:+9.3f}% {g.pnl.median():+8.3f}% "
                  f"{(g.pnl>0).mean()*100:5.1f}% {g.bars.median():>6.0f} "
                  f"{v[int(len(v)*.1):].mean():+8.3f}% "
                  f"{int((per>0).sum())}/{len(per)} {int((yrs>0).sum())}/{len(yrs)}")
        print()

print("=== EMA ПРОТИВ SMA (усреднение по периодам) ===")
for side, sn in [(1, "long"), (-1, "short")]:
    for kind in KINDS:
        g = R[(R.kind == kind) & (R.side == side)]
        print(f"  {sn:>5} {kind:>4}: нетто {g.pnl.mean():+.3f}% · мед "
              f"{g.pnl.median():+.3f}% · n={len(g):,}")

print("\n=== ГЛАДКОСТЬ: насколько соседние периоды похожи ===")
print("   (если разброс между соседями больше разброса по всей сетке — параметр шумовой)")
for side, sn in [(1, "long"), (-1, "short")]:
    for kind in KINDS:
        vals = []
        for p in PERIODS:
            g = R[(R.kind == kind) & (R.p == p) & (R.side == side)]
            vals.append(g.pnl.mean() if len(g) > 200 else np.nan)
        v = np.array(vals, float)
        d = np.abs(np.diff(v[~np.isnan(v)]))
        print(f"  {sn:>5} {kind:>4}: разброс по сетке {np.nanmax(v)-np.nanmin(v):.3f} п.п. · "
              f"медианный шаг между соседями {np.median(d):.3f} п.п. · "
              f"макс шаг {d.max():.3f} п.п.")
