#!/usr/bin/env python3
"""
Сравнение: фиксированный OS vs динамический OS/OB по 4 таймфреймам
====================================================================
Стратегия: WT crossup в OS + ATR trend crossup | SL = trendup | ATR=1.25

Варианты OS-порога:
  fixed_45  — wt1 < -45 (статичный)
  fixed_60  — wt1 < -60 (статичный, стандарт)
  dyn_08    — wt1 < mean(50) - 0.8*std(50)  (динамический, k=0.8)
  dyn_10    — wt1 < mean(50) - 1.0*std(50)  (динамический, k=1.0)
  dyn_12    — wt1 < mean(50) - 1.2*std(50)  (динамический, k=1.2)

Таймфреймы: 3m / 5m / 15m / 1h

Запуск: python scripts/backtest_dynamic_os.py
"""
import os, sys, asyncio, sqlite3, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
import numpy as np

from core.data_collector import RealTimeData
from core.indicators import calculate_wt, calculate_trend

logging.basicConfig(level=logging.WARNING)

# ── Параметры ─────────────────────────────────────────────────────────────────
SYMBOLS_LIMIT = 50
ATR_FACTOR    = 1.25
ATR_WINDOW    = 1
MIN_SL_PCT    = 0.003
MAX_SL_PCT    = 0.08
DYN_WINDOW    = 50      # баров истории для динамического порога

TF_CANDLES = {
    "3m":  1440,   # max BingX
    "5m":  1000,
    "15m":  500,
    "1h":   500,
}

# Варианты стратегий: (label, threshold_type, param)
#   threshold_type="fixed" → param=порог (число)
#   threshold_type="dynamic" → param=k (множитель std)
STRATEGIES = [
    ("fixed -45",  "fixed",   -45.0),
    ("fixed -60",  "fixed",   -60.0),
    ("dyn k=0.8",  "dynamic",   0.8),
    ("dyn k=1.0",  "dynamic",   1.0),
    ("dyn k=1.2",  "dynamic",   1.2),
]


# ── Динамический порог на конкретном баре ─────────────────────────────────────

def compute_dyn_os(wt1_series: np.ndarray, idx: int, k: float, window: int) -> float:
    """
    Вычисляет динамический OS-порог на баре idx.
    Использует только данные ДО idx (no look-ahead).
    """
    start = max(0, idx - window)
    hist  = wt1_series[start:idx]
    if len(hist) < 20:
        return np.nan
    return float(np.mean(hist) - k * np.std(hist))


# ── Поиск сигналов ────────────────────────────────────────────────────────────

def find_signals(df: pd.DataFrame, threshold_type: str, param: float) -> list:
    wt1_arr = df["wt1"].values
    signals = []

    for i in range(2, len(df) - 1):
        wt1_prev = df["wt1"].iloc[i-1]
        wt2_prev = df["wt2"].iloc[i-1]
        wt1_cur  = df["wt1"].iloc[i]
        wt2_cur  = df["wt2"].iloc[i]

        if pd.isna(wt1_prev) or pd.isna(wt2_prev) or pd.isna(wt1_cur) or pd.isna(wt2_cur):
            continue

        # WT crossup
        if not ((wt1_prev < wt2_prev) and (wt1_cur >= wt2_cur)):
            continue

        # OS порог
        if threshold_type == "fixed":
            os_thr = param
        else:  # dynamic
            os_thr = compute_dyn_os(wt1_arr, i, k=param, window=DYN_WINDOW)
            if np.isnan(os_thr):
                continue

        if wt1_cur >= os_thr:
            continue

        # ATR trend crossup
        atr_crossup = False
        for w in range(ATR_WINDOW + 1):
            if i - w >= 1:
                t_now  = df["trend"].iloc[i - w]
                t_prev = df["trend"].iloc[i - w - 1] if (i - w - 1) >= 0 else np.nan
                if not pd.isna(t_now) and not pd.isna(t_prev):
                    if t_now == 1.0 and t_prev == -1.0:
                        atr_crossup = True
                        break
        if not atr_crossup:
            continue

        sl_price = df["trendup"].iloc[i]
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
            "wt1":         wt1_cur,
            "os_thr":      os_thr,
        })
    return signals


# ── Симуляция ─────────────────────────────────────────────────────────────────

def simulate_trade(df: pd.DataFrame, entry_idx: int, entry_price: float, sl_price: float) -> dict:
    one_r = entry_price - sl_price
    if one_r <= 0:
        return {"status": "INVALID", "exit_r": None}

    current_sl    = sl_price
    tsl_activated = False

    for i in range(entry_idx + 1, len(df)):
        low   = float(df["low"].iloc[i])
        close = float(df["close"].iloc[i])

        if low <= current_sl:
            exit_r = (current_sl - entry_price) / one_r
            return {"status": "TSL" if tsl_activated else "SL",
                    "exit_r": exit_r, "bars": i - entry_idx}

        if not tsl_activated and (close - entry_price) / one_r >= 1.0:
            tsl_activated = True

        new_sl = df["trendup"].iloc[i]
        if not pd.isna(new_sl) and new_sl > current_sl:
            current_sl = float(new_sl)

    final_r = (float(df["close"].iloc[-1]) - entry_price) / one_r
    return {"status": "OPEN", "exit_r": final_r, "bars": len(df) - entry_idx}


