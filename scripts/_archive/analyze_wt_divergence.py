"""
Анализ WT дивергенций: FIXED ±60 vs ADAPTIVE p10/p90.

Три типа сигналов:
  A: crossover В OS/OB зоне, без дивергенции  (текущий бот)
  B: crossover В OS/OB зоне, с дивергенцией
  C: crossover ВНЕ OS/OB зоны, с дивергенцией (паттерн пользователя)

Дивергенция: делим LOOKBACK окно пополам,
  min второй половины > min первой (оба в OS) → bullish div.

Запуск:
    python scripts/analyze_wt_divergence.py
    python scripts/analyze_wt_divergence.py --days 90
"""
import asyncio
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import ccxt.async_support as ccxt_async

from core.indicators import calculate_wt

# ─── Параметры ────────────────────────────────────────────────────────────────
WT_N1, WT_N2     = 10, 21
LOOKBACK         = 35
FORWARD_BARS     = 20    # 20 × 15m = 5 часов
ADAPTIVE_PCTILE  = 10    # p10/p90 для адаптивных порогов

# Пары разной волатильности
DEFAULT_SYMBOLS = [
    # Низкая волатильность (крупные)
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT",
    # Средняя волатильность
    "SOLUSDT", "DOTUSDT", "LINKUSDT", "AVAXUSDT", "TRXUSDT",
    "XLMUSDT", "ETCUSDT", "ALGOUSDT", "VETUSDT", "1INCHUSDT",
    # Высокая волатильность
    "DOGEUSDT", "APEUSDT", "GRTUSDT", "CFXUSDT", "SUIUSDT",
    "NOTUSDT", "MOVEUSDT", "SOLVUSDT", "BERAUSDT", "DYMUSDT",
    # Очень высокая волатильность (мелкие альты)
    "COTIUSDT", "API3USDT", "CETUSUSDT", "ANIMEUSDT", "B3USDT",
    "SUNUSDT", "0GUSDT", "XLMUSDT", "APEUSDT",
]


def adaptive_thresholds(wt1: np.ndarray) -> tuple:
    """Вычисляет адаптивные OS/OB пороги как p10/p90 от всей серии WT."""
    os_ = float(np.percentile(wt1, ADAPTIVE_PCTILE))
    ob  = float(np.percentile(wt1, 100 - ADAPTIVE_PCTILE))
    return os_, ob


def has_divergence(wt1_vals: list, os_: float) -> bool:
    """Bullish дивергенция: min второй половины окна > min первой (оба в OS)."""
    half = len(wt1_vals) // 2
    if half < 5:
        return False
    os1 = [v for v in wt1_vals[:half]  if v < os_]
    os2 = [v for v in wt1_vals[half:]  if v < os_]
    if not os1 or not os2:
        return False
    return min(os2) > min(os1)


def has_bearish_divergence(wt1_vals: list, ob: float) -> bool:
    """Bearish дивергенция: max второй половины < max первой (оба в OB)."""
    half = len(wt1_vals) // 2
    if half < 5:
        return False
    ob1 = [v for v in wt1_vals[:half]  if v > ob]
    ob2 = [v for v in wt1_vals[half:]  if v > ob]
    if not ob1 or not ob2:
        return False
    return max(ob2) < max(ob1)


