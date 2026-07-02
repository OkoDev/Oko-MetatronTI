"""LONG на НАСТОЯЩИХ БЫЧЬИХ периодах (Егор 03.07: «протестировать когда рынок БЫЛ бычий, чтобы
отработать бычий когда развернётся, а не пропускать его ради тестов»). Данные: ohlcv_cache.db
(Binance data.vision, 472 символа, 2022-2026).

Периоды: BULL1 = 2023-11-01..2024-03-31 (BTC 27k→73k) · BULL2 = 2024-10-01..2025-01-31 (54k→108k).
Варианты: LONG base (1h OTE long + 4h==long + возврат + SL 15m-слом + TP fib−1.0) · LONG цель−0.62 ·
LONG reversal (переворот) · SHORT base (контроль: живёт ли шорт в бычьем).
Честный walk-forward. % net, costs 0.2. Запуск: python scripts/test_ote_bull.py
"""
from __future__ import annotations
import sys, sqlite3
import pandas as pd

sys.path.insert(0, ".")
from core.smc.ote_matrix import structure_trend, build_ote

COST_PCT = 0.2
DB = "ohlcv_cache.db"
PERIODS = {"BULL1_2023Q4": ("2023-10-01", "2024-03-31"),
           "BULL2_2024Q4": ("2024-09-01", "2025-01-31")}
SYMBOLS = ["XLM", "SOL", "ADA", "DOGE", "LINK", "AVAX", "DOT", "TRX", "LTC",
           "ARB", "OP", "SUI", "APT", "NEAR", "INJ", "FIL", "ATOM", "RUNE", "SEI",
           "BNB", "ETH", "XRP", "UNI", "AAVE", "ETC", "BCH", "ICP", "TIA"]
VARIANTS = ["L_base", "L_m062", "L_reversal", "S_base"]


def load(conn, sym, tf, start, end):
    q = """SELECT time, open, high, low, close, volume FROM ohlcv_cache
           WHERE symbol=? AND timeframe=? AND time BETWEEN ? AND ? ORDER BY time"""
    t0 = int(pd.Timestamp(start).timestamp() * 1000) - 86400000 * 40   # +40 дней прогрева структуры
    t1 = int(pd.Timestamp(end).timestamp() * 1000)
    df = pd.read_sql(q, conn, params=(f"{sym}/USDT", tf, t0, t1))
    if len(df) < 200:
        return None
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    return df.set_index("time")


