# -*- coding: utf-8 -*-
"""
ARCH-137 · ШАГ 7: фаза ноги как НЕПРЕРЫВНАЯ ШКАЛА, а не порог.

Критерий: ищем МОНОТОННОСТЬ по децилям, а не лучшую клетку. Монотонная кривая —
признак механизма; одиночный горб посреди шкалы — признак подгонки.

Печатает по децилям: n, PF, безтоп10%, и отдельно ЗЕРКАЛО того же дециля,
потому что монотонность на обеих сторонах = среда, а не ось.

Запуск:
    python scripts/wave_family_scale.py --tf 15m --side short
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from scripts.research_harness import stat  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FILES = {"15m": ROOT / "cache/matrix_core_15m.parquet",
         "1h": ROOT / "cache/matrix_core_1h.parquet"}

SCALES = {
    "15m": ["leg_pos_15m", "leg_retr_15m", "leg_span_bars_4h__from_4h",
            "leg_age_origin_15m", "leg_minor_breaks_15m", "leg_pos_4h__from_4h"],
    "1h": ["leg_pos_1h", "leg_retr_1h", "leg_span_bars_1h",
           "leg_age_origin_1h", "leg_minor_breaks_1h", "leg_pos_4h__from_4h"],
}


def deciles(df: pd.DataFrame, side: str, feat: str, q: int = 8) -> None:
    own = df[df.side == side]
    other = df[df.side != side]
    b, b_o = stat(own), stat(other)
    v = own[feat]
    if v.notna().sum() < 300:
        print(f"\n{feat}: данных мало ({v.notna().sum()}) — пропуск")
        return
    edges = np.unique(np.nanquantile(v, np.linspace(0, 1, q + 1)))
    if len(edges) < 4:
        print(f"\n{feat}: значений мало для шкалы — пропуск")
        return
    print("\n" + "=" * 104)
    print(f"ШКАЛА  {feat}  ·  сторона {side.upper()}  ·  база PF {b['pf']:.2f}")
    print("=" * 104)
    print(f"  {'дециль':<26}{'n':>7}{'PF':>8}{'подъём':>9}{'безтоп10%':>12}"
          f"{'зеркало':>10}")
    lifts = []
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        m = (v >= lo) & (v < hi if i < len(edges) - 2 else v <= hi)
        st = stat(own[m.fillna(False)])
        vo = other[feat]
        mo = (vo >= lo) & (vo < hi if i < len(edges) - 2 else vo <= hi)
        st_o = stat(other[mo.fillna(False)])
        if st is None:
            print(f"  [{lo:8.3g},{hi:8.3g})  n<30")
            continue
        L = st["pf"] / b["pf"]
        lifts.append(L)
        mir = f"×{st_o['pf'] / b_o['pf']:.2f}" if st_o and b_o["pf"] else "—"
        print(f"  [{lo:8.3g},{hi:8.3g}){st['n']:>7}{st['pf']:>8.2f}"
              f"{L:>8.2f}×{st['bt']:>12.0f}{mir:>10}")
    if len(lifts) >= 4:
        r = np.corrcoef(np.arange(len(lifts)), lifts)[0, 1]
        first, last = np.mean(lifts[:2]), np.mean(lifts[-2:])
        print(f"\n  корреляция подъёма с номером дециля r={r:+.2f}   "
              f"края: {first:.2f} → {last:.2f}")
        if abs(r) > 0.7:
            print("  ✅ МОНОТОННО — похоже на механизм, а не на клетку")
        elif abs(r) > 0.4:
            print("  🟡 склон есть, но с изломами")
        else:
            print("  🔴 монотонности нет — эффект держится на одной клетке (подгонка)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="15m")
    ap.add_argument("--side", default="short")
    a = ap.parse_args()
    df = pd.read_parquet(FILES[a.tf])
    print("#" * 104)
    print(f"# ARCH-137 шаг 7 · ТФ {a.tf} · сторона {a.side} · {FILES[a.tf].name}")
    print("#" * 104)
    for f in SCALES[a.tf]:
        if f in df.columns:
            deciles(df, a.side, f)


if __name__ == "__main__":
    main()
