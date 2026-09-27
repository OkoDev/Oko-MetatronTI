# -*- coding: utf-8 -*-
"""🧮 SPOT_DUMP_GRID — симуляция счёта под вводные Егора (11.09.2026):
  «в начале готов отдавать под сделки до 30% депозита, т.е. 30-60 слотов; риски большой просадки минимизировать»

Сделки — small_account_trades.pkl (LONG, три схемы A 4h→1h · B 2h→15m · C 1h→15m, пороги −70/−75).
Счёт (сложный процент):
  экспозиция ≤ E = 30% текущего счёта; слот = E / K счёта на момент входа (K = 30 / 60)
  одна позиция на монету ОБЩАЯ для всех схем (монета занята любой схемой — сигнал пропускается)
  плечо L: 1 (спот) · 2 · 3 (фьючерсы, изолированная маржа, ликвидация при MAE ≤ −(1/L − 0.5%))
  комиссия: 0.20% (спот, мейкер/тейкер 0.1%×2) и 0.35% (с проскальзыванием) — от объёма
  отбор при заполненных слотах: «кто первый» (каузально)
Выход: годовая доходность, макс. просадка, худший месяц, по годам, доля пропущенных, пик экспозиции.
"""
import sys, os, itertools
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

D = os.path.dirname(os.path.abspath(__file__))
T = pd.read_pickle(os.path.join(D, "small_account_trades.pkl"))
T = T[T.side == 1].copy()
span = (T.t_in.max() - T.t_in.min()).days / 365.25
E = 0.30


def run(g, K, L, fee):
    g = g.sort_values("t_in")
    eq, peak, maxdd = 1.0, 1.0, 0.0
    open_pos, taken, skipped, liq, peak_exp = [], 0, 0, 0, 0.0
    busy_coin = {}
    marks = []
    liq_edge = -(100.0 / L - 0.5)
    for r in g.itertuples():
        still = []
        for p in open_pos:
            if p[0] <= r.t_in:
                eq += p[1] * p[2] / 100
                peak = max(peak, eq); maxdd = min(maxdd, eq / peak - 1)
                marks.append((p[0], eq))
            else:
                still.append(p)
        open_pos = still
        if busy_coin.get(r.sym, pd.Timestamp.min) > r.t_in:
            continue                                   # монета уже в позиции (любая схема)
        if len(open_pos) >= K:
            skipped += 1
            continue
        margin = eq * E / K
        if L > 1 and r.mae <= liq_edge:
            res = -100.0; liq += 1
        else:
            res = r.pnl * L - fee * L
        open_pos.append((r.t_out, margin, max(res, -100.0)))
        busy_coin[r.sym] = r.t_out
        taken += 1
        peak_exp = max(peak_exp, sum(p[1] for p in open_pos) / eq)
    for p in sorted(open_pos):
        eq += p[1] * p[2] / 100
        peak = max(peak, eq); maxdd = min(maxdd, eq / peak - 1)
        marks.append((p[0], eq))
    s = pd.Series([m[1] for m in marks], index=[m[0] for m in marks]).sort_index()
    me = s.resample("ME").last().ffill()
    mret = me.pct_change().dropna()
    ye = s.resample("YE").last().ffill()
    yret = ye.pct_change()
    yret.iloc[0] = ye.iloc[0] - 1
    return dict(cagr=(max(eq, 1e-9) ** (1 / span) - 1) * 100, dd=maxdd * 100,
                wm=mret.min() * 100, liq=liq, taken=taken,
                skip=skipped / max(taken + skipped, 1) * 100, exp=peak_exp * 100,
                years={int(k.year): round(v * 100, 1) for k, v in yret.items()}, mult=eq)


SETS = {
    "A 4h→1h −75": T[(T.scheme == "4h→1h") & (T.z == 75)],
    "A 4h→1h −70": T[(T.scheme == "4h→1h") & (T.z == 70)],
    "B 2h→15m −75": T[(T.scheme == "2h→15m") & (T.z == 75)],
    "C 1h→15m −75": T[(T.scheme == "1h→15m") & (T.z == 75)],
    "A+B+C −75": T[T.z == 75],
    "A−70 + B,C −75": pd.concat([T[(T.scheme == "4h→1h") & (T.z == 70)],
                                 T[(T.scheme != "4h→1h") & (T.z == 75)]]),
}
print(f"лет {span:.1f} · экспозиция ≤ {int(E*100)}% счёта\n")
print(f"{'набор':>16} {'K':>3} {'L':>2} {'кост':>5} {'годовых':>9} {'макс DD':>8} {'худш.мес':>9} "
      f"{'ликв':>5} {'сделок':>7} {'пропущ':>7} {'пик эксп':>9} {'итог ×':>7}  по годам")
for name, g in SETS.items():
    for K, L, fee in itertools.product([30, 60], [1, 2, 3], [0.10, 0.15, 0.35]):
        r = run(g, K, L, fee)
        print(f"{name:>16} {K:>3} {L:>2} {fee:>5.2f} {r['cagr']:+8.1f}% {r['dd']:+7.1f}% {r['wm']:+8.1f}% "
              f"{r['liq']:>5} {r['taken']:>7} {r['skip']:6.0f}% {r['exp']:8.0f}% {r['mult']:6.2f}×  {r['years']}")
    print()
