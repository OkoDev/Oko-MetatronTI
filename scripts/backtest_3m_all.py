#!/usr/bin/env python3
"""
Полный прогон всех стратегий на 3m таймфрейме
==============================================
Стратегии:
  1. WT crossup OS (sweep: -10 / -20 / -30 / -45 / -59 / -70 / -80) + ATR trend
  2. ATR trend only (без WT фильтра)
  3. WT < -30 + ATR + дивергенция
  4. WT < -59 + ATR + дивергенция

SL = trendup (ATR factor=1.25)
TSL активируется после +1R

Запуск: python scripts/backtest_3m_all.py
"""
import os, sys, asyncio, sqlite3, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
import numpy as np

from core.data_collector import RealTimeData
from core.indicators import calculate_wt, calculate_trend

logging.basicConfig(level=logging.WARNING)

# ── Параметры ────────────────────────────────────────────────────────────────
SYMBOLS_LIMIT   = 50
CANDLES         = 1440       # max BingX 3m ≈ 3 дня
TIMEFRAME       = "3m"
ATR_FACTOR      = 1.25
ATR_WINDOW      = 1          # баров назад для ATR crossup
MIN_SL_PCT      = 0.003
MAX_SL_PCT      = 0.08
DIV_LOOKBACK    = 50
DIV_MIN_BARS    = 5

# OS пороги для sweep
WT_OS_LEVELS    = [-10, -20, -30, -45, -59, -70, -80]


# ── Дивергенция ───────────────────────────────────────────────────────────────

def detect_wt_divergence(df: pd.DataFrame, i: int) -> bool:
    cur_wt  = df["wt1"].iloc[i]
    cur_low = df["low"].iloc[i]
    start   = max(1, i - DIV_LOOKBACK)
    end     = i - DIV_MIN_BARS
    if end <= start:
        return False
    for j in range(end, start, -1):
        wt_j = df["wt1"].iloc[j]
        if pd.isna(wt_j):
            continue
        wt_p = df["wt1"].iloc[j - 1]
        wt_n = df["wt1"].iloc[j + 1] if j + 1 < len(df) else np.nan
        if pd.isna(wt_p) or pd.isna(wt_n):
            continue
        if wt_j < wt_p and wt_j < wt_n:
            if cur_low <= df["low"].iloc[j] and cur_wt > wt_j:
                return True
    return False


# ── Поиск сигналов ────────────────────────────────────────────────────────────

