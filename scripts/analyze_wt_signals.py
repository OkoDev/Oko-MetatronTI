"""
Анализ трёх гипотез улучшения WT сигналов на реальных данных из БД.

Гипотеза 1: Нулевая линия как bias
  - wt1_1h > 0 = лонг-зона, < 0 = шорт-зона на 1h
  - Вопрос: LONG-сигналы при wt1_1h > 0 выигрывают чаще?

Гипотеза 2: WT1-WT2 разрыв как сила сигнала
  - gap = |wt1 - wt2| при crossover
  - Вопрос: большой gap коррелирует с лучшим R_multiple?

Гипотеза 3: WT дивергенции
  - Цена делает новый экстремум, WT1 — нет
  - Вопрос: дивергенция перед crossover улучшает win rate?

Запуск:
    python scripts/analyze_wt_signals.py
    python scripts/analyze_wt_signals.py --days 30 --top 10
"""
import asyncio
import sys
import os
import argparse
import sqlite3
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import ccxt.async_support as ccxt_async

from core.indicators import calculate_wt


# ─── Параметры ────────────────────────────────────────────────────────────────
WT_N1, WT_N2 = 10, 21
DIV_LOOKBACK = 40   # баров назад для поиска дивергенции


def load_trades(days: int) -> pd.DataFrame:
    """Загружает закрытые wt_signal сделки из БД."""
    conn = sqlite3.connect("subscriptions.db")
    query = """
        SELECT symbol, direction, status, R_multiple, created_at, entry_price
        FROM simulated_trades
        WHERE signal_type = 'wt_signal'
          AND status != 'OPEN'
          AND R_multiple IS NOT NULL
          AND created_at >= datetime('now', ?)
        ORDER BY created_at
    """
    df = pd.read_sql_query(query, conn, params=(f"-{days} days",))
    conn.close()
    df["win"] = df["R_multiple"] > 0
    return df


async def fetch_ohlcv_cached(exchange, symbol: str, timeframe: str,
                              cache: dict, days: int = 20) -> pd.DataFrame:
    """Загружает OHLCV с кешированием по (symbol, timeframe)."""
    key = (symbol, timeframe)
    if key in cache:
        return cache[key]
    import time
    since = int((time.time() - days * 86400) * 1000)
    limit = min(days * 96 + 100, 1500)
    try:
        ccxt_sym = symbol.replace("USDT", "/USDT")
        ohlcv = await exchange.fetch_ohlcv(ccxt_sym, timeframe, since=since, limit=limit)
        if not ohlcv:
            cache[key] = pd.DataFrame()
            return cache[key]
        df = pd.DataFrame(ohlcv, columns=["time", "open", "high", "low", "close", "volume"])
        df = df.astype({"open": float, "high": float, "low": float, "close": float})
        # Добавляем WT заранее
        df = calculate_wt(df, n1=WT_N1, n2=WT_N2)
        cache[key] = df
        return df
    except Exception as e:
        print(f"  ERR fetch {symbol} {timeframe}: {e}")
        cache[key] = pd.DataFrame()
        return cache[key]


def find_bar_idx(df: pd.DataFrame, created_at_str: str) -> int:
    """Находит индекс бара ближайшего к времени сделки."""
    try:
        # Парсим время сделки
        ts_str = created_at_str.replace("+00:00", "").replace("Z", "")
        ts = pd.Timestamp(ts_str, tz="UTC")
        ts_ms = int(ts.timestamp() * 1000)
        # Ищем ближайший бар (time = открытие бара)
        idx = (df["time"] - ts_ms).abs().idxmin()
        return int(idx)
    except Exception:
        return -1


def detect_wt_divergence(df_wt: pd.DataFrame, idx: int, direction: str,
                          lookback: int = DIV_LOOKBACK) -> bool:
    """
    Проверяет наличие дивергенции WT перед сигналом.

    Bullish (LONG): цена делает новый лоу, WT1 — нет (higher low).
    Bearish (SHORT): цена делает новый хай, WT1 — нет (lower high).
    """
    start = max(0, idx - lookback)
    window = df_wt.iloc[start:idx + 1]
    if len(window) < 10:
        return False

    prices = window["close"].values
    wt1 = window["wt1"].values

    if direction == "LONG":
        # Цена на новом минимуме, WT1 выше предыдущего минимума
        price_min_last = prices[-5:].min()
        price_min_prev = prices[:-5].min() if len(prices) > 5 else price_min_last
        wt1_min_last = wt1[-5:].min()
        wt1_min_prev = wt1[:-5].min() if len(wt1) > 5 else wt1_min_last
        return price_min_last < price_min_prev and wt1_min_last > wt1_min_prev
    else:  # SHORT
        price_max_last = prices[-5:].max()
        price_max_prev = prices[:-5].max() if len(prices) > 5 else price_max_last
        wt1_max_last = wt1[-5:].max()
        wt1_max_prev = wt1[:-5].max() if len(wt1) > 5 else wt1_max_last
        return price_max_last > price_max_prev and wt1_max_last < wt1_max_prev


