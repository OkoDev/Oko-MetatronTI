# -*- coding: utf-8 -*-
"""МАССОВОСТЬ ТЕКУЩЕГО ДНЯ как ось денег ядра волн (Егор 08.10, пункт 5: «массовость текущего дня как ось на истории —
для доказанного и недоказанного потоков отдельно»).

Повод: тень 14.09–08.10 — 21 из 39 бумажных лонгов «вне зоны» вошли 16.09 (+193% суммы, +78.7R), без этого дня поток
−0.66%/сд; USELESS 07–08.10 — одиночка, 7 стопов. Поле `cluster_3d` тени считает только 3 ПРОШЛЫХ дня и запаздывает.

ЗАДАНО ДО ПРОГОНА:
  · массовость дня m_day = сколько ДРУГИХ монет той же стороны уже дали вход с начала UTC-дня до входа этой сделки
    (вход другой монеты ≤ входа этой) — причинно, по входам, без заглядывания вперёд;
  · m_3d = сколько других монет той же стороны дали вход за 3 прошлых UTC-дня (без текущего) — аналог cluster_3d;
  · кандидат: m_day ≥ 3; корзины 0 / 1–2 / 3–5 / ≥6 справочно;
  · деньги: % (кост 0.35) и R = % / стоп (капитал при равном риске на сделку); потоки отдельно: доказанные лонги
    (стоп ≥6% или коридор) · лонг вне зоны · шорт;
  · сделки — `wave_portfolio_sim.prepare()` (выход пересчитан, голден 99.9%), 2023 → 08.2026.

Запуск: python scripts/wave_day_mass_lab.py [процессов]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                        # noqa: BLE001
    pass

import research_verify as V                               # noqa: E402
import wave_portfolio_sim as W                            # noqa: E402

BINS = [(0, 0, "0"), (1, 2, "1–2"), (3, 5, "3–5"), (6, 10 ** 6, "≥6")]


def day_mass(D: pd.DataFrame) -> pd.DataFrame:
    """m_day и m_3d по каждой сделке (см. шапку). D: sym, side, E."""
    out_day = np.zeros(len(D), int)
    out_3d = np.zeros(len(D), int)
    D = D.reset_index(drop=True)
    day = D.E.dt.floor("D")
    for side, g in D.groupby("side"):
        idx = g.sort_values("E").index.values
        Es, syms, days = D.E.values[idx], D.sym.values[idx], day.values[idx]
        for j, i in enumerate(idx):
            same = (days == days[j]) & (Es <= Es[j]) & (syms != syms[j])
            out_day[i] = len(set(syms[same]))
            prev = (days >= days[j] - np.timedelta64(3, "D")) & (days < days[j]) & (syms != syms[j])
            out_3d[i] = len(set(syms[prev]))
    return D.assign(m_day=out_day, m_3d=out_3d)


def main() -> int:
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else max(1, (os.cpu_count() or 2) - 6)
    D, proven = W.prepare(procs)
    D = D.assign(proven=proven.values).reset_index(drop=True)
    D = day_mass(D)
    D["R"] = D.pnl_re / D.stop_pct
    D["flow"] = np.where(D.side == "SHORT", "шорт", np.where(D.proven, "доказанный лонг", "лонг вне зоны"))
    D["y"] = D.E.dt.year
    # §0A.2 golden: ответ посчитан вручную. A первой за день → 0; B и C в один бар → видят A и друг друга (2);
    # D позже → A, B, C (3); повтор A себя не считает (B, C, D → 3); E назавтра → 0 за день, 4 монеты за 3 дня; шорт отдельно
    t = pd.Timestamp
    G = day_mass(pd.DataFrame({"sym": ["A", "B", "C", "D", "A", "E", "Z"], "side": ["LONG"] * 6 + ["SHORT"],
                               "E": [t("2026-09-16 01:00"), t("2026-09-16 05:00"), t("2026-09-16 05:00"), t("2026-09-16 09:00"),
                                     t("2026-09-16 12:00"), t("2026-09-17 03:00"), t("2026-09-16 09:00")]}))
    assert G.m_day.tolist() == [0, 2, 2, 3, 3, 0, 0], G.m_day.tolist()
    assert G.m_3d.tolist()[5] == 4 and G.m_3d.tolist()[0] == 0
    assert set(D.flow) <= {"шорт", "доказанный лонг", "лонг вне зоны"}

    print("=" * 112)
    print(f"МАССОВОСТЬ ДНЯ × ДЕНЬГИ ЯДРА ВОЛН · {len(D)} сделок · {D.E.min():%Y-%m-%d} → {D.E.max():%Y-%m-%d}")
    print("=" * 112)
    print(D[["sym", "side", "E", "flow", "m_day", "m_3d", "stop_pct", "pnl_re", "R"]].sort_values("E").head(4)
          .round(2).to_string(index=False))
    for flow, F in D.groupby("flow"):
        print(f"\n{flow}: n {len(F)} · средн {F.pnl_re.mean():+.2f}% · R {F.R.mean():+.3f}")
        print(f"  {'m_day':<6}{'n':>6}{'дней':>6}{'средн %':>9}{'медиана':>9}{'R':>8}{'в плюсе':>9}   по годам (средн %)")
        for lo, hi, lab in BINS:
            g = F[(F.m_day >= lo) & (F.m_day <= hi)]
            if len(g) < 10:
                print(f"  {lab:<6}{len(g):>6}")
                continue
            yy = " ".join(f"{y} {v:+.2f}({n})" for (y, v), n in zip(g.groupby("y").pnl_re.mean().items(), g.groupby("y").size()))
            print(f"  {lab:<6}{len(g):>6}{g.E.dt.floor('D').nunique():>6}{g.pnl_re.mean():>+9.2f}{g.pnl_re.median():>+9.2f}"
                  f"{g.R.mean():>+8.3f}{(g.pnl_re > 0).mean() * 100:>8.0f}%   {yy}")
        print(f"  {'m_3d':<6} (3 прошлых дня, справочно)")
        for lo, hi, lab in BINS:
            g = F[(F.m_3d >= lo) & (F.m_3d <= hi)]
            if len(g) >= 10:
                print(f"  {lab:<6}{len(g):>6}{g.E.dt.floor('D').nunique():>6}{g.pnl_re.mean():>+9.2f}{g.pnl_re.median():>+9.2f}"
                      f"{g.R.mean():>+8.3f}{(g.pnl_re > 0).mean() * 100:>8.0f}%")
    # карточка: кандидат m_day ≥ 3 против остального внутри своего потока, в % и в R
    for flow in ("доказанный лонг", "лонг вне зоны", "шорт"):
        F = D[D.flow == flow].reset_index(drop=True)
        for unit in ("pnl_re", "R"):
            DD = V.normalize(F.assign(pnl=F[unit], ts=F.E), pnl="pnl", ts="ts")
            V.card(DD, (F.m_day >= 3).values, name=f"{flow} × массовость дня ≥3 ({'%' if unit == 'pnl_re' else 'R'})",
                   study="wave-day-mass", geo=("stop_pct",))
    D.to_pickle("G:/oko_lab/out/wave_day_mass.pkl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
