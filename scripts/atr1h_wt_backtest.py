# -*- coding: utf-8 -*-
"""ATR-CHANGE 1h + WT-кросс от OB/OS — бэктест рецепта Егора (13.07).

Егор: «atr_change работает на 15m? давай переключим на 1h и дадим WT кросс от OB/OS».
Полигонный 15m (RR3) мёртв (−1.16%×8K, research_1307_evening_dig) — пересборка.

Рецепт: флип ATR-тренда на 1h (закрытая свеча, atr_period=43 factor=1.25 — боевые) +
гейт: WT-кросс (wt1×wt2) в пределах последних N баров, стартовавший из зоны
(cross-up из OS≤−60 → LONG; cross-down из OB≥+60 → SHORT).
Исполнение честное: вход close сигнальной свечи, SL/TP по КАСАНИЮ (wick), тай-брейк
в одной свече = SL (консервативно), costs 0.11% (2×taker+funding).
Линейки выхода: (A) SL за swing12 + TP на 1R… нет — как atr_s2: цель-структура.
    A: SL swing12, TP = 1.5×риск (RR1.5)
    B: SL swing12, TP = фикс 1.5%
    C: SL swing12, TP = фикс 2.5%
Контроль: те же флипы БЕЗ WT-гейта (вклад гейта).
Данные: ohlcv_cache.db 1h 2022-2026, top-N символов по глубине истории.
"""
import sys
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
import sqlite3
import numpy as np
import pandas as pd

N_SYM = 60
COSTS = 0.11          # % round-trip
WT_LOOKBACK = 3       # кросс не старше N закрытых баров
OB, OS = 60.0, -60.0
SWING = 12

db = sqlite3.connect("ohlcv_cache.db")
syms = [r[0] for r in db.execute(
    "SELECT symbol, COUNT(*) c FROM ohlcv_cache WHERE timeframe='1h' GROUP BY symbol "
    "ORDER BY c DESC LIMIT ?", (N_SYM,)).fetchall()]


def wt_cols(df):
    ap = (df["high"] + df["low"] + df["close"]) / 3
    esa = ap.ewm(span=10, adjust=False).mean()
    d = (ap - esa).abs().ewm(span=10, adjust=False).mean()
    ci = (ap - esa) / (0.015 * d.replace(0, np.nan))
    wt1 = ci.ewm(span=21, adjust=False).mean()
    wt2 = wt1.rolling(4).mean()
    return wt1, wt2


def atr_trend(df, period=43, factor=1.25):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - np.roll(c, 1)[1:]), abs(l[1:] - np.roll(c, 1)[1:])))
    atr = pd.Series(tr).ewm(alpha=1 / period, adjust=False).mean().values  # RMA
    atr = np.concatenate([[np.nan], atr])
    hl2 = (h + l) / 2
    up = hl2 - factor * atr
    dn = hl2 + factor * atr
    trend = np.ones(len(df))
    for i in range(1, len(df)):
        if np.isnan(atr[i]):
            continue
        up[i] = max(up[i], up[i - 1]) if c[i - 1] > up[i - 1] else up[i]
        dn[i] = min(dn[i], dn[i - 1]) if c[i - 1] < dn[i - 1] else dn[i]
        if trend[i - 1] == 1:
            trend[i] = -1 if c[i] < up[i - 1] else 1
        else:
            trend[i] = 1 if c[i] > dn[i - 1] else -1
    return trend


def run(sym, use_wt_gate=True, tp_mode="rr15"):
    df = pd.read_sql("SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe='1h' ORDER BY time",
                     db, params=(sym,))
    if len(df) < 500:
        return []
    trend = atr_trend(df)
    wt1, wt2 = wt_cols(df)
    wt1v, wt2v = wt1.values, wt2.values
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    out = []
    i = 100
    while i < len(df) - 2:
        side = None
        if trend[i] == 1 and trend[i - 1] == -1:
            side = "LONG"
        elif trend[i] == -1 and trend[i - 1] == 1:
            side = "SHORT"
        if side is None:
            i += 1
            continue
        if use_wt_gate:
            ok = False
            for j in range(max(1, i - WT_LOOKBACK + 1), i + 1):
                if side == "LONG" and wt1v[j] > wt2v[j] and wt1v[j - 1] <= wt2v[j - 1] and wt2v[j - 1] <= OS:
                    ok = True
                if side == "SHORT" and wt1v[j] < wt2v[j] and wt1v[j - 1] >= wt2v[j - 1] and wt2v[j - 1] >= OB:
                    ok = True
            if not ok:
                i += 1
                continue
        entry = c[i]
        if side == "LONG":
            sl = l[max(0, i - SWING):i + 1].min() * 0.998
        else:
            sl = h[max(0, i - SWING):i + 1].max() * 1.002
        risk = abs(entry - sl) / entry
        if risk <= 0.001 or risk > 0.10:
            i += 1
            continue
        if tp_mode == "rr15":
            tp = entry + 1.5 * (entry - sl) if side == "LONG" else entry - 1.5 * (sl - entry)
        elif tp_mode == "fix15":
            tp = entry * (1.015 if side == "LONG" else 0.985)
        else:
            tp = entry * (1.025 if side == "LONG" else 0.975)
        net = None
        for k in range(i + 1, min(i + 400, len(df))):
            if side == "LONG":
                hit_sl, hit_tp = l[k] <= sl, h[k] >= tp
            else:
                hit_sl, hit_tp = h[k] >= sl, l[k] <= tp
            if hit_sl:                       # тай-брейк консервативно = SL
                net = (sl / entry - 1) * 100 * (1 if side == "LONG" else -1) - COSTS
                i = k
                break
            if hit_tp:
                net = (tp / entry - 1) * 100 * (1 if side == "LONG" else -1) - COSTS
                i = k
                break
        if net is None:                      # не закрылась за 400 баров — по close
            k = min(i + 400, len(df) - 1)
            net = (c[k] / entry - 1) * 100 * (1 if side == "LONG" else -1) - COSTS
            i = k
        yr = pd.to_datetime(df["time"].iloc[i], unit="ms" if df["time"].iloc[0] > 1e11 else "s").year
        out.append((net, side, yr))
        i += 1
    return out


def report(tag, res):
    if not res:
        print(f"{tag}: пусто")
        return
    nets = [x[0] for x in res]
    wr = 100 * sum(1 for x in nets if x > 0) / len(nets)
    print(f"{tag:34} n={len(nets):6} net={sum(nets)/len(nets):+.3f}%/сд WR={wr:.0f}% "
          f"сумм={sum(nets):+.0f}%")
    for side in ("LONG", "SHORT"):
        v = [x[0] for x in res if x[1] == side]
        if v:
            print(f"    {side:5} n={len(v):5} net={sum(v)/len(v):+.3f}% WR={100*sum(1 for x in v if x>0)/len(v):.0f}%")
    by_yr = {}
    for n, _, y in res:
        by_yr.setdefault(y, []).append(n)
    print("    годы: " + " · ".join(f"{y}:{sum(v)/len(v):+.2f}%(n={len(v)})" for y, v in sorted(by_yr.items())))


for tp_mode in ("rr15", "fix15", "fix25"):
    all_g, all_b = [], []
    for s in syms:
        all_g += run(s, True, tp_mode)
        all_b += run(s, False, tp_mode)
    print(f"\n═══ TP={tp_mode} ═══")
    report(f"1h флип + WT-кросс из OB/OS", all_g)
    report(f"1h флип БЕЗ гейта (контроль)", all_b)
