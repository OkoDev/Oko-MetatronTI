# -*- coding: utf-8 -*-
"""КАРТА ЛИКВИДАЦИЙ: реконструкция позиционирования из объёма и плеча (10.09.2026).

Идея Егора: цена ходит за ликвидациями, и уровни ликвидации КЛАСТЕРНЫ — позиции
набираются в зонах (где объём), а не в точке, и с несколькими популярными плечами.
Кластер там, где проекции от разных зон с разными плечами накладываются.

Отличие от нашего `etl_liquidity`: тот ищет кластеры swing-точек, то есть СТОПЫ,
расположенные СТРУКТУРНО (за экстремумами). Ликвидации расположены АРИФМЕТИЧЕСКИ —
на доле 1/n от цены входа. Второго механизма в проекте нет вообще.

🔴 Это РЕКОНСТРУКЦИЯ: реального OI и распределения плеч мы не знаем, объём говорит
где торговали, но не сколько позиций осталось. Проверяется только предсказательность.

Метод:
  1. профиль объёма по ценовым уровням за окно назад (что торговалось и сколько)
  2. проекция каждого уровня на точки ликвидации для плеч из конфига проекта
  3. сложение проекций → карта плотности
  4. проверка: тянется ли цена к пикам карты сильнее, чем к контрольным уровням
"""
import os, sys, glob
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
TF = 15                      # сетка расчёта, мин
LOOKBACK = 96                # окно профиля объёма: 96 баров 15m = сутки
BINS = 200                   # ценовых корзин в профиле
LEVS = [5, 10, 20, 30]       # плечи из config.yaml проекта
MM = 0.005                   # поддерживающая маржа, доля
FWD = 96                     # горизонт проверки: сутки
NSYM = 20
RNG = np.random.default_rng(20260910)
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))[:NSYM]
print(f"монет: {len(files)} · сетка {TF}m · профиль {LOOKBACK} баров · плечи {LEVS}\n",
      flush=True)

