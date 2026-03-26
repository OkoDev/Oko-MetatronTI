#!/usr/bin/env python3
"""
Бэктест: ATR trend flip на 1h — просто и всё.
Signal = смена тренда: -1→+1 = LONG, +1→-1 = SHORT
SL = trendup/trenddown на момент входа
TSL = следует за trendup/trenddown
Активация TSL после +1R
"""
import os, sys, asyncio, sqlite3, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
import numpy as np

from core.data_collector import RealTimeData
from core.indicators import calculate_trend

logging.basicConfig(level=logging.WARNING)

SYMBOLS_LIMIT = 50
CANDLES       = 500       # ~20 дней на 1h
TIMEFRAME     = "1h"
ATR_FACTOR    = 1.25
MIN_SL_PCT    = 0.003
MAX_SL_PCT    = 0.08


def find_signals(df: pd.DataFrame) -> list:
    signals = []
    for i in range(1, len(df) - 1):
        t_prev = df["trend"].iloc[i - 1]
        t_cur  = df["trend"].iloc[i]
        if pd.isna(t_prev) or pd.isna(t_cur):
            continue
        # Смена тренда
        if t_prev == t_cur:
            continue

        direction = "LONG" if t_cur == 1.0 else "SHORT"

        if direction == "LONG":
            sl_price = df["trendup"].iloc[i]
        else:
            sl_price = df["trenddown"].iloc[i] if "trenddown" in df.columns else df["trendup"].iloc[i]

        if pd.isna(sl_price) or sl_price <= 0:
            continue

        entry_price = float(df["open"].iloc[i + 1])
        if entry_price <= 0:
            continue

        sl_dist_pct = abs(entry_price - sl_price) / entry_price
        if sl_dist_pct < MIN_SL_PCT or sl_dist_pct > MAX_SL_PCT:
            continue

        signals.append({
            "entry_idx":   i + 1,
            "entry_price": entry_price,
            "sl_price":    float(sl_price),
            "sl_pct":      sl_dist_pct * 100,
            "direction":   direction,
        })
    return signals


def simulate_trade(df: pd.DataFrame, entry_idx: int, entry_price: float,
                   sl_price: float, direction: str) -> dict:
    one_r = abs(entry_price - sl_price)
    if one_r <= 0:
        return {"status": "INVALID", "exit_r": None}

    current_sl    = sl_price
    tsl_activated = False

    for i in range(entry_idx + 1, len(df)):
        low   = float(df["low"].iloc[i])
        high  = float(df["high"].iloc[i])
        close = float(df["close"].iloc[i])

        if direction == "LONG":
            hit = low <= current_sl
            profit_r = (close - entry_price) / one_r
            new_sl_raw = df["trendup"].iloc[i]
            if not pd.isna(new_sl_raw) and float(new_sl_raw) > current_sl:
                new_sl = float(new_sl_raw)
            else:
                new_sl = current_sl
        else:
            hit = high >= current_sl
            profit_r = (entry_price - close) / one_r
            col = "trenddown" if "trenddown" in df.columns else "trendup"
            new_sl_raw = df[col].iloc[i]
            if not pd.isna(new_sl_raw) and float(new_sl_raw) < current_sl:
                new_sl = float(new_sl_raw)
            else:
                new_sl = current_sl

        if hit:
            if direction == "LONG":
                exit_r = (current_sl - entry_price) / one_r
            else:
                exit_r = (entry_price - current_sl) / one_r
            return {"status": "TSL" if tsl_activated else "SL",
                    "exit_r": exit_r, "bars": i - entry_idx}

        if not tsl_activated and profit_r >= 1.0:
            tsl_activated = True

        current_sl = new_sl

    if direction == "LONG":
        final_r = (float(df["close"].iloc[-1]) - entry_price) / one_r
    else:
        final_r = (entry_price - float(df["close"].iloc[-1])) / one_r
    return {"status": "OPEN", "exit_r": final_r, "bars": len(df) - entry_idx}