def run(d4h, d1h, d15, start_ts):
    res = {v: [] for v in VARIANTS}; pos = {v: None for v in VARIANTS}
    l1 = l4 = -1; c1 = c4 = None
    prev_broken = False
    start = pd.Timestamp(start_ts)
    for i in range(200, len(d15)):
        t = d15.index[i]
        bar = d15.iloc[i]
        price = float(bar["close"]); hi = float(bar["high"]); lo = float(bar["low"])
        for v in VARIANTS:
            p = pos[v]
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
                res[v].append({"net": gross - COST_PCT, "win": gross - COST_PCT > 0, "ts": p["ts"]})
                pos[v] = None
        d1 = d1h[d1h.index <= t]
        if len(d1) < 120:
            continue
        if len(d1) != l1:
            c1 = structure_trend(d1, lookback=250); l1 = len(d1)
        d4 = d4h[d4h.index <= t]
        if len(d4) != l4:
            l4 = len(d4)
            c4 = structure_trend(d4, lookback=250) if len(d4) >= 120 else None
        if not c1 or not c4 or t < start:
            continue
        # --- L_reversal: 1h short + пробой слома вверх ---
        if c1["trend"] == "short" and c1["break_level"] is not None and c1["extreme"] is not None:
            broken_now = price > c1["break_level"]
            if broken_now and not prev_broken and pos["L_reversal"] is None:
                brk = c1["break_level"]; llow = c1["extreme"]; entry = price
                st15 = structure_trend(d15.iloc[:i + 1], lookback=250)
                b15 = st15.get("break_level")
                sl = b15 * 0.999 if (b15 is not None and b15 < entry) else llow * 0.999
                risk = abs(entry - sl); tp = 2 * brk - llow
                if risk > 0 and risk / entry * 100 <= 6 and tp > entry:
                    pos["L_reversal"] = {"dir": "long", "entry": entry, "sl": sl, "tp": tp, "ts": t}
            prev_broken = broken_now
        else:
            prev_broken = False
        # --- зона 1h OTE (в обе стороны, у каждой свои варианты) ---
        if c1["trend"] is None or c1["break_level"] is None or c1["extreme"] is None:
            continue
        bias = c1["trend"]
        if c4["trend"] != bias:
            continue
        ob = build_ote(c1["extreme"], c1["break_level"])
        lo_z, hi_z = ob["ote"]; lv = ob["levels"]
        if not (lo_z <= price <= hi_z):
            continue
        if lo_z <= float(d15.iloc[i - 1]["close"]) <= hi_z:
            continue
        st15 = structure_trend(d15.iloc[:i + 1], lookback=250)
        b15 = st15.get("break_level")
        entry = price
        if b15 is None or not ((bias == "long" and b15 < entry) or (bias == "short" and b15 > entry)):
            continue
        sl = b15 * (0.999 if bias == "long" else 1.001)
        risk = abs(entry - sl)
        if risk <= 0 or risk / entry * 100 > 6:
            continue
        tp1 = lv.get(-1.0); tp062 = lv.get(-0.62)
        def ok(tp):
            return tp is not None and ((bias == "long" and tp > entry) or (bias == "short" and tp < entry))
        if bias == "long":
            if pos["L_base"] is None and ok(tp1):
                pos["L_base"] = {"dir": "long", "entry": entry, "sl": sl, "tp": tp1, "ts": t}
            if pos["L_m062"] is None and ok(tp062):
                pos["L_m062"] = {"dir": "long", "entry": entry, "sl": sl, "tp": tp062, "ts": t}
        else:
            if pos["S_base"] is None and ok(tp1):
                pos["S_base"] = {"dir": "short", "entry": entry, "sl": sl, "tp": tp1, "ts": t}
    return res


def main():
    import statistics as s
    conn = sqlite3.connect(DB)
    for pname, (start, end) in PERIODS.items():
        agg = {v: [] for v in VARIANTS}
        done = 0
        for sym in SYMBOLS:
            d4h = load(conn, sym, "4h", start, end)
            d1h = load(conn, sym, "1h", start, end)
            d15 = load(conn, sym, "15m", start, end)
            if any(x is None for x in (d4h, d1h, d15)):
                continue
            res = run(d4h, d1h, d15, start)
            for v in agg:
                agg[v].extend(res[v])
            done += 1
        print(f"\n===== {pname} ({start}..{end}) — {done} символов =====")
        print(f"{'вариант':12} {'n':>4} {'WR':>5} {'mean%':>8} {'med%':>8} {'sum%':>8}")
        for v in VARIANTS:
            tr = agg[v]
            if not tr:
                print(f"{v:12} n=0"); continue
            nets = [x["net"] for x in tr]; wr = 100 * sum(1 for x in tr if x["win"]) / len(tr)
            print(f"{v:12} {len(tr):>4} {wr:>4.0f}% {s.mean(nets):>+7.3f} {s.median(nets):>+7.3f} {sum(nets):>+7.1f}")
        # OOS внутри периода
        for v in VARIANTS:
            tr = sorted(agg[v], key=lambda x: x["ts"])
            if len(tr) < 12:
                continue
            mid = len(tr) // 2
            a = [x["net"] for x in tr[:mid]]; b = [x["net"] for x in tr[mid:]]
            print(f"  {v:10} сплит: 1я n={len(a)} mean={s.mean(a):+.3f}% / 2я n={len(b)} mean={s.mean(b):+.3f}%")
    conn.close()
    print(f"\ncosts={COST_PCT}% · данные Binance data.vision (ohlcv_cache.db) · walk-forward")


if __name__ == "__main__":
    main()
