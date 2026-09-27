# -*- coding: utf-8 -*-
"""ЛИМИТНЫЙ ВХОД ВНУТРИ СОБЫТИЯ СТАРШЕГО СЛОЯ (мысль Егора 09.09.2026):
«2000 мин — где-то в середине можно было залетать с коротким стопом».

Событие на окне 2000 мин длится ~33 часа. Внутри него ждём откат против направления
и входим лимитом — стоп становится коротким, RR растёт. Плата: часть сигналов не
заполнится вовсе.

🔴 Считаем по ВСЕМУ ПОТОКУ, а не по заполненным: незаполненный сигнал = 0, иначе
сравнение нечестное (закон «отсеивает много» — довод о частоте, не о деньгах).
"""
import os, sys, glob
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.smc.oko_sm_engine import run_structure

LEN = 10
LAYERS = [(200, "2000 мин"), (60, "600 мин"), (18, "180 мин")]   # ТФ события
WAIT_W = 2.0          # сколько окон ждать заполнения лимита
PULL = [0.0, 0.25, 0.5, 1.0, 1.5, 2.0]        # глубина отката, %
COST = 0.35
NSYM = 24
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))[:NSYM]
print(f"монет: {len(files)}\n", flush=True)


def resample(d1, tf):
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


res = {}
for fi, f in enumerate(files, 1):
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    m1 = d1[["high", "low", "close"]].values
    ts1 = d1.index.values
    for tf, lbl in LAYERS:
        d = resample(d1, tf)
        if len(d) < 400:
            continue
        st = run_structure(d.reset_index(drop=True), swing_len=LEN, internal_len=3)
        ev = [(d.index.values[e.i], 1 if e.bull else -1)
              for e in st.events if not e.internal]
        win_min = tf * LEN
        wait_bars = int(WAIT_W * win_min)                 # в минутах = барах 1m
        hold_bars = int(2 * win_min)                      # горизонт удержания: 2 окна
        for tstamp, side in ev:
            i = int(np.searchsorted(ts1, tstamp, "right")) - 1
            if i < 10 or i + wait_bars + hold_bars >= len(m1):
                continue
            e0 = m1[i, 2]
            seg_wait = m1[i + 1:i + 1 + wait_bars]
            for p in PULL:
                lim = e0 * (1 - side * p / 100)
                if p == 0:
                    j, entry = i, e0
                else:
                    hit = (np.where(seg_wait[:, 1] <= lim)[0] if side == 1
                           else np.where(seg_wait[:, 0] >= lim)[0])
                    if len(hit) == 0:
                        res.setdefault((lbl, p), []).append((0, np.nan, np.nan))
                        continue
                    j = i + 1 + int(hit[0]); entry = lim
                seg = m1[j + 1:j + 1 + hold_bars]
                if len(seg) < hold_bars // 2:
                    continue
                if side == 1:
                    mfe = (seg[:, 0].max() - entry) / entry * 100
                    mae = (seg[:, 1].min() - entry) / entry * 100
                else:
                    mfe = (entry - seg[:, 1].min()) / entry * 100
                    mae = (entry - seg[:, 0].max()) / entry * 100
                res.setdefault((lbl, p), []).append((1, mfe, mae))
    if fi % 6 == 0:
        print(f"  [{fi}/{len(files)}]", flush=True)

print(f"\n{'слой':>10} {'откат':>7} {'сигналов':>9} {'залив':>7} {'MFE мед':>9} "
      f"{'MAE мед':>9} {'RR':>6} {'MFE на ВЕСЬ поток':>18}")
for (lbl, p), v in sorted(res.items(), key=lambda kv: (kv[0][0], kv[0][1])):
    a = np.array(v, dtype=float)
    n = len(a); fill = a[:, 0].mean()
    ok = a[a[:, 0] == 1]
    if len(ok) < 50:
        continue
    mfe = np.nanmedian(ok[:, 1]); mae = np.nanmedian(ok[:, 2])
    rr = abs(mfe / mae) if mae else np.nan
    print(f"{lbl:>10} {p:6.2f}% {n:>9,} {fill*100:6.1f}% {mfe:+8.3f}% {mae:+8.3f}% "
          f"{rr:6.2f} {mfe*fill:+17.3f}%")

print("\n🔑 «MFE на весь поток» = медианный ход × доля заполнения — честное сравнение:")
print("   глубокий лимит даёт лучший RR, но реже заполняется.")