def scan_signals(df: pd.DataFrame, symbol: str,
                 os_: float, ob: float, mode: str) -> pd.DataFrame:
    """Сканирует бары и возвращает сигналы A/B/C для заданных порогов."""
    wt1    = df["wt1"].values
    wt2    = df["wt2"].values
    closes = df["close"].values
    records = []

    for i in range(LOOKBACK + 2, len(df) - FORWARD_BARS):
        cross_up   = wt1[i-1] < wt2[i-1] and wt1[i] > wt2[i]
        cross_down = wt1[i-1] > wt2[i-1] and wt1[i] < wt2[i]
        if not cross_up and not cross_down:
            continue

        entry  = closes[i]
        future = closes[i+1 : i+FORWARD_BARS+1]
        if entry == 0 or len(future) < FORWARD_BARS:
            continue

        window  = list(wt1[i - LOOKBACK: i])
        gap     = abs(wt1[i] - wt2[i])

        if cross_up:
            in_os   = wt1[i] < os_
            has_div = has_divergence(window, os_)
            ret     = (future[-1] - entry) / entry * 100
            max_ret = (max(future)  - entry) / entry * 100

            if   in_os and not has_div: sig = "A_os"
            elif in_os and has_div:     sig = "B_os"
            elif not in_os and has_div: sig = "C_exos"
            else: continue

            records.append({"symbol": symbol, "mode": mode, "sig": sig,
                             "direction": "LONG", "wt1": round(wt1[i], 2),
                             "gap": round(gap, 2), "ret": round(ret, 3),
                             "max_ret": round(max_ret, 3), "win": ret > 0})

        if cross_down:
            in_ob   = wt1[i] > ob
            has_div = has_bearish_divergence(window, ob)
            ret     = (entry - future[-1]) / entry * 100
            max_ret = (entry - min(future)) / entry * 100

            if   in_ob and not has_div: sig = "A_ob"
            elif in_ob and has_div:     sig = "B_ob"
            elif not in_ob and has_div: sig = "C_exob"
            else: continue

            records.append({"symbol": symbol, "mode": mode, "sig": sig,
                             "direction": "SHORT", "wt1": round(wt1[i], 2),
                             "gap": round(gap, 2), "ret": round(ret, 3),
                             "max_ret": round(max_ret, 3), "win": ret > 0})

    return pd.DataFrame(records)


def print_comparison(fixed: pd.DataFrame, adaptive: pd.DataFrame,
                     adaptive_thresholds_map: dict) -> None:

    # Средние адаптивные пороги
    os_vals = [v["os"] for v in adaptive_thresholds_map.values()]
    ob_vals = [v["ob"] for v in adaptive_thresholds_map.values()]
    print(f"\n  Адаптивные пороги (среднее по {len(os_vals)} парам):")
    print(f"    OS: mean={np.mean(os_vals):.1f}  min={min(os_vals):.1f}  max={max(os_vals):.1f}")
    print(f"    OB: mean={np.mean(ob_vals):.1f}  min={min(ob_vals):.1f}  max={max(ob_vals):.1f}")

    sigs = [
        ("A_os",   "A  в OS,  без дивергенции (текущий LONG)"),
        ("A_ob",   "A  в OB,  без дивергенции (текущий SHORT)"),
        ("B_os",   "B  в OS,  с дивергенцией"),
        ("B_ob",   "B  в OB,  с дивергенцией"),
        ("C_exos", "C  вне OS, с дивергенцией  LONG"),
        ("C_exob", "C  вне OB, с дивергенцией  SHORT"),
    ]

    print("\n" + "=" * 78)
    print(f"  {'Тип':35} | {'--- FIXED ±60 ---':^20} | {'--- ADAPTIVE ---':^16}")
    print(f"  {'':35} | {'n':>4}  {'WR%':>6}  {'avgR%':>6} | {'n':>4}  {'WR%':>6}  {'avgR%':>6}")
    print("-" * 78)

    for code, label in sigs:
        f = fixed[fixed["sig"] == code]
        a = adaptive[adaptive["sig"] == code]

        def fmt(g):
            if g.empty: return f"{'—':>4}  {'—':>6}  {'—':>6}"
            wr  = g["win"].mean() * 100
            avg = g["ret"].mean()
            marker = "*" if wr > 55 else " "
            return f"{len(g):>4}  {wr:>5.1f}%{marker} {avg:>+5.2f}%"

        print(f"  {label:35} | {fmt(f)} | {fmt(a)}")

    print("=" * 78)

    # Итоговое сравнение по ключевым метрикам
    print("\n  ИТОГ — прирост от адаптивных порогов:")
    for code, label in [("A_os", "A LONG"), ("C_exos", "C LONG"), ("C_exob", "C SHORT")]:
        f = fixed[fixed["sig"] == code]
        a = adaptive[adaptive["sig"] == code]
        if f.empty or a.empty:
            continue
        dwr  = a["win"].mean()*100 - f["win"].mean()*100
        dn   = len(a) - len(f)
        print(f"    {label:12}: WR {dwr:+.1f}%  сигналов {dn:+d} ({len(f)} -> {len(a)})")
    print()


