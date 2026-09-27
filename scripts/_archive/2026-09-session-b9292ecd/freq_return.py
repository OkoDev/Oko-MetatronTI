# -*- coding: utf-8 -*-
"""📈 ЧАСТОТА И ДОХОДНОСТЬ двух схем (Егор, 11.09.2026).

Источники (одна позиция на монету, без перекрытия, 291 монета, 15m-кэш 2022-01…2026-07):
  verify_240_60.pkl / verify_60_15.pkl — сделки по сетке порогов (pnl, время входа)
  up_ladder.pkl — у ±70/+60 есть время удержания ⇒ одновременность позиций и загрузка капитала

Доходность на КАПИТАЛ считается так: счёт делится на S равных слотов, каждая сделка берёт
один слот; S = 95-й перцентиль числа одновременно открытых позиций (почти никогда не упираемся
в лимит). Годовая доходность = сумма pnl за год / S. Без плеча, косты 0.35% уже внутри pnl.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
V = {"4h→1h": pd.read_pickle(D + r"\verify_240_60.pkl"),
     "1h→15m": pd.read_pickle(D + r"\verify_60_15.pkl")}
U = pd.read_pickle(D + r"\up_ladder.pkl")
U = U[(U["part"] == 2) & (U["kind"] == "sig")]
UMAP = {"4h→1h": "240m→60m", "1h→15m": "60m→15m"}


def concurrency(g):
    """число одновременно открытых позиций по времени (событийный проход)."""
    t_in = pd.to_datetime(g.ts).values
    t_out = t_in + (g.hold_h.values * 3600).astype("timedelta64[s]")
    ev = np.concatenate([np.stack([t_in.astype("int64"), np.ones(len(g))], 1),
                         np.stack([t_out.astype("int64"), -np.ones(len(g))], 1)])
    ev = ev[np.lexsort((ev[:, 1], ev[:, 0]))]
    cur = np.cumsum(ev[:, 1])
    dt = np.diff(ev[:, 0], append=ev[-1, 0])
    busy = dt[cur > 0].sum() / max(dt.sum(), 1)
    # распределение по времени (взвешенное длительностью)
    order = np.argsort(cur)
    w = dt[order] / max(dt.sum(), 1)
    cdf = np.cumsum(w)
    p95 = cur[order][np.searchsorted(cdf, 0.95)]
    return cur.max(), float(np.average(cur, weights=dt)) if dt.sum() else 0, p95, busy


slots_by = {}
print("=== ОДНОВРЕМЕННОСТЬ ПОЗИЦИЙ (±70/+60, из up_ladder) ===")
for nm, var in UMAP.items():
    g = U[U["var"] == var].copy()
    mx, avg, p95, busy = concurrency(g)
    slots_by[nm] = max(int(p95), 1)
    print(f"  {nm:>7}: удержание мед {g.hold_h.median():.0f} ч · одновременно в среднем {avg:.1f} · "
          f"95-й перцентиль {p95:.0f} · максимум {mx:.0f} · есть хоть одна позиция {busy*100:.0f}% времени")
print()

rows = []
for nm, R in V.items():
    S = R[R["kind"] == "sig"].copy()
    S["ts"] = pd.to_datetime(S["ts"])
    span_y = (S.ts.max() - S.ts.min()).days / 365.25
    for iz, ez in [(70.0, 60.0), (75.0, 60.0)]:
        g = S[(S["iz"] == iz) & (S["ez"] == ez)].copy()
        g["day"] = g.ts.dt.normalize()
        k = g.groupby("day").sym.nunique()
        g = g.join(k.rename("k"), on="day")
        for flt, G in [("все", g), ("кластер k≥30" if nm == "4h→1h" else "кластер k≥10",
                                    g[g.k >= (30 if nm == "4h→1h" else 10)])]:
            if len(G) < 30:
                continue
            ym = G.groupby(G.ts.dt.to_period("M")).size()
            months = pd.period_range(S.ts.min().to_period("M"), S.ts.max().to_period("M"), freq="M")
            ym = ym.reindex(months, fill_value=0)
            active_days = G.day.nunique()
            per_coin_y = G.groupby("sym").size() / span_y
            yr = G.groupby(G.ts.dt.year).pnl.sum()
            slots = slots_by[nm]
            rows.append(dict(
                схема=nm, вход=f"±{iz:.0f}", фильтр=flt, сделок=len(G),
                в_год=len(G) / span_y, в_месяц_мед=float(ym.median()),
                пустых_мес=int((ym == 0).sum()), всего_мес=len(ym),
                дней_с_входом=active_days, в_день_когда_есть=len(G) / active_days,
                на_монету_в_год=float(per_coin_y.median()),
                pnl_сделка=G.pnl.mean(), сумма_в_год=G.pnl.sum() / span_y,
                слотов=slots, на_капитал_в_год=G.pnl.sum() / span_y / slots,
                годы={int(y): round(v / slots, 1) for y, v in yr.items()}))

O = pd.DataFrame(rows)
print("=== ЧАСТОТА ===")
for _, r in O.iterrows():
    print(f"  {r.схема:>7} {r.вход} {r.фильтр:>13}: сделок {r.сделок:>6,} · {r.в_год:>6.0f} в год "
          f"(по всем монетам) · в месяц медиана {r.в_месяц_мед:.0f} · пустых месяцев "
          f"{r.пустых_мес}/{r.всего_мес} · дней с входом {r.дней_с_входом} · "
          f"{r.в_день_когда_есть:.1f} входа в такой день · на монету {r.на_монету_в_год:.1f}/год")
print("\n=== ДОХОДНОСТЬ (без плеча; счёт делится на слоты = 95-й перцентиль одновременных позиций) ===")
for _, r in O.iterrows():
    print(f"  {r.схема:>7} {r.вход} {r.фильтр:>13}: {r.pnl_сделка:+.3f}%/сделка · сумма "
          f"{r.сумма_в_год:+.0f}% в год на 1 слот · слотов {r.слотов} · "
          f"≈ {r.на_капитал_в_год:+.1f}% годовых на счёт · по годам {r.годы}")

# ── общая эквити и просадка: 4h→1h ±70/+60, счёт на слотах
print("\n=== ЭКВИТИ СЧЁТА (±70/+60, по времени входа, % от счёта) ===")
for nm in V:
    g = V[nm]
    g = g[(g["kind"] == "sig") & (g["iz"] == 70.0) & (g["ez"] == 60.0)].copy()
    g["ts"] = pd.to_datetime(g["ts"]); g = g.sort_values("ts")
    eq = np.cumsum(g.pnl.values / slots_by[nm])
    dd = (eq - np.maximum.accumulate(eq)).min()
    m = pd.Series(g.pnl.values / slots_by[nm], index=g.ts).resample("M").sum()
    print(f"  {nm:>7}: итог {eq[-1]:+.0f}% за период · макс. просадка {dd:.0f}% · месяцев в плюсе "
          f"{(m > 0).sum()}/{len(m)} · худший месяц {m.min():+.1f}% · лучший {m.max():+.1f}%")
