# -*- coding: utf-8 -*-
"""Гипотеза Егора (03.09.2026): «слом на 3м скорее всего означает смену ATRTrend».

Если микро-слом структуры совпадает со сменой ATR Supertrend, то микро-слой
ИЗБЫТОЧЕН: тот же сигнал уже лежит в матрице как `atr_cross_up/down` и стоит
в 40 раз дешевле (SMC-набор B: 62 мс против 1.5 мс на детектор).

Меряем на каждом ТФ:
  · долю сломов, у которых смена ATRTrend случилась в окне ±TOL баров;
  · обратную долю (сколько смен ATRTrend имеют рядом слом);
  · Жаккар — общая мера пересечения событий;
  · раздельно для swing-слоя (len=50) и микро (len=5).

Малый Жаккар = детекторы ловят РАЗНОЕ, слой не дублирует индикатор.
Большой = дублирует, и дорогой детектор на младшем ТФ не нужен.

Запуск: python scripts/break_vs_atrtrend.py [n_symbols] [tf ...]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from research_harness import load, universe  # noqa: E402

TOL = 2          # окно совпадения, баров


def _flips(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Бары смены направления ATR Supertrend — тем же калькулятором, что и матрица."""
    from core.calculators.combinator_core import atr_supertrend
    t = np.asarray(atr_supertrend(df.reset_index(drop=True)))
    prev = np.concatenate([[t[0]], t[:-1]])
    up = np.where((t == 1) & (prev != 1))[0]
    dn = np.where((t == -1) & (prev != -1))[0]
    return up, dn


def _near(a: np.ndarray, b: np.ndarray, tol: int = TOL) -> int:
    """Сколько элементов a имеют элемент b в пределах ±tol."""
    if len(a) == 0 or len(b) == 0:
        return 0
    bs = np.sort(b)
    idx = np.searchsorted(bs, a)
    hit = 0
    for x, i in zip(a, idx):
        lo = bs[i - 1] if i > 0 else -10 ** 9
        hi = bs[i] if i < len(bs) else 10 ** 9
        if min(abs(x - lo), abs(x - hi)) <= tol:
            hit += 1
    return hit


def main() -> None:
    n_sym = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    tfs = sys.argv[2:] or ["3m", "15m", "1h"]
    from core.smc.oko_sm_engine import run_structure

    print(f"окно совпадения ±{TOL} баров · тот же калькулятор ATR, что в матрице\n")
    print(f"{'ТФ':5s} {'слой':7s} {'сломов':>8s} {'ATR-смен':>9s} "
          f"{'слом→ATR':>10s} {'ATR→слом':>10s} {'Жаккар':>8s} {'монет':>6s}")
    for tf in tfs:
        try:
            syms = universe(tf, n=n_sym)
        except Exception as e:  # noqa: BLE001
            print(f"{tf}: вселенная недоступна — {type(e).__name__}: {str(e)[:50]}")
            continue
        agg = {"swing": [0, 0, 0, 0], "micro": [0, 0, 0, 0]}   # br, flips, br→atr, atr→br
        used = 0
        for s in syms:
            try:
                df = load(s, tf)
            except Exception:  # noqa: BLE001
                continue
            if len(df) < 3000:
                continue
            used += 1
            dd = df.reset_index(drop=True)
            st = run_structure(dd, swing_len=50, internal_len=5, record_legs=False)
            up, dn = _flips(dd)
            flips = np.sort(np.concatenate([up, dn]))
            for layer, want in (("swing", False), ("micro", True)):
                # слом сопоставляем со сменой ATR В ТУ ЖЕ сторону — иначе «совпадение»
                # ловило бы противоположные события и завышало пересечение
                bu = np.array([e.i for e in st.events if e.internal == want and e.bull])
                bd = np.array([e.i for e in st.events if e.internal == want and not e.bull])
                br_n = len(bu) + len(bd)
                hit_b = _near(bu, up) + _near(bd, dn)
                hit_a = _near(up, bu) + _near(dn, bd)
                a = agg[layer]
                a[0] += br_n; a[1] += len(flips); a[2] += hit_b; a[3] += hit_a
        for layer in ("swing", "micro"):
            br, fl, hb, ha = agg[layer]
            if not br or not fl:
                continue
            jac = (hb + ha) / (br + fl) if (br + fl) else 0
            print(f"{tf:5s} {layer:7s} {br:8d} {fl:9d} {hb/br*100:9.1f}% "
                  f"{ha/fl*100:9.1f}% {jac:8.3f} {used:6d}")
        print()


if __name__ == "__main__":
    main()
