# -*- coding: utf-8 -*-
"""ЛОВЛЯ НОЖА: лонг ядра волн, вход которого пришёлся на ШИРОКИЙ слив рынка (Егор 08.10: «за 6 часов упали 81% монет,
а мы этого не видим и не реагируем?!» · «бот продолжает ловлю ножей и пытается лонговать падение»).

ЗАДАНО ДО ПРОГОНА:
  · ширина слива br6 = доля монет вселенной (журнал общего состояния, 469 монет), у которых close упал > 3% за 6
    закрытых часов; причинно — последний час, закрывшийся не позже входа (час h, h + 1ч ≤ вход);
  · «нож» — br6 ≥ 0.5 (08.10 было 0.81); корзины <0.1 / 0.1–0.3 / 0.3–0.5 / ≥0.5;
  · потоки отдельно (доказанный лонг · лонг вне зоны · шорт), % (кост 0.35) и R; срез с массовостью дня
    (`wave_day_mass_lab`, m_day ≥ 3);
  · сделки — `G:/oko_lab/out/wave_day_mass.pkl` (5270, 2023→08.2026; журнал до 06.10.2026).

Запуск: python scripts/wave_knife_lab.py [процессов]
"""
from __future__ import annotations

import os
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                        # noqa: BLE001
    pass

import research_verify as V                               # noqa: E402

JOURNAL = Path("G:/oko_lab/joint/1h")
BR_OUT = Path("G:/oko_lab/out/market_breadth_1h.pkl")
BINS = [(0.0, 0.1, "<0.1"), (0.1, 0.3, "0.1–0.3"), (0.3, 0.5, "0.3–0.5"), (0.5, 1.01, "≥0.5 нож")]


def _ret6(f):
    c = pd.read_parquet(f, columns=["close"]).close
    c.index = c.index.tz_convert(None) if c.index.tz is not None else c.index
    return (c / c.shift(6) - 1).rename(f.stem)


def breadth(procs: int) -> pd.DataFrame:
    if BR_OUT.exists():
        return pd.read_pickle(BR_OUT)
    with Pool(procs) as pool:
        R = pd.concat(pool.map(_ret6, sorted(JOURNAL.glob("*.parquet"))), axis=1)
    n = R.notna().sum(axis=1)
    B = pd.DataFrame({"br6": (R < -0.03).sum(axis=1) / n, "n": n, "med6": R.median(axis=1)})
    B = B[B.n >= 50]
    B.to_pickle(BR_OUT)
    return B


def main() -> int:
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else max(1, (os.cpu_count() or 2) - 6)
    B = breadth(procs)
    # §0A.2 golden: 3 монеты из 4 упали > 3% → 0.75
    G = pd.DataFrame({"a": [-0.05], "b": [-0.04], "c": [-0.031], "d": [0.0]})
    assert float(((G < -0.03).sum(axis=1) / G.notna().sum(axis=1)).iloc[0]) == 0.75
    print(f"ширина слива: {len(B)} часов · {B.index.min()} → {B.index.max()} · монет в часе медиана {int(B.n.median())}")
    print(f"  распределение br6: медиана {B.br6.median():.2f} · ≥0.5 в {(B.br6 >= 0.5).mean() * 100:.1f}% часов · "
          f"дней с хотя бы одним «ножом» {B[B.br6 >= 0.5].index.floor('D').nunique()}")
    D = pd.read_pickle("G:/oko_lab/out/wave_day_mass.pkl")
    key = D.E.dt.floor("h") - pd.Timedelta("1h")                    # последний закрытый час до входа
    n0 = len(D)
    D = D.assign(h=key).merge(B[["br6"]], left_on="h", right_index=True, how="left")
    assert len(D) == n0                                              # §0A.3
    D = D[D.br6.notna()].reset_index(drop=True)
    print(f"сделок с шириной на входе: {len(D)} из {n0}")
    print(D[["sym", "E", "flow", "br6", "m_day", "pnl_re"]].sort_values("br6").tail(3).round(2).to_string(index=False))
    for flow, F in D.groupby("flow"):
        print(f"\n{flow}: n {len(F)} · средн {F.pnl_re.mean():+.2f}% · R {F.R.mean():+.3f}")
        print(f"  {'br6':<10}{'n':>6}{'дней':>6}{'средн %':>9}{'медиана':>9}{'R':>8}{'в плюсе':>9}   массовый день (m_day≥3): средн / n")
        for lo, hi, lab in BINS:
            g = F[(F.br6 >= lo) & (F.br6 < hi)]
            if len(g) < 5:
                print(f"  {lab:<10}{len(g):>6}")
                continue
            gm = g[g.m_day >= 3]
            print(f"  {lab:<10}{len(g):>6}{g.E.dt.floor('D').nunique():>6}{g.pnl_re.mean():>+9.2f}{g.pnl_re.median():>+9.2f}"
                  f"{g.R.mean():>+8.3f}{(g.pnl_re > 0).mean() * 100:>8.0f}%   {gm.pnl_re.mean() if len(gm) else float('nan'):+.2f} / {len(gm)}")
    for flow in ("доказанный лонг", "лонг вне зоны"):
        F = D[D.flow == flow].reset_index(drop=True)
        DD = V.normalize(F.assign(pnl=F.pnl_re, ts=F.E), pnl="pnl", ts="ts")
        V.card(DD, (F.br6 >= 0.5).values, name=f"{flow} × вход в «нож» (br6 ≥ 0.5)", study="wave-knife",
               geo=("stop_pct",))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
