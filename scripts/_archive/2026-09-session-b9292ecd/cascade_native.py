# -*- coding: utf-8 -*-
"""КАСКАД — НЕЗАВИСИМАЯ РЕАЛИЗАЦИЯ ОТ 1m, БЕЗ КУБА (09.09.2026).

Куб дал ноль после починки утечки. Но это та же реализация с исправленной строкой.
Здесь — вторая, независимая: никакой общей сетки моментов, никакой склейки массивов.
Каждый слой живёт на своих барах, согласование только по ВРЕМЕНИ ЗАКРЫТИЯ.

Лестница от 1m: 1 · 3 · 5 · 15 · 30 · 60 · 240 (окна = ТФ × swing_len).
Каскад: слой k сменил направление, и ВСЕ младшие слои на своих закрытых барах
        уже смотрят туда же.
Форвард считается на ТФ слоя k, горизонт = 1 окно слоя.

🔴 Все обращения к младшим слоям идут через bisect по времени ЗАКРЫТИЯ бара:
   close_time = open_time + tf. Ровно та ошибка, что убила прошлый замер.
"""
import os, sys, glob, bisect
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.smc.oko_sm_engine import run_structure

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
TFS = [1, 3, 5, 15, 30, 60, 240]
SWING = 10
NSYM = 50
RNG = np.random.default_rng(20260909)
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))[:NSYM]
print(f"монет: {len(files)} | лестница ТФ: {TFS} | окна: {[t*SWING for t in TFS]}\n",
      flush=True)


def resample(d1, tf):
    if tf == 1:
        return d1[["open", "high", "low", "close"]]
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


def trend_series(d):
    """Тренд слоя по его барам: знак последнего swing-события (не internal)."""
    st = run_structure(d.reset_index(drop=True), swing_len=SWING, internal_len=3)
    n = len(d)
    tr = np.zeros(n, np.int8)
    ev = sorted([e for e in st.events if not e.internal], key=lambda e: e.i)
    t_, p = 0, 0
    changes = []
    for b in range(n):
        while p < len(ev) and ev[p].i <= b:
            nt = 1 if ev[p].bull else -1
            if nt != t_:
                changes.append((b, nt))
            t_ = nt
            p += 1
        tr[b] = t_
    return tr, changes


rows = []
for fi, f in enumerate(files, 1):
    sym = os.path.basename(f)[:-8]
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    lay = {}
    for tf in TFS:
        d = resample(d1, tf)
        if len(d) < 400:
            continue
        tr, ch = trend_series(d)
        # ВРЕМЯ ЗАКРЫТИЯ каждого бара слоя
        close_t = (d.index.values + np.timedelta64(tf, "m")).astype("datetime64[ns]")
        c = d["close"].values
        n = len(c)
        h = SWING                                   # горизонт = 1 окно слоя
        fwd = np.full(n, np.nan)
        fwd[:-h] = (c[h:] - c[:-h]) / c[:-h] * 100
        atr = ((d["high"] - d["low"]) / d["close"]).rolling(100,
                                                            min_periods=30).mean().values
        lay[tf] = dict(tr=tr, ch=ch, close_t=close_t, fwd=fwd, atr=atr, n=n)
    for li in range(1, len(TFS)):                   # слой 0 не имеет младших
        tf = TFS[li]
        if tf not in lay:
            continue
        A = lay[tf]
        ok = ~np.isnan(A["fwd"]) & ~np.isnan(A["atr"])
        if ok.sum() < 200:
            continue
        q = np.zeros(A["n"], np.int8)
        v = A["atr"]; m_ok = ~np.isnan(v)
        q[m_ok] = np.digitize(v[m_ok], np.nanpercentile(v[m_ok], [20, 40, 60, 80]))
        pools = {b: np.where(ok & (q == b))[0] for b in range(5)}
        for b, side in A["ch"]:
            if b >= A["n"] or not ok[b]:
                continue
            t_close = A["close_t"][b]               # момент, когда событие стало известно
            # согласны ли ВСЕ младшие слои на своих ЗАКРЫТЫХ барах
            agree = 0; total = 0
            for lj in range(li):
                tj = TFS[lj]
                if tj not in lay:
                    continue
                B = lay[tj]
                j = bisect.bisect_right(B["close_t"], t_close) - 1
                if j < 0:
                    continue
                total += 1
                if B["tr"][j] == side:
                    agree += 1
            if total == 0:
                continue
            pl = pools[q[b]]
            ctl = A["fwd"][pl[RNG.integers(len(pl))]] * side if len(pl) else 0.0
            rows.append((tf, tf * SWING, side, sym, agree, total,
                         float(A["fwd"][b] * side), float(ctl), int(b >= A["n"] // 2)))
    if fi % 8 == 0:
        print(f"  [{fi}/{len(files)}] событий {len(rows):,}", flush=True)

R = pd.DataFrame(rows, columns=["tf", "win", "side", "sym", "agree", "total",
                                "ret", "ctl", "half"])
R["net"] = R.ret - R.ctl
R["full"] = R.agree == R.total
R.to_pickle(D + r"\cascade_native.pkl")
print(f"\nсобытий: {len(R):,}\n")

print("=== КАСКАД (все младшие согласны) против ОСТАЛЬНЫХ смен направления ===")
print(f"{'окно':>7} {'стор':>6} {'каскад n':>9} {'каскад':>9} {'мед':>9} "
      f"{'прочие n':>9} {'прочие':>9} {'IS→OOS':>8} {'монет+':>8}")
for (win, side), g in R.groupby(["win", "side"]):
    gc = g[g.full]; go = g[~g.full]
    if len(gc) < 150:
        continue
    nm = "вверх" if side == 1 else "вниз"
    i_, o_ = gc[gc.half == 0].net, gc[gc.half == 1].net
    tag = "—"
    if len(i_) >= 60 and len(o_) >= 60:
        tag = "✓" if i_.mean() * o_.mean() > 0 and i_.mean() > 0 else "✗"
    per = gc.groupby("sym").net.mean()
    print(f"{win:>7} {nm:>6} {len(gc):>9,} {gc.net.mean():+8.4f}% "
          f"{gc.net.median():+8.4f}% {len(go):>9,} "
          f"{(go.net.mean() if len(go) else np.nan):+8.4f}% {tag:>8} "
          f"{int((per>0).sum())}/{len(per)}")

print("\n=== ГРАДИЕНТ ПО ЧИСЛУ СОГЛАСНЫХ МЛАДШИХ ===")
print(f"{'окно':>7} {'согл.':>7} {'n':>8} {'сила':>9} {'мед':>9}")
for win, g in R.groupby("win"):
    for a, gg in g.groupby("agree"):
        if len(gg) < 200:
            continue
        print(f"{win:>7} {a:>3}/{gg.total.iloc[0]} {len(gg):>8,} "
              f"{gg.net.mean():+8.4f}% {gg.net.median():+8.4f}%")
    print()
