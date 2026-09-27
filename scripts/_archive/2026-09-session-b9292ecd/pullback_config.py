# -*- coding: utf-8 -*-
"""КОНФИГУРАЦИЯ ЭТАЛОНА: откат по тренду, формализованный в слоях (09.09.2026).

Снята с реального разворота HYPE 02.08.2026 (минимум 51.107):
    средние слои (окна 150-600)  ▲  тренд вверх
    цена в их диапазоне          0.07-0.09  — у самого дна
    младшие слои (окна 10-50)    ▼  откат внутри тренда
    свежая дивергенция на младшем (< 4 часов)
    ВХОД — CHoCH на младшем слое (в эталоне: +2.2ч от дна, +0.68% от минимума)

🔴 Вход на МЛАДШЕМ слое, не на старшем. Прошлые замеры входили на старшем и потому
   опаздывали на две недели и 15% хода.
🔴 Всё каузально: слои читаются по времени ЗАКРЫТИЯ бара, вход на баре сигнала.
🔴 Контроль: случайный бар той же монеты, тот же квинтиль ATR, та же геометрия.
"""
import os, sys, glob, bisect
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.smc.oko_sm_engine import run_structure
from core.calculators.combinator_core import _wtx_divergences
from core.indicators.indicators import calculate_wt

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
TF_TRG = 3                      # слой входа (младший)
TF_MID = [15, 30, 60]           # средние слои — контекст тренда
TF_LOW = [1, 5]                 # младшие — должны быть в откате
SWING = 10
POS_MAX = 0.25                  # цена в нижней четверти диапазона средних (для long)
DIV_H = 4.0                     # свежесть дивергенции на младшем, часов
HOR = [20, 60, 120, 240, 480]   # горизонты в барах TF_TRG (1ч…24ч)
NSYM = 50
COST = 0.35
RNG = np.random.default_rng(20260909)


def resample(d1, tf):
    if tf == 1:
        return d1[["open", "high", "low", "close"]]
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


def layer(d, tf):
    st = run_structure(d.reset_index(drop=True), swing_len=SWING, internal_len=3)
    n = len(d)
    tr = np.zeros(n, np.int8); t_ = 0; p = 0
    ev = sorted([e for e in st.events if not e.internal], key=lambda e: e.i)
    flips = []
    for b in range(n):
        while p < len(ev) and ev[p].i <= b:
            nt = 1 if ev[p].bull else -1
            if nt != t_:
                flips.append((b, nt))
            t_ = nt; p += 1
        tr[b] = t_
    lo = pd.Series(d["low"]).rolling(SWING, min_periods=3).min().values
    hi = pd.Series(d["high"]).rolling(SWING, min_periods=3).max().values
    rng_ = np.where(hi > lo, hi - lo, np.nan)
    pos = np.clip((d["close"].values - lo) / rng_, 0, 1)
    wd = calculate_wt(d.reset_index(drop=True))
    br, ber, _, _ = _wtx_divergences(wd["wt1"].values, d["low"].values, d["high"].values)
    ct = list(d.index + pd.Timedelta(minutes=tf))
    return dict(tr=tr, pos=pos, flips=flips, br=br, ber=ber, ct=ct, idx=d.index, n=n)


rows = []
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))[:NSYM]
print(f"монет: {len(files)} | вход на {TF_TRG}m | контекст {TF_MID} | откат {TF_LOW}\n",
      flush=True)
