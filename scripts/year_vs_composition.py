"""
year_vs_composition.py — ГОД ИЛИ СОСТАВ? (30.08.2026)

Вопрос Егора: «выводы вида "2023 работал, 2026 нет" — как проверять будем?»

Повод. Инвентаризация показала, что вселенная замера меняется по годам:

    2023: 15 монет · ВСЕ из ядра (100%)
    2024: 22 монеты · из ядра 15
    2025: 36 монет · из ядра 15
    2026: 40 монет · из ядра 15 (37%)

2023 состоит ТОЛЬКО из монет, доживших до сегодня. 2026 на две трети — из монет, которых
в 2023 в данных не было. Значит любое «в 2023 работало, в 2026 нет» имеет ДВА объяснения,
и они неразличимы в общей строке:
    (а) изменился РЫНОК;
    (б) изменился СОСТАВ монет.

Три теста, от самого чистого к самому общему.

ТЕСТ 1 — СОСТАВ БЕЗ ПРИМЕСИ ВРЕМЕНИ (самый чистый).
    Внутри ОДНОГО года сравнить монеты ядра и монеты-новички. Время одно, рынок один,
    различается только состав. Если новички ведут себя иначе — состав влияет ДОКАЗАННО.

ТЕСТ 2 — ВРЕМЯ БЕЗ ПРИМЕСИ СОСТАВА (балансированная панель).
    Все годовые сравнения на одних и тех же 15 монетах ядра. Если вывод сохраняется —
    он о рынке. Если исчезает — он был о составе.

ТЕСТ 3 — ДЕКОМПОЗИЦИЯ.
    Δ_total = M(год A, все) − M(год B, все)        ← то, что мы докладывали
    Δ_core  = M(год A, ядро) − M(год B, ядро)      ← чистый эффект времени
    Δ_comp  = Δ_total − Δ_core                     ← вклад состава
    Доля состава = |Δ_comp| / |Δ_total|. Больше 0.5 — вывод в основном о составе.

🔴 ОГРАНИЧЕНИЕ МЕТОДА, которое нельзя замалчивать: ядро — это ВЫЖИВШИЕ монеты. Если явление
жило только в монетах, которые с тех пор ушли, ядро его не покажет. Тест отвечает на вопрос
«не составом ли объясняется разница», а НЕ на вопрос «как вело себя всё, что торговалось».

    python scripts/year_vs_composition.py
    python scripts/year_vs_composition.py --col rs_rank30 --lo 26.2 --hi 48.5
"""
from __future__ import annotations

import argparse
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

from research_harness import stat        # noqa: E402

PQ = ROOT / "cache" / "matrix_run_15m.parquet"


def core_symbols(X: pd.DataFrame) -> set[str]:
    """Монеты, торговавшиеся ВО ВСЕ годы окна — балансированная панель."""
    g = X.groupby("sym").year.nunique()
    return set(g[g == X.year.nunique()].index)


def pf(X: pd.DataFrame) -> float:
    s = stat(X)
    return float(s["pf"]) if s else float("nan")


def test1_composition(X: pd.DataFrame, core: set[str], side: str) -> None:
    """Внутри одного года: ядро против новичков. Время одно — различается только состав."""
    print("\n" + "─" * 96)
    print("ТЕСТ 1 · СОСТАВ БЕЗ ПРИМЕСИ ВРЕМЕНИ — внутри ОДНОГО года: ядро против новичков")
    print("─" * 96)
    S = X[X.side == side]
    print(f"  {'год':<6} {'ядро PF':>10} {'n':>6}   {'новички PF':>12} {'n':>6}   {'разрыв':>8}")
    for y in sorted(S.year.dropna().unique()):
        g = S[S.year == y]
        a, b = g[g.sym.isin(core)], g[~g.sym.isin(core)]
        if not len(b):
            print(f"  {int(y):<6} {pf(a):>10.2f} {len(a):>6}   {'— новичков нет':>19}")
            continue
        pa, pb = pf(a), pf(b)
        gap = pb / pa if pa and not np.isnan(pa) and pa > 0 else float("nan")
        flag = ""
        if not np.isnan(gap) and (gap >= 1.4 or gap <= 0.7):
            flag = "  🔴 состав ВЛИЯЕТ"
        print(f"  {int(y):<6} {pa:>10.2f} {len(a):>6}   {pb:>12.2f} {len(b):>6}   ×{gap:>6.2f}{flag}")
    print("  🔑 если новички систематически хуже/лучше ядра — годовые сравнения загрязнены составом")


def test2_panel(X: pd.DataFrame, core: set[str]) -> None:
    """Балансированная панель: те же 15 монет во все годы."""
    print("\n" + "─" * 96)
    print(f"ТЕСТ 2 · ВРЕМЯ БЕЗ ПРИМЕСИ СОСТАВА — только ядро ({len(core)} монет во все годы)")
    print("─" * 96)
    print(f"  {'год':<6} │ {'ВСЯ вселенная':^28} │ {'ТОЛЬКО ЯДРО':^28}")
    print(f"  {'':<6} │ {'long':>9} {'short':>9} {'n':>7} │ {'long':>9} {'short':>9} {'n':>7}")
    for y in sorted(X.year.dropna().unique()):
        g = X[X.year == y]
        c = g[g.sym.isin(core)]
        print(f"  {int(y):<6} │ {pf(g[g.side=='long']):>9.2f} {pf(g[g.side=='short']):>9.2f}"
              f" {len(g):>7} │ {pf(c[c.side=='long']):>9.2f} {pf(c[c.side=='short']):>9.2f}"
              f" {len(c):>7}")
    print("  🔑 если картина по годам на ядре ДРУГАЯ — вывод был о составе, а не о рынке")