rows = []
for fi, f in enumerate(files, 1):
    sym = os.path.basename(f)[:-8]
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    r = d1.resample(f"{TF}min", label="left", closed="left")
    d = pd.DataFrame({"high": r["high"].max(), "low": r["low"].min(),
                      "close": r["close"].last(), "vol": r["volume"].sum()}).dropna()
    hi, lo, cl, vol = (d["high"].values, d["low"].values,
                       d["close"].values, d["vol"].values)
    n = len(d)
    if n < LOOKBACK + FWD + 100:
        continue
    tp = (hi + lo + cl) / 3.0
    for t in range(LOOKBACK, n - FWD, 4):        # шаг 4 бара, чтобы не копить дубли
        p0 = cl[t]
        s = t - LOOKBACK
        vp_price = tp[s:t]; vp_vol = vol[s:t]
        if vp_vol.sum() <= 0:
            continue
        # ── карта ликвидаций: проекции зон набора на уровни ликвидации
        lvl, wgt = [], []
        for L_ in LEVS:
            step = 1.0 / L_ - MM
            lvl.append(vp_price * (1.0 + step))   # ликвидации ШОРТОВ (выше цены входа)
            wgt.append(vp_vol)
            lvl.append(vp_price * (1.0 - step))   # ликвидации ЛОНГОВ (ниже)
            wgt.append(vp_vol)
        lvl = np.concatenate(lvl); wgt = np.concatenate(wgt)
        band_lo, band_hi = p0 * 0.90, p0 * 1.10
        m = (lvl >= band_lo) & (lvl <= band_hi)
        if m.sum() < 50:
            continue
        edges = np.linspace(band_lo, band_hi, BINS + 1)
        dens, _ = np.histogram(lvl[m], bins=edges, weights=wgt[m])
        if dens.sum() <= 0:
            continue
        dens = dens / dens.sum()
        centers = (edges[:-1] + edges[1:]) / 2
        above = centers > p0
        below = ~above
        if not above.any() or not below.any():
            continue
        # ближайший ПИК карты сверху и снизу (локальный максимум плотности)
        def peak(mask):
            idx = np.where(mask)[0]
            if len(idx) < 3:
                return None
            k = idx[np.argmax(dens[idx])]
            return centers[k], dens[k]
        pu = peak(above); pd_ = peak(below)
        if pu is None or pd_ is None:
            continue
        # контроль: случайный уровень в той же полосе и на том же расстоянии
        du = (pu[0] - p0) / p0 * 100
        dd = (p0 - pd_[0]) / p0 * 100
        seg_h = hi[t + 1:t + 1 + FWD]; seg_l = lo[t + 1:t + 1 + FWD]
        reach_u = int(seg_h.max() >= pu[0])
        reach_d = int(seg_l.min() <= pd_[0])
        # контрольные уровни — та же дистанция, но в случайную сторону от p0
        cu = p0 * (1 + abs(RNG.normal(du, 0.15)) / 100)
        cd = p0 * (1 - abs(RNG.normal(dd, 0.15)) / 100)
        rows.append((sym, du, dd, pu[1], pd_[1], reach_u, reach_d,
                     int(seg_h.max() >= cu), int(seg_l.min() <= cd),
                     int(t >= n // 2)))
    if fi % 5 == 0:
        print(f"  [{fi}/{len(files)}] точек {len(rows):,}", flush=True)

R = pd.DataFrame(rows, columns=["sym", "du", "dd", "wu", "wd", "reach_u", "reach_d",
                                "ctl_u", "ctl_d", "half"])
R.to_pickle(D + r"\liq_map.pkl")
print(f"\nточек: {len(R):,}\n")

print("=== ДОСТИГАЕТ ЛИ ЦЕНА ПИКОВ КАРТЫ ЛИКВИДАЦИЙ (горизонт сутки) ===")
print(f"{'сторона':>10} {'n':>9} {'дистанция':>11} {'достигнуто':>12} "
      f"{'контроль':>10} {'разница':>9}")
for side, rc, cc, dc in [("вверх", "reach_u", "ctl_u", "du"),
                         ("вниз", "reach_d", "ctl_d", "dd")]:
    print(f"{side:>10} {len(R):>9,} {R[dc].median():10.2f}% "
          f"{R[rc].mean()*100:11.1f}% {R[cc].mean()*100:9.1f}% "
          f"{(R[rc].mean()-R[cc].mean())*100:+8.1f}")

print("\n=== ПО СИЛЕ ПИКА (вес кластера ликвидаций) ===")
print(f"{'квинтиль веса':>14} {'n':>9} {'вверх дост.':>12} {'контроль':>10} "
      f"{'разница':>9}")
R["wq"] = pd.qcut(R.wu, 5, labels=False, duplicates="drop")
for q in sorted(R.wq.dropna().unique()):
    g = R[R.wq == q]
    print(f"{int(q)+1:>14} {len(g):>9,} {g.reach_u.mean()*100:11.1f}% "
          f"{g.ctl_u.mean()*100:9.1f}% {(g.reach_u.mean()-g.ctl_u.mean())*100:+8.1f}")

print("\n=== ЗЕРКАЛЬНОСТЬ И IS→OOS ===")
for side, rc, cc in [("вверх", "reach_u", "ctl_u"), ("вниз", "reach_d", "ctl_d")]:
    i_ = R[R.half == 0]; o_ = R[R.half == 1]
    di = (i_[rc].mean() - i_[cc].mean()) * 100
    do = (o_[rc].mean() - o_[cc].mean()) * 100
    per = R.groupby("sym").apply(lambda g: (g[rc].mean() - g[cc].mean()) * 100)
    print(f"  {side:>6}: IS {di:+.2f} п.п. · OOS {do:+.2f} п.п. · "
          f"{'✓' if di*do > 0 and di > 0 else '✗'} · монет+ "
          f"{int((per > 0).sum())}/{len(per)}")
