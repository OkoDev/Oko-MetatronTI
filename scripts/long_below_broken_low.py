"""
long_below_broken_low.py — LONG ПОД ПРОБИТЫМ SWING-МИНИМУМОМ (29.08.2026).

Запрос Егора: «очень нужно лонг найти! ОЧЕНЬ». Слепой отбор по трём новым семьям дал
P(шум) = 0.300 — не отличимо от шума. Сработала НАЗВАННАЯ гипотеза, но с перевёрнутым
знаком, и это оказалось содержательнее перебора:

    цена ВЫШЕ swing low (поддержка держит)   n=330  PF 0.95  ×1.07
    цена НИЖЕ swing low (ПРОБОЙ)             n=258  PF 1.83  ×2.04

Физика — канонический liquidity grab: пробой поддержки собирает стопы, после чего цена
возвращается. Тот же механизм, что [[stop_on_line_is_liquidity_sweep]], но с обратной
стороны от EQH-находки для short ([[eqh_liquidity_short_works_in_2026]]).

🔴 Признак берётся из ПЕРЕСЧИТАННОЙ матрицы (`_lw`, боевое окно 1000 баров) — то есть
сразу в боевой конфигурации, без ловушки, на которой сгорел EQH: там замер шёл на полной
истории, и находка не воспроизвелась ([[window_sensitivity_only_smc_breaks]]).

Печатаются обязательные срезы протокола: плато глубины · год · зеркало на short ·
временной OOS · перестановка · охват монет и вклад лучших трёх.

    python scripts/long_below_broken_low.py
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

PQ = ROOT / "cache" / "matrix_run_15m_lw.parquet"
COL = "smc_swing_major_l_dist_atr_15m_lw"      # знаковая дистанция до старшего swing-минимума
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")


def main() -> int:
    X = pd.read_parquet(PQ)
    X["_ts"] = pd.to_datetime(X.entry_ts, utc=True, errors="coerce")
    lo, sh = X.side == "long", X.side == "short"
    d = X[COL]
    b = stat(X[lo])

    print("=" * 100)
    print(f"LONG ПОД ПРОБИТЫМ SWING-МИНИМУМОМ · {len(X)} сделок")
    print("=" * 100)
    print(line(X[lo], "  база все long"))

    print("\n🔑 ЗНАК ДИСТАНЦИИ — вся суть находки (порог 1.0 ATR):")
    for nm, m in (("цена ВЫШЕ уровня (поддержка держит)", lo & (d > 0) & (d <= 1.0)),
                  ("цена НИЖЕ уровня (ПРОБОЙ)", lo & (d < 0) & (d >= -1.0))):
        s = stat(X[m])
        if s:
            print(f"  {nm:<38} n={s['n']:>4}  PF {s['pf']:5.2f}  ×{s['pf']/b['pf']:.2f}"
                  f"  безтоп10% {s['bt']:+6.0f}")

    print("\nПЛАТО ГЛУБИНЫ ПРОБОЯ:")
    for lo_, hi_ in ((-0.5, 0), (-1.0, 0), (-1.5, 0), (-2.0, 0), (-3.0, 0)):
        m = lo & (d >= lo_) & (d < hi_)
        s = stat(X[m])
        if s:
            print(f"  {lo_:>5} .. {hi_:<4} n={s['n']:>4}  PF {s['pf']:5.2f}  ×{s['pf']/b['pf']:.2f}"
                  f"  безтоп10% {s['bt']:+6.0f}  охват {s['cov']:3.0f}%")

    m = lo & (d >= -1.0) & (d < 0)

    print("\nГОД (против базы long своего года):")
    for y in sorted(X.year.unique()):
        g = X[(X.year == y) & lo]
        a, bb = stat(g[m[g.index]]), stat(g)
        if a and bb and bb["pf"]:
            print(f"  {y}: PF {a['pf']:5.2f} (n={a['n']:>3}) против {bb['pf']:5.2f}"
                  f"  ×{a['pf']/bb['pf']:.2f}  безтоп10% {a['bt']:+6.0f}")
        else:
            print(f"  {y}: мало")

    ms = sh & (d >= -1.0) & (d < 0)
    ss, bs = stat(X[ms]), stat(X[sh])
    if ss and bs:
        print(f"\nЗЕРКАЛО short в той же зоне: PF {ss['pf']:.2f} (база short {bs['pf']:.2f})"
              f"  ×{ss['pf']/bs['pf']:.2f}   — должно быть НЕ лучше базы")

    print("\nВРЕМЕННОЙ OOS:")
    for lbl, sel in (("train", X._ts < SPLIT), ("test", X._ts >= SPLIT)):
        a, bb = stat(X[sel & m]), stat(X[sel & lo])
        if a and bb:
            print(f"  {lbl}: PF {a['pf']:5.2f} (n={a['n']:>3}) против {bb['pf']:5.2f}"
                  f"  ×{a['pf']/bb['pf']:.2f}  безтоп10% {a['bt']:+6.0f}")

    real = stat(X[m])["pf"] / b["pf"]
    rng = np.random.default_rng(121)
    noise = []
    for _ in range(50):
        Xs = X.assign(pnl=rng.permutation(X.pnl.values))
        a, bb = stat(Xs[m]), stat(Xs[lo])
        if a and bb and bb["pf"]:
            noise.append(a["pf"] / bb["pf"])
    noise = np.array(noise)
    p = float((noise >= real).mean())
    print(f"\n🎲 перестановка (50): наш ×{real:.2f} · шум макс ×{noise.max():.2f} · P={p:.3f} "
          + ("🟢" if p < 0.05 else "🟡" if p <= 0.15 else "🔴"))

    per = X[m].groupby("sym").pnl.sum().sort_values(ascending=False)
    print(f"охват: {int((per>0).sum())}/{len(per)} монет · сумма {per.sum():+.0f}%"
          f" · без лучших трёх {per.iloc[3:].sum():+.0f}%")

    print("\n── СВЯЗКА С БОЕВЫМ ДРЕЙФ-ГЕЙТОМ (гейт калиброван под short — проверяем) ──")
    gate = X.mkt_drift_slope > 0
    for nm, mm in (("long + гейт", lo & gate), ("long + пробой", m),
                   ("long + пробой + гейт", m & gate),
                   ("long + пробой БЕЗ гейта", m & ~gate)):
        s = stat(X[mm])
        if s:
            print(line(X[mm], f"  {nm:<26}"))

    print("\n🔴 Оговорка, которую нельзя терять: абсолютный PF в 2025-2026 ниже 1.")
    print("   Подъём есть, но год в плюс не выводит — это фильтр «где long менее плох».")
    return 0


if __name__ == "__main__":
    sys.exit(main())