def test3_decompose(X: pd.DataFrame, core: set[str], side: str,
                    mask: pd.Series | None = None, label: str = "база") -> None:
    """Разложить разницу между годами на вклад времени и вклад состава."""
    print("\n" + "─" * 96)
    print(f"ТЕСТ 3 · ДЕКОМПОЗИЦИЯ РАЗНИЦЫ МЕЖДУ ГОДАМИ · {side} · {label}")
    print("─" * 96)
    S = X[X.side == side]
    if mask is not None:
        S = S[mask.reindex(S.index, fill_value=False)]
    yrs = sorted(S.year.dropna().unique())
    if len(yrs) < 2:
        print("  недостаточно лет")
        return
    print(f"  {'пара лет':<14} {'Δ вся вселенная':>17} {'Δ ядро (время)':>17}"
          f" {'Δ состав':>11} {'доля состава':>14}")
    for i in range(len(yrs) - 1):
        for j in range(i + 1, len(yrs)):
            ya, yb = yrs[i], yrs[j]
            A, B = S[S.year == ya], S[S.year == yb]
            Ac, Bc = A[A.sym.isin(core)], B[B.sym.isin(core)]
            if min(len(A), len(B), len(Ac), len(Bc)) < 30:
                continue
            d_tot = pf(A) - pf(B)
            d_core = pf(Ac) - pf(Bc)
            d_comp = d_tot - d_core
            share = abs(d_comp) / abs(d_tot) if abs(d_tot) > 1e-9 else float("nan")
            flag = ""
            if not np.isnan(share):
                flag = ("  🔴 в основном СОСТАВ" if share > 0.5
                        else "  🟢 в основном ВРЕМЯ" if share < 0.25 else "  🟡 пополам")
            print(f"  {int(ya)} против {int(yb):<4} {d_tot:>+17.2f} {d_core:>+17.2f}"
                  f" {d_comp:>+11.2f} {share*100:>13.0f}%{flag}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--side", default="long", choices=["long", "short"])
    ap.add_argument("--col", default=None, help="проверить конкретную находку")
    ap.add_argument("--lo", type=float, default=None)
    ap.add_argument("--hi", type=float, default=None)
    a = ap.parse_args()

    X = pd.read_parquet(PQ)
    if a.col and a.col not in X.columns:
        # признаки RS живут в отдельной панели и приклеиваются по (день, символ)
        from scripts.rs_probe import attach
        X = attach(X)
    core = core_symbols(X)

    print("=" * 96)
    print(f"ГОД ИЛИ СОСТАВ · {len(X)} сделок · {X.sym.nunique()} монет · ядро {len(core)}")
    print("=" * 96)
    for y in sorted(X.year.dropna().unique()):
        s = set(X[X.year == y].sym)
        print(f"  {int(y)}: {len(s):>3} монет · из ядра {len(s & core):>2}"
              f" ({len(s & core)/len(s)*100:>3.0f}%) · новичков {len(s - core):>2}")

    test1_composition(X, core, a.side)
    test2_panel(X, core)
    test3_decompose(X, core, a.side)

    if a.col and a.col in X.columns and a.lo is not None:
        m = (X[a.col] >= a.lo) & (X[a.col] <= a.hi)
        print("\n" + "=" * 96)
        print(f"ПРОВЕРКА НАХОДКИ: {a.lo} <= {a.col} <= {a.hi}")
        print("=" * 96)
        S = X[(X.side == a.side)]
        print(f"  {'год':<6} {'вся вселенная':>28} {'только ядро':>28}")
        for y in sorted(X.year.dropna().unique()):
            g = S[S.year == y]
            gm = g[m.reindex(g.index, fill_value=False)]
            c = g[g.sym.isin(core)]
            cm = c[m.reindex(c.index, fill_value=False)]
            if len(gm) < 10 or len(cm) < 10:
                print(f"  {int(y):<6} мало сделок (вся {len(gm)}, ядро {len(cm)})")
                continue
            r1 = pf(gm) / pf(g) if pf(g) else float("nan")
            r2 = pf(cm) / pf(c) if pf(c) else float("nan")
            print(f"  {int(y):<6} PF {pf(gm):5.2f} ×{r1:4.2f} (n={len(gm):>3})"
                  f"      PF {pf(cm):5.2f} ×{r2:4.2f} (n={len(cm):>3})")
        test3_decompose(X, core, a.side, m, f"{a.col} ∈ [{a.lo}, {a.hi}]")

    print("\n" + "=" * 96)
    print("🔴 ОГРАНИЧЕНИЕ: ядро — это ВЫЖИВШИЕ монеты. Если явление жило только в тех,")
    print("   что с тех пор ушли, ядро его не покажет. Тест отвечает «не составом ли")
    print("   объясняется разница», а не «как вело себя всё, что торговалось».")
    return 0


if __name__ == "__main__":
    sys.exit(main())
