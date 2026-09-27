# -*- coding: utf-8 -*-
"""ЕДИНЫЙ ПРОХОД ПО ТОЧКАМ: можно ли получить свинги крупных окон фильтрацией мелких.

Кривая вложенности: 95-97% свингов большого окна содержатся в свингах малого при R≥0.85.
Проверяем инженерное следствие — заменить N проходов детектора на 1 проход + фильтр.

A. ТОЧНОСТЬ: совпадают ли отфильтрованные свинги с честно посчитанными.
B. СКОРОСТЬ: сколько времени экономится.
"""
import os, sys, time, glob
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.smc.oko_sm_engine import _swings

LENS = [5, 10, 21, 34, 55]          # слои по длине на ОДНОМ ряду
NSYM = 6
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))[:NSYM]


def base_swings(d, length):
    """Честный вызов детектора."""
    return _swings(d["high"], d["low"], length)


def filtered(sw_small, hi, lo, length):
    """Свинги окна `length` из готового списка мелких: экстремум держится на окне length.
    Проверка идёт по массивам цен, но ТОЛЬКО в точках-кандидатах, которых мало."""
    out = []
    n = len(hi)
    for conf_i, sw_i, price, is_top in sw_small:
        a, b = max(0, sw_i - length), min(n, sw_i + length + 1)
        if is_top:
            if hi[sw_i] >= hi[a:b].max():
                out.append((sw_i + length, sw_i, price, True))
        else:
            if lo[sw_i] <= lo[a:b].min():
                out.append((sw_i + length, sw_i, price, False))
    return out


print(f"монет: {len(files)} | длины слоёв: {LENS}\n")
tot_base = tot_new = 0.0
rec = []
for f in files:
    d = pd.read_parquet(f)[["high", "low"]]
    hi, lo = d["high"].values, d["low"].values
    sym = os.path.basename(f)[:-8]
    # честно: каждый слой отдельным проходом
    t0 = time.perf_counter()
    ref = {L: base_swings(d, L) for L in LENS}
    t_base = time.perf_counter() - t0
    # единый проход по самому мелкому + фильтрация
    t0 = time.perf_counter()
    small = base_swings(d, min(LENS))
    new = {min(LENS): small}
    for L in LENS[1:]:
        new[L] = filtered(small, hi, lo, L)
    t_new = time.perf_counter() - t0
    tot_base += t_base; tot_new += t_new
    for L in LENS:
        R = {(i, t) for _, i, _, t in ref[L]}
        N = {(i, t) for _, i, _, t in new[L]}
        rec.append((sym, L, len(R), len(N), len(R & N)))
    print(f"  {sym:<14} баров {len(d):>8,} · честно {t_base:6.2f}с · "
          f"единый {t_new:6.2f}с · ×{t_base/max(t_new,1e-9):.2f}", flush=True)

df = pd.DataFrame(rec, columns=["sym", "L", "n_ref", "n_new", "n_both"])
print(f"\n=== A. ТОЧНОСТЬ ФИЛЬТРАЦИИ ===")
print(f"{'длина':>6} {'свингов честно':>15} {'фильтром':>10} {'совпало':>9} "
      f"{'полнота':>9} {'точность':>10}")
for L in LENS:
    g = df[df.L == L]
    ref_n, new_n, both = g.n_ref.sum(), g.n_new.sum(), g.n_both.sum()
    print(f"{L:>6} {ref_n:>15,} {new_n:>10,} {both:>9,} "
          f"{both/max(ref_n,1)*100:8.1f}% {both/max(new_n,1)*100:9.1f}%")

print(f"\n=== B. СКОРОСТЬ ===")
print(f"  честно (5 проходов): {tot_base:.2f} с")
print(f"  единый проход + фильтр: {tot_new:.2f} с")
print(f"  ускорение: ×{tot_base/max(tot_new,1e-9):.2f}")
