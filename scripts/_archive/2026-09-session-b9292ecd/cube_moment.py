# -*- coding: utf-8 -*-
"""СРЕЗ ГИПЕРКУБА В МОМЕНТ ЯКОРЯ (постановка Егора, 09.09.2026).

Якорь: WT-кросс вверх ИЗ ПЕРЕПРОДАННОСТИ на 3m (wt1 пересекает wt2 снизу, wt1 < -60).
Вопрос: что было в кубе вокруг этого момента на трёх ОКНАХ (не ТФ!) — и что было потом.

Слои по окнам детектора (len=50): 3m→150 мин · 15m→750 мин · 60m→3000 мин.
🔴 Каузальность: у старших слоёв берётся последний ЗАКРЫТЫЙ бар строго ДО якоря.
🔴 Первый заход — ОПИСАТЕЛЬНЫЙ. Никакого отбора конфигураций: их тысячи, отбор без
   слепого протокола гарантированно найдёт шум. Отбор — отдельным шагом, через
   research_harness.blind_select.
"""
import os, sys, glob
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.smc.oko_sm_engine import run_structure
from core.indicators.indicators import calculate_wt

SRC = r"C:\oko_history\1m"
OUT = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
       r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19"
       r"\scratchpad\cube_moment.pkl")
WT_OS = -60.0
LAYERS = [("L0", 3), ("L1", 15), ("L2", 60)]     # окна 150 / 750 / 3000 мин при len=50
FWD_H = [1, 4, 12, 24]


def resample(d1, tf):
    if tf == 1:
        return d1
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last(),
                         "volume": r["volume"].sum() if "volume" in d1 else 0}).dropna()


def layer_state(d):
    """Каузальное состояние структуры по барам: тренд, давность и вид последнего слома."""
    st = run_structure(d.reset_index(drop=True), swing_len=50, internal_len=5)
    n = len(d)
    trend = np.zeros(n, np.int8); itrend = np.zeros(n, np.int8)
    last_i = np.full(n, -1, np.int32)
    kind = np.zeros(n, np.int8)          # 1 = CHoCH, 2 = BOS (последний swing-слом)
    t = it = 0; li = -1; kd = 0
    ev = sorted(st.events, key=lambda e: e.i)
    p = 0
    for b in range(n):
        while p < len(ev) and ev[p].i <= b:
            e = ev[p]
            if e.internal:
                it = 1 if e.bull else -1
            else:
                t = 1 if e.bull else -1
                li = e.i; kd = 1 if e.kind == "CHoCH" else 2
            p += 1
        trend[b] = t; itrend[b] = it; last_i[b] = li; kind[b] = kd
    age = np.where(last_i >= 0, np.arange(n) - last_i, -1)
    return dict(trend=trend, itrend=itrend, age=age, kind=kind)


rows = []
files = sorted(glob.glob(SRC + r"\*.parquet"))
print(f"монет: {len(files)}", flush=True)
for fi, f in enumerate(files, 1):
    sym = os.path.basename(f)[:-8]
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    L = {}
    for name, tf in LAYERS:
        d = resample(d1, tf)
        d = calculate_wt(d.reset_index().rename(columns={"ts": "t"}))
        d.index = resample(d1, tf).index
        L[name] = (d, layer_state(d))

    d3, s3 = L["L0"]
    wt1 = d3["wt1"].values; wt2 = d3["wt2"].values
    cross = (wt1[1:] > wt2[1:]) & (wt1[:-1] <= wt2[:-1])
    deep = wt1[:-1] < WT_OS                       # перепроданность НА ПРЕДЫДУЩЕМ баре
    anchors = np.where(cross & deep)[0] + 1
    ts3 = d3.index.values
    close3 = d3["close"].values

    rec = []
    for a in anchors:
        if a < 300 or a >= len(d3) - 24 * 20:
            continue
        t0 = ts3[a]
        r = dict(sym=sym, ts=t0, px=close3[a])
        for name, tf in LAYERS:
            d, s = L[name]
            # каузально: последний ЗАКРЫТЫЙ бар слоя строго ДО якоря
            j = int(np.searchsorted(d.index.values, t0, "left")) - 1
            if j < 100:
                r = None; break
            r[f"{name}_trend"] = int(s["trend"][j])
            r[f"{name}_itrend"] = int(s["itrend"][j])
            r[f"{name}_age"] = int(s["age"][j])
            r[f"{name}_kind"] = int(s["kind"][j])
            r[f"{name}_wt"] = float(d["wt1"].values[j])
        if r is None:
            continue
        for h in FWD_H:
            k = a + h * 20                        # 20 баров 3m = 1 час
            r[f"fwd{h}h"] = ((close3[k] - close3[a]) / close3[a] * 100
                             if k < len(close3) else np.nan)
        rec.append(r)
    rows += rec
    print(f"[{fi}/{len(files)}] {sym}: якорей {len(rec):,}", flush=True)

df = pd.DataFrame(rows)
df.to_pickle(OUT)
print(f"\nвсего якорей: {len(df):,}\n", flush=True)

# --- КОНТРОЛЬ: базовая доходность на случайных барах тех же монет ---
print("=== БАЗА (все якоря) против рынка ===")
for h in FWD_H:
    c = f"fwd{h}h"
    print(f"  +{h:>2}ч: среднее {df[c].mean():+.3f}%  медиана {df[c].median():+.3f}%  "
          f"доля>0 {(df[c] > 0).mean()*100:.1f}%  n={df[c].notna().sum():,}")

print("\n=== СРЕЗ ПО КОНФИГУРАЦИИ ТРЕНДОВ ТРЁХ СЛОЁВ (описательно, без отбора) ===")
df["cfg"] = (df.L0_trend.astype(str) + "/" + df.L1_trend.astype(str)
             + "/" + df.L2_trend.astype(str))
g = df.groupby("cfg").agg(n=("fwd4h", "size"), m4=("fwd4h", "mean"),
                          med4=("fwd4h", "median"), p4=("fwd4h", lambda x: (x > 0).mean()),
                          m24=("fwd24h", "mean"), med24=("fwd24h", "median"))
g = g[g.n >= 200].sort_values("m4", ascending=False)
print(f"{'L0/L1/L2':>10} {'n':>7} {'ср +4ч':>9} {'мед +4ч':>9} {'>0':>6} "
      f"{'ср +24ч':>9} {'мед +24ч':>9}")
for k, r in g.iterrows():
    print(f"{k:>10} {int(r.n):7,} {r.m4:+8.3f}% {r.med4:+8.3f}% {r.p4*100:5.1f}% "
          f"{r.m24:+8.3f}% {r.med24:+8.3f}%")

print("\n=== ЧТО ДАЁТ КАЖДЫЙ СЛОЙ ПО ОТДЕЛЬНОСТИ (тренд слоя vs форвард +4ч) ===")
for name, _ in LAYERS:
    s = df.groupby(f"{name}_trend")["fwd4h"].agg(["size", "mean", "median"])
    print(f"  {name}: " + " | ".join(
        f"тренд {int(k):+d}: n={int(v['size']):,} ср {v['mean']:+.3f}% мед {v['median']:+.3f}%"
        for k, v in s.iterrows()))