for fi, f in enumerate(files, 1):
    sym = os.path.basename(f)[:-8]
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    lay = {}
    for tf in sorted(set([TF_TRG] + TF_MID + TF_LOW)):
        d = resample(d1, tf)
        if len(d) < 300:
            continue
        lay[tf] = layer(d, tf)
    if TF_TRG not in lay or not all(t in lay for t in TF_MID):
        continue
    A = lay[TF_TRG]
    dtr = resample(d1, TF_TRG)
    c = dtr["close"].values
    atr = ((dtr["high"] - dtr["low"]) / dtr["close"]).rolling(200,
                                                              min_periods=60).mean().values
    q = np.zeros(A["n"], np.int8)
    okq = ~np.isnan(atr)
    if okq.sum() > 200:
        q[okq] = np.digitize(atr[okq], np.nanpercentile(atr[okq], [20, 40, 60, 80]))
    pools = {b: np.where(okq & (q == b))[0] for b in range(5)}
    for b, side in A["flips"]:
        if b < 50 or b >= A["n"] - max(HOR) - 2 or np.isnan(atr[b]):
            continue
        t_now = A["ct"][b]
        # контекст: средние слои должны смотреть В СТОРОНУ входа, цена у края их диапазона
        ok_mid = True; poss = []
        for tf in TF_MID:
            B = lay.get(tf)
            if B is None:
                ok_mid = False; break
            j = bisect.bisect_right(B["ct"], t_now) - 1
            if j < 5 or B["tr"][j] != side:
                ok_mid = False; break
            pp = B["pos"][j] if side == 1 else 1 - B["pos"][j]
            if not (pp <= POS_MAX):
                ok_mid = False; break
            poss.append(pp)
        if not ok_mid:
            continue
        # младшие: были в откате (тренд ПРОТИВ) + свежая дивергенция в сторону входа
        low_against = 0; div_fresh = False
        for tf in TF_LOW:
            B = lay.get(tf)
            if B is None:
                continue
            j = bisect.bisect_right(B["ct"], t_now) - 1
            if j < 5:
                continue
            if B["tr"][j] == -side:
                low_against += 1
            dv = B["br"] if side == 1 else B["ber"]
            hits = np.where(dv[:j + 1])[0]
            if len(hits):
                age = (B["ct"][j] - B["ct"][hits[-1]]).total_seconds() / 3600
                if age <= DIV_H:
                    div_fresh = True
        e = c[b]
        rec = dict(sym=sym, side=side, b=b, low_against=low_against,
                   div=int(div_fresh), pos=float(np.mean(poss)),
                   half=int(b >= A["n"] // 2))
        for h in HOR:
            rec[f"f{h}"] = (c[b + h] - e) / e * 100 * side
        pl = pools[q[b]]
        j2 = int(pl[RNG.integers(len(pl))]) if len(pl) else b
        j2 = min(j2, A["n"] - max(HOR) - 2)
        for h in HOR:
            rec[f"c{h}"] = (c[j2 + h] - c[j2]) / c[j2] * 100 * side
        rows.append(rec)
    if fi % 8 == 0:
        print(f"  [{fi}/{len(files)}] сигналов {len(rows):,}", flush=True)

R = pd.DataFrame(rows)
R.to_pickle(D + r"\pullback_config.pkl")
print(f"\nсигналов: {len(R):,}\n")
if len(R) < 100:
    print("СЛИШКОМ МАЛО — условие слишком узкое"); sys.exit()

print("=== КОНФИГУРАЦИЯ ЭТАЛОНА · вход CHoCH на 3m ===")
print(f"{'фильтр':>28} {'стор':>6} {'n':>7} " + " ".join(f"{h*3/60:>6.0f}ч" for h in HOR))
for nm, sub in [("база: контекст+позиция", R),
                ("+ младшие в откате (≥1)", R[R.low_against >= 1]),
                ("+ младшие в откате (=2)", R[R.low_against >= 2]),
                ("+ свежая дивергенция", R[R.div == 1]),
                ("ВСЁ ВМЕСТЕ (эталон)", R[(R.low_against >= 1) & (R.div == 1)])]:
    for side, sn in [(1, "long"), (-1, "short")]:
        g = sub[sub.side == side]
        if len(g) < 60:
            continue
        vals = " ".join(f"{g[f'f{h}'].mean() - g[f'c{h}'].mean():+6.3f}" for h in HOR)
        print(f"{nm:>28} {sn:>6} {len(g):>7,} {vals}")
    print()

print("=== ЭТАЛОННЫЙ НАБОР: полный протокол (горизонт 6ч) ===")
G = R[(R.low_against >= 1) & (R.div == 1)]
print(f"{'стор':>6} {'n':>7} {'сила':>9} {'мед':>9} {'IS':>9} {'OOS':>9} "
      f"{'перенос':>8} {'монет+':>8}")
for side, sn in [(1, "long"), (-1, "short")]:
    g = G[G.side == side]
    if len(g) < 60:
        continue
    net = g.f120 - g.c120
    i_, o_ = net[g.half == 0], net[g.half == 1]
    tag = "✓" if len(i_) > 25 and len(o_) > 25 and i_.mean() * o_.mean() > 0 \
        and i_.mean() > 0 else "✗"
    per = g.assign(n=net).groupby("sym").n.mean()
    print(f"{sn:>6} {len(g):>7,} {net.mean():+8.4f}% {net.median():+8.4f}% "
          f"{i_.mean():+8.4f}% {o_.mean():+8.4f}% {tag:>8} "
          f"{int((per>0).sum())}/{len(per)}")