def analyze_all(trades: pd.DataFrame, ohlcv_cache: dict) -> None:
    """Анализирует все три гипотезы и выводит результаты."""

    # ── Собираем данные по каждой сделке ──────────────────────────────────────
    records = []
    skipped = 0

    for _, trade in trades.iterrows():
        sym = trade["symbol"].replace("/", "").replace(":USDT", "")
        df_15m = ohlcv_cache.get((sym, "15m"), pd.DataFrame())
        df_1h  = ohlcv_cache.get((sym, "1h"),  pd.DataFrame())

        if df_15m.empty or "wt1" not in df_15m.columns:
            skipped += 1
            continue

        idx = find_bar_idx(df_15m, trade["created_at"])
        if idx < 50 or idx >= len(df_15m) - 1:
            skipped += 1
            continue

        wt1_15m = float(df_15m["wt1"].iloc[idx])
        wt2_15m = float(df_15m["wt2"].iloc[idx])
        gap     = abs(wt1_15m - wt2_15m)

        # WT на 1h в момент сделки
        wt1_1h = None
        if not df_1h.empty and "wt1" in df_1h.columns:
            idx_1h = find_bar_idx(df_1h, trade["created_at"])
            if 10 <= idx_1h < len(df_1h):
                wt1_1h = float(df_1h["wt1"].iloc[idx_1h])

        # Дивергенция
        has_div = detect_wt_divergence(df_15m, idx, trade["direction"])

        records.append({
            "direction": trade["direction"],
            "win": trade["win"],
            "R": trade["R_multiple"],
            "wt1_15m": wt1_15m,
            "wt2_15m": wt2_15m,
            "gap": gap,
            "wt1_1h": wt1_1h,
            "wt1_1h_sign": ("LONG" if wt1_1h > 0 else "SHORT") if wt1_1h is not None else None,
            "has_div": has_div,
        })

    df = pd.DataFrame(records)
    n_total = len(df)
    print(f"\nОбработано сделок: {n_total} | Пропущено: {skipped}")

    if n_total < 10:
        print("Мало данных для анализа.")
        return

    # ══ ГИПОТЕЗА 1: Нулевая линия (1h WT bias) ════════════════════════════════
    print("\n" + "=" * 70)
    print("ГИПОТЕЗА 1: Нулевая линия (wt1_1h > 0 = лонг-зона, < 0 = шорт-зона)")
    print("=" * 70)
    df_with_1h = df[df["wt1_1h"].notna()]
    print(f"  Сделок с данными 1h: {len(df_with_1h)}")

    for direction in ["LONG", "SHORT"]:
        d = df_with_1h[df_with_1h["direction"] == direction]
        if d.empty:
            continue
        with_bias    = d[d["wt1_1h_sign"] == direction]   # bias совпадает
        against_bias = d[d["wt1_1h_sign"] != direction]   # bias против

        def wr(sub): return sub["win"].mean() * 100 if len(sub) > 0 else 0
        def avg_r(sub): return sub["R"].mean() if len(sub) > 0 else 0

        print(f"\n  {direction}:")
        print(f"    Bias совпадает ({direction} bias):  n={len(with_bias):3d}  WR={wr(with_bias):5.1f}%  avgR={avg_r(with_bias):+.3f}")
        print(f"    Bias против   ({'SHORT' if direction=='LONG' else 'LONG'} bias): n={len(against_bias):3d}  WR={wr(against_bias):5.1f}%  avgR={avg_r(against_bias):+.3f}")

        if len(with_bias) > 5 and len(against_bias) > 5:
            diff_wr = wr(with_bias) - wr(against_bias)
            diff_r  = avg_r(with_bias) - avg_r(against_bias)
            verdict = "ПОДТВЕРЖДЕНА" if diff_wr > 3 else ("СЛАБО" if diff_wr > 0 else "ОПРОВЕРГНУТА")
            print(f"    Разница: WR {diff_wr:+.1f}%  avgR {diff_r:+.3f}  -> {verdict}")

    # ══ ГИПОТЕЗА 2: WT1-WT2 разрыв (gap) ═════════════════════════════════════
    print("\n" + "=" * 70)
    print("ГИПОТЕЗА 2: WT1-WT2 разрыв при crossover -> сила сигнала")
    print("=" * 70)

    # Разбиваем на квартили по gap
    df["gap_q"] = pd.qcut(df["gap"], q=4, labels=["Q1\n(мал)", "Q2", "Q3", "Q4\n(бол)"])
    print(f"\n  {'Квартиль':12} | {'n':>4} | {'WR%':>6} | {'avgR':>7} | {'gap диапазон'}")
    print(f"  {'-'*55}")
    for q_label, group in df.groupby("gap_q", observed=True):
        gap_min = group["gap"].min()
        gap_max = group["gap"].max()
        label = str(q_label).replace("\n", " ")
        print(f"  {label:12} | {len(group):>4d} | {group['win'].mean()*100:>5.1f}% | {group['R'].mean():>+6.3f} | {gap_min:.1f} - {gap_max:.1f}")

    corr = df["gap"].corr(df["R"])
    print(f"\n  Корреляция gap <-> R_multiple: r = {corr:+.3f}")
    verdict2 = "ПОДТВЕРЖДЕНА" if corr > 0.05 else ("СЛАБО" if corr > 0 else "ОПРОВЕРГНУТА")
    print(f"  -> {verdict2}")

    # ══ ГИПОТЕЗА 3: WT дивергенции ════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("ГИПОТЕЗА 3: WT дивергенция перед сигналом")
    print("=" * 70)

    with_div    = df[df["has_div"] == True]
    without_div = df[df["has_div"] == False]

    def wr(sub): return sub["win"].mean() * 100 if len(sub) > 0 else 0
    def avg_r(sub): return sub["R"].mean() if len(sub) > 0 else 0

    print(f"\n  С дивергенцией:    n={len(with_div):3d}  WR={wr(with_div):5.1f}%  avgR={avg_r(with_div):+.3f}")
    print(f"  Без дивергенции:   n={len(without_div):3d}  WR={wr(without_div):5.1f}%  avgR={avg_r(without_div):+.3f}")

    if len(with_div) > 5 and len(without_div) > 5:
        diff_wr = wr(with_div) - wr(without_div)
        diff_r  = avg_r(with_div) - avg_r(without_div)
        verdict3 = "ПОДТВЕРЖДЕНА" if diff_wr > 3 else ("СЛАБО" if diff_wr > 0 else "ОПРОВЕРГНУТА")
        print(f"  Разница: WR {diff_wr:+.1f}%  avgR {diff_r:+.3f}  -> {verdict3}")

    # Детально по direction
    print(f"\n  По направлению:")
    for direction in ["LONG", "SHORT"]:
        d = df[df["direction"] == direction]
        wd = d[d["has_div"] == True]
        wod = d[d["has_div"] == False]
        print(f"    {direction}: с див n={len(wd)} WR={wr(wd):.1f}%  без див n={len(wod)} WR={wr(wod):.1f}%")

    # ══ ИТОГ ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("ИТОГ")
    print("=" * 70)
    print("  Базовый win rate wt_signal:", f"{df['win'].mean()*100:.1f}%  (n={len(df)})")
    print()


async def main(days: int, top: int):
    trades = load_trades(days)
    if trades.empty:
        print("Нет данных в БД.")
        return

    symbols = trades["symbol"].str.replace("/", "").str.replace(":USDT", "").unique().tolist()
    print(f"Загружаем OHLCV для {len(symbols)} символов ({days} дней)...")

    exchange = ccxt_async.bingx({
        "enableRateLimit": False,
        "options": {"defaultType": "swap"},
    })

    cache = {}
    sem = asyncio.Semaphore(5)

    async def fetch_both(sym):
        async with sem:
            await fetch_ohlcv_cached(exchange, sym, "15m", cache, days)
            await fetch_ohlcv_cached(exchange, sym, "1h",  cache, days)

    await asyncio.gather(*[fetch_both(s) for s in symbols])
    await exchange.close()

    loaded = sum(1 for k, v in cache.items() if not v.empty and k[1] == "15m")
    print(f"Загружено: {loaded}/{len(symbols)} символов")

    analyze_all(trades, cache)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=15)
    parser.add_argument("--top",  type=int, default=20)
    args = parser.parse_args()
    asyncio.run(main(args.days, args.top))
