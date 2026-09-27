# -*- coding: utf-8 -*-
"""🔔 КЛАСТЕР-ФИЛЬТР: слепой тест + перестановочный контроль (11.09.2026).

Из разреза по режиму: сильнее всего разделяет КЛАСТЕР — сколько монет дали вход в тот же день.
    ±75/+70: одиночка −0.248% · 2-4 +0.082% · 5-14 −0.941% · 15+ +2.351% (безтоп10 +0.616%)
Но нарезано ~32 ячейки ⇒ лучшая может быть отбором максимума. Здесь:
  1. ПОРОГ КЛАСТЕРА выбирается на IS (2022-2024), проверяется на OOS (2025-2026) — вслепую
  2. ПЕРЕСТАНОВКА: метки кластера перемешиваются между сделками ВНУТРИ ГОДА (сохраняя число
     сделок в кластере по годам) — 2000 перестановок, p-value разницы «кластер − остальные»
  3. ДУБЛИРОВАНИЕ: кластер 15+ ≈ «BTC упал»? доля пересечения и синергия в комбинации
  4. по годам для кластерного фильтра
Данные — eq_regime.pkl (одна позиция на монету, без перекрытия).
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
R = pd.read_pickle(D + r"\eq_regime.pkl")
R["day"] = R["ts"].dt.normalize()
RNG = np.random.default_rng(1)
RG = {2022: "МЕДВ", 2023: "БЫК", 2024: "нейтр", 2025: "МЕДВ", 2026: "МЕДВ"}
KS = [3, 5, 8, 10, 15, 20, 30]


def stat(g):
    if len(g) < 30:
        return None
    v = np.sort(g.pnl.values)[::-1]
    per = g.groupby("sym").pnl.mean()
    return (len(g), g.pnl.mean(), g.pnl.median(), v[int(len(v)*.1):].mean(),
            int((per > 0).sum()), len(per))


for IZ, EZ in [(70.0, 60.0), (75.0, 70.0)]:
    G = R[(R["iz"] == IZ) & (R["ez"] == EZ)].copy()
    G = G.join(G.groupby("day").sym.nunique().rename("k"), on="day")
    print(f"\n{'='*78}\n=== вход ±{IZ:.0f} / выход +{EZ:.0f} · сделок {len(G):,} ===\n{'='*78}")

    print("\n1. СЛЕПОЙ ВЫБОР ПОРОГА КЛАСТЕРА: IS = 2022-2024, OOS = 2025-2026")
    IS, OOS = G[G.year <= 2024], G[G.year >= 2025]
    print(f"{'k ≥':>5} {'IS n':>6} {'IS нетто':>9} {'IS безтоп10':>12} {'OOS n':>6} "
          f"{'OOS нетто':>10} {'OOS безтоп10':>13} {'OOS монет+':>11}")
    best_is = None
    for k in KS:
        a, b = stat(IS[IS.k >= k]), stat(OOS[OOS.k >= k])
        if not a or not b:
            continue
        print(f"{k:>5} {a[0]:>6,} {a[1]:+8.3f}% {a[3]:+11.3f}% {b[0]:>6,} {b[1]:+9.3f}% "
              f"{b[3]:+12.3f}% {b[4]}/{b[5]}")
        if best_is is None or a[3] > best_is[1]:
            best_is = (k, a[3])
    k_star = best_is[0]
    a, b = stat(IS[IS.k >= k_star]), stat(OOS[OOS.k >= k_star])
    a0, b0 = stat(IS), stat(OOS)
    print(f"\n  порог, выбранный на IS по безтоп10%: k ≥ {k_star}")
    print(f"  IS : без фильтра {a0[1]:+.3f}% → с фильтром {a[1]:+.3f}% "
          f"(безтоп10 {a0[3]:+.3f} → {a[3]:+.3f})")
    print(f"  OOS: без фильтра {b0[1]:+.3f}% → с фильтром {b[1]:+.3f}% "
          f"(безтоп10 {b0[3]:+.3f} → {b[3]:+.3f}) · монет+ {b[4]}/{b[5]}")
    print(f"  → перенос: {'✅ фильтр работает на OOS' if b[1] > b0[1] and b[1] > 0 else '🔴 НЕ перенёсся'}")

    print(f"\n2. ПЕРЕСТАНОВОЧНЫЙ КОНТРОЛЬ (k ≥ {k_star}, перемешивание внутри года, 2000 раз)")
    flag = (G.k >= k_star).values
    pnl = G.pnl.values
    years = G.year.values
    real_diff = pnl[flag].mean() - pnl[~flag].mean()
    null = np.empty(2000)
    idx_by_year = {y: np.where(years == y)[0] for y in np.unique(years)}
    for t in range(2000):
        f2 = np.zeros(len(G), bool)
        for y, ix in idx_by_year.items():
            m = int(flag[ix].sum())
            if m:
                f2[RNG.choice(ix, m, replace=False)] = True
        null[t] = pnl[f2].mean() - pnl[~f2].mean()
    p = (null >= real_diff).mean()
    print(f"  разница «кластер − остальные»: реальная {real_diff:+.3f} п.п. · "
          f"перестановки мед {np.median(null):+.3f} [95й {np.percentile(null,95):+.3f}] · "
          f"p = {p:.4f} → {'✅ не случайно' if p < 0.01 else '🔴 может быть случайным'}")

    print("\n3. ДУБЛИРОВАНИЕ: кластер против «BTC упал > 10%» и «монета −30%»")
    cl, bd, od = G.k >= k_star, G.btc30 < -10, G.own30 < -30
    print(f"  доля кластерных сделок, где BTC упал >10%: {(cl & bd).sum()/max(cl.sum(),1)*100:.1f}%")
    print(f"  доля сделок «BTC упал», попавших в кластер: {(cl & bd).sum()/max(bd.sum(),1)*100:.1f}%")
    for lbl, cond in [("кластер И BTC упал", cl & bd), ("кластер, BTC НЕ упал", cl & ~bd),
                      ("BTC упал, НЕ кластер", ~cl & bd), ("ни то ни другое", ~cl & ~bd),
                      ("кластер И монета −30%", cl & od), ("кластер, монета не −30%", cl & ~od)]:
        s = stat(G[cond])
        if s:
            print(f"  {lbl:>26}: n={s[0]:>5,} · {s[1]:+7.3f}% · мед {s[2]:+7.3f}% · "
                  f"безтоп10 {s[3]:+7.3f}% · монет+ {s[4]}/{s[5]}")

    print(f"\n4. ПО ГОДАМ: кластер k ≥ {k_star} против остальных")
    for y in sorted(G.year.unique()):
        s1, s0 = stat(G[(G.year == y) & cl]), stat(G[(G.year == y) & ~cl])
        t1 = f"{s1[1]:+7.3f}% (n={s1[0]:,}, безтоп10 {s1[3]:+.3f}, монет+ {s1[4]}/{s1[5]})" if s1 else "—"
        t0 = f"{s0[1]:+7.3f}% (n={s0[0]:,})" if s0 else "—"
        print(f"  {y} {RG.get(y,'?'):>6}: кластер {t1} · остальные {t0}")
