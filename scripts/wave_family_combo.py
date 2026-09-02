# -*- coding: utf-8 -*-
"""
ARCH-137 · ШАГ 6: вложенность НАБОРОМ + согласованность ног 15m↔1h↔4h.

Повод (пункт 1.2 плана перепроверки): «290 признаков старших ТФ мерились
поодиночке, набором — ни разу». Здесь меряется именно набор.

Что делает:
  1. связка независимых осей (Жаккар 0.21) — умножаются или нет;
  2. согласованность направлений ног 15m / 1h / 4h — все комбинации знаков;
  3. 🔴 перекрытие с БОЕВЫМ дрейф-гейтом (`mkt_drift30`) — не переоткрыл ли я
     то, что уже стоит в бою;
  4. перестановочный контроль для связки (шум берёт ЛУЧШУЮ из всех клеток набора).

Запуск:
    python scripts/wave_family_combo.py --tf 15m --side short
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
}

# оси, прошедшие критерии 1-6 поодиночке (зеркало ✅, годы ✅, хрупкость +)
AXES = {
    ("15m", "short"): [
        ("нога 4h ВВЕРХ", "leg_dir_4h__from_4h", "≥", 0.5),
        ("нога 4h ДЛИННАЯ ≥107 баров", "leg_span_bars_4h__from_4h", "≥", 107.0),
    ],
    ("1h", "long"): [
        ("сломов младшей ≤5", "leg_minor_breaks_1h", "≤", 5.0),
        ("нога 1h КОРОТКАЯ ≤86", "leg_span_bars_1h", "≤", 86.0),
    ],
}


def m_of(df, feat, op, thr):
    v = df[feat]
    return ((v >= thr) if op == "≥" else (v <= thr)).fillna(False)


def lift(st, base):
    if st is None or base is None or not base["pf"]:
        return float("nan")
    return st["pf"] / base["pf"]


def combo(df: pd.DataFrame, side: str, axes: list[tuple]) -> pd.Series:
    own = df[df.side == side]
    other = df[df.side != side]
    b_own, b_other = stat(own), stat(other)
    print("\n" + "=" * 104)
    print(f"СВЯЗКА ОСЕЙ · сторона {side.upper()}")
    print("=" * 104)
    print(line(own, "база"))

    masks = [(nm, m_of(own, f, o, t)) for nm, f, o, t in axes]
    for nm, m in masks:
        st = stat(own[m])
        print(line(own[m], nm) + f"   подъём ×{lift(st, b_own):.2f}")

    both = masks[0][1]
    for _, m in masks[1:]:
        both = both & m
    st_b = stat(own[both])
    print(line(own[both], "ОБЕ ОСИ") + f"   подъём ×{lift(st_b, b_own):.2f}")

    neither = ~masks[0][1]
    for _, m in masks[1:]:
        neither = neither & (~m)
    print(line(own[neither], "НИ ОДНОЙ") + f"   подъём ×{lift(stat(own[neither]), b_own):.2f}")

    # умножаются ли: ожидание при независимости = произведение подъёмов
    l1 = lift(stat(own[masks[0][1]]), b_own)
    l2 = lift(stat(own[masks[1][1]]), b_own)
    lb = lift(st_b, b_own)
    print(f"\n  подъём поодиночке ×{l1:.2f} и ×{l2:.2f} · "
          f"произведение (если независимы) ×{l1 * l2:.2f} · ФАКТ ×{lb:.2f}")
    if lb >= l1 * l2 * 0.85:
        print("  ✅ оси УМНОЖАЮТСЯ — набор сильнее любой поодиночке")
    elif lb > max(l1, l2):
        print("  🟡 набор лучше каждой, но слабее произведения — оси частично об одном")
    else:
        print("  🔴 набор НЕ лучше лучшей оси — складывать смысла нет")

    # зеркало для связки
    mb_o = m_of(other, axes[0][1], axes[0][2], axes[0][3])
    for _, f, o, t in axes[1:]:
        mb_o = mb_o & m_of(other, f, o, t)
    st_mir = stat(other[mb_o])
    if st_mir is None:
        print("  критерий 5 (зеркало связки): мало данных 🔴")
    else:
        lm = lift(st_mir, b_other)
        print(f"  критерий 5 (зеркало связки): n={st_mir['n']} PF {st_mir['pf']:.2f} "
              f"= ×{lm:.2f}  {'✅ односторонняя' if lm < 1.15 else '🔴 СРЕДА'}")

    print("\n  ГОДЫ связки:")
    for y in sorted(own.year.unique()):
        yo = own[own.year == y]
        yb = both.loc[yo.index]
        s_y, s_b = stat(yo[yb]), stat(yo)
        if s_y is None or s_b is None or not s_b["pf"]:
            print(f"    {y}  n={int(yb.sum()):<5} — мало")
            continue
        print(f"    {y}  n={s_y['n']:<5} PF {s_y['pf']:5.2f}  база года {s_b['pf']:5.2f}"
              f"  = ×{s_y['pf'] / s_b['pf']:.2f}")
    return both


def agree(df: pd.DataFrame, side: str, tfs: list[str]) -> None:
    """Согласованность направлений ног по трём ТФ — пункт 4 постановки ARCH-137."""
    own = df[df.side == side]
    b = stat(own)
    cols = [c for c in tfs if c in own.columns]
    if len(cols) < 2:
        print("\n🔴 согласованность: нет колонок leg_dir по нужным ТФ")
        return
    print("\n" + "=" * 104)
    print(f"СОГЛАСОВАННОСТЬ НОГ по ТФ ({' · '.join(cols)}) · сторона {side.upper()}")
    print("=" * 104)
    print(line(own, "база"))
    sig = own[cols].apply(lambda s: np.sign(s.fillna(0)).astype(int))
    key = sig.astype(str).agg("/".join, axis=1)
    for k, grp in own.groupby(key.values):
        st = stat(grp)
        if st is None:
            print(f"  {k:<24} n={len(grp)} — мало")
            continue
        print(line(grp, f"  {k}") + f"   подъём ×{lift(st, b):.2f}")
    print("  (1 = нога вверх · -1 = вниз · 0 = нет данных; порядок колонок как в шапке)")


def vs_drift(df: pd.DataFrame, side: str, both: pd.Series) -> None:
    """🔴 Не переоткрыл ли я боевой дрейф-гейт другими словами."""
    own = df[df.side == side]
    if "mkt_drift30" not in own.columns:
        print("\n🔴 mkt_drift30 нет в матрице — сверку с боевым гейтом сделать нечем")
        return
    g = (own["mkt_drift30"] >= 5.0).fillna(False)
    b = stat(own)
    inter = int((both & g).sum()); union = int((both | g).sum())
    print("\n" + "=" * 104)
    print("🔴 СВЕРКА С БОЕВЫМ ДРЕЙФ-ГЕЙТОМ (mkt_drift30 ≥ 5) — то же самое или разное")
    print("=" * 104)
    print(line(own[g], "дрейф-гейт один") + f"   подъём ×{lift(stat(own[g]), b):.2f}")
    print(line(own[both], "волновой набор") + f"   подъём ×{lift(stat(own[both]), b):.2f}")
    print(line(own[both & g], "оба") + f"   подъём ×{lift(stat(own[both & g]), b):.2f}")
    print(line(own[both & ~g], "волна БЕЗ дрейфа") + f"   подъём ×{lift(stat(own[both & ~g]), b):.2f}")
    print(line(own[~both & g], "дрейф БЕЗ волны") + f"   подъём ×{lift(stat(own[~both & g]), b):.2f}")
    print(f"\n  Жаккар(волновой набор, дрейф-гейт) = {inter / union if union else 0:.2f}"
          f"   (высокий = я переоткрыл боевой гейт)")


def permutation(df: pd.DataFrame, side: str, axes: list[tuple], n_perm: int = 200,
                seed: int = 19) -> None:
    """Шум берёт ЛУЧШУЮ клетку набора — поправка на множественность (критерий 7)."""
    own = df[df.side == side].copy()
    b = stat(own)
    masks = [m_of(own, f, o, t) for _, f, o, t in axes]
    both = masks[0]
    for m in masks[1:]:
        both = both & m
    real = lift(stat(own[both]), b)

    rng = np.random.default_rng(seed)
    best = []
    pnl = own.pnl.values.copy()
    for _ in range(n_perm):
        own["pnl"] = rng.permutation(pnl)
        bp = stat(own)
        cand = [lift(stat(own[m]), bp) for m in masks] + [lift(stat(own[both]), bp)]
        cand = [c for c in cand if not np.isnan(c)]
        best.append(max(cand) if cand else 0.0)
    arr = np.array(best)
    p = float((arr >= real).mean())
    print("\n" + "=" * 104)
    print(f"🎲 ПЕРЕСТАНОВКА С ПОПРАВКОЙ НА НАБОР ({n_perm} перемешиваний, "
          f"шум берёт ЛУЧШУЮ из {len(masks) + 1} клеток)")
    print("=" * 104)
    print(f"  реальный подъём связки ×{real:.2f}")
    print(f"  шум: медиана ×{np.median(arr):.2f} · 95-й перцентиль ×{np.quantile(arr, .95):.2f}"
          f" · максимум ×{arr.max():.2f}")
    print(f"  P(шум ≥ реального) = {p:.3f}  "
          f"{'✅ отличимо от шума' if p < 0.05 else '🔴 НЕ отличимо от шума'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="15m")
    ap.add_argument("--side", default="short")
    a = ap.parse_args()
    df = pd.read_parquet(FILES[a.tf])
    axes = AXES[(a.tf, a.side)]
    print("#" * 104)
    print(f"# ARCH-137 шаг 6 · ТФ {a.tf} · {FILES[a.tf].name} · сторона {a.side} · "
          f"сделок {len(df)} · монет {df.sym.nunique()}")
    print("#" * 104)
    both = combo(df, a.side, axes)
    suffix = "15m" if a.tf == "15m" else "1h"
    agree(df, a.side, [f"leg_dir_{suffix}", "leg_dir_1h__from_1h", "leg_dir_4h__from_4h"])
    vs_drift(df, a.side, both)
    permutation(df, a.side, axes)


if __name__ == "__main__":
    main()
