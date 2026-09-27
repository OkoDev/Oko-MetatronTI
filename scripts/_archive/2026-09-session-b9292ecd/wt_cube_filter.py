# -*- coding: utf-8 -*-
"""КУБ КАК ФИЛЬТР ДОЛЁТА (Егор: «куб поможет с медианой вопрос решить», 10.09.2026).

Проблема прошлого замера: 30-38% сделок НЕ долетают до разворота в зоне и портят
результат. Плюс я считал по долетевшим — выжившая выборка.

Здесь:
  1. ЕДИНАЯ политика выхода для ВСЕХ входов, без отсева:
        разворот в зоне если случился → иначе кросс против → иначе таймаут
  2. КУБ как классификатор долёта: различает ли состояние 7 слоёв в момент входа
     тех, кто долетит, от тех, кто зависнет
  3. Фильтр по кубу: улучшает ли отбор результат ПО ВСЕМУ ПОТОКУ

Куб — hypercube50_fix (без look-ahead), сетка 3m; входы на 60m по режиму 240m.
🔴 Метка долёта известна только ПОСЛЕ — поэтому куб проверяется как ПРЕДИКТОР, а
   решение о входе принимается ТОЛЬКО по состоянию куба в момент входа.
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
z = np.load(D + r"\hypercube50_fix.npz", allow_pickle=True)
T, SY_C = z["T"], z["SY"]
W = [int(x) for x in z["windows"]]; L = T.shape[1]
TF_REG, TF_IN = 240, 60
MED_LEN = 34
OS, OB = -60.0, 60.0
TIMEOUT = 200
COST = 0.35

# ── восстановить временную ось куба (тот же порядок файлов и прогрев)
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))
cube_ts, cube_sym = [], []
fi = 0
for f in files:
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    fi += 1
    r = d1.resample("3min", label="left", closed="left")
    c = pd.DataFrame({"close": r["close"].last()}).dropna()
    cube_ts.append(c.index.values[2200:])
    cube_sym.append(np.full(len(c) - 2200, os.path.basename(f)[:-8], dtype=object))
CTS = np.concatenate(cube_ts); CSY = np.concatenate(cube_sym)
assert len(CTS) == len(T)
code = np.zeros(len(T), np.int32)
for i in range(L):
    code = code * 3 + (T[:, i] + 1)
print(f"куб: {len(T):,} баров · {len(np.unique(CSY))} монет\n", flush=True)
by_sym = {}
for s in np.unique(CSY):
    m = np.where(CSY == s)[0]
    by_sym[s] = (CTS[m], code[m], T[m])


def resample(d1, tf):
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


rows = []
for fi, f in enumerate(files, 1):
    sym = os.path.basename(f)[:-8]
    if sym not in by_sym:
        continue
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
    cts, ccode, cT = by_sym[sym]
    for i in range(MED_LEN + 5, n - 5):
        for sig, side in ((cu[i], 1), (cd[i], -1)):
            if not sig:
                continue
            t_now = di.index[i] + pd.Timedelta(minutes=TF_IN)
            j = bisect.bisect_right(ct_r, t_now) - 1
            if j < 5 or np.isnan(medr[j]):
                continue
            if (1 if above[j] else -1) != side:
                continue                      # только ПО режиму старшего
            # состояние куба на момент входа (последний бар куба ДО t_now)
            k = bisect.bisect_right(cts, t_now.to_datetime64()) - 1
            if k < 0:
                continue
            e = c[i]
            exit_arr = x_up if side == 1 else x_dn
            opp = cd if side == 1 else cu
            lim = min(i + TIMEOUT, n - 1)
            # ЕДИНАЯ политика: зона → иначе кросс против → иначе таймаут
            jz = np.where(exit_arr[i + 1:lim + 1])[0]
            jo = np.where(opp[i + 1:lim + 1])[0]
            if len(jz):
                jx, how = i + 1 + int(jz[0]), "zone"
            elif len(jo):
                jx, how = i + 1 + int(jo[0]), "opp"
            else:
                jx, how = lim, "timeout"
            rows.append(dict(sym=sym, side=side, cell=int(ccode[k]),
                             against=int((cT[k] == -side).sum()),
                             along=int((cT[k] == side).sum()),
                             pnl=(c[jx] - e) / e * 100 * side, how=how,
                             reached=int(how == "zone"), bars=jx - i,
                             half=int(i >= n // 2)))
    if fi % 8 == 0:
        print(f"  [{fi}/{len(files)}] сделок {len(rows):,}", flush=True)

R = pd.DataFrame(rows)
R["net"] = R.pnl - COST
R.to_pickle(D + r"\wt_cube_filter.pkl")
print(f"\nсделок: {len(R):,} · долетело до зоны: {R.reached.mean()*100:.1f}%\n")

print("=== 1. ЧЕСТНЫЙ РЕЗУЛЬТАТ ПО ВСЕМУ ПОТОКУ (единая политика выхода) ===")
print(f"{'стор':>6} {'n':>8} {'нетто':>9} {'мед':>9} {'WR':>6} {'IS':>9} {'OOS':>9} "
      f"{'перенос':>8} {'монет+':>9}")
for side, sn in [(1, "long"), (-1, "short")]:
    g = R[R.side == side]
    if len(g) < 200:
        continue
    i_, o_ = g[g.half == 0].net, g[g.half == 1].net
    tag = "✓" if i_.mean() * o_.mean() > 0 and i_.mean() > 0 else "✗"
    per = g.groupby("sym").net.mean()
    print(f"{sn:>6} {len(g):>8,} {g.net.mean():+8.3f}% {g.net.median():+8.3f}% "
          f"{(g.net>0).mean()*100:5.1f}% {i_.mean():+8.3f}% {o_.mean():+8.3f}% "
          f"{tag:>8} {int((per>0).sum())}/{len(per)}")

print("\n=== 2. РАЗЛИЧАЕТ ЛИ КУБ ДОЛЁТ (слоёв ПРОТИВ входа) ===")
base = R.reached.mean()
print(f"{'слоёв против':>13} {'n':>8} {'долетело':>10} {'lift':>7} {'нетто':>9} "
      f"{'мед':>9}")
for a in range(0, L + 1):
    g = R[R.against == a]
    if len(g) < 300:
        continue
    print(f"{a:>13} {len(g):>8,} {g.reached.mean()*100:9.1f}% "
          f"{g.reached.mean()/base:7.2f} {g.net.mean():+8.3f}% {g.net.median():+8.3f}%")

print("\n=== 3. ФИЛЬТР ПО КУБУ: улучшает ли ПО ВСЕМУ ПОТОКУ ===")
print(f"{'фильтр':>22} {'стор':>6} {'n':>8} {'доля':>7} {'нетто':>9} {'мед':>9} "
      f"{'IS':>9} {'OOS':>9} {'перенос':>8} {'монет+':>9}")
for lbl, cond in [("без фильтра", R.against >= 0),
                  ("слоёв против ≤2", R.against <= 2),
                  ("слоёв против ≤1", R.against <= 1),
                  ("слоёв против =0", R.against == 0)]:
    for side, sn in [(1, "long"), (-1, "short")]:
        g = R[cond & (R.side == side)]
        if len(g) < 200:
            continue
        i_, o_ = g[g.half == 0].net, g[g.half == 1].net
        tag = "✓" if len(i_) > 50 and len(o_) > 50 and i_.mean() * o_.mean() > 0 \
            and i_.mean() > 0 else "✗"
        per = g.groupby("sym").net.mean()
        tot = len(R[R.side == side])
        print(f"{lbl:>22} {sn:>6} {len(g):>8,} {len(g)/tot*100:6.1f}% "
              f"{g.net.mean():+8.3f}% {g.net.median():+8.3f}% {i_.mean():+8.3f}% "
              f"{o_.mean():+8.3f}% {tag:>8} {int((per>0).sum())}/{len(per)}")
    print()

print("=== 4. ЛУЧШИЕ ЯЧЕЙКИ КУБА ДЛЯ ДОЛЁТА (n≥300) ===")
def arr(u):
    s = []
    for _ in range(L):
        s.append({0: "▼", 1: "·", 2: "▲"}[int(u % 3)]); u //= 3
    return "".join(s[::-1])
agg = R.groupby(["cell", "side"]).agg(n=("net", "size"), reach=("reached", "mean"),
                                      net=("net", "mean")).reset_index()
agg = agg[agg.n >= 300].sort_values("net", ascending=False)
print(f"{'ячейка':>9} {'стор':>6} {'n':>7} {'долетело':>10} {'нетто':>9}")
for _, r in agg.head(8).iterrows():
    print(f"{arr(int(r.cell)):>9} {'long' if r.side==1 else 'short':>6} {int(r.n):>7,} "
          f"{r.reach*100:9.1f}% {r.net:+8.3f}%")
