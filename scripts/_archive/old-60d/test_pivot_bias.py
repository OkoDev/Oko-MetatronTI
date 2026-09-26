"""PIVOT BIAS (Егор 03.07): сторона недельного PP = bias, WT-экстремум = вход, пивоты = цели.

  close > WPP → ЛОНГ от перепроданности (WT-кросс вверх из OS на 1h) → цели R1/R2/R3
  close < WPP → ШОРТ от перекупленности (WT-кросс вниз из OB)       → цели S1/S2/S3
ЧЕСТНОСТЬ: все компоненты каузальны — WPP статичен всю неделю (пивоты прошлой недели), WT-кросс по
CLOSE входного 1h-бара (сигнальный=торговый, intrabar-имитация не нужна), цели статичны, SL за
swing-структуру 1h. % net, costs 0.2. 2022-2026, 37 симв. Свип целей R1/R2/R3 + WT-порог 40/53.
Запуск: python scripts/test_pivot_bias.py
"""
from __future__ import annotations
import sys, sqlite3
import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from core.calculators.combinator_core import wavetrend

COST_PCT = 0.2
DB = "ohlcv_cache.db"
THS = [40.0, 53.0]
TARGETS = ["P1", "P2", "P3"]          # R1/R2/R3 для лонга, S1/S2/S3 для шорта
SYMBOLS = ["XLM", "SOL", "ADA", "DOGE", "LINK", "AVAX", "DOT", "TRX", "LTC",
           "ARB", "OP", "APT", "NEAR", "INJ", "FIL", "ATOM", "RUNE", "SEI", "SUI",
           "BNB", "ETH", "XRP", "UNI", "AAVE", "ETC", "BCH", "ICP", "TIA",
           "GRT", "ALGO", "EGLD", "SAND", "MANA", "CHZ", "ENJ", "KAVA", "ZIL", "IOTA"]


def load1h(conn, sym):
    q = """SELECT time, open, high, low, close, volume FROM ohlcv_cache
           WHERE symbol=? AND timeframe='1h' ORDER BY time"""
    df = pd.read_sql(q, conn, params=(f"{sym}/USDT",))
    if len(df) < 1500:
        return None
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    return df.set_index("time")


def weekly_pivots(d1h):
    wk = d1h.resample("W").agg({"high": "max", "low": "min", "close": "last"}).dropna()
    pp = (wk["high"] + wk["low"] + wk["close"]) / 3
    rng = wk["high"] - wk["low"]
    return pd.DataFrame({
        "PP": pp,
        "R1": 2 * pp - wk["low"], "S1": 2 * pp - wk["high"],
        "R2": pp + rng, "S2": pp - rng,
        "R3": wk["high"] + 2 * (pp - wk["low"]), "S3": wk["low"] - 2 * (wk["high"] - pp),
    }).shift(1)


def wt_crosses_1h(d1h, th):
    wt1 = wavetrend(d1h); wt2 = wt1.rolling(4).mean()
    w1 = wt1.values; w2 = wt2.values
    b = set(); s = set()
    for i in range(1, len(d1h)):
        if np.isnan(w1[i]) or np.isnan(w2[i]) or np.isnan(w1[i - 1]) or np.isnan(w2[i - 1]):
            continue
        if w1[i - 1] <= w2[i - 1] and w1[i] > w2[i] and w1[i] < -th:
            b.add(i)
        elif w1[i - 1] >= w2[i - 1] and w1[i] < w2[i] and w1[i] > th:
            s.add(i)
    return b, s


