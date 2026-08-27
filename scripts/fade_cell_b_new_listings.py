# -*- coding: utf-8 -*-
"""КЛЕТКА B: новые листинги (появились после 2024-01) — фейд 4h в 2026 (13.08.2026, DS).

Разделяющий тест [[2026-08-12-Fade-Side-Flip-Full-Data]] показал: переворот = ПЕРИОД,
не состав (клетка C≈B). Здесь закрываем вторую клетку: монеты-«новые» (первый бар 4h
после 2024-01) против «старых» (<2023-01) на окне 2024+. Если и новые, и старые
в 2026 показывают SHORT-фейд живым (LONG мёртвым) — переворот действительно период.

Запуск: python scripts/fade_cell_b_new_listings.py
"""
import datetime as dt
import sqlite3
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

DB = "ohlcv_cache.db"
COST = 0.35
TF = "4h"
COOL = 2
t2024 = int(dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
t2023 = int(dt.datetime(2023, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)


def wt(df, n1=10, n2=21):
    hlc = (df.high + df.low + df.close) / 3
    esa = hlc.ewm(span=n1).mean()
    d = (hlc - esa).abs().ewm(span=n1).mean()
    return ((hlc - esa) / (0.015 * d.replace(0, np.nan))).ewm(span=n2).mean().fillna(0).values


def atrt(df, period=43, factor=1.25):
    h, l, c = df.high, df.low, df.close
    hl2 = ((h + l) / 2).values
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean().values
    up = hl2 - factor * atr; dn = hl2 + factor * atr
    n = len(c); cv = c.values
    u = np.zeros(n); d_ = np.zeros(n); dirn = np.zeros(n)
    u[0], d_[0], dirn[0] = up[0], dn[0], 1
    for i in range(1, n):
        u[i] = max(up[i], u[i-1]) if cv[i-1] > u[i-1] else up[i]
        d_[i] = min(dn[i], d_[i-1]) if cv[i-1] < d_[i-1] else dn[i]
        dirn[i] = 1 if cv[i] > d_[i-1] else (-1 if cv[i] < u[i-1] else dirn[i-1])
    return dirn


def ex(i, H, L, C, sl, side, ttl=24):
    e = C[i]
    if side == "LONG":
        tp = e + (e - sl); end = min(i + ttl, len(C) - 1)
        for j in range(i + 1, end + 1):
            if L[j] <= sl: return (sl - e) / e * 100
            if H[j] >= tp: return (tp - e) / e * 100
        return (C[end] - e) / e * 100
    tp = e - (sl - e); end = min(i + ttl, len(C) - 1)
    for j in range(i + 1, end + 1):
        if H[j] >= sl: return (e - sl) / e * 100
        if L[j] <= tp: return (e - tp) / e * 100
    return (e - C[end]) / e * 100


con = sqlite3.connect(DB)
first_bar = {r[0]: r[1] for r in con.execute(
    "SELECT symbol,MIN(time) FROM ohlcv_cache WHERE timeframe='4h' GROUP BY symbol")}
new_syms = [s for s, ft in first_bar.items() if ft >= t2024]
old_syms = [s for s, ft in first_bar.items() if ft < t2023]
print(f"монет всего {len(first_bar)} · НОВЫХ (первый бар >=2024-01) {len(new_syms)} · "
      f"СТАРЫХ (<2023-01) {len(old_syms)}")


def run(syms, label):
    sig = []   # (ts_ms, side, net)
    for s in syms:
        d = pd.read_sql("SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? "
                        "AND timeframe='4h' AND time>=? ORDER BY time", con, params=(s, t2024))
        if len(d) < 400:
            continue
        w = wt(d); tr = atrt(d)
        H, L, C, T = d.high.values, d.low.values, d.close.values, d.time.values
        last = {"LONG": -10**9, "SHORT": -10**9}
        for i in range(210, len(d) - 1):
            for side in ("LONG", "SHORT"):
                if i - last[side] < COOL:
                    continue
                if side == "LONG":
                    if not (tr[i] > 0 and w[i] < -60 and w[i] > w[i-1]):
                        continue
                    sl = L[max(0, i-3):i+1].min() * 0.997
                    if sl >= C[i]:
                        continue
                    sp = (C[i] - sl) / C[i] * 100
                else:
                    if not (tr[i] < 0 and w[i] > 60 and w[i] < w[i-1]):
                        continue
                    sl = H[max(0, i-3):i+1].max() * 1.003
                    if sl <= C[i]:
                        continue
                    sp = (sl - C[i]) / C[i] * 100
                if not (4.0 < sp <= 12.0):
                    continue
                last[side] = i
                sig.append((int(T[i]), side, ex(i, H, L, C, sl, side) - COST))
    print(f"\n{label} (4h, кулдаун 6ч, косты 0.35%): сигналов {len(sig)}")
    for side in ("LONG", "SHORT"):
        v = [x[2] for x in sig if x[1] == side]
        if len(v) >= 20:
            a = np.array(v)
            pf = (a[a > 0].sum() / abs(a[a < 0].sum())) if (a < 0).any() else 9.9
            print(f"  {side:5} n={len(v):4} WR{100*(a>0).mean():3.0f}% МЕД{np.median(a):+6.2f}% PF{pf:5.2f}")
        else:
            print(f"  {side:5} n={len(v):4} — мало")
    # разрез по годам (клетка B: переворот в 2026 для ОБЕИХ групп?)
    for y in (2024, 2025, 2026):
        lo = int(dt.datetime(y, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
        hi = int(dt.datetime(y + 1, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
        print(f"  {y}:", end=" ")
        for side in ("LONG", "SHORT"):
            v = [x[2] for x in sig if x[1] == side and lo <= x[0] < hi]
            if len(v) >= 20:
                a = np.array(v)
                pf = (a[a > 0].sum() / abs(a[a < 0].sum())) if (a < 0).any() else 9.9
                print(f"{side} n={len(v):4} МЕД{np.median(a):+6.2f}% PF{pf:5.2f} |", end=" ")
            else:
                print(f"{side} n={len(v):3} мало |", end=" ")
        print()
    return sig


new_sig = run(new_syms, "НОВЫЕ ЛИСТИНГИ (первый бар >=2024-01)")
old_sig = run(old_syms, "СТАРЫЕ (первый бар <2023-01)")
con.close()
