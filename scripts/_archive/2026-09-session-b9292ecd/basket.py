# -*- coding: utf-8 -*-
"""🧺 КАПИТАЛ ПОД ПАЧКИ СИГНАЛОВ (11.09.2026). Данные — safety.pkl (сделки уже посчитаны).

Проблема: лимит слотов «кто первый» забивают одиночки в спокойное время, а эдж — в кластерных
днях, которые приходят, когда слоты заняты. 1h→15m со слотами уходит в минус, 4h→1h даёт
лишь +11-13%/год при DD −26…−37%.

Варианты распределения (эквити по времени выхода, % от счёта, без плеча):
  SLOT   эталон: S слотов «кто первый»
  PRIO   S слотов, но в пределах суток сначала берём сделки из самых массовых дней
  DAY    дневной бюджет B% счёта делится поровну между ВСЕМИ входами суток;
         общий лимит экспозиции 100% (если не влезает — день масштабируется)
  CLUST  то же, что DAY, но торгуем ТОЛЬКО дни с k ≥ K входов (массовая капитуляция)
Политики выхода: база (зона +60) и «БУ после 3 ATR».
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
T = pd.read_pickle(D + r"\safety.pkl")
POLS = {0: "база", 8: "БУ после 3 ATR"}
span_y = (T.t_in.max() - T.t_in.min()).days / 365.25
T["day"] = T.t_in.dt.normalize()


def curve(weights, g):
    """weights — доля счёта на сделку (Series по индексу g)."""
    e = pd.Series((weights * g.pnl).values, index=g.t_out.values).sort_index()
    cum = e.cumsum()
    mon = e.resample("ME").sum()
    yr = e.groupby(e.index.year).sum()
    return (cum.iloc[-1] / span_y, (cum - cum.cummax()).min(), mon.min(),
            (mon > 0).mean(), {int(k): round(v, 1) for k, v in yr.items()})


def exposure_scale(g, w, cap=1.0):
    """масштабировать веса по дням так, чтобы открытая экспозиция не превышала cap."""
    g = g.assign(w=w).sort_values("t_in")
    w_out = pd.Series(0.0, index=g.index)
    open_pos = []                      # (t_out, weight)
    for day, gd in g.groupby("day", sort=True):
        open_pos = [(t, x) for t, x in open_pos if t > day]
        used = sum(x for _, x in open_pos)
        need = gd.w.sum()
        k = min(1.0, max(cap - used, 0) / need) if need > 0 else 0
        for idx, r in gd.iterrows():
            w_out[idx] = r.w * k
            open_pos.append((r.t_out, r.w * k))
    return w_out


def slot(g, S, prio=False):
    g = g.copy()
    if prio:
        g = g.sort_values(["day", "k"], ascending=[True, False])
    else:
        g = g.sort_values("t_in")
    take = pd.Series(0.0, index=g.index)
    open_ends = []
    for idx, r in g.iterrows():
        open_ends = [t for t in open_ends if t > r.t_in]
        if len(open_ends) < S:
            take[idx] = 1.0 / S
            open_ends.append(r.t_out)
    return take.reindex(g.index)


print(f"лет {span_y:.1f}\n")
print(f"{'схема':>8} {'выход':>15} {'распределение':>28} {'годовых':>9} {'макс DD':>9} "
      f"{'худш.мес':>9} {'мес+':>5}  по годам")
for scope in ["4h→1h", "1h→15m", "обе"]:
    for pi, pn in POLS.items():
        g = T[(T.pol == pi) & ((T.scheme == scope) | (scope == "обе"))].copy()
        g = g.join(g.groupby("day").sym.nunique().rename("k"), on="day")
        variants = []
        for S in (30, 50):
            variants.append((f"SLOT {S} слотов", slot(g, S)))
            variants.append((f"PRIO {S} слотов, кластер первым", slot(g, S, prio=True)))
        nday = g.groupby("day").sym.transform("count")
        for B in (0.10, 0.20, 0.30):
            w = B / nday
            variants.append((f"DAY бюджет {int(B*100)}%/день", exposure_scale(g, w)))
        kq = [int(np.percentile(g.groupby("day").sym.nunique(), q)) for q in (75, 90)]
        for K in sorted(set(max(k, 3) for k in kq)):
            m = g.k >= K
            for B in (0.20, 0.40):
                w = np.where(m, B / nday, 0.0)
                variants.append((f"CLUST k≥{K}, {int(B*100)}%/день", exposure_scale(g, w)))
        for name, w in variants:
            r = curve(pd.Series(w, index=g.index) if not isinstance(w, pd.Series) else w.reindex(g.index), g)
            print(f"{scope:>8} {pn:>15} {name:>28} {r[0]:+8.1f}% {r[1]:+8.1f}% {r[2]:+8.1f}% "
                  f"{r[3]*100:4.0f}%  {r[4]}")
        print()