def run(d1h, th):
    b1h, s1h = wt_crosses_1h(d1h, th)
    piv = weekly_pivots(d1h); piv_idx = piv.index
    res = {tgt: [] for tgt in TARGETS}
    pos = {tgt: None for tgt in TARGETS}
    highs = d1h["high"].values; lows = d1h["low"].values; closes = d1h["close"].values
    idx = d1h.index
    for i in range(200, len(d1h)):
        t = idx[i]; c = float(closes[i]); hi = float(highs[i]); lo = float(lows[i])
        for tgt in TARGETS:
            p = pos[tgt]
            if not p:
                continue
            ex = None
            if p["dir"] == "long":
                if lo <= p["sl"]: ex = p["sl"]                     # SL first (консервативно)
                elif hi >= p["tp"]: ex = p["tp"]
            else:
                if hi >= p["sl"]: ex = p["sl"]
                elif lo <= p["tp"]: ex = p["tp"]
            if ex is not None:
                sign = 1 if p["dir"] == "long" else -1
                gross = (ex - p["entry"]) / p["entry"] * 100 * sign
                res[tgt].append({"net": gross - COST_PCT, "ts": p["ts"], "dir": p["dir"]})
                pos[tgt] = None
        pi = piv_idx.searchsorted(t)
        if pi >= len(piv_idx):
            pi = len(piv_idx) - 1
        row = piv.iloc[pi] if pi < len(piv) else None
        if row is None or pd.isna(row["PP"]):
            continue
        PP = float(row["PP"])
        if i in b1h and c > PP:
            d = "long"; tps = [float(row["R1"]), float(row["R2"]), float(row["R3"])]
        elif i in s1h and c < PP:
            d = "short"; tps = [float(row["S1"]), float(row["S2"]), float(row["S3"])]
        else:
            continue
        entry = c
        if d == "long":
            sl = float(lows[max(0, i - 12):i + 1].min()) * 0.9985
            if sl >= entry:
                continue
        else:
            sl = float(highs[max(0, i - 12):i + 1].max()) * 1.0015
            if sl <= entry:
                continue
        risk = abs(entry - sl)
        if risk <= 0 or risk / entry * 100 > 6:
            continue
        for tgt, tp in zip(TARGETS, tps):
            if pos[tgt] is not None:
                continue
            if (d == "long" and tp <= entry) or (d == "short" and tp >= entry):
                continue                              # цель уже пройдена — невалидна
            pos[tgt] = {"dir": d, "entry": entry, "sl": sl, "tp": tp, "ts": t}
    return res


def main():
    import statistics as s
    conn = sqlite3.connect(DB)
    for th in THS:
        agg = {tgt: [] for tgt in TARGETS}
        done = 0
        for sym in SYMBOLS:
            d1h = load1h(conn, sym)
            if d1h is None:
                continue
            r = run(d1h, th)
            for tgt in agg:
                agg[tgt].extend(r[tgt])
            done += 1
        print(f"\n===== th=±{th} ({done} симв, 2022-2026, вход 1h WT-кросс, bias=WPP) =====")
        print(f"{'цель':6} {'n':>5} {'WR':>4} {'mean%':>8} {'med%':>8} {'sum%':>9}  LONG/SHORT")
        for tgt in TARGETS:
            tr = agg[tgt]
            if not tr:
                print(f"{tgt:6} n=0"); continue
            nets = [x["net"] for x in tr]
            wr = 100 * sum(1 for x in tr if x["net"] > 0) / len(tr)
            lg = [x["net"] for x in tr if x["dir"] == "long"]; sh = [x["net"] for x in tr if x["dir"] == "short"]
            ls = ""
            if lg: ls += f"L:{s.mean(lg):+.2f}(n{len(lg)}) "
            if sh: ls += f"S:{s.mean(sh):+.2f}(n{len(sh)})"
            print(f"{tgt:6} {len(tr):>5} {wr:>3.0f}% {s.mean(nets):>+7.3f} {s.median(nets):>+7.3f} {sum(nets):>+8.1f}  {ls}")
        # по годам для P2
        tr = agg["P2"]
        if tr:
            print("ГОДЫ (P2):", end=" ")
            for yr in [2022, 2023, 2024, 2025, 2026]:
                part = [x["net"] for x in tr if x["ts"].year == yr]
                if len(part) >= 10:
                    print(f"{yr}:{s.mean(part):+.2f}%(n{len(part)})", end="  ")
            print()
    conn.close()
    print(f"\ncosts={COST_PCT}% · SL=swing12 1h (SL-first) · walk-forward честный (все компоненты каузальны)")


if __name__ == "__main__":
    main()
