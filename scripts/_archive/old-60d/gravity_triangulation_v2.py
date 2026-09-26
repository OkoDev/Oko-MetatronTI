"""
DS-GRAVITY-TRI v2: оптимизированная версия.
- Ищет символ во всех форматах (GRT/USDT, binance:GRT/USDT, bingx:GRT/USDT:USDT)
- Загружает только нужные бары (LIMIT)
"""
import sqlite3, sys, time, statistics as st
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.smc.ote_matrix import structure_trend, build_ote

COST_PCT = 0.2
RISK_CAP = 6.0
DB = str(Path(__file__).resolve().parent.parent / "ohlcv_cache.db")

SYMBOLS = ["XLM", "GRT", "SOL", "ADA", "DOGE", "LINK", "AVAX", "DOT", "TRX", "LTC",
           "ARB", "OP", "SUI", "APT", "NEAR", "INJ", "FIL", "ATOM", "RUNE", "SEI",
           "BNB", "ETH", "XRP", "UNI", "AAVE", "ETC", "BCH", "ICP", "TIA", "WLD"]

def find_symbol(cur, base):
    """Ищет символ во всех форматах."""
    patterns = [f"{base}/USDT", f"binance:{base}/USDT", f"bingx:{base}/USDT:USDT"]
    for pat in patterns:
        r = cur.execute("SELECT 1 FROM ohlcv_cache WHERE symbol=? LIMIT 1", (pat,)).fetchone()
        if r:
            return pat
    return None

def load_tf(cur, sym, tf, limit=3000):
    """Загружает данные одного timeframe для символа с LIMIT."""
    cur.execute(
        "SELECT time, open, high, low, close FROM ohlcv_cache "
        "WHERE symbol=? AND timeframe=? ORDER BY time DESC LIMIT ?",
        (sym, tf, limit)
    )
    rows = cur.fetchall()[::-1]  # обратно в хронологический порядок
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close"])
    df["time"] = pd.to_datetime(df["ts"], unit="ms")
    return df.set_index("time")

def run(base, d1h_raw, d15_raw):
    """Симулирует SHORT-рецепт на данных."""
    if d1h_raw is None or d15_raw is None or len(d15_raw) < 400 or len(d1h_raw) < 200:
        return []

    trades = []
    pos = None
    last1_len = -1
    cache = None
    d15 = d15_raw
    d1h = d1h_raw

    for i in range(200, len(d15)):
        t = d15.index[i]
        price = float(d15.iloc[i]["close"])
        hi = float(d15.iloc[i]["high"])
        lo = float(d15.iloc[i]["low"])

        if pos:
            dr = pos["dir"]; ex = None
            if dr == "long":
                if lo <= pos["sl"]: ex = pos["sl"]
                elif hi >= pos["tp"]: ex = pos["tp"]
            else:
                if hi >= pos["sl"]: ex = pos["sl"]
                elif lo <= pos["tp"]: ex = pos["tp"]
            if ex:
                sign = 1 if dr == "long" else -1
                net = (ex - pos["entry"]) / pos["entry"] * 100 * sign - COST_PCT
                trades.append({"net": net, "win": net > 0, "ts": t})
                pos = None

        d1 = d1h[d1h.index <= t]
        if len(d1) < 120: continue
        if len(d1) != last1_len:
            try:
                st1 = structure_trend(d1, lookback=250)
                last1_len = len(d1)
                if st1["trend"] and st1.get("break_level") and st1.get("extreme"):
                    ob = build_ote(st1["extreme"], st1["break_level"])
                    cache = {"bias": st1["trend"], "lo": ob["ote"][0], "hi": ob["ote"][1], "lv": ob["levels"]}
                else: cache = None
            except Exception:
                cache = None; continue
        if not cache: continue
        bias, lo_z, hi_z, lv = cache["bias"], cache["lo"], cache["hi"], cache["lv"]
        if not (lo_z <= price <= hi_z): continue
        if lo_z <= float(d15.iloc[i-1]["close"]) <= hi_z: continue

        try:
            st15 = structure_trend(d15.iloc[:i+1], lookback=250)
        except Exception: continue
        brk15 = st15.get("break_level")
        if not brk15: continue
        entry = price
        if bias == "long" and brk15 < entry: sl = brk15 * 0.999
        elif bias == "short" and brk15 > entry: sl = brk15 * 1.001
        else: continue
        risk = abs(entry - sl)
        if risk <= 0 or risk/entry*100 > RISK_CAP: continue
        fib = lv.get(-1.0)
        if not fib: continue
        if (bias == "long" and fib <= entry) or (bias == "short" and fib >= entry): continue
        tp = fib
        pos = {"dir": bias, "entry": entry, "sl": sl, "tp": tp, "ts": t}
    return trades


def main():
    print("="*66)
    print("DS-GRAVITY-TRI v2: GRAVITY-триангуляция SHORT-рецепта")
    print(f"БД: {DB}")
    print(f"Символов: {len(SYMBOLS)}")
    print(f"Выход: fib_-1.0")
    print(f"Мера: % net")
    print("="*66)

    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    all_trades = []

    for sym in SYMBOLS:
        t0 = time.time()
        found = find_symbol(cur, sym)
        if not found:
            print(f"  {sym:5} НЕТ в БД")
            continue

        d1h = load_tf(cur, found, "1h", 2000)
        d15 = load_tf(cur, found, "15m", 5000)
        if d1h is None or d15 is None:
            print(f"  {sym:5} нет 1h/15m")
            continue

        trades = run(sym, d1h, d15)
        all_trades.extend(trades)
        dt = time.time() - t0
        print(f"  {sym:5} | {found:<25} | {len(trades):>3} трейдов | {dt:.1f}с", flush=True)

        if len(all_trades) >= 5000:
            print("  ... лимит 5000")
            break

    conn.close()

    print("\n"+"="*66)
    print(f"ИТОГО: {len(all_trades)} трейдов")
    print("="*66)

    if not all_trades:
        print("Нет сделок. Возможно SHORT-рецепт не даёт входов на этих данных.")
        return

    nets = [t["net"] for t in all_trades]
    wr = sum(1 for t in all_trades if t["win"]) / len(all_trades) * 100
    print(f"ALL: n={len(all_trades)} WR={wr:.0f}% mean={st.mean(nets):+.3f}% sum={sum(nets):+.1f}%")

    # OOS split
    sorted_trades = sorted(all_trades, key=lambda x: x["ts"])
    mid = len(sorted_trades) // 2
    for lbl, part in [("IS", sorted_trades[:mid]), ("OOS", sorted_trades[mid:])]:
        ns = [t["net"] for t in part]
        w = sum(1 for t in part if t["win"]) / len(part) * 100
        print(f"  {lbl:5} n={len(part):>5} WR={w:>3.0f}% mean={st.mean(ns):+.3f}% sum={sum(ns):+.1f}%")

    # По символам
    by_sym = {}
    for t in all_trades:
        by_sym.setdefault(t.get("sym", "?"), []).append(t["net"])
    print(f"\n{'Symbol':>5} {'n':>4} {'mean%':>8}")
    for sym, ns in sorted(by_sym.items(), key=lambda x: -len(x[1]))[:10]:
        print(f"  {sym:>5} {len(ns):>4} {st.mean(ns):+7.3f}%")


if __name__ == "__main__":
    main()
