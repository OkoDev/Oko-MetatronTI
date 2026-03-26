"""
Детальный анализ типа B: crossover В OS/OB зоне + дивергенция.

Проверяем гипотезы:
  1. Сила дивергенции важна: чем больше разрыв min1-min2, тем лучше?
  2. Глубина первого лоу важна: чем глубже — тем сильнее разворот?
  3. Gap WT1-WT2 при crossover?
  4. По каким парам тип B работает лучше всего?

Запуск:
    python scripts/analyze_wt_typeB.py
    python scripts/analyze_wt_typeB.py --days 90
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

WT_N1, WT_N2 = 10, 21
LOOKBACK     = 35
FORWARD_BARS = 20

DEFAULT_SYMBOLS = [
    # Крупные (низкая волатильность)
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT",
    "SOLUSDT", "DOTUSDT", "LINKUSDT", "AVAXUSDT", "TRXUSDT",
    "LTCUSDT", "MATICUSDT", "ATOMUSDT", "UNIUSDT", "AAVEUSDT",
    "TONUSDT", "ICPUSDT", "APTUSDT", "MKRUSDT", "LDOUSDT",
    # Средняя волатильность
    "XLMUSDT", "ETCUSDT", "ALGOUSDT", "VETUSDT", "1INCHUSDT",
    "DOGEUSDT", "SHIBUSDT", "FILUSDT", "SANDUSDT", "MANAUSDT",
    "GALAUSDT", "CHZUSDT", "ENJUSDT", "LRCUSDT", "ZILUSDT",
    "NEARUSDT", "FTMUSDT", "EGLDUSDT", "HBARUSDT", "FLOWUSDT",
    "RUNEUSDT", "KAVAUSDT", "CRVUSDT", "COMPUSDT", "SNXUSDT",
    "YFIUSDT", "BALUSDT", "SKLUSDT", "CELOUSDT", "STORJUSDT",
    # Высокая волатильность
    "APEUSDT", "GRTUSDT", "CFXUSDT", "SUIUSDT", "PEPEUSDT",
    "NOTUSDT", "MOVEUSDT", "SOLVUSDT", "BERAUSDT", "DYMUSDT",
    "WLDUSDT", "ARBUSDT", "OPUSDT", "INJUSDT", "STXUSDT",
    "TIAUSDT", "SEIUSDT", "PYTHUSDT", "JUPUSDT", "RENDERUSDT",
    "ZROUSDT", "ZKUSDT", "TAOUSDT", "FETUSDT", "AGIXUSDT",
    "AIUSDT", "TURBOUSDT", "BONKUSDT", "WIFUSDT", "FLOKIUSDT",
    # Очень высокая волатильность (мелкие альты)
    "COTIUSDT", "API3USDT", "CETUSUSDT", "ANIMEUSDT", "B3USDT",
    "SUNUSDT", "0GUSDT", "ONDOUSDT", "EIGENUSDT",
    "KAITOUSDT", "BOMEUSDT", "POPCATUSDT", "ACTUSDT",
    "PNUTUSDT", "GOATUSDT", "CHILLGUYUSDT", "VIRTUALUSDT", "SPXUSDT",
    "FARTCOINUSDT", "AI16ZUSDT", "LAUSDT", "TRUMPUSDT", "MELANIAUSDT",
]


def adaptive_thresholds(wt1: np.ndarray) -> tuple:
    return float(np.percentile(wt1, 10)), float(np.percentile(wt1, 90))


def check_divergence_detail(wt1_vals: list, os_: float) -> dict:
    """
    Проверяет bullish дивергенцию и возвращает детали.
    Returns: found, div_strength (min2 - min1), depth (min1), n_os_bars
    """
    half = len(wt1_vals) // 2
    if half < 5:
        return {"found": False}

    os1 = [v for v in wt1_vals[:half] if v < os_]
    os2 = [v for v in wt1_vals[half:] if v < os_]

    if not os1 or not os2:
        return {"found": False}

    min1 = min(os1)
    min2 = min(os2)

    if min2 <= min1:
        return {"found": False}

    return {
        "found":        True,
        "div_strength": round(min2 - min1, 2),   # насколько второй лоу выше первого
        "depth":        round(min1, 2),            # глубина первого лоу
        "n_os_bars":    len(os1) + len(os2),       # сколько баров в OS
    }


def check_bearish_div_detail(wt1_vals: list, ob: float) -> dict:
    """Bearish дивергенция с деталями."""
    half = len(wt1_vals) // 2
    if half < 5:
        return {"found": False}

    ob1 = [v for v in wt1_vals[:half] if v > ob]
    ob2 = [v for v in wt1_vals[half:] if v > ob]

    if not ob1 or not ob2:
        return {"found": False}

    max1 = max(ob1)
    max2 = max(ob2)

    if max2 >= max1:
        return {"found": False}

    return {
        "found":        True,
        "div_strength": round(max1 - max2, 2),
        "depth":        round(max1, 2),
        "n_ob_bars":    len(ob1) + len(ob2),
    }


LOOKBACK_4H = 15   # 15 баров × 4h = 60 часов для проверки 4h дивергенции


def check_cascade_4h(df_4h: pd.DataFrame, ts_ms: int, direction: str) -> bool:
    """
    Мягкая проверка: WT1 на 4h находится в OS/OB зоне в момент сигнала на 1h.
    OS/OB = adaptive p10/p90 от всей серии 4h.
    """
    if df_4h is None or df_4h.empty:
        return False
    idx_4h = int((df_4h["time"] - ts_ms).abs().idxmin())
    if idx_4h < 5:
        return False
    wt1_4h = df_4h["wt1"].values
    os_4h  = float(np.percentile(wt1_4h, 10))
    ob_4h  = float(np.percentile(wt1_4h, 90))
    wt1_now = wt1_4h[idx_4h]
    if direction == "LONG":
        return wt1_now < os_4h
    else:
        return wt1_now > ob_4h


def has_divergence_simple(wt1_vals: list, os_: float) -> bool:
    half = len(wt1_vals) // 2
    if half < 3:
        return False
    os1 = [v for v in wt1_vals[:half] if v < os_]
    os2 = [v for v in wt1_vals[half:] if v < os_]
    if not os1 or not os2:
        return False
    return min(os2) > min(os1)


def has_bearish_div_simple(wt1_vals: list, ob: float) -> bool:
    half = len(wt1_vals) // 2
    if half < 3:
        return False
    ob1 = [v for v in wt1_vals[:half] if v > ob]
    ob2 = [v for v in wt1_vals[half:] if v > ob]
    if not ob1 or not ob2:
        return False
    return max(ob2) < max(ob1)


def scan_typeB(df: pd.DataFrame, symbol: str,
               os_: float, ob: float,
               df_4h: pd.DataFrame = None) -> pd.DataFrame:
    """Сканирует только тип B — crossover В зоне + дивергенция."""
    wt1    = df["wt1"].values
    wt2    = df["wt2"].values
    closes = df["close"].values
    times  = df["time"].values
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

        window = list(wt1[i - LOOKBACK: i])
        gap    = round(abs(wt1[i] - wt2[i]), 2)
        ts_ms  = int(times[i])

        if cross_up and wt1[i] < os_:
            d = check_divergence_detail(window, os_)
            if not d["found"]:
                continue
            ret     = (future[-1] - entry) / entry * 100
            max_ret = (max(future) - entry) / entry * 100
            cascade = check_cascade_4h(df_4h, ts_ms, "LONG")
            records.append({
                "symbol":       symbol,
                "direction":    "LONG",
                "wt1":          round(wt1[i], 2),
                "gap":          gap,
                "div_strength": d["div_strength"],
                "depth":        d["depth"],
                "n_os_bars":    d.get("n_os_bars", 0),
                "cascade_4h":   cascade,
                "ret":          round(ret, 3),
                "max_ret":      round(max_ret, 3),
                "win":          ret > 0,
            })

        if cross_down and wt1[i] > ob:
            d = check_bearish_div_detail(window, ob)
            if not d["found"]:
                continue
            ret     = (entry - future[-1]) / entry * 100
            max_ret = (entry - min(future)) / entry * 100
            cascade = check_cascade_4h(df_4h, ts_ms, "SHORT")
            records.append({
                "symbol":       symbol,
                "direction":    "SHORT",
                "wt1":          round(wt1[i], 2),
                "gap":          gap,
                "div_strength": d["div_strength"],
                "depth":        d["depth"],
                "n_ob_bars":    d.get("n_ob_bars", 0),
                "cascade_4h":   cascade,
                "ret":          round(ret, 3),
                "max_ret":      round(max_ret, 3),
                "win":          ret > 0,
            })

    return pd.DataFrame(records)


def print_results(df: pd.DataFrame, div_max: float = 999, div_min: float = 0) -> None:
    if df.empty:
        print("Нет сигналов типа B.")
        return

    if div_max < 999 or div_min > 0:
        before = len(df)
        df = df[(df["div_strength"] >= div_min) & (df["div_strength"] <= div_max)].copy()
        print(f"\n  Фильтр div_strength {div_min}-{div_max}: {before} -> {len(df)} сигналов")

    total_wr  = df["win"].mean() * 100
    total_avg = df["ret"].mean()
    print(f"\n  Тип B всего: n={len(df)}  WR={total_wr:.1f}%  avgRet={total_avg:+.2f}%")

    for direction in ["LONG", "SHORT"]:
        d = df[df["direction"] == direction]
        if d.empty:
            continue
        wr  = d["win"].mean() * 100
        avg = d["ret"].mean()
        print(f"  {direction}: n={len(d)}  WR={wr:.1f}%  avgRet={avg:+.2f}%")

    # ── Сила дивергенции (div_strength = min2 - min1) ─────────────────────────
    print("\n" + "=" * 65)
    print("  Сила дивергенции (разрыв между лоу)")
    print(f"  {'Диапазон':15} | {'n':>4} | {'WR%':>6} | {'avgRet%':>8}")
    print("-" * 65)
    bins = [(0, 3), (3, 6), (6, 10), (10, 20), (20, 999)]
    for lo, hi in bins:
        g = df[(df["div_strength"] >= lo) & (df["div_strength"] < hi)]
        if g.empty:
            continue
        label = f"{lo}-{hi if hi < 999 else '999+'}"
        wr  = g["win"].mean() * 100
        avg = g["ret"].mean()
        marker = " **" if wr > 55 else ""
        print(f"  {label:15} | {len(g):>4d} | {wr:>5.1f}% | {avg:>+7.2f}%{marker}")

    # ── Глубина первого лоу ────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("  Глубина первого лоу (depth)")
    print(f"  {'Диапазон':15} | {'n':>4} | {'WR%':>6} | {'avgRet%':>8}")
    print("-" * 65)
    depth_bins = [(-999, -80), (-80, -70), (-70, -65), (-65, -60), (-60, 0)]
    for lo, hi in depth_bins:
        g = df[(df["depth"] >= lo) & (df["depth"] < hi) & (df["direction"] == "LONG")]
        if g.empty:
            continue
        label = f"{lo if lo > -999 else '-999+'}..{hi}"
        wr  = g["win"].mean() * 100
        avg = g["ret"].mean()
        marker = " **" if wr > 55 else ""
        print(f"  {label:15} | {len(g):>4d} | {wr:>5.1f}% | {avg:>+7.2f}%{marker}")

    # ── Gap при crossover ──────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("  Gap WT1-WT2 при crossover")
    print(f"  {'Диапазон':15} | {'n':>4} | {'WR%':>6} | {'avgRet%':>8}")
    print("-" * 65)
    gap_bins = [(0, 3), (3, 6), (6, 10), (10, 999)]
    for lo, hi in gap_bins:
        g = df[(df["gap"] >= lo) & (df["gap"] < hi)]
        if g.empty:
            continue
        label = f"gap {lo}-{hi if hi < 999 else '999+'}"
        wr  = g["win"].mean() * 100
        avg = g["ret"].mean()
        marker = " **" if wr > 55 else ""
        print(f"  {label:15} | {len(g):>4d} | {wr:>5.1f}% | {avg:>+7.2f}%{marker}")

    # ── Каскад 4h ──────────────────────────────────────────────────────────────
    if "cascade_4h" in df.columns:
        print("\n" + "=" * 65)
        print("  Каскадная дивергенция 4h")
        print(f"  {'Группа':20} | {'n':>4} | {'WR%':>6} | {'avgRet%':>8}")
        print("-" * 65)
        c  = df[df["cascade_4h"] == True]
        nc = df[df["cascade_4h"] == False]
        for label, g in [("B + 4h дивергенция", c), ("B только 1h", nc)]:
            if g.empty:
                continue
            wr  = g["win"].mean() * 100
            avg = g["ret"].mean()
            marker = " **" if wr > 70 else ""
            print(f"  {label:20} | {len(g):>4d} | {wr:>5.1f}% | {avg:>+7.2f}%{marker}")

    # ── По парам ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("  По парам (топ и аутсайдеры)")
    by_sym = []
    for sym, g in df.groupby("symbol"):
        if len(g) < 2:
            continue
        by_sym.append((g["win"].mean()*100, sym, len(g), g["ret"].mean()))
    by_sym.sort(reverse=True)

    print(f"  {'Пара':15} | {'n':>4} | {'WR%':>6} | {'avgRet%':>8}")
    print("-" * 65)
    for wr, sym, n, avg in by_sym:
        marker = " **" if wr >= 60 else (" xx" if wr < 35 else "")
        print(f"  {sym:15} | {n:>4d} | {wr:>5.1f}% | {avg:>+7.2f}%{marker}")
    print()


async def fetch_ohlcv(exchange, symbol: str, days: int, tf: str = "1h") -> pd.DataFrame:
    import time
    ccxt_sym = symbol.replace("USDT", "/USDT")
    since    = int((time.time() - days * 86400) * 1000)
    end_ms   = int(time.time() * 1000)
    rows     = []
    while since < end_ms:
        try:
            chunk = await exchange.fetch_ohlcv(ccxt_sym, tf, since=since, limit=1500)
        except Exception:
            break
        if not chunk: break
        rows.extend(chunk)
        last = chunk[-1][0]
        if last <= since or len(chunk) < 1500: break
        since = last + 1
        await asyncio.sleep(0.15)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["time","open","high","low","close","volume"])
    df = df.drop_duplicates("time").sort_values("time").reset_index(drop=True)
    df = df.astype({"open": float, "high": float, "low": float, "close": float})
    return calculate_wt(df, n1=WT_N1, n2=WT_N2)


async def main(symbols: list, days: int, tf: str):
    exchange = ccxt_async.bingx({
        "enableRateLimit": False,
        "options": {"defaultType": "swap"},
    })
    symbols = list(dict.fromkeys(symbols))

    # FORWARD_BARS в часах / минутах зависит от TF
    tf_label = {"15m": "5ч", "1h": "20ч", "4h": "80ч"}.get(tf, tf)
    print(f"\nТип B детальный анализ | {len(symbols)} пар | {days} дней | TF={tf} | Forward={FORWARD_BARS} баров ({tf_label})")
    print("=" * 65)

    all_results = []
    sem = asyncio.Semaphore(4)

    async def process(symbol):
        async with sem:
            try:
                df_1h, df_4h = await asyncio.gather(
                    fetch_ohlcv(exchange, symbol, days, tf),
                    fetch_ohlcv(exchange, symbol, days, "4h"),
                )
                if df_1h is None or len(df_1h) < 200:
                    print(f"  SKP {symbol}")
                    return
                os_, ob = adaptive_thresholds(df_1h["wt1"].values)
                res = scan_typeB(df_1h, symbol, os_, ob, df_4h=df_4h)
                n = len(res)
                n4h = res["cascade_4h"].sum() if not res.empty else 0
                print(f"  OK  {symbol:15} | {len(df_1h):4} баров | OS={os_:+.0f}/OB={ob:+.0f} | B={n} (4h={n4h})")
                if not res.empty:
                    all_results.append(res)
            except Exception as e:
                print(f"  ERR {symbol}: {e}")

    await asyncio.gather(*[process(s) for s in symbols])
    await exchange.close()

    if not all_results:
        print("Нет сигналов.")
        return

    df = pd.concat(all_results, ignore_index=True)
    print_results(df, div_max=args.div_max, div_min=args.div_min)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--days",    type=int,  default=90)
    parser.add_argument("--tf",      type=str,  default="1h",
                        help="Таймфрейм: 15m, 1h, 4h")
    parser.add_argument("--div-max", type=float, default=999,
                        help="Фильтр: max div_strength (напр. 20)")
    parser.add_argument("--div-min", type=float, default=0,
                        help="Фильтр: min div_strength (напр. 3)")
    args = parser.parse_args()
    asyncio.run(main(args.symbols, args.days, args.tf))