# ── Метрики ───────────────────────────────────────────────────────────────────

def calc_metrics(trades: list) -> dict | None:
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
    return {"n": n, "wr": wrate, "avg_r": sum(rs)/n, "win_r": win_r,
            "pf": pf, "sharpe": sharpe, "max_dd": max_dd, "moon": moon, "avg_sl": avg_sl}


# ── Основная функция ──────────────────────────────────────────────────────────

async def run_backtest():
    print("=" * 80)
    print(f"  ДИНАМИЧЕСКИЙ vs ФИКСИРОВАННЫЙ OS | ATR={ATR_FACTOR} | {SYMBOLS_LIMIT} пар")
    print("=" * 80)

    conn = sqlite3.connect("subscriptions.db")
    symbols = [r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM simulated_trades WHERE timeframe='15m' ORDER BY created_at DESC LIMIT ?",
        (SYMBOLS_LIMIT,)
    ).fetchall()]
    conn.close()

    dc = RealTimeData("bingx", api_semaphore_size=15, api_rps=15.0)
    await dc.load_markets()

    # Структура результатов: results[tf][strategy_label] = [trades]
    all_results = {}

    for tf, candles in TF_CANDLES.items():
        print(f"\nЗагрузка {tf} ({candles} свечей × {len(symbols)} пар)...")
        datasets = {}
        skipped  = 0

        for sym in symbols:
            try:
                df = await dc.get_ohlcv(sym, timeframe=tf, limit=candles)
                if df is None or len(df) < 100:
                    skipped += 1
                    continue
                df = calculate_wt(df)
                df = calculate_trend(df, factor=ATR_FACTOR)
                datasets[sym] = df
            except Exception:
                skipped += 1

        print(f"  Загружено: {len(datasets)}/{len(symbols)}")

        tf_results = {lbl: [] for lbl, _, _ in STRATEGIES}

        for sym, df in datasets.items():
            for lbl, t_type, param in STRATEGIES:
                sigs = find_signals(df, t_type, param)
                for sig in sigs:
                    result = simulate_trade(df, sig["entry_idx"], sig["entry_price"], sig["sl_price"])
                    if result["exit_r"] is None:
                        continue
                    tf_results[lbl].append({**sig, **result})

        all_results[tf] = tf_results

    await dc.stop()

    # ── Вывод таблицы ──────────────────────────────────────────────────────────
    col_w = 12

    for tf in TF_CANDLES:
        print(f"\n{'='*80}")
        print(f"  ТАЙМФРЕЙМ: {tf}")
        print(f"{'='*80}")
        print(f"  {'Стратегия':<14}", end="")
        for hdr in ["n", "WR%", "Avg R", "PF", "Sharpe", "MaxDD R", "Moon", "SL%"]:
            print(f"  {hdr:>7}", end="")
        print()
        print(f"  {'─'*14}", end="")
        for _ in range(8):
            print(f"  {'─'*7}", end="")
        print()

        tf_res = all_results[tf]
        rows = []
        for lbl, _, _ in STRATEGIES:
            m = calc_metrics(tf_res[lbl])
            rows.append((lbl, m))

        # Сортировка по Avg R
        rows.sort(key=lambda x: x[1]["avg_r"] if x[1] else -99, reverse=True)

        best_avg_r = max((r[1]["avg_r"] for r in rows if r[1]), default=0)

        for lbl, m in rows:
            if m is None:
                print(f"  {lbl:<14}  {'нет данных':>7}")
                continue
            warn = "⚠️" if m["n"] < 20 else "  "
            mark = " ←" if abs(m["avg_r"] - best_avg_r) < 0.001 else "  "
            print(f"  {lbl:<14}"
                  f"  {m['n']:>7}"
                  f"  {m['wr']:>6.1f}%"
                  f"  {m['avg_r']:>+7.2f}"
                  f"  {m['pf']:>7.2f}"
                  f"  {m['sharpe']:>7.2f}"
                  f"  {m['max_dd']:>+7.2f}"
                  f"  {m['moon']:>7}"
                  f"  {m['avg_sl']:>6.2f}%"
                  f"  {warn}{mark}")

    # ── Сводная таблица ────────────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print("  СВОДНАЯ ТАБЛИЦА — Avg R по всем TF")
    print(f"{'='*80}")
    print(f"  {'Стратегия':<14}", end="")
    for tf in TF_CANDLES:
        print(f"  {tf:>10}", end="")
    print(f"  {'Avg':>10}")
    print(f"  {'─'*14}", end="")
    for _ in TF_CANDLES:
        print(f"  {'─'*10}", end="")
    print(f"  {'─'*10}")

    for lbl, _, _ in STRATEGIES:
        print(f"  {lbl:<14}", end="")
        vals = []
        for tf in TF_CANDLES:
            m = calc_metrics(all_results[tf][lbl])
            if m and m["n"] >= 10:
                print(f"  {m['avg_r']:>+10.2f}", end="")
                vals.append(m["avg_r"])
            else:
                n = m["n"] if m else 0
                print(f"  {'—':>10}", end="")
        avg = sum(vals) / len(vals) if vals else float("nan")
        print(f"  {avg:>+10.2f}")

    print()


if __name__ == "__main__":
    asyncio.run(run_backtest())
