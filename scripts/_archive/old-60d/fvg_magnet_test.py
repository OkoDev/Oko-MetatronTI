"""FVG midpoint reach rate test for ARCH-113 TPSelector."""
import pandas as pd
import numpy as np

BASE = "E:/MTF BOT/CURSOR/crypto_volume_bot/data/history"

df_1h = pd.read_parquet(f"{BASE}/1h/BTCUSDT.parquet")
df_4h = df_1h.resample("4h").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()

H4 = df_4h.high.values
L4 = df_4h.low.values
C4 = df_4h.close.values
H1 = df_1h.high.values
L1 = df_1h.low.values
C1 = df_1h.close.values


def find_bear_fvg(H, L):
    """Bear FVG = gap above price (LONG TP magnet). high[i] < low[i-2]."""
    out = []
    for i in range(2, len(H)):
        if H[i] < L[i-2]:
            b, t = H[i], L[i-2]
            out.append((i, b, t, (t + b) / 2))
    return out


def find_bull_fvg(H, L):
    """Bull FVG = gap below price (SL zone / SHORT TP magnet). low[i] > high[i-2]."""
    out = []
    for i in range(2, len(H)):
        if L[i] > H[i-2]:
            b, t = H[i-2], L[i]
            out.append((i, b, t, (t + b) / 2))
    return out


def test_reach_above(bars_close, bars_high, fvgs, lookahead, window=100):
    hit = miss = 0
    for bar in range(window, len(bars_close) - lookahead - 1):
        price = bars_close[bar]
        fh = bars_high[bar+1:bar+lookahead+1].max()
        best = None
        for (idx, b, t, m) in fvgs:
            if idx >= bar:
                break
            if idx < bar - window:
                continue
            if m <= price:
                continue
            max_h = bars_high[idx+1:bar].max() if idx+1 < bar else 0
            if max_h >= b:
                continue  # filled
            if best is None or m < best[3]:
                best = (idx, b, t, m)
        if best:
            if fh >= best[3]:
                hit += 1
            else:
                miss += 1
    return hit + miss, hit


fvgs4_bear = find_bear_fvg(H4, L4)
fvgs1_bear = find_bear_fvg(H1, L1)
print(f"4h Bear FVGs (LONG TP magnets): {len(fvgs4_bear)}")
print(f"1h Bear FVGs (LONG TP magnets): {len(fvgs1_bear)}")

t4, h4 = test_reach_above(C4, H4, fvgs4_bear, 20, 100)
print(f"\n4h Bear FVG mid reached (in 80h): {h4}/{t4} = {h4/t4*100:.0f}%")

t1, h1 = test_reach_above(C1, H1, fvgs1_bear, 48, 300)
print(f"1h Bear FVG mid reached (in 48h): {h1}/{t1} = {h1/t1*100:.0f}%")

# MTF cluster: 4h + 1h bear FVG midpoints within eps%
eps = 0.005
lookahead_4h = 20
hit_mtf = miss_mtf = 0
for bar4 in range(100, len(C4) - lookahead_4h - 1):
    price = C4[bar4]
    bar1 = bar4 * 4
    if bar1 >= len(C1):
        continue
    fh = H4[bar4+1:bar4+lookahead_4h+1].max()

    best4 = None
    for (idx, b, t, m) in fvgs4_bear:
        if idx >= bar4:
            break
        if idx < bar4 - 100:
            continue
        if m <= price:
            continue
        mh = H4[idx+1:bar4].max() if idx+1 < bar4 else 0
        if mh >= b:
            continue
        if best4 is None or m < best4[3]:
            best4 = (idx, b, t, m)

    if best4 is None:
        continue

    for (idx1, b1, t1, m1) in fvgs1_bear:
        if idx1 >= bar1:
            break
        if idx1 < bar1 - 400:
            continue
        if m1 <= price:
            continue
        if abs(m1 - best4[3]) / best4[3] > eps:
            continue
        mh1 = H1[idx1+1:bar1].max() if idx1+1 < bar1 else 0
        if mh1 >= b1:
            continue
        cluster = (best4[3] + m1) / 2
        if fh >= cluster:
            hit_mtf += 1
        else:
            miss_mtf += 1
        break

total_mtf = hit_mtf + miss_mtf
print(f"\nMTF 4h+1h Bear FVG cluster (eps={eps*100:.1f}%): {total_mtf} cases")
if total_mtf:
    print(f"  cluster reached in 80h: {hit_mtf}/{total_mtf} = {hit_mtf/total_mtf*100:.0f}%")

print(f"\n=== SUMMARY: BTC USDT, 2024-01 to 2026-05 ===")
print(f"  4h single Bear FVG mid as TP:  {h4/t4*100:.0f}%  (n={t4}, window=80h)")
print(f"  1h single Bear FVG mid as TP:  {h1/t1*100:.0f}%  (n={t1}, window=48h)")
if total_mtf:
    print(f"  MTF 4h+1h cluster as TP:       {hit_mtf/total_mtf*100:.0f}%  (n={total_mtf}, window=80h)")
