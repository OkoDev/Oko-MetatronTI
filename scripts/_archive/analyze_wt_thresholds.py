"""
Анализ оптимальных OS/OB порогов для WT индикатора.

Текущие: ob=+60, os=-60 (фиксированные для всех пар).
Идея: каждая пара имеет свой "нормальный" диапазон WT.

Метод: перцентильный анализ + сравнение качества сигналов.
  os_threshold = percentile(10) от WT за N дней
  ob_threshold = percentile(90) от WT за N дней

Запуск:
    python scripts/analyze_wt_thresholds.py
    python scripts/analyze_wt_thresholds.py --symbols BTCUSDT ETHUSDT --days 60
"""
import asyncio
import sys
import os
import argparse
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import ccxt.async_support as ccxt_async

from core.indicators import calculate_wt


# ─── Параметры тестирования ───────────────────────────────────────────────
FIXED_OB = 60.0
FIXED_OS = -60.0
PERCENTILES_OB = [80, 85, 90, 95]   # верхние перцентили = зона OB
PERCENTILES_OS = [20, 15, 10, 5]    # нижние перцентили = зона OS
FORWARD_BARS = 20    # сколько баров смотрим вперёд для оценки сигнала


async def fetch_ohlcv(exchange, symbol: str, timeframe: str = "15m", days: int = 60) -> pd.DataFrame:
    import time
    since = int((time.time() - days * 86400) * 1000)
    limit = min(days * 96 + 50, 1500)
    ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
    if not ohlcv:
        return pd.DataFrame()
    df = pd.DataFrame(ohlcv, columns=["time", "open", "high", "low", "close", "volume"])
    return df.astype({"open": float, "high": float, "low": float, "close": float})


def compute_wt_series(df: pd.DataFrame) -> pd.Series:
    """Возвращает серию WT1 значений."""
    try:
        df_wt = calculate_wt(df)
        if "wt1" in df_wt.columns:
            return df_wt["wt1"].dropna()
        # fallback: wt или первый числовой столбец
        for col in df_wt.columns:
            if col not in ("time", "open", "high", "low", "close", "volume"):
                return df_wt[col].dropna()
    except Exception as e:
        print(f"    WT error: {e}")
    return pd.Series(dtype=float)


def evaluate_signals(df: pd.DataFrame, wt: pd.Series,
                     ob: float, os_: float,
                     forward: int = FORWARD_BARS) -> dict:
    """
    Оценивает качество сигналов при заданных ob/os порогах.

    OS-сигнал (LONG): WT пересекает os снизу вверх (wt[i-1] < os и wt[i] >= os)
    OB-сигнал (SHORT): WT пересекает ob сверху вниз (wt[i-1] > ob и wt[i] <= ob)

    Качество: сколько сигналов дали прибыль через forward баров.
    """
    closes = df["close"].values
    wt_vals = wt.values
    idx_list = wt.index.tolist()

    long_wins = long_total = 0
    short_wins = short_total = 0
    long_avg_r = []
    short_avg_r = []

    for i in range(1, len(wt_vals) - forward):
        df_idx = idx_list[i]
        if df_idx >= len(closes) - forward:
            break

        entry_price = closes[df_idx]
        future_prices = closes[df_idx + 1: df_idx + forward + 1]
        if len(future_prices) == 0 or entry_price == 0:
            continue

        # OS сигнал: WT пересёк os снизу вверх -> LONG
        if wt_vals[i - 1] < os_ and wt_vals[i] >= os_:
            long_total += 1
            max_ret = (max(future_prices) - entry_price) / entry_price * 100
            exit_ret = (future_prices[-1] - entry_price) / entry_price * 100
            if exit_ret > 0:
                long_wins += 1
            long_avg_r.append(exit_ret)

        # OB сигнал: WT пересёк ob сверху вниз -> SHORT
        if wt_vals[i - 1] > ob and wt_vals[i] <= ob:
            short_total += 1
            exit_ret = (entry_price - future_prices[-1]) / entry_price * 100
            if exit_ret > 0:
                short_wins += 1
            short_avg_r.append(exit_ret)

    total = long_total + short_total
    wins  = long_wins + short_wins
    all_r = long_avg_r + short_avg_r

    return {
        "signals": total,
        "long": long_total,
        "short": short_total,
        "win_rate": wins / total * 100 if total > 0 else 0,
        "avg_ret": np.mean(all_r) if all_r else 0,
        "long_wr": long_wins / long_total * 100 if long_total > 0 else 0,
        "short_wr": short_wins / short_total * 100 if short_total > 0 else 0,
    }


