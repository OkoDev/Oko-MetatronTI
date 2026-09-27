# -*- coding: utf-8 -*-
"""ПРОВЕРКА СХЕМЫ: утечка · контроль удержанием · сила кросса (10.09.2026).

Схема дала +338.9% на монету за 20 мес, 48/48 монет. Прежде чем верить — три теста:

  1. УТЕЧКА: вход по СЛЕДУЮЩЕМУ бару вместо бара сигнала. Если результат рушится —
     сигнал использовал цену, недоступную в момент решения.
  2. КОНТРОЛЬ: просто держать по режиму 240m БЕЗ кроссов вообще. Если контроль даёт
     столько же — кроссы ни при чём, работает только режим старшего ТФ.
  3. СИЛА КРОССА (идея Егора): |wt1 − wt2| в момент пересечения как мера импульса.
     Отбор по силе должен давать градиент, если величина информативна.
"""
import os, sys, glob, bisect, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_wt

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
TF_REG, TF_IN = 240, 60
MED_LEN = 34
OS, OB = -60.0, 60.0
TIMEOUT = 200
COST = 0.35
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))
print(f"монет: {len(files)} · режим {TF_REG}m → вход {TF_IN}m\n", flush=True)


def resample(d1, tf):
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


rows, ctl_rows = [], []
for fi, f in enumerate(files, 1):
    sym = os.path.basename(f)[:-8]
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    dr = resample(d1, TF_REG); di = resample(d1, TF_IN)
    if len(dr) < 200 or len(di) < 600:
        continue
    wr_ = calculate_wt(dr.reset_index(drop=True))
    medr = pd.Series(wr_["wt1"].values).rolling(MED_LEN,
                                                min_periods=MED_LEN // 2).mean().values
    above = wr_["wt1"].values > medr
    ct_r = list(dr.index + pd.Timedelta(minutes=TF_REG))
    wi = calculate_wt(di.reset_index(drop=True))
    w1, w2 = wi["wt1"].values, wi["wt2"].values
    c = di["close"].values
    o = di["open"].values
    n = len(c)
    cu = np.zeros(n, bool); cd = np.zeros(n, bool)
    cu[1:] = (w1[:-1] <= w2[:-1]) & (w1[1:] > w2[1:])
    cd[1:] = (w1[:-1] >= w2[:-1]) & (w1[1:] < w2[1:])
    x_up = cd & (w1 > OB)
    x_dn = cu & (w1 < OS)
    delta = np.abs(w1 - w2)          # сила кросса

    def exit_bar(i, side):
        arr = x_up if side == 1 else x_dn
        opp = cd if side == 1 else cu
        lim = min(i + TIMEOUT, n - 1)
        jz = np.where(arr[i + 1:lim + 1])[0]
        jo = np.where(opp[i + 1:lim + 1])[0]
        if len(jz):
            return i + 1 + int(jz[0])
        if len(jo):
            return i + 1 + int(jo[0])
        return lim

    # ── КОНТРОЛЬ: держать по режиму 240m без кроссов
    sd = np.zeros(n)
    for i in range(1, n):
        j = bisect.bisect_right(ct_r, di.index[i] + pd.Timedelta(minutes=TF_IN)) - 1
        if j < 5 or np.isnan(medr[j]):
            continue
        sd[i] = 1 if above[j] else -1
    ret = np.zeros(n)
    ret[1:] = (c[1:] - c[:-1]) / c[:-1] * 100 * sd[:-1]
    flips = int((np.diff(sd) != 0).sum())
    ctl_rows.append((sym, ret.sum() - flips * COST, flips))

    # ── сигналы + три варианта входа
    busy = {0: -1, 1: -1}     # busy[0] — вход по close бара сигнала, busy[1] — по следующему
    acc = {0: 0.0, 1: 0.0}
    cnt = {0: 0, 1: 0}
    for i in range(MED_LEN + 5, n - 5):
        for sig, side in ((cu[i], 1), (cd[i], -1)):
            if not sig:
                continue
            j = bisect.bisect_right(ct_r, di.index[i] + pd.Timedelta(minutes=TF_IN)) - 1
            if j < 5 or np.isnan(medr[j]):
                continue
            if (1 if above[j] else -1) != side:
                continue
            for shift in (0, 1):
                ii = i + shift
                if ii >= n - 3 or ii <= busy[shift]:
                    continue
                # вход: shift=0 → close бара сигнала; shift=1 → OPEN следующего бара
                entry = c[i] if shift == 0 else o[ii]
                jx = exit_bar(ii, side)
                r_ = (c[jx] - entry) / entry * 100 * side - COST
                acc[shift] += r_; cnt[shift] += 1; busy[shift] = jx
                if shift == 1:
                    rows.append((sym, side, float(delta[i]), r_, jx - ii,
                                 int(i >= n // 2)))
    if fi % 10 == 0:
        print(f"  [{fi}/{len(files)}] {sym}", flush=True)
    ctl_rows[-1] = ctl_rows[-1] + (acc[0], cnt[0], acc[1], cnt[1])

C = pd.DataFrame(ctl_rows, columns=["sym", "hold", "flips", "e0", "n0", "e1", "n1"])
R = pd.DataFrame(rows, columns=["sym", "side", "delta", "pnl", "bars", "half"])
R.to_pickle(D + r"\wt_verify.pkl")
print(f"\nмонет: {len(C)} · сделок (со сдвигом): {len(R):,}\n")

print("=== 1. ТЕСТ НА УТЕЧКУ: вход по бару сигнала против входа по следующему ===")
print(f"{'вариант':>34} {'сделок':>9} {'на монету':>11} {'на сделку':>11} {'монет+':>9}")
print(f"{'вход по close бара сигнала':>34} {C.n0.sum():>9,} {C.e0.mean():+10.1f}% "
      f"{C.e0.sum()/max(C.n0.sum(),1):+10.3f}% {int((C.e0>0).sum())}/{len(C)}")
print(f"{'вход по OPEN следующего бара':>34} {C.n1.sum():>9,} {C.e1.mean():+10.1f}% "
      f"{C.e1.sum()/max(C.n1.sum(),1):+10.3f}% {int((C.e1>0).sum())}/{len(C)}")
loss = (C.e0.mean() - C.e1.mean()) / max(abs(C.e0.mean()), 1e-9) * 100
print(f"\n  потеря от сдвига: {loss:.1f}%   "
      f"{'🔴 БЫЛА УТЕЧКА' if loss > 50 else '✅ утечки нет' if loss < 25 else '⚠️ частичная'}")

print("\n=== 2. КОНТРОЛЬ: удержание по режиму 240m БЕЗ кроссов ===")
print(f"  удержание по режиму: {C.hold.mean():+.1f}% на монету · переворотов "
      f"{C.flips.mean():.0f} · монет+ {int((C.hold>0).sum())}/{len(C)}")
print(f"  схема с кроссами:    {C.e1.mean():+.1f}% на монету · сделок "
      f"{C.n1.mean():.0f}")
print(f"  🔑 вклад кроссов сверх режима: {C.e1.mean() - C.hold.mean():+.1f} п.п. "
      f"({'кроссы добавляют' if C.e1.mean() > C.hold.mean() else 'кроссы НЕ добавляют'})")

print("\n=== 3. СИЛА КРОССА |wt1 − wt2| (идея Егора) ===")
R["dq"] = pd.qcut(R.delta, 5, labels=False, duplicates="drop")
print(f"{'квинтиль':>9} {'|wt1-wt2|':>11} {'n':>8} {'нетто':>9} {'мед':>9} "
      f"{'WR':>6} {'баров':>7}")
for q in sorted(R.dq.dropna().unique()):
    g = R[R.dq == q]
    print(f"{int(q)+1:>9} {g.delta.median():10.2f} {len(g):>8,} {g.pnl.mean():+8.3f}% "
          f"{g.pnl.median():+8.3f}% {(g.pnl>0).mean()*100:5.1f}% {g.bars.median():>7.0f}")
print()
for side, sn in [(1, "long"), (-1, "short")]:
    g = R[R.side == side]
    if len(g) < 200:
        continue
    hi = g[g.delta >= g.delta.quantile(.8)]
    lo = g[g.delta <= g.delta.quantile(.2)]
    print(f"  {sn:>5}: сильные кроссы {hi.pnl.mean():+.3f}% (n={len(hi):,}) · "
          f"слабые {lo.pnl.mean():+.3f}% (n={len(lo):,}) · "
          f"разница {hi.pnl.mean()-lo.pnl.mean():+.3f} п.п.")
