# -*- coding: utf-8 -*-
"""
ARCH-137 · ШАГИ 3-5: зеркало · годы/месяцы · перекрытие клеток.

Берёт клетки, пережившие слепой отбор (`wave_family_run.py`), и прогоняет их
через обязательные проверки критериев 4-6:

  критерий 4  n≥100 и монет≥30 в КЛЕТКЕ
  критерий 5  ЗЕРКАЛО — та же клетка на противоположной стороне; рост обеих = среда
  критерий 6  ГОДЫ — подъём >1.0 в ≥3 годах, ни одного < 0.7
  + месяцы (устойчивость внутри года)
  + ЖАККАР между клетками: три «находки» об одном — это одна ось, а не три

🔑 Клетка задаётся тройкой (признак, сторона порога, число) — тем же числом,
   что выбрано на IS. Пересчёта квантиля нет намеренно.

Запуск:
    python scripts/wave_family_cells.py --tf 1h --side long
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

ROOT = Path(__file__).resolve().parent.parent
FILES = {
    "15m": ROOT / "cache/matrix_core_15m.parquet",
    "1h": ROOT / "cache/matrix_core_1h.parquet",
    "1h_wide": ROOT / "cache/matrix_core_1h_wide.parquet",
    "4h_wide": ROOT / "cache/matrix_core_4h_wide.parquet",
}

# Клетки, пережившие OOS на 1h long (прогон 01.09, w137_1h.log).
# Порог — ТО ЖЕ ЧИСЛО, что выбрано на IS.
CELLS_1H_LONG = [
    ("leg_age_origin_1h", "≤", 86.0),
    ("leg_span_bars_1h", "≤", 86.0),
    ("leg_speed_atr_1h", "≥", 0.1526),
    ("leg_minor_breaks_1h", "≤", 5.0),
    ("leg_amp_atr_4h__from_4h", "≥", 13.16),
]
# Клетки, пережившие OOS на 15m short (прогон 01.09, w137_15m.log).
# leg_dir > 0 = нога ВВЕРХ (код: d_ = +1 при lg["trend"] == "long"), порог 0.5 разделяет ±1.
CELLS_15M_SHORT = [
    ("leg_dir_4h__from_4h", "≥", 0.5),
    ("leg_span_bars_4h__from_4h", "≥", 107.0),
    ("leg_amp_atr_4h__from_4h", "≥", 13.457),
    ("leg_speed_atr_4h__from_4h", "≤", 0.14197),
    ("leg_minor_per100_15m", "≥", 5.3333),
    ("leg_amp_pct_1h__from_1h", "≤", 16.119),
]

CELLS = {
    ("1h", "long"): CELLS_1H_LONG,
    ("15m", "short"): CELLS_15M_SHORT,
}


def mask_of(df: pd.DataFrame, feat: str, op: str, thr: float) -> pd.Series:
    v = df[feat]
    m = (v >= thr) if op == "≥" else (v <= thr)
    return m.fillna(False)


def lift(sub_st: dict | None, base_st: dict | None) -> str:
    if sub_st is None or base_st is None or not base_st["pf"]:
        return "  —  "
    return f"×{sub_st['pf'] / base_st['pf']:.2f}"


def check_cell(df: pd.DataFrame, side: str, feat: str, op: str, thr: float) -> None:
    own = df[df.side == side]
    other = df[df.side != side]
    b_own, b_other = stat(own), stat(other)

    m = mask_of(own, feat, op, thr)
    cell = own[m]
    st = stat(cell)

    print("\n" + "=" * 104)
    print(f"КЛЕТКА  {feat} {op} {thr}   ·   сторона {side.upper()}")
    print("=" * 104)
    print(line(own, f"база {side}"))
    if st is None:
        print(f"  🔴 клетка: n={len(cell)} — меньше 30, статистики нет")
        return
    print(line(cell, "КЛЕТКА") + f"   подъём {lift(st, b_own)}")

    # ── критерий 4: размер ────────────────────────────────────────────────
    ok_n = st["n"] >= 100
    ok_c = st["coins"] >= 30
    print(f"\n  критерий 4 (размер):  n={st['n']} {'✅' if ok_n else '🔴 <100'}   "
          f"монет={st['coins']} {'✅' if ok_c else '🔴 <30'}")

    # ── критерий 5: зеркало ───────────────────────────────────────────────
    m2 = mask_of(other, feat, op, thr)
    mir = other[m2]
    st_mir = stat(mir)
    if st_mir is None:
        print(f"  критерий 5 (зеркало): n={len(mir)} — мало, ПРОВЕРИТЬ НЕЧЕМ 🔴")
    else:
        lm = st_mir["pf"] / b_other["pf"] if b_other and b_other["pf"] else float("nan")
        verdict = "✅ односторонняя ось" if lm < 1.15 else "🔴 растут ОБЕ = СРЕДА"
        print(f"  критерий 5 (зеркало): {other.side.iloc[0]} n={st_mir['n']} "
              f"PF {st_mir['pf']:.2f} против базы {b_other['pf']:.2f} = ×{lm:.2f}  {verdict}")

    # ── критерий 6: годы ──────────────────────────────────────────────────
    print(f"\n  критерий 6 (годы):")
    lifts, bad = [], []
    for y in sorted(own.year.unique()):
        yo = own[own.year == y]
        yc = yo[mask_of(yo, feat, op, thr)]
        s_y, s_b = stat(yc), stat(yo)
        if s_y is None or s_b is None or not s_b["pf"]:
            print(f"    {y}  n={len(yc):<5} — мало")
            continue
        L = s_y["pf"] / s_b["pf"]
        lifts.append(L)
        if L < 0.7:
            bad.append(y)
        print(f"    {y}  n={s_y['n']:<5} PF {s_y['pf']:5.2f}  против базы года "
              f"{s_b['pf']:5.2f}  = ×{L:.2f}{'  🔴' if L < 0.7 else ''}")
    up = sum(1 for L in lifts if L > 1.0)
    print(f"    → лет с подъёмом >1.0: {up} из {len(lifts)}"
          f"{'  ✅' if up >= 3 else '  🔴 нужно ≥3'}"
          f"{'' if not bad else f'   🔴 провал <0.7 в {bad}'}")

    # ── месяцы ────────────────────────────────────────────────────────────
    if "entry_ts" in own.columns:
        ts = pd.to_datetime(own["entry_ts"], errors="coerce", utc=True)
        mo = ts.dt.to_period("M")
        cell_mo = mo[m]
        per = cell.assign(_m=cell_mo.values).groupby("_m").pnl.sum()
        pos = float((per > 0).mean()) * 100 if len(per) else float("nan")
        print(f"\n  месяцы: клетка торгует в {len(per)} месяцах, "
              f"прибыльных {pos:.0f}%")


def jaccard(df: pd.DataFrame, side: str, cells: list[tuple]) -> None:
    own = df[df.side == side]
    masks = {f"{f} {o} {t}": mask_of(own, f, o, t) for f, o, t in cells}
    keys = list(masks)
    print("\n" + "=" * 104)
    print("ЖАККАР между клетками — совпадают ли они по СДЕЛКАМ")
    print("(высокий = это ОДНА ось под разными именами, а не N находок)")
    print("=" * 104)
    print(f"{'':<38}" + "".join(f"{k.split()[0][:14]:>16}" for k in keys))
    for a in keys:
        row = f"{a:<38}"
        for b in keys:
            inter = (masks[a] & masks[b]).sum()
            union = (masks[a] | masks[b]).sum()
            row += f"{(inter / union if union else 0):>16.2f}"
        print(row)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--side", default="long")
    a = ap.parse_args()

    df = pd.read_parquet(FILES[a.tf])
    cells = CELLS.get((a.tf, a.side))
    if not cells:
        print(f"🔴 нет записанных клеток для {a.tf}/{a.side}")
        return
    print("#" * 104)
    print(f"# ARCH-137 шаги 3-5 · ТФ {a.tf} · файл {FILES[a.tf].name} · "
          f"сторона {a.side} · клеток {len(cells)}")
    print("#" * 104)
    for f, o, t in cells:
        check_cell(df, a.side, f, o, t)
    jaccard(df, a.side, cells)


if __name__ == "__main__":
    main()
