# -*- coding: utf-8 -*-
"""ГДЕ ИНФОРМАЦИЯ СКОНЦЕНТРИРОВАНА: ищем подмножество с локальным плюсом (09.09.2026).

Потолок 55.6% — СРЕДНЕЕ по всем моментам. Информация неравномерна: слой 6600 несёт
её в 10 раз больше остальных. Значит есть ячейки с локальной точностью выше средней.

Протокол честный: порог отбора выбирается на IS (первая половина), проверяется на OOS
(вторая), открывается один раз. Плюс охват монет и зеркальность (long/short).
Косты варьируются: 0.35% (рынок) · 0.15% (лимит) · 0.06% (maker).
"""
import os, sys
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
z = np.load(D + r"\hypercube50_fix.npz", allow_pickle=True)
T, F, SY = z["T"], z["F"], z["SY"]
L = T.shape[1]
HOR = {"4ч": 1, "12ч": 2, "24ч": 3}
COSTS = [0.35, 0.15, 0.06]

code = np.zeros(len(T), np.int32)
for i in range(L):
    code = code * 3 + (T[:, i] + 1)
uniq, cinv = np.unique(code, return_inverse=True)
NC = len(uniq)
# IS/OOS по времени внутри каждой монеты
half = np.zeros(len(T), np.int8)
for s in np.unique(SY):
    m = np.where(SY == s)[0]
    half[m[len(m) // 2:]] = 1
print(f"баров {len(T):,} · ячеек {NC} · IS {(half==0).sum():,} / OOS {(half==1).sum():,}\n")


def arr(u):
    s = []
    for _ in range(L):
        s.append({0: "▼", 1: "·", 2: "▲"}[int(u % 3)]); u //= 3
    return "".join(s[::-1])


for hn, hj in HOR.items():
    y = F[:, hj]
    ok = ~np.isnan(y)
    print(f"{'='*96}\nГОРИЗОНТ {hn}   средний |ход| {np.nanmean(np.abs(y)):.3f}%")
    # средний знаковый исход по ячейке НА IS
    stats = {}
    for ci in range(NC):
        m_is = (cinv == ci) & ok & (half == 0)
        if m_is.sum() < 400:
            continue
        stats[ci] = float(np.nanmean(y[m_is]))
    if not stats:
        continue
    keys = np.array(list(stats)); vals = np.array([stats[k] for k in keys])
    print(f"  ячеек с n_IS≥400: {len(keys)} · среднее по ним {vals.mean():+.4f}% · "
          f"разброс {vals.std():.4f}%")
    print(f"\n{'порог IS':>10} {'ячеек':>7} {'сделок OOS':>11} {'ход OOS':>9} "
          f"{'WR OOS':>7} " + " ".join(f"нетто@{c:.2f}" for c in COSTS) + "  монет+")
    for q in [50, 70, 85, 95, 99]:
        thr = np.percentile(np.abs(vals), q)
        sel_lo = keys[vals <= -thr]      # ячейки с отрицательным сдвигом → шорт
        sel_hi = keys[vals >= thr]       # с положительным → лонг
        mask = np.zeros(len(T), bool); sgn = np.zeros(len(T), np.int8)
        for ci in sel_hi:
            mm = (cinv == ci); mask |= mm; sgn[mm] = 1
        for ci in sel_lo:
            mm = (cinv == ci); mask |= mm; sgn[mm] = -1
        m_oos = mask & ok & (half == 1)
        if m_oos.sum() < 2000:
            continue
        v = y[m_oos] * sgn[m_oos]
        per = []
        for s in np.unique(SY[m_oos]):
            mm = m_oos & (SY == s)
            if mm.sum() > 50:
                per.append(np.nanmean(y[mm] * sgn[mm]))
        nets = " ".join(f"{v.mean()-c:+10.4f}" for c in COSTS)
        print(f"{q:>9}% {len(sel_hi)+len(sel_lo):>7} {m_oos.sum():>11,} "
              f"{v.mean():+8.4f}% {(v>0).mean()*100:6.1f}% {nets}  "
              f"{sum(1 for x in per if x>0)}/{len(per)}")
    # топ-ячейки по IS и их поведение на OOS
    order = np.argsort(-np.abs(vals))[:8]
    print(f"\n  {'ячейка':>9} {'IS ход':>9} {'n IS':>8} {'OOS ход':>9} {'n OOS':>8} "
          f"{'знак':>6}")
    for oi in order:
        ci = keys[oi]
        m_o = (cinv == ci) & ok & (half == 1)
        if m_o.sum() < 200:
            continue
        vo = float(np.nanmean(y[m_o]))
        print(f"  {arr(int(uniq[ci])):>9} {vals[oi]:+8.4f}% "
              f"{int(((cinv==ci)&ok&(half==0)).sum()):>8,} {vo:+8.4f}% {m_o.sum():>8,} "
              f"{'✓' if vals[oi]*vo > 0 else '✗':>6}")
    print()