def calc_metrics(trades: list) -> dict:
    if not trades:
        return None
    rs     = [t["exit_r"] for t in trades]
    wins   = [t for t in trades if t["exit_r"] > 0]
    losses = [t for t in trades if t["exit_r"] <= 0]
    n      = len(trades)
    win_r  = sum(t["exit_r"] for t in wins)   / len(wins)   if wins   else 0
    loss_r = sum(t["exit_r"] for t in losses) / len(losses) if losses else 0
    wrate  = 100 * len(wins) / n
    pf     = win_r * len(wins) / abs(loss_r * len(losses)) if losses and loss_r != 0 else float("inf")
    rs_arr = np.array(rs)
    sharpe = rs_arr.mean() / rs_arr.std() * np.sqrt(n) if rs_arr.std() > 0 else 0
    cum    = np.cumsum(rs_arr)
    max_dd = (cum - np.maximum.accumulate(cum)).min()
    moon   = sum(1 for t in trades if t["exit_r"] >= 5)
    avg_sl = sum(t["sl_pct"] for t in trades) / n
    tsl_n  = sum(1 for t in trades if t["status"] == "TSL")
    sl_n   = sum(1 for t in trades if t["status"] == "SL")
    return {"n": n, "wr": wrate, "avg_r": sum(rs)/n, "win_r": win_r,
            "loss_r": loss_r, "pf": pf, "sharpe": sharpe,
            "max_dd": max_dd, "moon": moon, "avg_sl": avg_sl,
            "tsl_n": tsl_n, "sl_n": sl_n}


async def run_backtest():
    print("=" * 72)
    print(f"  ATR TREND FLIP 1h | simple and that's it | {SYMBOLS_LIMIT} пар")
    print("=" * 72)

    conn = sqlite3.connect("subscriptions.db")
    symbols = [r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM simulated_trades WHERE timeframe='15m' ORDER BY created_at DESC LIMIT ?",
        (SYMBOLS_LIMIT,)
    ).fetchall()]
    conn.close()

    dc = RealTimeData("bingx", api_semaphore_size=15, api_rps=15.0)
    await dc.load_markets()

    print(f"Загрузка {TIMEFRAME} × {len(symbols)} пар × {CANDLES} свечей...")
    datasets = {}
    for sym in symbols:
        try:
            df = await dc.get_ohlcv(sym, timeframe=TIMEFRAME, limit=CANDLES)
            if df is None or len(df) < 50:
                continue
            df = calculate_trend(df, factor=ATR_FACTOR)
            # trenddown = зеркало trendup для SHORT
            if "trenddown" not in df.columns:
                df["trenddown"] = df["trendup"]
            datasets[sym] = df
        except Exception:
            pass

    await dc.stop()
    print(f"Загружено: {len(datasets)} символов\n")

    all_trades = []
    long_trades  = []
    short_trades = []

    for sym, df in datasets.items():
        sigs = find_signals(df)
        for sig in sigs:
            res = simulate_trade(df, sig["entry_idx"], sig["entry_price"],
                                 sig["sl_price"], sig["direction"])
            if res["exit_r"] is None:
                continue
            t = {**sig, **res}
            all_trades.append(t)
            if sig["direction"] == "LONG":
                long_trades.append(t)
            else:
                short_trades.append(t)

    print("=" * 72)
    print("  РЕЗУЛЬТАТЫ")
    print("=" * 72)

    for label, trades in [("ВСЕ", all_trades), ("LONG", long_trades), ("SHORT", short_trades)]:
        m = calc_metrics(trades)
        if not m:
            print(f"\n{label}: нет данных")
            continue
        print(f"\n  {label} ({m['n']} сделок):")
        print(f"    WR:     {m['wr']:5.1f}%")
        print(f"    Avg R:  {m['avg_r']:+.3f}")
        print(f"    Win R:  {m['win_r']:+.2f}  |  Loss R: {m['loss_r']:+.2f}")
        print(f"    PF:     {m['pf']:.2f}")
        print(f"    Sharpe: {m['sharpe']:.2f}")
        print(f"    MaxDD:  {m['max_dd']:+.2f}R")
        print(f"    Moon≥5: {m['moon']}")
        print(f"    SL/TSL: {m['sl_n']}/{m['tsl_n']}")
        print(f"    Avg SL: {m['avg_sl']:.2f}%")

    # Распределение R
    m = calc_metrics(all_trades)
    if m:
        print(f"\n  {'─'*40}")
        print(f"  Распределение R:")
        buckets = [("<-1", lambda r: r < -1), ("-1→0", lambda r: -1 <= r < 0),
                   ("0→1", lambda r: 0 <= r < 1), ("1→2", lambda r: 1 <= r < 2),
                   ("2→5", lambda r: 2 <= r < 5), ("5R+", lambda r: r >= 5)]
        for lbl, fn in buckets:
            cnt = sum(1 for t in all_trades if fn(t["exit_r"]))
            bar = "█" * (cnt * 30 // max(1, len(all_trades)))
            pct = 100 * cnt / len(all_trades)
            print(f"  {lbl:6s}: {cnt:4d} ({pct:4.1f}%)  {bar}")

    print()


if __name__ == "__main__":
    asyncio.run(run_backtest())
