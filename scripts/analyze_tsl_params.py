"""
Анализ параметров TSL: atr_period и factor в calculate_trend().

Загружает реальные OHLCV с биржи, симулирует TSL-выходы с разными
параметрами и показывает сравнительную таблицу.

Запуск: python scripts/analyze_tsl_params.py
        python scripts/analyze_tsl_params.py --symbol BTCUSDT --days 60
"""
import asyncio
import sys
import os
import argparse
import sqlite3
from itertools import product
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import ccxt.async_support as ccxt_async

from core.indicators import calculate_trend, get_trend_info


# ─── Параметры тестирования ───────────────────────────────────────────────
ATR_PERIODS = [14, 21, 34, 43, 55, 89]
FACTORS     = [0.8, 1.0, 1.1, 1.25, 1.3, 1.5, 2.0]  # 1.25 — ручное наблюдение пользователя
TSL_ACTIVATION_R = 1.0   # активация TSL после +1R (как в живом боте)
SL_PCT = 0.02            # фиксированный SL 2% (для симуляции)


def simulate_tsl(df: pd.DataFrame, direction: str, entry_idx: int,
                 atr_period: int, factor: float,
                 sl_pct: float = SL_PCT,
                 tsl_activation_r: float = TSL_ACTIVATION_R) -> dict:
    """
    Симулирует одну сделку начиная с entry_idx.
    Возвращает метрики: exit_r, max_r, capture_pct, exit_reason.
    """
    if entry_idx >= len(df) - 3:
        return None

    entry_price = float(df.iloc[entry_idx]["close"])
    is_long = direction == "LONG"
    sl_dist = entry_price * sl_pct
    stop_loss = entry_price - sl_dist if is_long else entry_price + sl_dist

    tsl_active = False
    tsl_level = stop_loss
    max_r = 0.0
    exit_r = None
    exit_reason = "EXPIRED"

    df_trend = calculate_trend(df, atr_period=atr_period, factor=factor)

    for i in range(entry_idx + 1, min(entry_idx + 201, len(df))):
        row = df.iloc[i]
        high = float(row.get("high", row["close"]))
        low  = float(row.get("low",  row["close"]))
        close = float(row["close"])

        # Текущий R
        if is_long:
            current_r = (close - entry_price) / sl_dist
            peak_r    = (high  - entry_price) / sl_dist
        else:
            current_r = (entry_price - close) / sl_dist
            peak_r    = (entry_price - low)   / sl_dist

        max_r = max(max_r, peak_r)

        # SL hit
        if is_long and low <= stop_loss:
            exit_r, exit_reason = (stop_loss - entry_price) / sl_dist, "SL"
            break
        if not is_long and high >= stop_loss:
            exit_r, exit_reason = (entry_price - stop_loss) / sl_dist, "SL"
            break

        # TSL активация при +1R
        if not tsl_active and current_r >= tsl_activation_r:
            tsl_active = True
            ti = get_trend_info(df_trend.iloc[:i + 1])
            if ti and ti["tsl"] > 0:
                tsl_level = ti["tsl"]

        # TSL трекинг
        if tsl_active:
            ti = get_trend_info(df_trend.iloc[:i + 1])
            if ti and ti["tsl"] > 0:
                new_tsl = ti["tsl"]
                if is_long:
                    tsl_level = max(tsl_level, new_tsl)  # только вверх
                else:
                    tsl_level = min(tsl_level, new_tsl)  # только вниз

            if is_long and low <= tsl_level:
                exit_r = (tsl_level - entry_price) / sl_dist
                exit_reason = "TSL"
                break
            if not is_long and high >= tsl_level:
                exit_r = (entry_price - tsl_level) / sl_dist
                exit_reason = "TSL"
                break

    if exit_r is None:
        exit_r = current_r

    capture = (exit_r / max_r * 100) if max_r > 0.1 else 0
    return {
        "exit_r": exit_r,
        "max_r": max_r,
        "capture_pct": capture,
        "exit_reason": exit_reason,
    }


async def fetch_ohlcv(exchange, symbol: str, timeframe: str = "15m", days: int = 60) -> pd.DataFrame:
    """Загружает OHLCV с биржи."""
    import time
    since = int((time.time() - days * 86400) * 1000)
    limit = min(days * 96 + 50, 1500)  # 96 свечей × 15min в сутки
    ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
    if not ohlcv:
        return pd.DataFrame()
    df = pd.DataFrame(ohlcv, columns=["time", "open", "high", "low", "close", "volume"])
    df = df.astype({"open": float, "high": float, "low": float, "close": float})
    return df


