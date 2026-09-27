# -*- coding: utf-8 -*-
"""ВХОД ПО ВОЗРАСТУ СОСТОЯНИЯ (следствие hazard-замера, 09.09.2026).

Слом сам по себе не работает — половина сломов ложные (короткие состояния имеют
ОТРИЦАТЕЛЬНУЮ амплитуду). Но возраст состояния известен В МОМЕНТЕ и отличает их:
прожившее 12 баров состояние уже не может оказаться коротким.

Вход на возрасте A баров после слома, форвард = 1 окно слоя вперёд ОТ ЭТОЙ ТОЧКИ.
Всё считается на СВОЁМ ТФ — склейки слоёв нет, значит и утечки вида 6 нет.
Контроль: случайный бар той же монеты, тот же квинтиль ATR.
"""
import os, sys, glob
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.smc.oko_sm_engine import run_structure

LEN = 10
TFS = [10, 30, 90, 240]
AGES = [0, 3, 7, 12, 20, 30]
NSYM = 24
RNG = np.random.default_rng(20260909)
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))[:NSYM]
print(f"монет: {len(files)}\n", flush=True)


def resample(d1, tf):
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


acc = {(tf, a, s): [0, 0.0, 0.0] for tf in TFS for a in AGES for s in (1, -1)}
per = {(tf, a): [] for tf in TFS for a in AGES}
for fi, f in enumerate(files, 1):
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    for tf in TFS:
        d = resample(d1, tf)
        if len(d) < 400:
            continue
        c = d["close"].values
        n = len(c)
        h = LEN                                     # горизонт = 1 окно слоя
        fwd = np.full(n, np.nan)
        fwd[:-h] = (c[h:] - c[:-h]) / c[:-h] * 100
        atr = ((d["high"] - d["low"]) / d["close"]).rolling(100, min_periods=30).mean().values
        ok = ~np.isnan(fwd) & ~np.isnan(atr)
        if ok.sum() < 200:
            continue
        q = np.zeros(n, np.int8)
        q[ok] = np.digitize(atr[ok], np.nanpercentile(atr[ok], [20, 40, 60, 80]))
        pools = {b: np.where(ok & (q == b))[0] for b in range(5)}
        st = run_structure(d.reset_index(drop=True), swing_len=LEN, internal_len=3)
        ev = sorted([(e.i, 1 if e.bull else -1) for e in st.events if not e.internal])
        for k in range(len(ev) - 1):
            i0, side = ev[k]
            i_next = ev[k + 1][0]
            for a in AGES:
                i = i0 + a
                if i >= i_next or i >= n or not ok[i]:
                    continue                        # состояние уже сменилось — не входим
                acc[(tf, a, side)][0] += 1
                acc[(tf, a, side)][1] += fwd[i] * side
                pl = pools[q[i]]
                cs = np.mean([fwd[pl[RNG.integers(len(pl))]] * side for _ in range(3)]) \
                    if len(pl) else 0.0
                acc[(tf, a, side)][2] += cs
    if fi % 8 == 0:
        print(f"  [{fi}/{len(files)}]", flush=True)

print(f"\n=== ВХОД ПО ВОЗРАСТУ СОСТОЯНИЯ (форвард = 1 окно слоя) ===")
print(f"{'окно':>7} {'возраст':>8} {'n':>8} {'событие':>10} {'контроль':>10} {'сила':>9}")
for tf in TFS:
    for a in AGES:
        tot = sum(acc[(tf, a, s)][0] for s in (1, -1))
        if tot < 300:
            continue
        ev_ = sum(acc[(tf, a, s)][1] for s in (1, -1)) / tot
        ct = sum(acc[(tf, a, s)][2] for s in (1, -1)) / tot
        print(f"{tf*LEN:>7} {a:>8} {tot:>8,} {ev_:+9.4f}% {ct:+9.4f}% {ev_-ct:+8.4f}%")
    print()
