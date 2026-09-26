"""WAVE-TREND-LONG (03.07): wave_smc TREND-режим (BOS ПО тренду) в % net на Binance-кэше 2022-26.

Класс ПРОДОЛЖЕНИЕ = единственный выживший (atr_S2). LONG-кандидат: импульс вверх активен (откат<38%)
+ BOS bull свежий → LONG по импульсу, SL за zigzag-low. Reuse setup_at-логики scripts/wave_smc_backtest.py
(июнь, была +0.445R TREND) — теперь % net, costs 0.2, SL-first, funding-разрез, годы.
Запуск: python scripts/test_wave_trend_long.py
"""
from __future__ import annotations
import sys, sqlite3, bisect
import pandas as pd

sys.path.insert(0, ".")
from core.smc.smc_engine import zigzag_atr, detect_elliott_impulse, detect_structure_breaks, _zz_typed

COST_PCT = 0.2
DB = "ohlcv_cache.db"
TF = "4h"
RRS = [2.0, 3.0]
HORIZON = 60
STEP = 2
SYMBOLS = ["XLM", "SOL", "ADA", "DOGE", "LINK", "AVAX", "DOT", "TRX", "LTC",
           "ARB", "OP", "APT", "NEAR", "INJ", "FIL", "ATOM", "RUNE", "SEI", "SUI",
           "BNB", "ETH", "XRP", "UNI", "AAVE", "ETC", "BCH", "ICP", "TIA",
           "GRT", "ALGO", "EGLD", "SAND", "MANA", "CHZ", "ENJ", "KAVA", "ZIL", "IOTA"]


def load(conn, sym):
    q = """SELECT time, open, high, low, close, volume FROM ohlcv_cache
           WHERE symbol=? AND timeframe=? ORDER BY time"""
    df = pd.read_sql(q, conn, params=(f"{sym}/USDT", TF))
    if len(df) < 600:
        return None
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    return df.set_index("time")


def load_funding(conn, sym):
    rows = conn.execute("SELECT time, rate FROM funding_rates WHERE symbol=? ORDER BY time",
                        (f"{sym}/USDT",)).fetchall()
    return [r[0] for r in rows], [r[1] for r in rows]


def setup_at(dfh):
    """TREND-сетап на прошлом (reuse wave_smc_backtest): импульс + откат<38% + свежий BOS по тренду."""
    price = float(dfh["close"].iloc[-1])
    li = None
    for dev in (3.0, 5.0):
        try:
            for imp in detect_elliott_impulse(zigzag_atr(dfh, 11, dev)):
                if li is None or imp["waves"][-1][0] > li["waves"][-1][0]:
                    li = imp
        except Exception:
            continue
    if not li:
        return None
    d = li["direction"]; w5 = li["waves"][-1][1]; w0 = li["waves"][0][1]
    if d == "down" and w0 != w5:
        b = (price - w5) / (w0 - w5) * 100
    elif w5 != w0:
        b = (w5 - price) / (w5 - w0) * 100
    else:
        b = 0
    if b >= 38:
        return None                                   # только ТРЕНД-режим
    try:
        typed = _zz_typed(zigzag_atr(dfh, 11, 3.0))
        brks = detect_structure_breaks(dfh, length=5)
    except Exception:
        return None
    lows = [p for _, p, t in typed if t == "L"]; highs = [p for _, p, t in typed if t == "H"]
    bos = [x for x in brks if x.kind == "BOS"]
    n = len(dfh)
    lb = [x for x in bos if (x.direction == "bear") == (d == "down")]
    if lb and (n - 1 - lb[-1].idx) <= 30:
        if d == "up" and lows:
            return ("LONG", float(lows[-1]))
        if d == "down" and highs:
            return ("SHORT", float(highs[-1]))
    return None


def main():
    import statistics as s
    conn = sqlite3.connect(DB)
    res = {(side, rr): [] for side in ("LONG", "SHORT") for rr in RRS}
    done = 0
    for sym in SYMBOLS:
        df = load(conn, sym)
        if df is None:
            continue
        ft, fr = load_funding(conn, sym)
        ts_ms = (df.index.astype("int64") // 10**6).values
        highs = df["high"].values; lows = df["low"].values; closes = df["close"].values
        i = 250
        while i < len(df) - HORIZON - 1:
            # ОКНО 400 баров вместо полного среза: O(n²)→O(n) (урок bug_last_confirmed_pivot_quadratic)
            st = setup_at(df.iloc[max(0, i - 400):i + 1])
            if st is None:
                i += STEP; continue
            side, sl = st
            entry = float(closes[i])
            risk = abs(entry - sl)
            if risk <= 0 or risk / entry > 0.10 or \
               (side == "LONG" and sl >= entry) or (side == "SHORT" and sl <= entry):
                i += STEP; continue
            j = bisect.bisect_right(ft, int(ts_ms[i])) - 1
            fund = fr[j] if j >= 0 else None
            for rr in RRS:
                tp = entry + rr * risk if side == "LONG" else entry - rr * risk
                out = None
                for k in range(i + 1, min(i + HORIZON, len(df))):
                    hi = float(highs[k]); lo = float(lows[k])
                    if side == "LONG":
                        if lo <= sl:                    # SL-first
                            out = sl; break
                        if hi >= tp:
                            out = tp; break
                    else:
                        if hi >= sl:
                            out = sl; break
                        if lo <= tp:
                            out = tp; break
                if out is None:
                    out = float(closes[min(i + HORIZON - 1, len(df) - 1)])
                sign = 1 if side == "LONG" else -1
                gross = (out - entry) / entry * 100 * sign
                res[(side, rr)].append({"net": gross - COST_PCT, "ts": df.index[i], "fund": fund})
            i += 6                                      # после сделки шаг больше (не дублировать вход)
        done += 1
        print(f"  {sym} ok")
    print("=" * 68)
    print(f"({done} симв, {TF}, 2022-2026, ТРЕНД-режим wave_smc, % net, costs {COST_PCT})")
    for side in ("LONG", "SHORT"):
        for rr in RRS:
            tr = res[(side, rr)]
            if not tr:
                continue
            nets = [x["net"] for x in tr]
            wr = 100 * sum(1 for x in nets if x > 0) / len(nets)
            print(f"{side} RR{rr}: n={len(tr):5} WR={wr:3.0f}% mean={s.mean(nets):+.3f}% "
                  f"med={s.median(nets):+.3f}% sum={sum(nets):+.0f}%")
    # годы + funding-разрез для LONG RR2
    tr = res[("LONG", 2.0)]
    if tr:
        print("\nLONG RR2 по годам:")
        for yr in [2022, 2023, 2024, 2025, 2026]:
            part = [x["net"] for x in tr if x["ts"].year == yr]
            if len(part) >= 15:
                print(f"  {yr}: n={len(part):4} mean={s.mean(part):+.3f}%")
        print("LONG RR2 × funding (симметрия: шорты платят = топливо вверх?):")
        for name, cond in [("fund<0", lambda f: f is not None and f < 0),
                           ("0..0.01%", lambda f: f is not None and 0 <= f < 0.0001),
                           ("fund>=0.01%", lambda f: f is not None and f >= 0.0001)]:
            part = [x["net"] for x in tr if cond(x["fund"])]
            if len(part) >= 15:
                print(f"  {name:12} n={len(part):4} mean={s.mean(part):+.3f}%")
    conn.close()


if __name__ == "__main__":
    main()