def find_signal_entries(df: pd.DataFrame, n_signals: int = 40) -> list:
    """
    Находит точки входа для симуляции — простой трендовый фильтр.
    LONG: цена пробивает EMA20 снизу вверх.
    SHORT: цена пробивает EMA20 сверху вниз.
    """
    df = df.copy()
    df["ema20"] = df["close"].ewm(span=20).mean()
    df["above"] = df["close"] > df["ema20"]
    entries = []
    step = max(1, len(df) // (n_signals * 2))
    for i in range(20, len(df) - 10, step):
        if df.iloc[i]["above"] and not df.iloc[i - 1]["above"]:
            entries.append((i, "LONG"))
        elif not df.iloc[i]["above"] and df.iloc[i - 1]["above"]:
            entries.append((i, "SHORT"))
        if len(entries) >= n_signals:
            break
    return entries


def print_comparison_table(results: dict, symbols: list):
    """Выводит сравнительную таблицу параметров."""
    print()
    print("=" * 90)
    print(f"  {'Параметры':18} | {'Avg exit R':>10} | {'Avg max R':>9} | {'Capture%':>8} | {'Win%':>6} | {'TSL%':>6} | {'SL%':>6}")
    print("-" * 90)

    # Текущие настройки выделяем
    current = (43, 1.1)
    rows = []
    for (period, factor), stats in results.items():
        n = stats["n"]
        if n == 0:
            continue
        avg_exit  = stats["exit_r"] / n
        avg_max   = stats["max_r"] / n
        avg_cap   = stats["capture"] / n
        win_pct   = stats["wins"] / n * 100
        tsl_pct   = stats["tsl"] / n * 100
        sl_pct_v  = stats["sl"] / n * 100
        rows.append((avg_exit, period, factor, avg_max, avg_cap, win_pct, tsl_pct, sl_pct_v, n))

    # Сортировка по avg_exit_r (лучшие сверху)
    rows.sort(key=lambda x: x[0], reverse=True)
    best_exit = rows[0][0] if rows else 1

    for rank, (avg_exit, period, factor, avg_max, avg_cap, win_pct, tsl_pct, sl_pct_v, n) in enumerate(rows):
        marker = " <- CURRENT" if (period, factor) == current else ""
        best   = " ** BEST **" if rank == 0 else ""
        label  = f"ATR={period:2d} F={factor:.1f}"
        print(f"  {label:18} | {avg_exit:>+10.3f} | {avg_max:>9.2f} | {avg_cap:>7.1f}% | {win_pct:>5.1f}% | {tsl_pct:>5.1f}% | {sl_pct_v:>5.1f}%{marker}{best}")

    print("=" * 90)
    print()
    print(f"  Symbols: {', '.join(symbols)} | ~40 signals each")
    print(f"  Capture% = exit_R / max_R * 100 (how much of peak move captured)")
    print(f"  Win% = trades with exit_R > 0 | TSL% = TSL exits | SL% = SL exits")


async def main(symbols: list, days: int):
    exchange = ccxt_async.bingx({
        "enableRateLimit": False,
        "options": {"defaultType": "swap"},
    })

    results = defaultdict(lambda: {"exit_r": 0, "max_r": 0, "capture": 0,
                                    "wins": 0, "tsl": 0, "sl": 0, "n": 0})

    print(f"\nЗагружаем данные для: {', '.join(symbols)} ({days} дней, 15m)...")

    for symbol in symbols:
        ccxt_sym = symbol.replace("USDT", "/USDT")
        try:
            df = await fetch_ohlcv(exchange, ccxt_sym, "15m", days)
        except Exception as e:
            print(f"  ERR {symbol}: {e}")
            continue

        if df is None or len(df) < 100:
            print(f"  ERR {symbol}: mало данных ({len(df) if df is not None else 0} свечей)")
            continue

        entries = find_signal_entries(df, n_signals=40)
        print(f"  OK  {symbol}: {len(df)} свечей, {len(entries)} сигналов")

        for period, factor in product(ATR_PERIODS, FACTORS):
            key = (period, factor)
            for idx, direction in entries:
                res = simulate_tsl(df, direction, idx, period, factor)
                if res is None:
                    continue
                results[key]["n"]       += 1
                results[key]["exit_r"]  += res["exit_r"]
                results[key]["max_r"]   += res["max_r"]
                results[key]["capture"] += res["capture_pct"]
                if res["exit_r"] > 0:
                    results[key]["wins"] += 1
                if res["exit_reason"] == "TSL":
                    results[key]["tsl"] += 1
                elif res["exit_reason"] == "SL":
                    results[key]["sl"] += 1

    await exchange.close()

    if not results:
        print("Нет данных для анализа.")
        return

    print_comparison_table(results, symbols)

    # Рекомендация
    best_key = max(results, key=lambda k: results[k]["exit_r"] / max(results[k]["n"], 1))
    bp, bf = best_key
    print(f"  Best: atr_period={bp}, factor={bf:.1f}")
    print(f"  Update config.yaml:")
    print(f"    analysis.indicators.trend.atr_period: {bp}")
    print(f"    analysis.indicators.trend.factor: {bf:.1f}")


def get_top_symbols_from_db(n: int = 5) -> list:
    """Берёт топ N символов по количеству сделок в БД."""
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
        # Нормализуем: BTC/USDT → BTCUSDT
        return [r[0].replace("/", "").replace(":USDT", "") for r in rows]
    except Exception:
        return ["BTCUSDT", "ETHUSDT", "BNBUSDT"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Анализ параметров TSL (atr_period, factor)")
    parser.add_argument("--symbols", nargs="+", default=None,
                        help="Символы для анализа (напр. BTCUSDT ETHUSDT)")
    parser.add_argument("--days", type=int, default=30,
                        help="Глубина истории в днях (default: 30)")
    parser.add_argument("--top", type=int, default=3,
                        help="Топ N символов из БД (если --symbols не указан)")
    args = parser.parse_args()

    symbols = args.symbols or get_top_symbols_from_db(args.top)
    print(f"Символы: {symbols}")
    print(f"Периоды ATR: {ATR_PERIODS}")
    print(f"Факторы: {FACTORS}")
    print(f"Комбинаций: {len(ATR_PERIODS) * len(FACTORS)}")

    asyncio.run(main(symbols, args.days))
