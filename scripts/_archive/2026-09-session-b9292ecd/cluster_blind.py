# -*- coding: utf-8 -*-
"""🔒 СЛЕПОЙ ПОРОГ МАССОВОСТИ ДНЯ для «торговать только массовые дни» (11.09.2026).

basket.py: обе схемы вместе, только дни с k≥42 входами, бюджет 40%/день поровну между монетами дня
→ +10.1%/год, DD −12.0%, худший месяц −4.0%; с БУ после 3 ATR — +8.5%, DD −5.7%.
Но K=42 выбран как 90-й перцентиль по ВСЕМУ периоду ⇒ нужен слепой выбор.

IS = 2022-2024: выбрать K по отношению доходность/просадка (бюджет 40%/день).
OOS = 2025-2026: применить без изменений.
Плюс: сколько таких дней и сделок по годам, приоритет кластеру в слотах (PRIO 50) по годам.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
T = pd.read_pickle(D + r"\safety.pkl")
T["day"] = T.t_in.dt.normalize()
KS = [10, 15, 20, 25, 30, 35, 42, 50, 60]
B = 0.40


def exposure_scale(g, w, cap=1.0):
    g = g.assign(w=w).sort_values("t_in")
    w_out = pd.Series(0.0, index=g.index)
    open_pos = []
    for day, gd in g.groupby("day", sort=True):
        open_pos = [(t, x) for t, x in open_pos if t > day]
        used = sum(x for _, x in open_pos)
        need = gd.w.sum()
        k = min(1.0, max(cap - used, 0) / need) if need > 0 else 0
        for idx, r in gd.iterrows():
            w_out[idx] = r.w * k
            open_pos.append((r.t_out, r.w * k))
    return w_out


def evaluate(g, w, years):
    e = pd.Series((w * g.pnl).values, index=g.t_out.values).sort_index()
    e = e[e.index.year.isin(years)]
    if not len(e) or e.abs().sum() == 0:
        return None
    span = len(years)
    cum = e.cumsum()
    dd = (cum - cum.cummax()).min()
    mon = e.resample("ME").sum()
    ann = cum.iloc[-1] / span
    return ann, dd, mon.min(), ann / abs(dd) if dd < 0 else np.inf


for pi, pn in [(0, "база"), (8, "БУ после 3 ATR")]:
    g = T[T.pol == pi].copy()
    kday = g.groupby("day").sym.nunique()
    g = g.join(kday.rename("k"), on="day")
    nday = g.groupby("day").sym.transform("count")
    print(f"\n{'='*92}\n=== ОБЕ СХЕМЫ · выход: {pn} · бюджет {int(B*100)}%/день ===\n{'='*92}")
    print(f"{'K':>4} | {'IS 2022-24: годовых':>20} {'DD':>7} {'худш.мес':>9} {'дох/DD':>7} | "
          f"{'OOS 2025-26: годовых':>21} {'DD':>7} {'худш.мес':>9} | {'дней IS/OOS':>12} "
          f"{'сделок IS/OOS':>14}")
    best = None
    for K in KS:
        m = g.k >= K
        w = exposure_scale(g, np.where(m, B / nday, 0.0))
        a = evaluate(g, w, [2022, 2023, 2024])
        b = evaluate(g, w, [2025, 2026])
        days_is = g[m & (g.day.dt.year <= 2024)].day.nunique()
        days_oos = g[m & (g.day.dt.year >= 2025)].day.nunique()
        tr_is = int((m & (g.day.dt.year <= 2024)).sum())
        tr_oos = int((m & (g.day.dt.year >= 2025)).sum())
        fa = f"{a[0]:+19.1f}% {a[1]:+6.1f}% {a[2]:+8.1f}% {a[3]:6.2f}" if a else f"{'нет сделок':>44}"
        fb = f"{b[0]:+20.1f}% {b[1]:+6.1f}% {b[2]:+8.1f}%" if b else f"{'нет сделок':>38}"
        print(f"{K:>4} | {fa} | {fb} | {days_is:>5}/{days_oos:<6} {tr_is:>6}/{tr_oos:<7}")
        if a and days_is >= 5 and (best is None or a[3] > best[1]):
            best = (K, a[3])
    if best:
        K = best[0]
        m = g.k >= K
        w = exposure_scale(g, np.where(m, B / nday, 0.0))
        b = evaluate(g, w, [2025, 2026])
        print(f"\n  → на IS выбран K≥{K} (лучшее доходность/просадка при ≥5 днях) → OOS: "
              + (f"{b[0]:+.1f}%/год · DD {b[1]:+.1f}% · худший месяц {b[2]:+.1f}%" if b else "нет сделок"))
    print("\n  дней с k≥K по годам:")
    for K in (20, 30, 42):
        per = g[g.k >= K].groupby(g.day.dt.year).day.nunique()
        print(f"    K≥{K}: " + " · ".join(f"{y}: {per.get(y, 0)}" for y in range(2022, 2027)))