async def fetch_ohlcv(exchange, symbol: str, days: int) -> pd.DataFrame:
    """Загружает OHLCV с пагинацией."""
    import time
    ccxt_sym = symbol.replace("USDT", "/USDT")
    end_ms   = int(time.time() * 1000)
    since    = int((time.time() - days * 86400) * 1000)
    all_rows = []

    while since < end_ms:
        try:
            chunk = await exchange.fetch_ohlcv(ccxt_sym, "15m", since=since, limit=1500)
        except Exception:
            break
        if not chunk:
            break
        all_rows.extend(chunk)
        last = chunk[-1][0]
        if last <= since or len(chunk) < 1500:
            break
        since = last + 1
        await asyncio.sleep(0.15)

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows, columns=["time","open","high","low","close","volume"])
    df = df.drop_duplicates("time").sort_values("time").reset_index(drop=True)
    df = df.astype({"open": float, "high": float, "low": float, "close": float})
    return calculate_wt(df, n1=WT_N1, n2=WT_N2)


async def main(symbols: list, days: int):
    exchange = ccxt_async.bingx({
        "enableRateLimit": False,
        "options": {"defaultType": "swap"},
    })

    # Убираем дубли
    symbols = list(dict.fromkeys(symbols))

    print(f"\nWT дивергенции: FIXED ±60 vs ADAPTIVE p{ADAPTIVE_PCTILE}/p{100-ADAPTIVE_PCTILE}")
    print(f"{len(symbols)} пар | {days} дней | Lookback={LOOKBACK} | Forward={FORWARD_BARS} баров (5ч)")
    print("=" * 78)

    all_fixed    = []
    all_adaptive = []
    thresholds   = {}
    sem = asyncio.Semaphore(4)

    async def process(symbol):
        async with sem:
            try:
                df = await fetch_ohlcv(exchange, symbol, days)
                if df is None or len(df) < 200:
                    print(f"  SKP {symbol}: мало данных ({len(df) if df is not None else 0})")
                    return

                wt1 = df["wt1"].values

                # Fixed ±60
                res_fixed = scan_signals(df, symbol, -60.0, 60.0, "fixed")

                # Adaptive p10/p90
                os_a, ob_a = adaptive_thresholds(wt1)
                thresholds[symbol] = {"os": round(os_a, 1), "ob": round(ob_a, 1)}
                res_adap = scan_signals(df, symbol, os_a, ob_a, "adaptive")

                nf = len(res_fixed);  na = len(res_adap)
                print(f"  OK  {symbol:15} | {len(df):4} баров"
                      f" | OS={os_a:+.0f}/OB={ob_a:+.0f}"
                      f" | fixed={nf} adap={na}")

                if not res_fixed.empty:    all_fixed.append(res_fixed)
                if not res_adap.empty:     all_adaptive.append(res_adap)
            except Exception as e:
                print(f"  ERR {symbol}: {e}")

    await asyncio.gather(*[process(s) for s in symbols])
    await exchange.close()

    if not all_fixed:
        print("Нет данных.")
        return

    fixed    = pd.concat(all_fixed,    ignore_index=True)
    adaptive = pd.concat(all_adaptive, ignore_index=True)

    print_comparison(fixed, adaptive, thresholds)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--days",    type=int,  default=90)
    args = parser.parse_args()
    asyncio.run(main(args.symbols, args.days))
