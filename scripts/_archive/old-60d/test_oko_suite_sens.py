"""Чувствительность S2 (OKO Suite: WT-кросс 15m + ATRTrend 1h): TP-свип × WT-порог + эпохи + символы.

Цель: убедиться что +0.94 не параметр-лак. Свип: TP∈{1,1.5,2,3}R × th∈{53,60}. Разбивки: эпохи
(2024H1 / 2024Q4-бык / 2025H1 / 2025H2 / 2026) + per-symbol (сколько символов в плюсе).
Запуск: python scripts/test_oko_suite_sens.py
"""
from __future__ import annotations
import sys, sqlite3
import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from core.smc.ote_matrix import structure_trend
from core.calculators.combinator_core import wavetrend, atr_supertrend

COST_PCT = 0.2
DB = "ohlcv_cache.db"
START, END = "2024-01-15", "2026-05-31"
THS = [53.0, 60.0]
TPS = [1.0, 1.5, 2.0, 3.0]
SYMBOLS = ["XLM", "SOL", "ADA", "DOGE", "LINK", "AVAX", "DOT", "TRX", "LTC",
           "ARB", "OP", "APT", "NEAR", "INJ", "FIL", "ATOM", "RUNE",
           "BNB", "ETH", "XRP", "UNI", "AAVE", "ETC", "BCH", "ICP"]
EPOCHS = [("2024H1", "2024-01-15", "2024-06-30"), ("2024H2_bull", "2024-07-01", "2024-12-31"),
          ("2025H1", "2025-01-01", "2025-06-30"), ("2025H2", "2025-07-01", "2025-12-31"),
          ("2026", "2026-01-01", "2026-05-31")]


def load(conn, sym, tf, warm_days=40):
    q = """SELECT time, open, high, low, close, volume FROM ohlcv_cache
           WHERE symbol=? AND timeframe=? AND time BETWEEN ? AND ? ORDER BY time"""
    t0 = int(pd.Timestamp(START).timestamp() * 1000) - 86400000 * warm_days
    t1 = int(pd.Timestamp(END).timestamp() * 1000)
    df = pd.read_sql(q, conn, params=(f"{sym}/USDT", tf, t0, t1))
    if len(df) < 500:
        return None
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    return df.set_index("time")


def wt_crosses(df, th):
    wt1 = wavetrend(df); wt2 = wt1.rolling(4).mean()
    b = set(); s = set()
    w1 = wt1.values; w2 = wt2.values
    for i in range(1, len(df)):
        if np.isnan(w1[i]) or np.isnan(w2[i]) or np.isnan(w1[i - 1]) or np.isnan(w2[i - 1]):
            continue
        if w1[i - 1] <= w2[i - 1] and w1[i] > w2[i] and w1[i] < -th:
            b.add(i)
        elif w1[i - 1] >= w2[i - 1] and w1[i] < w2[i] and w1[i] > th:
            s.add(i)
    return b, s