def find_signals(df: pd.DataFrame, wt_threshold: float) -> list:
    """
    wt_threshold=None → ATR-only (без WT фильтра)
    wt_threshold=-30  → WT < -30
    """
    signals = []
    for i in range(2, len(df) - 1):
        wt1_prev = df["wt1"].iloc[i-1]
        wt2_prev = df["wt2"].iloc[i-1]
        wt1_cur  = df["wt1"].iloc[i]
        wt2_cur  = df["wt2"].iloc[i]

        if pd.isna(wt1_prev) or pd.isna(wt2_prev) or pd.isna(wt1_cur) or pd.isna(wt2_cur):
            continue

        # WT crossup (нужен для всех стратегий кроме ATR-only)
        wt_crossup = (wt1_prev < wt2_prev) and (wt1_cur >= wt2_cur)

        if wt_threshold is not None:
            if not wt_crossup:
                continue
            if wt1_cur >= wt_threshold:
                continue
        else:
            # ATR-only: не требуем WT crossup
            pass

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

        has_div = detect_wt_divergence(df, i)

        signals.append({
            "signal_idx":  i,
            "entry_idx":   i + 1,
            "entry_price": entry_price,
            "sl_price":    float(sl_price),
            "sl_pct":      sl_dist_pct * 100,
            "wt1":         wt1_cur,
            "has_div":     has_div,
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
    return {
        "n": n, "wr": wrate, "avg_r": sum(rs)/n,
        "win_r": win_r, "loss_r": loss_r,
        "pf": pf, "sharpe": sharpe,
        "max_dd": max_dd, "moon": moon, "avg_sl": avg_sl,
    }


# ── Основная функция ──────────────────────────────────────────────────────────

async def run_backtest():
    print("=" * 72)
    print(f"  ПОЛНЫЙ ПРОГОН СТРАТЕГИЙ | TF={TIMEFRAME} | ATR={ATR_FACTOR} | {SYMBOLS_LIMIT} пар")
    print("=" * 72)

    conn = sqlite3.connect("subscriptions.db")
    symbols = [r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM simulated_trades WHERE timeframe='15m' ORDER BY created_at DESC LIMIT ?",
        (SYMBOLS_LIMIT,)
    ).fetchall()]
    conn.close()

    dc = RealTimeData("bingx", api_semaphore_size=15, api_rps=15.0)
    await dc.load_markets()

    # Сбор данных — один раз на символ
    print(f"Загрузка данных ({len(symbols)} пар × {CANDLES} свечей 3m)...")
    datasets = {}
    skipped  = 0
    for sym in symbols:
        try:
            df = await dc.get_ohlcv(sym, timeframe=TIMEFRAME, limit=CANDLES)
            if df is None or len(df) < 100:
                skipped += 1
                continue
            df = calculate_wt(df)
            df = calculate_trend(df, factor=ATR_FACTOR)
            datasets[sym] = df
        except Exception:
            skipped += 1

    await dc.stop()
    print(f"Загружено: {len(datasets)}/{len(symbols)} символов\n")

    # Стратегии для тестирования
    strategies = {}

    # 1. ATR-only (без WT фильтра)
    strategies["ATR only"] = {"threshold": None, "div": False}

    # 2. WT sweep
    for lvl in WT_OS_LEVELS:
        strategies[f"WT < {lvl}"] = {"threshold": lvl, "div": False}

    # 3. WT + дивергенция для -30 и -59
    strategies["WT < -30 + Div"] = {"threshold": -30, "div": True}
    strategies["WT < -59 + Div"] = {"threshold": -59, "div": True}

    # Прогон
    results = {name: [] for name in strategies}

    for sym, df in datasets.items():
        # Находим сигналы один раз с полной информацией
        # Для ATR-only нужны отдельные сигналы
        for name, cfg in strategies.items():
            threshold = cfg["threshold"]
            sigs = find_signals(df, threshold)
            for sig in sigs:
                if cfg["div"] and not sig["has_div"]:
                    continue
                result = simulate_trade(df, sig["entry_idx"], sig["entry_price"], sig["sl_price"])
                if result["exit_r"] is None:
                    continue
                results[name].append({**sig, **result})

    # ── Вывод результатов ────────────────────────────────────────────────────
    print("=" * 72)
    print("  СРАВНИТЕЛЬНАЯ ТАБЛИЦА  (sorted by Avg R)")
    print("=" * 72)
    print(f"  {'Стратегия':<22}  {'n':>4}  {'WR%':>6}  {'Avg R':>7}  {'PF':>5}  {'Sharpe':>6}  {'MaxDD':>7}  {'Moon':>4}  {'SL%':>5}")
    print(f"  {'─'*22}  {'─'*4}  {'─'*6}  {'─'*7}  {'─'*5}  {'─'*6}  {'─'*7}  {'─'*4}  {'─'*5}")

    ranked = sorted(
        [(name, calc_metrics(trades)) for name, trades in results.items() if calc_metrics(trades)],
        key=lambda x: x[1]["avg_r"],
        reverse=True
    )

    for name, m in ranked:
        warn = "⚠️" if m["n"] < 20 else "  "
        print(f"  {name:<22}  {m['n']:>4}  {m['wr']:>5.1f}%  {m['avg_r']:>+7.2f}  {m['pf']:>5.2f}  {m['sharpe']:>6.2f}  {m['max_dd']:>+7.2f}  {m['moon']:>4}  {m['avg_sl']:>5.2f}%  {warn}")

    # Детальный вывод топ-3
    print("\n" + "=" * 72)
    print("  ДЕТАЛИ: TOP-3 СТРАТЕГИИ")
    print("=" * 72)

    for i, (name, m) in enumerate(ranked[:3], 1):
        trades = results[name]
        print(f"\n  #{i} {name}")
        print(f"  {'─'*50}")
        print(f"  Сделок: {m['n']}  WR: {m['wr']:.1f}%  Avg R: {m['avg_r']:+.2f}")
        print(f"  Avg win: {m['win_r']:+.2f}R  Avg loss: {m['loss_r']:+.2f}R")
        print(f"  PF: {m['pf']:.2f}  Sharpe: {m['sharpe']:.2f}  MaxDD: {m['max_dd']:+.2f}R")
        print(f"  Moon ≥5R: {m['moon']}  Avg SL: {m['avg_sl']:.2f}%")

        sl_ex  = sum(1 for t in trades if t["status"] == "SL")
        tsl_ex = sum(1 for t in trades if t["status"] == "TSL")
        open_p = sum(1 for t in trades if t["status"] == "OPEN")
        print(f"  Выходы: SL={sl_ex}  TSL={tsl_ex}  OPEN={open_p}")

        buckets = [("<-1R", lambda r: r < -1), ("-1-0R", lambda r: -1 <= r < 0),
                   ("0-1R",  lambda r: 0 <= r < 1),  ("1-2R", lambda r: 1 <= r < 2),
                   ("2-3R",  lambda r: 2 <= r < 3),  ("3-5R", lambda r: 3 <= r < 5),
                   ("5R+",   lambda r: r >= 5)]
        print()
        for lbl, fn in buckets:
            cnt = sum(1 for t in trades if fn(t["exit_r"]))
            bar = "█" * (cnt // max(1, m["n"] // 30))
            print(f"  {lbl:7s}: {cnt:3d}  {bar}")

    print()


if __name__ == "__main__":
    asyncio.run(run_backtest())