def analyze_symbol(symbol: str, df: pd.DataFrame) -> None:
    wt = compute_wt_series(df)
    if len(wt) < 50:
        print(f"  {symbol}: nedostatochno WT dannyx ({len(wt)})")
        return

    # Распределение WT
    p = {q: np.percentile(wt, q) for q in [5, 10, 15, 20, 25, 50, 75, 80, 85, 90, 95]}

    print(f"\n  {symbol} | WT={len(wt)} bars")
    print(f"    WT распределение:")
    print(f"      p5={p[5]:.1f}  p10={p[10]:.1f}  p15={p[15]:.1f}  p20={p[20]:.1f}  [median={p[50]:.1f}]  p80={p[80]:.1f}  p85={p[85]:.1f}  p90={p[90]:.1f}  p95={p[95]:.1f}")
    print(f"      Фиксированные: OS={FIXED_OS:.0f} | OB={FIXED_OB:.0f}")

    # % времени в зоне OS/OB при фиксированных порогах
    pct_os_fixed = (wt < FIXED_OS).mean() * 100
    pct_ob_fixed = (wt > FIXED_OB).mean() * 100
    print(f"      Время в OS зоне (<{FIXED_OS:.0f}): {pct_os_fixed:.1f}% | OB зоне (>{FIXED_OB:.0f}): {pct_ob_fixed:.1f}%")

    # Оценка сигналов при разных порогах
    print(f"\n    Качество сигналов (wr за {FORWARD_BARS} баров вперёд):")
    print(f"      {'Метод':25} | {'OS':>5} | {'OB':>5} | {'Сигналов':>8} | {'Win%':>6} | {'Avg%':>6} | {'L_wr%':>6} | {'S_wr%':>6}")
    print(f"      {'-'*82}")

    # 1. Фиксированные (текущие)
    res = evaluate_signals(df, wt, FIXED_OB, FIXED_OS)
    marker = " <- CURRENT"
    print(f"      {'Fixed ±60':25} | {FIXED_OS:>5.0f} | {FIXED_OB:>5.0f} | {res['signals']:>8d} | {res['win_rate']:>5.1f}% | {res['avg_ret']:>+5.2f}% | {res['long_wr']:>5.1f}% | {res['short_wr']:>5.1f}%{marker}")

    # 2. Перцентильные варианты
    for pob_q, pos_q in zip(PERCENTILES_OB, PERCENTILES_OS):
        ob_val = p[pob_q]
        os_val = p[pos_q]
        res = evaluate_signals(df, wt, ob_val, os_val)
        label = f"p{pos_q}/{pob_q} ({os_val:.0f}/{ob_val:.0f})"
        print(f"      {label:25} | {os_val:>5.0f} | {ob_val:>5.0f} | {res['signals']:>8d} | {res['win_rate']:>5.1f}% | {res['avg_ret']:>+5.2f}% | {res['long_wr']:>5.1f}% | {res['short_wr']:>5.1f}%")

    # 3. Рекомендация: лучший порог по win_rate
    best_wr = 0
    best_cfg = None
    for pob_q, pos_q in zip(PERCENTILES_OB, PERCENTILES_OS):
        res = evaluate_signals(df, wt, p[pob_q], p[pos_q])
        if res["signals"] >= 5 and res["win_rate"] > best_wr:
            best_wr = res["win_rate"]
            best_cfg = (pos_q, pob_q, p[pos_q], p[pob_q])

    if best_cfg:
        print(f"\n    Лучший для {symbol}: p{best_cfg[0]}/p{best_cfg[1]} -> OS={best_cfg[2]:.1f} OB={best_cfg[3]:.1f} (wr={best_wr:.1f}%)")


def get_top_symbols_from_db(n: int = 5) -> list:
    try:
        conn = sqlite3.connect("subscriptions.db")
        cur = conn.cursor()
        cur.execute("""
            SELECT symbol, COUNT(*) as cnt FROM simulated_trades
            WHERE status != 'OPEN'
            GROUP BY symbol ORDER BY cnt DESC LIMIT ?
        """, (n,))
        rows = cur.fetchall()
        conn.close()
        return [r[0].replace("/", "").replace(":USDT", "") for r in rows]
    except Exception:
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT"]


async def main(symbols: list, days: int):
    exchange = ccxt_async.bingx({
        "enableRateLimit": False,
        "options": {"defaultType": "swap"},
    })

    print(f"\nАнализ WT OS/OB порогов | {len(symbols)} пар | {days} дней | 15m")
    print(f"Фиксированные: OS={FIXED_OS} OB={FIXED_OB}")
    print(f"Перцентильные: OS=p{{5,10,15,20}} OB=p{{95,90,85,80}}")
    print("=" * 90)

    for symbol in symbols:
        ccxt_sym = symbol.replace("USDT", "/USDT")
        try:
            df = await fetch_ohlcv(exchange, ccxt_sym, "15m", days)
            if df is None or len(df) < 100:
                print(f"  {symbol}: mало данных")
                continue
            analyze_symbol(symbol, df)
        except Exception as e:
            print(f"  {symbol} ERR: {e}")

    await exchange.close()

    print("\n" + "=" * 90)
    print("ВЫВОД:")
    print("  Если перцентильные пороги дают БОЛЬШЕ сигналов при ЛУЧШЕМ win% ->")
    print("  фиксированные ±60 слишком узкие/широкие для этой пары.")
    print()
    print("СЛЕДУЮЩИЙ ШАГ (если подтверждено):")
    print("  Добавить per-symbol os/ob кэш в indicators.py:")
    print("    wt_thresholds[symbol] = {ob: percentile(wt, 90), os: percentile(wt, 10)}")
    print("  Обновлять раз в 4h вместе с прогревом пивотного кэша.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=None)
    parser.add_argument("--days", type=int, default=45)
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args()

    symbols = args.symbols or get_top_symbols_from_db(args.top)
    print(f"Символы: {symbols}")
    asyncio.run(main(symbols, args.days))
