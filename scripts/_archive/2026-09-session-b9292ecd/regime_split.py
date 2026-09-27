# -*- coding: utf-8 -*-
"""РЕЖИМ ПРОТИВ СТРУКТУРЫ: лестница на 1h за 4 года, отбор на одной фазе → проверка
на противоположной (09.09.2026).

В окне 2025-01…2026-05 бычьей фазы нет, поэтому отбор ячеек всегда уходит в short
(58 против 3) и ловит режим. Здесь берём кэш 1h с 2022 года — там есть и бычий 2023.

Ячейка работает в ОБЕ фазы → структура. Только в свою → режим.

🔴 Каузально: состояние слоя берётся по времени ЗАКРЫТИЯ его бара (ошибка вида 6 учтена).
"""
import os, sys, sqlite3
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.smc.oko_sm_engine import run_structure

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
DB = "ohlcv_cache.db"
TFS_H = [1, 3, 8, 24, 72]        # часов: окна 10 · 30 · 80 · 240 · 720 ч
SWING = 10
FWD_H = 24                        # форвард 24 часа
NSYM = 80
cn = sqlite3.connect(DB)
syms = [r[0] for r in cn.execute(
    "SELECT symbol FROM ohlcv_cache WHERE timeframe='1h' AND symbol NOT LIKE 'binance:%' "
    "GROUP BY symbol HAVING COUNT(*)>25000 ORDER BY COUNT(*) DESC LIMIT ?", (NSYM,))]
print(f"монет: {len(syms)} | слои (окна, ч): {[t*SWING for t in TFS_H]}\n", flush=True)

allT, allF, allSY, allTS = [], [], [], []
for si, sym in enumerate(syms, 1):
    d = pd.read_sql("SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? "
                    "AND timeframe='1h' ORDER BY time", cn, params=(sym,))
    if len(d) < 20000:
        continue
    d.index = pd.to_datetime(d["time"], unit="ms", utc=True)
    d = d[["open", "high", "low", "close"]]
    nb = len(d)
    Tm = np.zeros((nb, len(TFS_H)), np.int8)
    for li, tf in enumerate(TFS_H):
        dd = d if tf == 1 else pd.DataFrame({
            "open": d["open"].resample(f"{tf}h").first(),
            "high": d["high"].resample(f"{tf}h").max(),
            "low": d["low"].resample(f"{tf}h").min(),
            "close": d["close"].resample(f"{tf}h").last()}).dropna()
        if len(dd) < 200:
            Tm = None; break
        st = run_structure(dd.reset_index(drop=True), swing_len=SWING, internal_len=3)
        n_ = len(dd)
        tr = np.zeros(n_, np.int8); t_ = 0; p = 0
        ev = sorted([e for e in st.events if not e.internal], key=lambda e: e.i)
        for b in range(n_):
            while p < len(ev) and ev[p].i <= b:
                t_ = 1 if ev[p].bull else -1; p += 1
            tr[b] = t_
        close_t = dd.index.values + np.timedelta64(tf, "h")   # ЗАКРЫТИЕ
        j = np.searchsorted(close_t, d.index.values, "right") - 1
        Tm[:, li] = np.where(j >= 0, tr[np.clip(j, 0, n_ - 1)], 0)
    if Tm is None:
        continue
    c = d["close"].values
    f = np.full(nb, np.nan)
    f[:-FWD_H] = (c[FWD_H:] - c[:-FWD_H]) / c[:-FWD_H] * 100
    warm = 72 * SWING
    allT.append(Tm[warm:]); allF.append(f[warm:])
    allSY.append(np.full(nb - warm, si, np.int16))
    allTS.append(d.index.values[warm:])
    if si % 20 == 0:
        print(f"  [{si}/{len(syms)}]", flush=True)

T = np.vstack(allT); F = np.concatenate(allF)
SY = np.concatenate(allSY); TS = np.concatenate(allTS)
L = T.shape[1]
print(f"\nбаров 1h: {len(T):,} | монет: {len(np.unique(SY))}\n")

