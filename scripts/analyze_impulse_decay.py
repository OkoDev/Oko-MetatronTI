# -*- coding: utf-8 -*-
"""ПОЧЕМУ МЕХАНИКА УМЕРЛА К 2026 — разбор по сохранённой базе (20.08.2026).

Финальный перемер: OOS-время (2025-26) PF 0.99, 2026 PF 0.95 при 2022 PF 3.88.
Механика едет на эпохе — ровно то, о чём предупреждал Егор про хардкод.

Здесь два вопроса, каждый решает, есть ли что спасать:
  1. Гейт «по тренду EMA200» — направленный. Переворачивается ли он по годам, как
     сторона? Если да, отбор ломается тем же механизмом, что и цель.
  2. Зона малых стопов (0.32–3.23%) дала PF 2.45 и ЕДИНСТВЕННЫЙ положительный
     безтоп10% (+621). Живёт ли она на OOS-времени или это тоже 2022-2023?
"""
import sys
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore")

RISK = 2.0
D = pd.read_pickle("scratch_impulse_live.pkl")
D = D[D.live_b.notna()].copy()
D["g3"] = (D.vratio >= 1.0) & (D.vratio < 1.5) & D.with_trend & (D.regime >= 1.1)
D["g2"] = (D.vratio >= 1.0) & (D.vratio < 1.5) & (D.regime >= 1.1)   # без гейта тренда


def rep(v, name, col="live_b", span_years=4.6):
    if len(v) < 25:
        return f"  {name:<44} n={len(v):<5} — мало"
    p = v[col].values
    w = p[p > 0]
    gl = -p[p <= 0].sum()
    s = np.sort(p)[::-1]
    cov = (v.groupby("sym")[col].sum() > 0).mean() * 100
    freq = len(p) / max(v.sym.nunique(), 1) / (span_years * 12) * 250
    depo = p.mean() / v[f"sp_{col}"].median() * RISK
    return (f"  {name:<44} n={len(p):<5} WR {len(w) / len(p) * 100:5.1f}%  "
            f"PF {(w.sum() / gl if gl else 0):5.2f}  ср {p.mean():+6.2f}%  "
            f"безтоп10% {s[int(len(s) * 0.1):].sum():+7.0f}  {freq:5.1f} сд/мес  "
            f"{depo * freq:+6.2f}% депо/мес  охват {cov:3.0f}%")


print("=" * 140)
print(f"РАЗБОР УГАСАНИЯ · {D.sym.nunique()} монет · {len(D)} входов")
print("=" * 140)

print("\n1. ГЕЙТ ТРЕНДА EMA200 — переворачивается ли по годам, как сторона?")
G2 = D[D.g2]
for y in sorted(D.year.unique()):
    a = G2[(G2.year == y) & G2.with_trend]
    b = G2[(G2.year == y) & ~G2.with_trend]
    pa = rep(a, f"{y} ПО тренду")
    pb = rep(b, f"{y} ПРОТИВ тренда")
    print(pa)
    print(pb)

print("\n   то же по сторонам (гейт тренда может ломаться только на одной):")
for side in ("long", "short"):
    for flag, nm in ((True, "ПО тренду"), (False, "ПРОТИВ")):
        print(rep(G2[(G2.side == side) & (G2.with_trend == flag)], f"{side} · {nm}"))

print("\n2. ЗОНА МАЛЫХ СТОПОВ — живёт ли на OOS-времени?")
G = D[D.g3]
edges = [0, 3.234, 4.141, 5.7, 100]
for lo, hi in zip(edges[:-1], edges[1:]):
    sub = G[(G.sp_live_b > lo) & (G.sp_live_b <= hi)]
    print(rep(sub, f"стоп {lo}-{hi}%  ВСЁ ОКНО"))
    print(rep(sub[sub.year <= 2024], f"   стоп {lo}-{hi}%  2022-24"))
    print(rep(sub[sub.year >= 2025], f"   стоп {lo}-{hi}%  2025-26 (OOS-время)"))

print("\n3. МАЛЫЕ СТОПЫ БЕЗ ГЕЙТОВ (частота против качества):")
S = D[(D.sp_live_b > 0) & (D.sp_live_b <= 3.234)]
print(rep(S, "малый стоп, БЕЗ гейтов, всё окно"))
print(rep(S[S.year >= 2025], "   он же 2025-26"))
print(rep(S[S.oos & (S.year >= 2025)], "   он же OOS × OOS"))
for side in ("long", "short"):
    print(rep(S[(S.side == side) & (S.year >= 2025)], f"   {side} 2025-26"))

print("\n4. ЧТО ВООБЩЕ ЖИВО В 2025-26 (перебор одиночных условий):")
R = D[D.year >= 2025]
base = rep(R, "база 2025-26")
print(base)
for nm, mask in (
    ("объём 1.0-1.5×", (R.vratio >= 1.0) & (R.vratio < 1.5)),
    ("объём <1.0", R.vratio < 1.0),
    ("объём >1.5", R.vratio >= 1.5),
    ("по тренду EMA200", R.with_trend),
    ("против тренда", ~R.with_trend),
    ("волатильность ≥1.1", R.regime >= 1.1),
    ("волатильность <1.1", R.regime < 1.1),
    ("стоп ≤3.2%", R.sp_live_b <= 3.234),
    ("стоп >5.7%", R.sp_live_b > 5.7),
    ("long", R.side == "long"),
    ("short", R.side == "short"),
    ("амплитуда ≥ медианы", R.amp_pct >= R.amp_pct.median()),
    ("амплитуда < медианы", R.amp_pct < R.amp_pct.median()),
):
    print(rep(R[mask], nm))
