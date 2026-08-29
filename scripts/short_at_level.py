"""
short_at_level.py — SHORT У ЗНАЧИМОГО УРОВНЯ СВЕРХУ: три независимые оси (29.08.2026).

Все три появились только после переписывания SMC из СОБЫТИЙ в СОСТОЯНИЯ
([[smc_in_matrix_is_dead_weight]]): раньше `bull_ob` помечал 4 бара из 19 851, а свингов
и sponsored candle в матрице не было вовсе, хотя детекторы находят 2983 и 318 событий.

  EQH        цена в пределах X·ATR от уровня равных хаёв — скопление стопов сверху
  SC bear    цена в зоне медвежьей sponsored candle (свеча, снявшая ликвидность)
  swing H    цена у старшего swing-максимума

Гипотезы НАЗВАНЫ заранее (канон SMC/ICT: у сопротивления шортим), поэтому меряются прямо,
а не выкапываются перебором — слепой отбор по всей семье SMC значимости не дал (P = 0.100).

🔴 Что скрипт печатает обязательно, а не по желанию: зеркало (long у тех же уровней),
разрез по годам против базы СВОЕГО года, временной OOS, перестановочный контроль, охват
монет и вклад лучших трёх. Без этого вердикт по протоколу выносить нельзя.

    python scripts/short_at_level.py
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:      # noqa: BLE001
    pass

from research_harness import line, stat        # noqa: E402

PQ = ROOT / "cache" / "matrix_run_15m.parquet"
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")


def main() -> int:
    R = pd.read_parquet(PQ)
    R["_ts"] = pd.to_datetime(R.entry_ts, utc=True, errors="coerce")
    gate = R.mkt_drift_slope > 0
    sh, lo = R.side == "short", R.side == "long"

    axes = {
        "EQH (равные хаи)":        R.near_smc_eqh_15m == 1.0,
        "SC bear (зона свечи)":    R.in_smc_bear_spons_15m == 1.0,
        "swing MAJOR high":        R.near_smc_swing_major_h_15m == 1.0,
    }
    b_sh, b_lo = stat(R[gate & sh]), stat(R[gate & lo])

    print("=" * 104)
    print(f"SHORT У ЗНАЧИМОГО УРОВНЯ · сделок {len(R)} · монет {R.sym.nunique()}")
    print("=" * 104)
    print(line(R[gate & sh], "  БАЗА гейт+short"))
    print(line(R[gate & lo], "  БАЗА гейт+long (для зеркала)"))

    print("\n── ОСИ ПО ОТДЕЛЬНОСТИ ──")
    for nm, m in axes.items():
        s = stat(R[gate & sh & m])
        if s:
            print(line(R[gate & sh & m], f"  {nm:<24}") +
                  f"  ×{s['pf'] / b_sh['pf']:.2f}")

    print("\n── ЗЕРКАЛО: те же уровни, но LONG (должно быть не лучше базы) ──")
    for nm, m in axes.items():
        s = stat(R[gate & lo & m])
        if s:
            print(f"  {nm:<24} long PF {s['pf']:5.2f} (n={s['n']:>4}) против базы "
                  f"{b_lo['pf']:.2f}  ×{s['pf'] / b_lo['pf']:.2f}")

    print("\n── НЕЗАВИСИМЫ ЛИ (Жаккар попарно) ──")
    ks = list(axes)
    for i, a in enumerate(ks):
        for b in ks[i + 1:]:
            ma, mb = axes[a], axes[b]
            print(f"  {a[:12]:<13} ∩ {b[:12]:<13} {(ma & mb).sum() / (ma | mb).sum():.3f}")

    any3 = np.logical_or.reduce([m.values for m in axes.values()])
    print("\n── ОБЪЕДИНЕНИЕ ──")
    print(line(R[gate & sh & any3], "  любой из трёх"))
    print(line(R[gate & sh & ~any3], "  ни одного"))

    print("\n── ГОД (против базы гейт+short СВОЕГО года) ──")
    for nm, m in list(axes.items()) + [("любой из трёх", pd.Series(any3, index=R.index))]:
        cells = []
        for y in sorted(R.year.unique()):
            g = R[(R.year == y) & gate & sh]
            a, b = stat(g[m[g.index]]), stat(g)
            cells.append(f"{y} ×{a['pf'] / b['pf']:5.2f} ({a['bt']:+5.0f})"
                         if (a and b and b["pf"]) else f"{y} мало       ")
        print(f"  {nm:<24} " + " | ".join(cells))

    print("\n── ВРЕМЕННОЙ OOS (train < 2025 → test 2025-26) ──")
    tr, te = R._ts < SPLIT, R._ts >= SPLIT
    for nm, m in axes.items():
        row = []
        for lbl, sel in (("train", tr), ("test", te)):
            a, b = stat(R[sel & gate & sh & m]), stat(R[sel & gate & sh])
            row.append(f"{lbl} ×{a['pf'] / b['pf']:.2f} (n={a['n']})"
                       if (a and b and b["pf"]) else f"{lbl} мало")
        print(f"  {nm:<24} " + " · ".join(row))

    print("\n🎲 ПЕРЕСТАНОВОЧНЫЙ КОНТРОЛЬ (50 перемешиваний на каждую ось)")
    rng = np.random.default_rng(61)
    for nm, m in axes.items():
        real = stat(R[gate & sh & m])["pf"] / b_sh["pf"]
        noise = []
        for _ in range(50):
            Rs = R.assign(pnl=rng.permutation(R.pnl.values))
            a, b = stat(Rs[gate & sh & m]), stat(Rs[gate & sh])
            if a and b and b["pf"]:
                noise.append(a["pf"] / b["pf"])
        noise = np.array(noise)
        p = float((noise >= real).mean())
        print(f"  {nm:<24} наш ×{real:.2f} · шум макс ×{noise.max():.2f} · P={p:.3f} "
              + ("🟢" if p < 0.05 else "🟡" if p <= 0.15 else "🔴"))

    print("\n── ОХВАТ МОНЕТ И ВКЛАД ЛУЧШИХ ──")
    for nm, m in list(axes.items()) + [("любой из трёх", pd.Series(any3, index=R.index))]:
        sub = R[gate & sh & m]
        per = sub.groupby("sym").pnl.sum().sort_values(ascending=False)
        if len(per) < 4:
            continue
        print(f"  {nm:<24} {int((per > 0).sum())}/{len(per)} монет · сумма {per.sum():+.0f}%"
              f" · без лучших трёх {per.iloc[3:].sum():+.0f}%")

    print("\n🔴 ГЛАВНАЯ ОГОВОРКА: 2026 проходит ТОЛЬКО чистый EQH и только БЕЗ гейта.")
    print("   Объединение осей в 2026 не спасает, а размывает.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
