# -*- coding: utf-8 -*-
"""
ARCH-137 · ШАГИ 1-2: база + слепой отбор ПО ВОЛНОВОЙ СЕМЬЕ на ядре.

Критерии записаны ДО прогона:
  obsidian/Research/2026-09-01-ARCH-137-Wave-Family-Criteria.md

Что делает:
  1. печатает БАЗУ по каждому ТФ и стороне — все подъёмы считаются от неё;
  2. слепой отбор ТОЛЬКО по семье WAVES (leg_* / elliott_*), обе стороны,
     булевые через blind_select, числовые через blind_select_num
     (с зашитым перестановочным контролем).

🔑 Отбор идёт по УРЕЗАННОЙ матрице: оставлены меты + семья. Поэтому харнесс
   переиспользуется как есть, а множественность считается по РАЗМЕРУ СЕМЬИ,
   а не по 757 признакам — так и требует критерий №7.

Запуск:
    python scripts/wave_family_run.py            # все ТФ
    python scripts/wave_family_run.py --tf 1h
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from scripts.research_harness import (  # noqa: E402
    blind_select, blind_select_num, line, stat,
)

ROOT = Path(__file__).resolve().parent.parent
META = ["sym", "oos", "year", "side", "pnl"]

# 🔑 136.D (01.09.2026): скрипт обобщён с волн на ЛЮБУЮ семью — механика отбора
# одна и та же, менять надо только префиксы ([[principle_reuse_not_duplication]]).
FAMILIES = {
    "waves": ("leg_", "elliott_"),
    "pivots": ("dist_piv_", "piv_"),          # 136.D: «216 признаков — артефакт 2024»
    "smc": ("bull_", "bear_", "ote_", "in_smc_", "near_smc_", "smc_"),
    "scales": ("st5_", "st50_", "sc_"),
    "wt": ("wt", "rsi_"),
    "market": ("mkt_", "rs", "btc_", "fund_"),
}
WAVE_PREFIX = FAMILIES["waves"]

FILES = {
    "15m": ROOT / "cache/matrix_core_15m.parquet",
    "1h": ROOT / "cache/matrix_core_1h.parquet",
    "1h_wide": ROOT / "cache/matrix_core_1h_wide.parquet",
    "4h_wide": ROOT / "cache/matrix_core_4h_wide.parquet",
}


def wave_cols(df: pd.DataFrame, prefixes: tuple = WAVE_PREFIX) -> list[str]:
    """Признаки семьи. Константы отбрасываем — на 1h такие есть (elliott_*_1h)."""
    out = []
    for c in df.columns:
        if not c.startswith(prefixes):
            continue
        if c in META:
            continue
        if df[c].nunique(dropna=True) <= 1:
            print(f"    ⚠️ {c}: КОНСТАНТА — исключён")
            continue
        out.append(c)
    return sorted(out)


def slim(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Меты + семья. Всё остальное вон, чтобы отбор не видел чужих признаков."""
    return df[META + cols].copy()


def run_tf(tf: str, path: Path, family: str = "waves") -> None:
    if not path.exists():
        print(f"\n🔴 [{tf}] нет файла {path}")
        return
    df = pd.read_parquet(path)
    print("\n\n" + "#" * 104)
    print(f"# ТФ {tf} · файл {path.name} · сделок {len(df)} · монет {df.sym.nunique()} "
          f"· СЕМЬЯ {family.upper()}")
    print("#" * 104)

    cols = wave_cols(df, FAMILIES[family])
    if not cols:
        print(f"\n🔴 семья {family}: НОЛЬ признаков — проверьте префиксы {FAMILIES[family]}")
        return
    print(f"\nсемья {family.upper()}: {len(cols)} признаков")

    # ── ШАГ 1. БАЗА ────────────────────────────────────────────────────────
    print(f"\n{'='*104}\nШАГ 1 — БАЗА (от неё считаются все подъёмы)\n{'='*104}")
    print(line(df, "ВСЁ"))
    for s in sorted(df.side.unique()):
        print(line(df[df.side == s], f"  {s}"))
    print("\nПО ГОДАМ:")
    for y in sorted(df.year.unique()):
        print(line(df[df.year == y], f"  {y}"))

    # ── ШАГ 2. СЛЕПОЙ ОТБОР ПО СЕМЬЕ, КАЖДАЯ СТОРОНА ОТДЕЛЬНО ─────────────
    for s in sorted(df.side.unique()):
        sub = slim(df[df.side == s], cols)
        print("\n\n" + "=" * 104)
        print(f"ШАГ 2 · ТФ {tf} · СТОРОНА {s.upper()} · n={len(sub)} · "
              f"монет {sub.sym.nunique()} · семья {len(cols)} признаков")
        print("=" * 104)
        if len(sub) < 200:
            print(f"🔴 сделок {len(sub)} — мало для протокола, пропуск "
                  f"(критерий №4: n≥100 в КЛЕТКЕ, значит в базе нужно кратно больше)")
            continue
        print("\n--- БУЛЕВЫЕ признаки семьи (порог f>0) ---")
        blind_select(sub)
        print("\n--- ЧИСЛОВЫЕ признаки семьи (порог по децилям + перестановка) ---")
        blind_select_num(sub)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default=None, help="15m | 1h | 1h_wide | 4h_wide")
    ap.add_argument("--family", default="waves", choices=list(FAMILIES),
                    help="какую семью признаков отбирать")
    a = ap.parse_args()
    todo = {a.tf: FILES[a.tf]} if a.tf else FILES
    for tf, path in todo.items():
        run_tf(tf, path, a.family)
    print("\n\n🔑 НЕ проверено этим прогоном (по критериям §5): зеркало клеток, "
          "годы/месяцы клеток,\n   вложенность НАБОРОМ, фаза как непрерывная шкала. "
          "Это шаги 3-7, отдельными прогонами.")


if __name__ == "__main__":
    main()