# режим по кварталам: медианный дрейф всех монет
q = pd.PeriodIndex(pd.to_datetime(TS), freq="Q")
qq = pd.Series(q.astype(str))
drift = {}
for qk, idx in qq.groupby(qq).groups.items():
    v = F[np.array(idx)]
    v = v[~np.isnan(v)]
    if len(v) > 5000:
        drift[qk] = float(np.median(v))
print("=== ДРЕЙФ ПО КВАРТАЛАМ (медиана 24ч-хода) ===")
bull_q = [k for k, v in drift.items() if v > 0]
bear_q = [k for k, v in drift.items() if v <= 0]
for k in sorted(drift):
    print(f"  {k}: {drift[k]:+.4f}%  {'БЫК' if drift[k] > 0 else 'медведь'}")
print(f"\n  бычьих кварталов: {len(bull_q)} · медвежьих: {len(bear_q)}")

code = np.zeros(len(T), np.int32)
for i in range(L):
    code = code * 3 + (T[:, i] + 1)
uniq, cinv = np.unique(code, return_inverse=True)
is_bull = qq.isin(bull_q).values
ok = ~np.isnan(F)
print(f"  баров в бычьих: {(is_bull & ok).sum():,} · в медвежьих: {(~is_bull & ok).sum():,}")


def arr(u):
    s = []
    for _ in range(L):
        s.append({0: "▼", 1: "·", 2: "▲"}[int(u % 3)]); u //= 3
    return "".join(s[::-1])


print("\n=== ОТБОР НА ОДНОЙ ФАЗЕ → ПРОВЕРКА НА ДРУГОЙ ===")
for train_bull, nm in [(True, "обучение БЫК → тест МЕДВЕДЬ"),
                       (False, "обучение МЕДВЕДЬ → тест БЫК")]:
    tr_m = (is_bull == train_bull) & ok
    te_m = (is_bull != train_bull) & ok
    base_tr = np.nanmean(F[tr_m]); base_te = np.nanmean(F[te_m])
    stats = {}
    for ci in range(len(uniq)):
        m = (cinv == ci) & tr_m
        if m.sum() >= 500:
            stats[ci] = float(np.nanmean(F[m]) - base_tr)
    if not stats:
        continue
    keys = np.array(list(stats)); vals = np.array([stats[k] for k in keys])
    print(f"\n  {nm}  (база: обуч {base_tr:+.4f}% · тест {base_te:+.4f}%)")
    print(f"  {'порог':>6} {'long яч':>8} {'short яч':>9} {'n тест':>10} "
          f"{'ход тест':>10} {'сверх базы':>11} {'WR':>7} {'монет+':>8}")
    for qp in [70, 85, 95]:
        thr = np.percentile(np.abs(vals), qp)
        hi = keys[vals >= thr]; lo = keys[vals <= -thr]
        sgn = np.zeros(len(T), np.int8)
        sgn[np.isin(cinv, hi)] = 1
        sgn[np.isin(cinv, lo)] = -1
        m = te_m & (sgn != 0)
        if m.sum() < 2000:
            continue
        v = F[m] * sgn[m]
        bb = base_te * np.sign(sgn[m]).mean()
        per = []
        for s in np.unique(SY[m]):
            mm = m & (SY == s)
            if mm.sum() > 50:
                per.append(np.nanmean(F[mm] * sgn[mm]))
        print(f"  {qp:>5}% {len(hi):>8} {len(lo):>9} {m.sum():>10,} "
              f"{v.mean():+9.4f}% {v.mean()-abs(base_te):+10.4f}% "
              f"{(v>0).mean()*100:6.1f}% {sum(1 for x in per if x>0)}/{len(per)}")
np.savez_compressed(D + r"\regime_cube.npz", T=T, F=F, SY=SY,
                    is_bull=is_bull, code=code)
print("\nсохранено: regime_cube.npz")
