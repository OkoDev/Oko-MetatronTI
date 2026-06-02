# -*- coding: utf-8 -*-
"""ARCH-127 — бэктест зональной MTF-reversion на истории.

Гипотеза (философия пользователя): ядро = LONG из OS-экстремума / SHORT из OB,
на младшем ТФ С СОГЛАСОВАНИЕМ старшего. RANGE/середину НЕ торгуем.

Тест: вход на WT-кроссе wt1×wt2 в зоне (15m) — сравнить ТРИ варианта:
  (B) baseline   — все кроссы в зоне (без MTF-фильтра)
  (M) MTF-aligned — кросс в зоне + старший 1h согласован (LONG: 1h wt1<0; SHORT: >0)
  (X) MTF-counter — кросс в зоне ПРОТИВ старшего (контроль: должно быть хуже)
Если M >> B и M >> X → MTF-согласование зон даёт альфу → концепция ARCH-127 жива.

Симуляция: вход на close сигнала, SL=1.5×ATR, TP=3×ATR (RR=2), time-exit 48 баров (12ч).
Запуск: python scripts/mtf_reversion_backtest.py [--pairs N] [--os -53] [--ob 53]
"""
import argparse
import glob
import os
import sys
from collections import defaultdict

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
import pandas as pd
from core.indicators.indicators import calculate_wt, compute_atr_values

H = "data/history"


def load(tf, sym, n=4000):
    f = os.path.join(H, tf, f"{sym}.parquet")
    if not os.path.exists(f):
        return None
    df = pd.read_parquet(f)
    df.columns = [c.lower() for c in df.columns]
    if "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True, errors="coerce")
        df = df.set_index("ts")
    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    return df[keep].dropna().tail(n)


def simulate(df15, i, direction, atr, rr=2.0, sl_mult=1.5, horizon=48):
    """Forward-симуляция от бара i. R: +rr если TP, -1 если SL, иначе по close."""
    entry = df15["close"].iloc[i]
    if not atr or atr <= 0:
        return None
    sl_dist = sl_mult * atr
    if direction == "LONG":
        sl, tp = entry - sl_dist, entry + rr * sl_dist
    else:
        sl, tp = entry + sl_dist, entry - rr * sl_dist
    for j in range(i + 1, min(i + 1 + horizon, len(df15))):
        hi, lo = df15["high"].iloc[j], df15["low"].iloc[j]
        if direction == "LONG":
            if lo <= sl:
                return -1.0
            if hi >= tp:
                return rr
        else:
            if hi >= sl:
                return -1.0
            if lo <= tp:
                return rr
    # time-exit
    last = df15["close"].iloc[min(i + horizon, len(df15) - 1)]
    return ((last - entry) if direction == "LONG" else (entry - last)) / sl_dist


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=int, default=50)
    ap.add_argument("--os", type=float, default=-53.0)
    ap.add_argument("--ob", type=float, default=53.0)
    args = ap.parse_args()

    syms = [os.path.basename(f)[:-8] for f in glob.glob(H + "/15m/*.parquet")][: args.pairs]
    # buckets: (variant, direction) → list R
    res = defaultdict(list)

    for sym in syms:
        d15, d1 = load("15m", sym), load("1h", sym)
        if d15 is None or d1 is None or len(d15) < 200 or len(d1) < 100:
            continue
        d15 = calculate_wt(d15.copy())
        d1 = calculate_wt(d1.copy())
        # ATR на 15m
        atrs = compute_atr_values(d15["high"].tolist(), d15["low"].tolist(), d15["close"].tolist(), 14)
        d15 = d15.iloc[-len(atrs):].copy() if atrs and len(atrs) < len(d15) else d15
        # 1h wt1 как старший контекст, выровнять на 15m по времени (asof)
        h1 = d1[["wt1"]].rename(columns={"wt1": "wt1_1h"})
        d15 = pd.merge_asof(d15.sort_index(), h1.sort_index(), left_index=True, right_index=True, direction="backward")

        w1 = d15["wt1"].values
        w2 = d15["wt2"].values
        h = d15["wt1_1h"].values
        for i in range(2, len(d15) - 1):
            if pd.isna(h[i]):
                continue
            atr = atrs[i] if i < len(atrs) else (atrs[-1] if atrs else None)
            # LONG: кросс wt1 над wt2 в OS
            long_cross = w1[i - 1] <= w2[i - 1] and w1[i] > w2[i] and w1[i] < args.os
            short_cross = w1[i - 1] >= w2[i - 1] and w1[i] < w2[i] and w1[i] > args.ob
            if long_cross:
                r = simulate(d15, i, "LONG", atr)
                if r is None:
                    continue
                res[("B", "LONG")].append(r)
                if h[i] < 0:
                    res[("M", "LONG")].append(r)     # старший согласован (нижняя зона)
                else:
                    res[("X", "LONG")].append(r)     # старший против (перекуплен)
            elif short_cross:
                r = simulate(d15, i, "SHORT", atr)
                if r is None:
                    continue
                res[("B", "SHORT")].append(r)
                if h[i] > 0:
                    res[("M", "SHORT")].append(r)
                else:
                    res[("X", "SHORT")].append(r)

    def stat(xs):
        if not xs:
            return "n=0"
        wr = sum(1 for x in xs if x > 0) / len(xs) * 100
        return f"n={len(xs):4} avgR={sum(xs)/len(xs):+.3f} WR={wr:.0f}%"

    print(f"Пар: {len(syms)} | OS<{args.os} OB>{args.ob} | вход WT-кросс в зоне, SL=1.5ATR TP=3ATR RR=2\n")
    names = {"B": "baseline (без MTF)", "M": "MTF-aligned (старший согласован)", "X": "MTF-counter (против старшего)"}
    for d in ("LONG", "SHORT"):
        print(f"=== {d} ===")
        for v in ("B", "M", "X"):
            print(f"  {names[v]:<38} {stat(res[(v, d)])}")
        # вклад MTF: M vs B
        m, b = res[("M", d)], res[("B", d)]
        if m and b:
            dm = sum(m)/len(m) - sum(b)/len(b)
            print(f"  → вклад MTF-согласования (M−B): {dm:+.3f}R\n")


if __name__ == "__main__":
    main()
