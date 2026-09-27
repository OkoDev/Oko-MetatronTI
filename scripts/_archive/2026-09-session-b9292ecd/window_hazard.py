# -*- coding: utf-8 -*-
"""ПРОГНОЗИРУЕМО ЛИ ОКНО (вопрос Егора 09.09.2026): есть ли у состояния память?

Считается ТОЛЬКО по длительностям состояний структуры, БЕЗ форварда цены —
поэтому look-ahead сюда попасть не может (в отличие от всего остального сегодня).

hazard(T) = P(состояние сменится на следующем баре | прожило уже T баров).
  постоянный  → экспоненциальное, памяти нет, «середина окна» не определена
  растущий    → возраст предсказывает конец, окно прогнозируемо
  убывающий   → старое состояние живучее молодого
"""
import os, sys, glob
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.smc.oko_sm_engine import run_structure

LEN = 10
TFS = [3, 10, 30, 90, 240]
NSYM = 24
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))[:NSYM]
print(f"монет: {len(files)}\n", flush=True)


def resample(d1, tf):
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


dur = {tf: [] for tf in TFS}        # длительности состояний, в барах слоя
amp = {tf: [] for tf in TFS}        # (длительность, амплитуда движения за состояние)
for fi, f in enumerate(files, 1):
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    for tf in TFS:
        d = resample(d1, tf)
        if len(d) < 400:
            continue
        st = run_structure(d.reset_index(drop=True), swing_len=LEN, internal_len=3)
        ev = sorted([(e.i, 1 if e.bull else -1) for e in st.events if not e.internal])
        c = d["close"].values
        for (i0, s0), (i1, _) in zip(ev[:-1], ev[1:]):
            if i1 <= i0 or i1 >= len(c):
                continue
            dur[tf].append(i1 - i0)
            amp[tf].append(((i1 - i0), (c[i1] - c[i0]) / c[i0] * 100 * s0))
    if fi % 8 == 0:
        print(f"  [{fi}/{len(files)}]", flush=True)

print(f"\n=== РАСПРЕДЕЛЕНИЕ ДЛИТЕЛЬНОСТИ СОСТОЯНИЯ (баров своего слоя) ===")
print(f"{'окно':>7} {'n':>8} {'медиана':>8} {'сред':>7} {'p75':>6} {'p90':>6} "
      f"{'p99':>7} {'CV':>6} {'экспон.CV=1':>12}")
for tf in TFS:
    a = np.array(dur[tf])
    if len(a) < 500:
        continue
    cv = a.std() / a.mean()
    print(f"{tf*LEN:>7} {len(a):>8,} {np.median(a):8.0f} {a.mean():7.1f} "
          f"{np.percentile(a,75):6.0f} {np.percentile(a,90):6.0f} "
          f"{np.percentile(a,99):7.0f} {cv:6.2f} "
          f"{'~экспон.' if 0.85 < cv < 1.15 else ('память есть' if cv > 1.15 else 'регулярно'):>12}")

print(f"\n=== HAZARD: P(смена | прожито уже T баров) ===")
print("  (если растёт — конец окна предсказуем; если плоский — памяти нет)")
for tf in TFS:
    a = np.array(dur[tf])
    if len(a) < 500:
        continue
    print(f"\n  окно {tf*LEN} мин, n={len(a):,}:")
    print(f"{'возраст T':>12} {'выжило':>9} {'сменилось':>10} {'hazard':>9} "
          f"{'ср. остаток':>12}")
    for lo, hi in [(0, 2), (2, 4), (4, 7), (7, 12), (12, 20), (20, 35), (35, 60),
                   (60, 100), (100, 10**9)]:
        alive = (a >= lo).sum()
        if alive < 60:
            continue
        died = ((a >= lo) & (a < hi)).sum()
        h = died / alive / max(1, hi - lo) if hi < 10**9 else died / alive
        rest = a[a >= lo].mean() - lo
        lbl = f"{lo}-{hi}" if hi < 10**9 else f"{lo}+"
        print(f"{lbl:>12} {alive:>9,} {died:>10,} {h*100:8.2f}% {rest:11.1f}")

print(f"\n=== ДЛИТЕЛЬНОСТЬ ↔ АМПЛИТУДА (предсказывает ли возраст размер хода) ===")
print(f"{'окно':>7} {'корр(длит,ампл)':>16} {'ампл. коротких':>15} {'ампл. длинных':>14}")
for tf in TFS:
    A = np.array(amp[tf])
    if len(A) < 500:
        continue
    d_, m_ = A[:, 0], A[:, 1]
    med = np.median(d_)
    print(f"{tf*LEN:>7} {np.corrcoef(d_, m_)[0,1]:+15.3f} "
          f"{np.median(m_[d_ <= med]):+14.3f}% {np.median(m_[d_ > med]):+13.3f}%")
