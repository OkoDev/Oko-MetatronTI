"""
rs_probe.py — ДАЁТ ЛИ ОТНОСИТЕЛЬНАЯ СИЛА МОНЕТЫ LONG-ЭДЖ (30.08.2026).

Егор возразил: «не может рынок давать только одну сторону». Инвентаризация подтвердила
его правоту и показала, ГДЕ была моя ошибка:

    2023 (единственный бычий год окна):  long PF 1.53 · short PF 0.13  — зеркало идеальное
    2024-2026 (три медвежьих):           long 1.35/0.64/0.48

Рынок двусторонний. Односторонне ОКНО. Но разрез по макро-режиму вселенной long не спас:
на КАЖДОЙ такой оси short растёт сильнее long (до ×6.02 против ×0.90) — признаки MKT
описывают рынок целиком, а рынок в этом окне медвежий.

Гипотеза, которую проверяем здесь: **long — свойство МОНЕТЫ, а не рынка.** Даже в худший
2026 три монеты из сорока дают long в плюс. Признака, отбирающего их, в матрице не было
НИКОГДА: среди 753 колонок ни одной про «сильнее ли монета вселенной».

Проба дешёвая: RS-панель приклеивается к готовой матрице по (день, символ), полный
пересчёт (часы) запускается только если проба покажет сигнал.

🔴 Обязательное к печати: зеркало short (ось обязана быть ОДНОСТОРОННЕЙ, иначе это
просто «хорошая среда»), состав по годам (иначе переименованный календарь), хрупкость.

    python scripts/rs_probe.py
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

from research_harness import stat                    # noqa: E402
from scripts.matrix_full import rs_context           # noqa: E402

PQ = ROOT / "cache" / "matrix_run_15m.parquet"
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")


def attach(X: pd.DataFrame) -> pd.DataFrame:
    """Приклеить RS по (день входа, символ). RS уже сдвинут на закрытый день."""
    RS = rs_context()
    X = X.copy()
    X["_ts"] = pd.to_datetime(X.entry_ts, utc=True, errors="coerce")
    X["_day"] = X._ts.dt.floor("D")
    idx = pd.MultiIndex.from_arrays([X._day, X.sym], names=["day", "symbol"])
    got = RS.reindex(idx)
    for c in RS.columns:
        X[c] = got[c].values
    return X


def probe(X: pd.DataFrame, col: str, side: str) -> None:
    """Один RS-признак: децили → PF, зеркало, состав по годам."""
    S = X[X.side == side]
    O = X[X.side == ("short" if side == "long" else "long")]
    b, bo = stat(S), stat(O)
    v = S[col].dropna()
    if not b or v.nunique() < 5:
        return
    print(f"\n── {col} ── (база {side} PF {b['pf']:.2f})")
    for lbl, q1, q2 in (("нижние 20%", 0.0, 0.2), ("20-40%", 0.2, 0.4),
                        ("40-60%", 0.4, 0.6), ("60-80%", 0.6, 0.8),
                        ("ВЕРХНИЕ 20%", 0.8, 1.0)):
        lo_, hi_ = v.quantile(q1), v.quantile(q2)
        m = (S[col] >= lo_) & (S[col] <= hi_) if q2 == 1.0 else (S[col] >= lo_) & (S[col] < hi_)
        mo = (O[col] >= lo_) & (O[col] <= hi_) if q2 == 1.0 else (O[col] >= lo_) & (O[col] < hi_)
        s, so = stat(S[m]), stat(O[mo])
        if not s:
            continue
        mir = f"зерк {so['pf']:.2f} ×{so['pf']/bo['pf']:.2f}" if so and bo["pf"] else "зерк —"
        vc = S[m].year.value_counts(normalize=True)
        top = float(vc.max()) if len(vc) else 1.0
        flag = " 🔴ОДИН ГОД" if top >= 0.7 else ""
        mark = ""
        if s["pf"] >= 1.0 and s["pf"] / b["pf"] >= 1.3 and top < 0.7:
            mark = " 🟢"
        print(f"   {lbl:<12} [{lo_:>8.1f}..{hi_:>8.1f}] n={s['n']:>4} PF {s['pf']:5.2f}"
              f" ×{s['pf']/b['pf']:.2f} безтоп10% {s['bt']:+6.0f} охват {s['cov']:3.0f}%"
              f"  {mir}{flag}{mark}")


def main() -> int:
    X = attach(pd.read_parquet(PQ))
    cols = ["rs30", "rs90", "rs180", "rs_rank30", "rs_rank90", "rs_slope",
            "own_above_ma200", "rs_days_up30", "beta_btc", "corr_btc90"]
    have = [c for c in cols if c in X.columns and X[c].notna().sum() > 500]

    print("=" * 106)
    print(f"ПРОБА RS · {len(X)} сделок · признаков приклеено {len(have)}"
          f" · покрытие {X[have[0]].notna().mean()*100:.0f}%")
    print("=" * 106)
    print("критерий интереса: PF>1 · подъём ≥×1.3 · НЕ один год · зеркало НЕ лучше")

    for c in have:
        probe(X, c, "long")

    print("\n" + "=" * 106)
    print("ЛУЧШИЕ КЛЕТКИ LONG (полный протокол по каждой)")
    print("🔴 отбор идёт ДИАПАЗОНАМИ, а не порогами: кривая RS оказалась СЕРЕДИННОЙ —")
    print("   и нижние 20% (падающий нож), и верхние 20% (моментум) хуже базы, живёт середина.")
    print("🔴 требуется ОДНОСТОРОННОСТЬ: зеркало short не лучше своей базы. Иначе это не")
    print("   long-ось, а просто «хорошая среда», где растут обе стороны.")
    L = X[X.side == "long"]
    O = X[X.side == "short"]
    bl, bo = stat(L), stat(O)
    best = []
    for c in have:
        v = L[c].dropna()
        for q1, q2 in ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0),
                       (0.2, 0.6), (0.3, 0.7), (0.4, 0.8)):
            lo_, hi_ = float(v.quantile(q1)), float(v.quantile(q2))
            m = (L[c] >= lo_) & (L[c] <= hi_)
            mo = (O[c] >= lo_) & (O[c] <= hi_)
            s, so = stat(L[m]), stat(O[mo])
            if not (s and s["n"] >= 300 and s["pf"] >= 1.0 and s["pf"] / bl["pf"] >= 1.25):
                continue
            if so and bo["pf"] and so["pf"] / bo["pf"] > 1.0:
                continue                       # зеркало растёт — среда, а не long-ось
            vc = L[m].year.value_counts(normalize=True)
            if float(vc.max()) < 0.7:
                mir = so["pf"] / bo["pf"] if so and bo["pf"] else float("nan")
                best.append((s["pf"] / bl["pf"],
                             f"{lo_:.4g}<={c}<={hi_:.4g}  [зерк ×{mir:.2f}]", m, s))
    best.sort(reverse=True, key=lambda x: x[0])
    seen = set()
    for mult, nm, m, s in best:
        base = next(c for c in have if c in nm)
        if base in seen:
            continue
        seen.add(base)
        print(f"\n🔹 {nm}   n={s['n']} PF {s['pf']:.2f} ×{mult:.2f} безтоп10% {s['bt']:+.0f}"
              f" охват {s['cov']:.0f}%")
        for y in sorted(L.year.dropna().unique()):
            g = L[L.year == y]
            a, bb = stat(g[m[g.index]]), stat(g)
            if a and bb and bb["pf"]:
                print(f"      {int(y)}: PF {a['pf']:5.2f} (n={a['n']:>4}) против {bb['pf']:5.2f}"
                      f"  ×{a['pf']/bb['pf']:.2f}")
        for lbl, sel in (("train", L._ts < SPLIT), ("test", L._ts >= SPLIT)):
            a, bb = stat(L[sel & m]), stat(L[sel])
            if a and bb and bb["pf"]:
                print(f"      {lbl}: PF {a['pf']:5.2f} (n={a['n']:>4}) ×{a['pf']/bb['pf']:.2f}")
        rng = np.random.default_rng(7)
        real = s["pf"] / bl["pf"]
        noise = []
        for _ in range(50):
            Ls = L.assign(pnl=rng.permutation(L.pnl.values))
            a, bb = stat(Ls[m]), stat(Ls)
            if a and bb and bb["pf"]:
                noise.append(a["pf"] / bb["pf"])
        p = float((np.array(noise) >= real).mean())
        print(f"      🎲 перестановка(50): наш ×{real:.2f} шум макс ×{max(noise):.2f}"
              f" P={p:.3f} " + ("🟢" if p < 0.05 else "🟡" if p <= 0.15 else "🔴"))
    if not best:
        print("\nНИ ОДНОЙ клетки: RS не даёт long-подъёма ≥×1.25 при составе из нескольких лет.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