def run(sym, d1h, d15, th, tps):
    b15, s15 = wt_crosses(d15, th)
    st1h = atr_supertrend(d1h)
    keys = [(tp,) for tp in tps]
    res = {k: [] for k in keys}; pos = {k: None for k in keys}
    start = pd.Timestamp(START)
    l1 = -1; cur1 = 0.0
    for i in range(200, len(d15)):
        t = d15.index[i]; bar = d15.iloc[i]
        price = float(bar["close"]); hi = float(bar["high"]); lo = float(bar["low"])
        for k in keys:
            p = pos[k]
            if not p:
                continue
            dr = p["dir"]; ex_px = None
            if dr == "long":
                if lo <= p["sl"]: ex_px = p["sl"]
                elif hi >= p["tp"]: ex_px = p["tp"]
            else:
                if hi >= p["sl"]: ex_px = p["sl"]
                elif lo <= p["tp"]: ex_px = p["tp"]
            if ex_px is not None:
                sign = 1 if dr == "long" else -1
                gross = (ex_px - p["entry"]) / p["entry"] * 100 * sign
                res[k].append({"net": gross - COST_PCT, "win": gross - COST_PCT > 0,
                               "ts": p["ts"], "dir": dr, "sym": sym})
                pos[k] = None
        if t < start:
            continue
        if i in b15:
            d = "long"
        elif i in s15:
            d = "short"
        else:
            continue
        d1sub = d1h[d1h.index <= t]
        if len(d1sub) < 120:
            continue
        if len(d1sub) != l1:
            l1 = len(d1sub); cur1 = float(st1h[l1 - 1]) if l1 - 1 < len(st1h) else 0.0
        if not ((cur1 > 0) if d == "long" else (cur1 < 0)):
            continue
        st15 = structure_trend(d15.iloc[:i + 1], lookback=250)
        bl = st15.get("break_level")
        entry = price
        if d == "long":
            sl = bl * 0.999 if (bl is not None and bl < entry) else float(d15["low"].values[i - 12:i + 1].min()) * 0.9985
            if sl >= entry:
                continue
        else:
            sl = bl * 1.001 if (bl is not None and bl > entry) else float(d15["high"].values[i - 12:i + 1].max()) * 1.0015
            if sl <= entry:
                continue
        risk = abs(entry - sl)
        if risk <= 0 or risk / entry * 100 > 6:
            continue
        for (tp_r,) in keys:
            if pos[(tp_r,)] is None:
                tp = entry + tp_r * risk if d == "long" else entry - tp_r * risk
                pos[(tp_r,)] = {"dir": d, "entry": entry, "sl": sl, "tp": tp, "ts": t}
    return res


def main():
    import statistics as s
    conn = sqlite3.connect(DB)
    for th in THS:
        agg = {(tp,): [] for tp in TPS}
        for sym in SYMBOLS:
            d1h = load(conn, sym, "1h"); d15 = load(conn, sym, "15m")
            if d1h is None or d15 is None:
                continue
            res = run(sym, d1h, d15, th, TPS)
            for k in agg:
                agg[k].extend(res[k])
        print(f"\n===== th=±{th} =====")
        for tp in TPS:
            tr = agg[(tp,)]
            if not tr:
                continue
            nets = [x["net"] for x in tr]
            wr = 100 * sum(1 for x in tr if x["win"]) / len(tr)
            lg = [x["net"] for x in tr if x["dir"] == "long"]; sh = [x["net"] for x in tr if x["dir"] == "short"]
            print(f"TP={tp}R: n={len(tr):4} WR={wr:3.0f}% mean={s.mean(nets):+.3f}% med={s.median(nets):+.3f}% "
                  f"sum={sum(nets):+.0f}%  L:{s.mean(lg):+.2f} S:{s.mean(sh):+.2f}")
        # эпохи и символы для th=53 TP=2R (эталон)
        if th == 53.0:
            tr = agg[(2.0,)]
            print("\nЭПОХИ (th53 2R):")
            for ep, a, b in EPOCHS:
                part = [x for x in tr if pd.Timestamp(a) <= x["ts"] <= pd.Timestamp(b)]
                if len(part) < 5:
                    continue
                nets = [x["net"] for x in part]
                print(f"  {ep:12} n={len(part):4} mean={s.mean(nets):+.3f}% sum={sum(nets):+.0f}%")
            print("СИМВОЛЫ (th53 2R):")
            sym_sum = {}
            for x in tr:
                sym_sum.setdefault(x["sym"], []).append(x["net"])
            pos_n = sum(1 for v in sym_sum.values() if sum(v) > 0)
            worst = sorted(sym_sum.items(), key=lambda kv: sum(kv[1]))[:3]
            best = sorted(sym_sum.items(), key=lambda kv: -sum(kv[1]))[:3]
            print(f"  в плюсе {pos_n}/{len(sym_sum)} · топ: " +
                  ", ".join(f"{k} {sum(v):+.0f}%" for k, v in best) + " · худшие: " +
                  ", ".join(f"{k} {sum(v):+.0f}%" for k, v in worst))
    conn.close()
    print(f"\ncosts={COST_PCT}% · S2 (WT-кросс 15m + ATRTrend 1h) · 2024-2026")


if __name__ == "__main__":
    main()
