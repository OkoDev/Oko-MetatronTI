# -*- coding: utf-8 -*-
"""ЭКВИТИ ВМЕСТО СРЕДНЕГО ПО СДЕЛКАМ (вопрос Егора о перекрытии, 10.09.2026).

Прошлый замер дал +1.82% / +2.86% на сделку, но сделки ПЕРЕКРЫВАЮТСЯ: 613 входов
на монету в год при удержании 14-23 бара. Среднее по перекрывающимся сделкам
завышает — одно движение засчитывается несколько раз.

Три политики на ОДНИХ И ТЕХ ЖЕ входах:
    A  одна позиция за раз (лишние сигналы игнорируются)
    B  пирамидинг: добавление в ту же сторону, размер делится
    C  замена: новый сигнал закрывает старую позицию и открывает новую

Метрика — ЭКВИТИ портфеля: доходность на занятый капитал, а не среднее по сделкам.
Плюс: доля времени в рынке, максимальная просадка эквити, число сделок.
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
NSYM = 49
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))[:NSYM]
print(f"монет: {len(files)} · режим {TF_REG}m → вход {TF_IN}m\n", flush=True)


def resample(d1, tf):
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


res = {k: [] for k in ["A", "B", "C"]}
stats = []
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
    n = len(c)
    cu = np.zeros(n, bool); cd = np.zeros(n, bool)
    cu[1:] = (w1[:-1] <= w2[:-1]) & (w1[1:] > w2[1:])
    cd[1:] = (w1[:-1] >= w2[:-1]) & (w1[1:] < w2[1:])
    x_up = cd & (w1 > OB)
    x_dn = cu & (w1 < OS)
    # список сигналов
    sigs = []
    for i in range(MED_LEN + 5, n - 5):
        for sig, side in ((cu[i], 1), (cd[i], -1)):
            if not sig:
                continue
            j = bisect.bisect_right(ct_r, di.index[i] + pd.Timedelta(minutes=TF_IN)) - 1
            if j < 5 or np.isnan(medr[j]):
                continue
            if (1 if above[j] else -1) != side:
                continue
            sigs.append((i, side))
    if len(sigs) < 20:
        continue

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

    # ── A: одна позиция за раз
    eq = np.zeros(n); in_pos = np.zeros(n, bool)
    busy_until, cnt_a = -1, 0
    for i, side in sigs:
        if i <= busy_until:
            continue
        jx = exit_bar(i, side)
        r_ = (c[jx] - c[i]) / c[i] * 100 * side - COST
        eq[jx] += r_; in_pos[i:jx + 1] = True
        busy_until = jx; cnt_a += 1
    res["A"].append((sym, eq.sum(), cnt_a, in_pos.mean(), eq.copy()))

    # ── B: пирамидинг, каждая позиция размером 1/MAXPOS
    MAXPOS = 3
    eqb = np.zeros(n); occ = np.zeros(n)
    open_pos, cnt_b = [], 0
    for i, side in sigs:
        open_pos = [p for p in open_pos if p[1] > i]
        if len(open_pos) >= MAXPOS:
            continue
        jx = exit_bar(i, side)
        r_ = ((c[jx] - c[i]) / c[i] * 100 * side - COST) / MAXPOS
        eqb[jx] += r_; occ[i:jx + 1] += 1.0 / MAXPOS
        open_pos.append((i, jx)); cnt_b += 1
    res["B"].append((sym, eqb.sum(), cnt_b, (occ > 0).mean(), eqb.copy()))

    # ── C: замена — новый сигнал закрывает старую позицию
    eqc = np.zeros(n); in_c = np.zeros(n, bool)
    cur, cnt_c = None, 0
    for i, side in sigs:
        if cur is not None:
            ci, cside, cjx = cur
            if i < cjx:
                r_ = (c[i] - c[ci]) / c[ci] * 100 * cside - COST
                eqc[i] += r_; in_c[ci:i + 1] = True
                cur = None
            else:
                r_ = (c[cjx] - c[ci]) / c[ci] * 100 * cside - COST
                eqc[cjx] += r_; in_c[ci:cjx + 1] = True
                cur = None
        jx = exit_bar(i, side)
        cur = (i, side, jx); cnt_c += 1
    if cur is not None:
        ci, cside, cjx = cur
        eqc[cjx] += (c[cjx] - c[ci]) / c[ci] * 100 * cside - COST
        in_c[ci:cjx + 1] = True
    res["C"].append((sym, eqc.sum(), cnt_c, in_c.mean(), eqc.copy()))
    stats.append((sym, n, len(sigs)))
    if fi % 8 == 0:
        print(f"  [{fi}/{len(files)}] {sym}", flush=True)

NAMES = {"A": "одна позиция", "B": "пирамидинг ×3", "C": "замена"}
print(f"\nмонет обработано: {len(stats)} · сигналов всего: "
      f"{sum(s[2] for s in stats):,}\n")
print("=== ЭКВИТИ ПО ПОЛИТИКАМ (сумма % на монету за 20 месяцев) ===")
print(f"{'политика':>16} {'сделок':>9} {'сумма %':>10} {'на сделку':>11} "
      f"{'в рынке':>9} {'монет+':>9} {'мед по монете':>14}")
for k in ["A", "B", "C"]:
    v = res[k]
    if not v:
        continue
    tot = np.array([x[1] for x in v])
    cnt = np.array([x[2] for x in v])
    occ = np.array([x[3] for x in v])
    print(f"{NAMES[k]:>16} {cnt.sum():>9,} {tot.mean():+9.1f}% "
          f"{tot.sum()/max(cnt.sum(),1):+10.3f}% {occ.mean()*100:8.1f}% "
          f"{int((tot > 0).sum())}/{len(tot)} {np.median(tot):+13.1f}%")

print("\n=== ПРОСАДКА ЭКВИТИ (политика A, по монетам) ===")
dds = []
for sym, tot, cnt, occ, eq in res["A"]:
    cum = np.cumsum(eq)
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak).min()
    dds.append((sym, tot, dd))
dds.sort(key=lambda x: x[2])
arr_dd = np.array([d[2] for d in dds])
print(f"  медианная макс. просадка: {np.median(arr_dd):.1f}%  ·  худшая "
      f"{arr_dd.min():.1f}%  ·  лучшая {arr_dd.max():.1f}%")
print(f"  монет с просадкой глубже суммарной прибыли: "
      f"{sum(1 for s, t, d in dds if abs(d) > t)}/{len(dds)}")

print("\n=== ТОП И АНТИТОП МОНЕТ (политика A) ===")
v = sorted(res["A"], key=lambda x: -x[1])
print(f"  {'символ':>16} {'сумма %':>10} {'сделок':>8} {'в рынке':>9}")
for x in v[:5] + v[-5:]:
    print(f"  {x[0]:>16} {x[1]:+9.1f}% {x[2]:>8,} {x[3]*100:8.1f}%")
