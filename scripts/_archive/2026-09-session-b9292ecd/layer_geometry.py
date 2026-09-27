# -*- coding: utf-8 -*-
"""ГЕОМЕТРИЯ СДЕЛКИ В МАСШТАБЕ СЛОЯ (чистый гиперкубный замер, 09.09.2026).

Гиперкуб выдал правило: стоп и цель обязаны быть из ОДНОГО слоя — рассогласование
масштабов гарантированно проигрывает (240m/5m: WR 0.7% против случайных 8.4%).
Здесь это правило применяется буквально.

Никаких признаков — только структура:
    событие = смена состояния слоя (на ЗАКРЫТОМ баре, куб пересчитан без утечки)
    стоп    = k × ATR слоя          (ATR в окне самого слоя)
    цель    = m × ATR слоя
Опора: случайное блуждание даёт WR ≈ 1/(1+m/k). Ищем отклонение ОТ НЕЁ, а не PF.

🔴 Контроль: случайный бар той же монеты, тот же квинтиль ATR, ТА ЖЕ геометрия.
"""
import os, sys, glob
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
z = np.load(D + r"\hypercube50_fix.npz", allow_pickle=True)
T, SY = z["T"], z["SY"]
W = [int(x) for x in z["windows"]]; L = T.shape[1]
BASE = 3
GRID = [(1.0, 1.0), (1.0, 2.0), (1.0, 3.0), (1.5, 1.5), (1.5, 3.0), (2.0, 2.0),
        (2.0, 4.0), (3.0, 3.0)]
MAXHOLD = 60          # держим не дольше 60 окон слоя
COST = 0.35
RNG = np.random.default_rng(20260909)

px = []
for f in sorted(glob.glob(r"C:\oko_history\1m\*.parquet")):
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    r = d1.resample("3min", label="left", closed="left")
    c = pd.DataFrame({"high": r["high"].max(), "low": r["low"].min(),
                      "close": r["close"].last()}).dropna()
    px.append(c.values[6600 // BASE:])
PX = np.vstack(px)
HI, LO, CL = PX[:, 0], PX[:, 1], PX[:, 2]
assert len(PX) == len(T), (len(PX), len(T))
print(f"баров: {len(PX):,} | монет: {len(np.unique(SY))}\n", flush=True)

bnd = {int(s): (int(np.where(SY == s)[0][0]), int(np.where(SY == s)[0][-1]))
       for s in np.unique(SY)}


def simulate(idx, side, stop_pct, tgt_pct, hold):
    """Проход вперёд до стопа или цели. Консервативно: стоп проверяется первым."""
    out = np.empty(len(idx))
    for n_, i in enumerate(idx):
        hi_b = bnd[int(SY[i])][1]
        e = CL[i]
        sl = e * (1 - side * stop_pct[n_] / 100)
        tp = e * (1 + side * tgt_pct[n_] / 100)
        r = None
        for b in range(i + 1, min(i + 1 + hold, hi_b + 1)):
            if side == 1:
                if LO[b] <= sl: r = -stop_pct[n_]; break
                if HI[b] >= tp: r = tgt_pct[n_]; break
            else:
                if HI[b] >= sl: r = -stop_pct[n_]; break
                if LO[b] <= tp: r = tgt_pct[n_]; break
        if r is None:
            j = min(i + hold, hi_b)
            r = (CL[j] - e) / e * 100 * side
        out[n_] = r
    return out


code = np.zeros(len(T), np.int32)
for i in range(L):
    code = code * 3 + (T[:, i] + 1)
ev_idx = []
for s in np.unique(SY):
    m = np.where(SY == s)[0]
    for k in np.where(np.diff(code[m]) != 0)[0] + 1:
        ev_idx.append(int(m[k]))
EV = np.array(ev_idx)
Tf, Tt = T[EV - 1], T[EV]

print("=== ГЕОМЕТРИЯ В МАСШТАБЕ СЛОЯ · опора = WR случайного блуждания ===")
print(f"{'слой':>5} {'окно':>6} {'стоп':>5} {'цель':>5} {'стор':>6} {'n':>7} "
      f"{'стоп%':>7} {'WR':>6} {'WR случ':>8} {'Δ WR':>7} {'нетто':>8} {'ctlΔ':>7}")
for li in (2, 3, 4, 5):
    wmin = W[li]
    span = max(2, wmin // BASE)                    # окно ATR = окно слоя, в барах 3m
    atr = pd.Series((HI - LO) / CL).rolling(span, min_periods=span // 2).mean().values * 100
    hold = min(MAXHOLD * span, 4000)
    q = np.zeros(len(T), np.int8)
    for s in np.unique(SY):
        m = np.where(SY == s)[0]
        v = atr[m]; ok = ~np.isnan(v)
        if ok.sum() > 100:
            q[m[ok]] = np.digitize(v[ok], np.nanpercentile(v[ok], [20, 40, 60, 80])) + 1
    valid = ~np.isnan(atr)
    pools = {}
    for s in np.unique(SY):
        for b in range(1, 6):
            w_ = np.where((SY == s) & (q == b) & valid)[0]
            w_ = w_[(w_ > 10) & (w_ < len(CL) - hold - 2)]
            if len(w_):
                pools[(int(s), b)] = w_
    for k_, m_ in GRID:
        for side, nm in ((1, "вверх"), (-1, "вниз")):
            sel = (Tf[:, li] != Tt[:, li]) & (Tt[:, li] == side)
            ii = EV[sel]
            ii = ii[valid[ii] & (ii > 10)]
            ii = np.array([i for i in ii if i < bnd[int(SY[i])][1] - hold - 2])
            if len(ii) < 300:
                continue
            sp = atr[ii] * k_; tg = atr[ii] * m_
            r = simulate(ii, side, sp, tg, hold) - COST
            wr = (r > 0).mean() * 100
            wr0 = 1 / (1 + m_ / k_) * 100
            # контроль той же геометрии
            pick = np.array([pools.get((int(SY[i]), q[i]), ii)[
                RNG.integers(len(pools.get((int(SY[i]), q[i]), ii)))] for i in ii])
            rc = simulate(pick, side, atr[pick] * k_, atr[pick] * m_, hold) - COST
            print(f"{li:>5} {wmin:>6} {k_:5.1f} {m_:5.1f} {nm:>6} {len(ii):>7,} "
                  f"{np.median(sp):6.2f}% {wr:5.1f}% {wr0:7.1f}% {wr-wr0:+6.1f} "
                  f"{r.mean():+7.3f}% {r.mean()-rc.mean():+6.3f}%")
    print()
