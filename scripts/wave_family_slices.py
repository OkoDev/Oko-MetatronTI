# -*- coding: utf-8 -*-
"""
ARCH-137 · обязательные срезы протокола `research-verdict` для волнового набора.

Секция 2 протокола: вердикт по общей строке ЗАПРЕЩЁН. Режем набор по
сторона · год · РЕЖИМ ГОДА · РАЗМЕР СТОПА · КЛАСТЕР · ЛИКВИДНОСТЬ,
печатаем хрупкость и охват монет в каждой строке.

Запуск:
    python scripts/wave_family_slices.py --tf 15m --side short
    python scripts/wave_family_slices.py --tf 1h  --side long
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from scripts.research_harness import line, stat  # noqa: E402
from scripts.wave_family_combo import AXES, m_of  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FILES = {"15m": ROOT / "cache/matrix_core_15m.parquet",
         "1h": ROOT / "cache/matrix_core_1h.parquet"}


def regime_of_years(df: pd.DataFrame) -> dict:
    """РЕЖИМ КАЖДОГО ГОДА считаем из данных, а не из памяти (секция 1.2 протокола).

    Прокси режима — медиана `mkt_drift90` по сделкам года: это дрейф вселенной,
    посчитанный при сборе матрицы, а не наша интерпретация.
    """
    out = {}
    if "mkt_drift90" not in df.columns:
        return out
    for y, g in df.groupby("year"):
        d = float(g["mkt_drift90"].median())
        out[int(y)] = ("БЫК" if d > 3 else "МЕДВЕДЬ" if d < -3 else "НЕЙТРАЛЬ", d)
    return out


def cluster_flag(df: pd.DataFrame) -> pd.Series:
    """КЛАСТЕР: ≥2 сделки набора в один день по РАЗНЫМ монетам = рыночное движение,
    а не свойство пары. Считаем по дате входа."""
    if "entry_ts" not in df.columns:
        return pd.Series(False, index=df.index)
    d = pd.to_datetime(df["entry_ts"], errors="coerce", utc=True).dt.floor("D")
    per_day = df.assign(_d=d).groupby("_d").sym.nunique()
    return d.map(per_day).fillna(1).astype(int).ge(2)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="15m")
    ap.add_argument("--side", default="short")
    a = ap.parse_args()

    df = pd.read_parquet(FILES[a.tf])
    own = df[df.side == a.side].copy()
    axes = AXES[(a.tf, a.side)]
    m = m_of(own, axes[0][1], axes[0][2], axes[0][3])
    for _, f, o, t in axes[1:]:
        m = m & m_of(own, f, o, t)
    cell = own[m]
    b = stat(own)

    print("#" * 104)
    print(f"# ARCH-137 · ОБЯЗАТЕЛЬНЫЕ СРЕЗЫ · ТФ {a.tf} · {FILES[a.tf].name} · "
          f"сторона {a.side}")
    print(f"# набор: {' И '.join(f'{f} {o} {t}' for _, f, o, t in axes)}")
    print("#" * 104)
    print(line(own, "БАЗА"))
    print(line(cell, "НАБОР") + f"   подъём ×{stat(cell)['pf'] / b['pf']:.2f}")

    # ── 1. ИНВЕНТАРИЗАЦИЯ: режим каждого года из данных ───────────────────
    print("\n" + "=" * 104)
    print("1. РЕЖИМ КАЖДОГО ГОДА (медиана mkt_drift90 по сделкам года, из данных)")
    print("=" * 104)
    reg = regime_of_years(own)
    for y in sorted(reg):
        nm, d = reg[y]
        print(f"   {y}: {nm:<9} дрейф90 медиана {d:+.2f}%   сделок базы {int((own.year == y).sum())}")
    if not any(v[0] == "БЫК" for v in reg.values()):
        print("   🔴 В ОКНЕ НЕТ БЫЧЬЕГО ГОДА — вердикт заведомо односторонний")

    print("\n   НАБОР по режиму года:")
    for nm in ("БЫК", "НЕЙТРАЛЬ", "МЕДВЕДЬ"):
        yrs = [y for y, v in reg.items() if v[0] == nm]
        if not yrs:
            continue
        sub_b = own[own.year.isin(yrs)]
        sub_c = cell[cell.year.isin(yrs)]
        s_c, s_b = stat(sub_c), stat(sub_b)
        lift = f"×{s_c['pf'] / s_b['pf']:.2f}" if s_c and s_b and s_b["pf"] else "—"
        print(line(sub_c, f"  {nm} {yrs}") + f"   подъём {lift}")

    # ── 2. РАЗМЕР СТОПА ───────────────────────────────────────────────────
    print("\n" + "=" * 104)
    print("2. РАЗМЕР СЕТАПА (корзины стопа) — закон размера подтверждён 3× на разных механиках")
    print("=" * 104)
    for lo, hi in ((0, 1.5), (1.5, 2.2), (2.2, 3.234), (3.234, 100)):
        sb = own[(own.stop_pct >= lo) & (own.stop_pct < hi)]
        sc = cell[(cell.stop_pct >= lo) & (cell.stop_pct < hi)]
        s_c, s_b = stat(sc), stat(sb)
        lift = f"×{s_c['pf'] / s_b['pf']:.2f}" if s_c and s_b and s_b["pf"] else "—"
        print(line(sc, f"  стоп {lo}-{hi}%") + f"   подъём к базе корзины {lift}")

    # ── 3. КЛАСТЕР ────────────────────────────────────────────────────────
    print("\n" + "=" * 104)
    print("3. КОМПАНИЯ: одиночка против кластера (≥2 монеты в один день)")
    print("=" * 104)
    # 🔴 Кластер считаем на ПОЛНОЙ базе, иначе «≥2 монеты в день» внутри набора —
    # это другое событие, чем в бою, и сравнивать не с чем.
    cl_all = cluster_flag(own)
    cl = cl_all.loc[cell.index]
    print(line(cell[~cl], "  набор · одиночка"))
    print(line(cell[cl], "  набор · кластер ≥2"))
    print(line(own[~cl_all], "  БАЗА · одиночка"))
    print(line(own[cl_all], "  БАЗА · кластер ≥2"))
    s_bc, s_nc = stat(own[cl_all]), stat(cell[cl])
    if s_bc and s_nc and s_bc["pf"]:
        print(f"\n  🔑 подъём набора ВНУТРИ кластера: ×{s_nc['pf'] / s_bc['pf']:.2f}"
              f"   (если ≈1.0 — волна была просто прокси кластера)")
    s_bs, s_ns = stat(own[~cl_all]), stat(cell[~cl])
    if s_bs and s_ns and s_bs["pf"]:
        print(f"     подъём набора среди одиночек:   ×{s_ns['pf'] / s_bs['pf']:.2f}")

    # ── 4. ЛИКВИДНОСТЬ ────────────────────────────────────────────────────
    print("\n" + "=" * 104)
    print("4. ЛИКВИДНОСТЬ (rs_rank30 как прокси размера монеты; vratio — объём входа)")
    print("=" * 104)
    for col in ("vratio", "rs_rank30"):
        if col not in cell.columns:
            continue
        q = cell[col].quantile([0, .33, .66, 1]).values
        for i in range(3):
            lo, hi = q[i], q[i + 1]
            sub = cell[(cell[col] >= lo) & (cell[col] <= hi)]
            print(line(sub, f"  {col} {lo:.2f}-{hi:.2f}"))

    # ── 5. ОХВАТ МОНЕТ ────────────────────────────────────────────────────
    print("\n" + "=" * 104)
    print("5. ОХВАТ: сколько монет в плюсе и держится ли без лучших")
    print("=" * 104)
    per = cell.groupby("sym").pnl.sum().sort_values(ascending=False)
    print(f"   монет в наборе {len(per)} · в плюсе {int((per > 0).sum())} "
          f"({(per > 0).mean() * 100:.0f}%)")
    print(f"   сумма всего {per.sum():+.0f}% · без топ-1 {per.iloc[1:].sum():+.0f}% · "
          f"без топ-3 {per.iloc[3:].sum():+.0f}% · без топ-10% "
          f"{per.iloc[int(len(per) * 0.1):].sum():+.0f}%")


if __name__ == "__main__":
    main()
