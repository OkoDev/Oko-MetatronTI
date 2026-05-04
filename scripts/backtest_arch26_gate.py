"""
ARCH-26 Backtest: сравнение WR с gate по 4h WT momentum и без него.

Воспроизводит логику wt_15m_reversal_scanner.py на исторических данных.

Gates (как в сканере):
  LONG  = wt_was_in_os + wt_cross_UP  + tsl_cross_UP
  SHORT = wt_was_in_ob + wt_cross_DOWN + tsl_cross_DOWN

ARCH-26 gate:
  LONG  блокируется если 4h wt1 < wt2 (медвежий momentum)
  SHORT блокируется если 4h wt1 > wt2 (бычий momentum)

Win = цена через FORWARD_BARS баров лучше entry по направлению сделки.

Запуск:
    python scripts/backtest_arch26_gate.py
    python scripts/backtest_arch26_gate.py --days 60 --symbols BTCUSDT ETHUSDT SOLUSDT
"""
import asyncio
import sys
import os
import argparse
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import ccxt.async_support as ccxt_async

from core.indicators.indicators import calculate_wt, calculate_trend

# ── Параметры (зеркало сканера) ───────────────────────────────────────────────
WT_N1, WT_N2     = 10, 21
WT_OS_THR        = -60.0
WT_OB_THR        =  60.0
LOOKBACK_BARS    = 35         # окно поиска OS/OB и кросса
FORWARD_BARS     = 20         # 20 баров × 15m = 5 часов
ATR_PERIOD       = 43
ATR_FACTOR       = 1.25       # как в config.yaml

DEFAULT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOTUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT",
    "ATOMUSDT", "UNIUSDT", "NEARUSDT", "INJUSDT", "ARBUSDT",
    "OPUSDT", "APTUSDT", "SUIUSDT", "PEPEUSDT", "DOGEUSDT",
]


async def fetch_ohlcv(exchange, symbol: str, days: int, tf: str) -> pd.DataFrame:
    ccxt_sym = symbol.replace("USDT", "/USDT")
    since    = int((time.time() - days * 86400) * 1000)
    end_ms   = int(time.time() * 1000)
    rows = []
    while since < end_ms:
        try:
            chunk = await exchange.fetch_ohlcv(ccxt_sym, tf, since=since, limit=1500)
        except Exception:
            break
        if not chunk:
            break
        rows.extend(chunk)
        last = chunk[-1][0]
        if last <= since or len(chunk) < 1500:
            break
        since = last + 1
        await asyncio.sleep(0.1)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates("time").sort_values("time").reset_index(drop=True)
    df = df.astype({c: float for c in ["open", "high", "low", "close"]})
    return df


def scan_signals(df15: pd.DataFrame, df4h: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """
    Сканирует 15m данные на сигналы reversal_scanner.
    Для каждого сигнала проверяет WR с gate и без gate (4h WT momentum).
    """
    # ── Индикаторы 15m ────────────────────────────────────────────────────────
    df15 = calculate_wt(df15, WT_N1, WT_N2)
    df15 = calculate_trend(df15, atr_period=ATR_PERIOD, factor=ATR_FACTOR)

    wt1    = df15["wt1"].values
    wt2    = df15["wt2"].values
    closes = df15["close"].values
    times  = df15["time"].values

    # TSL линии из calculate_trend
    trendup   = df15["trendup"].values   if "trendup"   in df15.columns else None
    trenddown = df15["trenddown"].values if "trenddown" in df15.columns else None

    # ── Индикаторы 4h ─────────────────────────────────────────────────────────
    df4h_wt = None
    if df4h is not None and len(df4h) >= 20:
        df4h_wt = calculate_wt(df4h, WT_N1, WT_N2)

    def get_4h_dir(ts_ms: int):
        """Возвращает '4h_dir' = UP/DOWN по wt1 vs wt2 на 4h в момент ts_ms."""
        if df4h_wt is None:
            return None
        # Ищем ближайший 4h бар, НЕ позже ts_ms (только прошлые данные)
        mask = df4h_wt["time"].values <= ts_ms
        if not mask.any():
            return None
        idx = int(np.where(mask)[0][-1])
        if idx < 1:
            return None
        _w1 = float(df4h_wt["wt1"].iloc[idx])
        _w2 = float(df4h_wt["wt2"].iloc[idx])
        return "UP" if _w1 > _w2 else "DOWN"

    records = []

    for i in range(LOOKBACK_BARS + 2, len(df15) - FORWARD_BARS):
        # ── Lookback окно ─────────────────────────────────────────────────────
        window_wt = wt1[i - LOOKBACK_BARS: i]

        wt_was_in_os = any(v < WT_OS_THR for v in window_wt)
        wt_was_in_ob = any(v > WT_OB_THR for v in window_wt)

        # ── Последний WT кросс в окне ─────────────────────────────────────────
        last_wt_cross = None
        for j in range(i - 1, i - LOOKBACK_BARS, -1):
            if j < 1:
                break
            if wt1[j-1] <= wt2[j-1] and wt1[j] > wt2[j]:
                last_wt_cross = "UP"
                break
            if wt1[j-1] >= wt2[j-1] and wt1[j] < wt2[j]:
                last_wt_cross = "DOWN"
                break

        # ── Последний TSL кросс в окне ────────────────────────────────────────
        last_tsl_cross = None
        if trendup is not None and trenddown is not None:
            for j in range(i - 1, i - LOOKBACK_BARS, -1):
                if j < 1:
                    break
                mid_cur  = (closes[j]   + closes[j-1])   / 2
                mid_prev = (closes[j-1] + closes[max(0, j-2)]) / 2
                if mid_prev <= trenddown[j-1] and mid_cur > trenddown[j]:
                    last_tsl_cross = "UP"
                    break
                if mid_prev >= trendup[j-1] and mid_cur < trendup[j]:
                    last_tsl_cross = "DOWN"
                    break
        else:
            # fallback: тренд по EMA20
            ema20 = pd.Series(closes[:i]).ewm(span=20, adjust=False).mean().values
            if closes[i-1] > ema20[i-1]:
                last_tsl_cross = "UP"
            elif closes[i-1] < ema20[i-1]:
                last_tsl_cross = "DOWN"

        entry    = closes[i]
        future   = closes[i+1: i+FORWARD_BARS+1]
        ts_ms    = int(times[i])
        dir_4h   = get_4h_dir(ts_ms)

        # ── LONG сетап ────────────────────────────────────────────────────────
        if wt_was_in_os and last_wt_cross == "UP" and last_tsl_cross == "UP":
            win = future[-1] > entry if len(future) == FORWARD_BARS else None
            if win is not None:
                gate_blocked = (dir_4h == "DOWN")
                records.append({
                    "symbol":       symbol,
                    "direction":    "LONG",
                    "ts":           ts_ms,
                    "entry":        round(entry, 6),
                    "ret_pct":      round((future[-1] - entry) / entry * 100, 3),
                    "win":          win,
                    "dir_4h":       dir_4h,
                    "gate_blocked": gate_blocked,
                })

        # ── SHORT сетап ───────────────────────────────────────────────────────
        if wt_was_in_ob and last_wt_cross == "DOWN" and last_tsl_cross == "DOWN":
            win = future[-1] < entry if len(future) == FORWARD_BARS else None
            if win is not None:
                gate_blocked = (dir_4h == "UP")
                records.append({
                    "symbol":       symbol,
                    "direction":    "SHORT",
                    "ts":           ts_ms,
                    "entry":        round(entry, 6),
                    "ret_pct":      round((entry - future[-1]) / entry * 100, 3),
                    "win":          win,
                    "dir_4h":       dir_4h,
                    "gate_blocked": gate_blocked,
                })

    return pd.DataFrame(records)


def print_report(df: pd.DataFrame, days: int, symbols: list):
    if df.empty:
        print("Нет сигналов.")
        return

    # ── Без gate ─────────────────────────────────────────────────────────────
    total = df
    n_total = len(total)
    wr_total = total["win"].mean() * 100
    avg_ret  = total["ret_pct"].mean()

    # ── С gate ───────────────────────────────────────────────────────────────
    gated = df[~df["gate_blocked"]]
    n_gated = len(gated)
    wr_gated = gated["win"].mean() * 100 if n_gated > 0 else 0.0
    avg_ret_gated = gated["ret_pct"].mean() if n_gated > 0 else 0.0

    # ── Заблокированные ──────────────────────────────────────────────────────
    blocked = df[df["gate_blocked"]]
    n_blocked = len(blocked)
    wr_blocked = blocked["win"].mean() * 100 if n_blocked > 0 else 0.0

    pct_filtered = n_blocked / n_total * 100 if n_total > 0 else 0

    print(f"\n{'='*65}")
    print(f"  ARCH-26 Backtest: gate по 4h WT momentum")
    print(f"  Символы: {', '.join(symbols)} | Период: {days} дней | TF: 15m")
    print(f"  Forward: {FORWARD_BARS} barov * 15m = {FORWARD_BARS//4}h")
    print(f"{'='*65}")
    print()
    print(f"  {'Группа':<28} | {'n':>5} | {'WR%':>7} | {'avgRet%':>8}")
    print(f"  {'-'*60}")

    def row(label, n, wr, avg, mark=""):
        print(f"  {label:<28} | {n:>5} | {wr:>6.1f}% | {avg:>+7.2f}%  {mark}")

    row("БЕЗ gate (все сигналы)",         n_total,   wr_total,   avg_ret)
    row(f"С gate (-{pct_filtered:.0f}% сигналов)",  n_gated,   wr_gated,  avg_ret_gated,
        mark="✓" if wr_gated > wr_total else "")
    row("Заблокированные gate",           n_blocked, wr_blocked, wr_blocked - 50.0)

    wr_delta = wr_gated - wr_total
    print(f"\n  Прирост WR от gate: {wr_delta:+.1f}%  (сигналов осталось: {n_gated}/{n_total})")

    # ── По направлениям ──────────────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"  По направлениям:")
    print(f"  {'Группа':<28} | {'n':>5} | {'WR%':>7} | {'avgRet%':>8}")
    print(f"  {'-'*60}")
    for direction in ["LONG", "SHORT"]:
        d_all   = df[df["direction"] == direction]
        d_gated = gated[gated["direction"] == direction]
        if d_all.empty:
            continue
        wr_a = d_all["win"].mean() * 100
        wr_g = d_gated["win"].mean() * 100 if not d_gated.empty else 0.0
        avg_a = d_all["ret_pct"].mean()
        avg_g = d_gated["ret_pct"].mean() if not d_gated.empty else 0.0
        print(f"  {direction} без gate             | {len(d_all):>5} | {wr_a:>6.1f}% | {avg_a:>+7.2f}%")
        mark = "✓" if wr_g > wr_a else ""
        print(f"  {direction} с gate               | {len(d_gated):>5} | {wr_g:>6.1f}% | {avg_g:>+7.2f}%  {mark}")

    # ── По парам (топ-10) ─────────────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"  По парам (сравнение WR):")
    print(f"  {'Пара':<14} | {'Без gate':>9} | {'С gate':>8} | {'Δ WR':>7} | {'n→m':>7}")
    print(f"  {'-'*60}")
    by_sym = []
    for sym, g_sym in df.groupby("symbol"):
        gated_sym = g_sym[~g_sym["gate_blocked"]]
        n_all = len(g_sym)
        n_g   = len(gated_sym)
        if n_all < 3:
            continue
        wr_a = g_sym["win"].mean() * 100
        wr_g = gated_sym["win"].mean() * 100 if n_g > 0 else 0.0
        by_sym.append((wr_g - wr_a, sym, n_all, n_g, wr_a, wr_g))
    by_sym.sort(reverse=True)
    for delta, sym, n_a, n_g, wr_a, wr_g in by_sym:
        mark = " ✓" if delta > 3 else (" ✗" if delta < -3 else "")
        print(f"  {sym:<14} | {wr_a:>7.1f}%  | {wr_g:>6.1f}% | {delta:>+5.1f}%  | {n_a}→{n_g}{mark}")

    # ── Итоговый вывод ────────────────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"  ИТОГ:")
    if wr_delta >= 5:
        verdict = "GATE ПОМОГАЕТ значительно (+{:.1f}% WR)".format(wr_delta)
    elif wr_delta >= 2:
        verdict = "GATE ПОМОГАЕТ умеренно (+{:.1f}% WR)".format(wr_delta)
    elif wr_delta >= 0:
        verdict = "GATE нейтрален ({:.1f}% WR)".format(wr_delta)
    else:
        verdict = "GATE УХУДШАЕТ ({:.1f}% WR) — рассмотреть отключение".format(wr_delta)

    print(f"  {verdict}")
    if n_gated < 30:
        print(f"  ⚠️  Мало сигналов с gate (n={n_gated}) — статистика ненадёжна!")
    print()


async def main(symbols: list, days: int):
    exchange = ccxt_async.bingx({
        "enableRateLimit": False,
        "options": {"defaultType": "swap"},
    })

    print(f"\nARCH-26 Gate Backtest | {len(symbols)} пар | {days} дней | 15m+4h")
    print("Загрузка данных...")

    all_results = []
    sem = asyncio.Semaphore(5)

    async def process(symbol):
        async with sem:
            try:
                df15, df4h = await asyncio.gather(
                    fetch_ohlcv(exchange, symbol, days, "15m"),
                    fetch_ohlcv(exchange, symbol, days, "4h"),
                )
                if df15 is None or len(df15) < 200:
                    print(f"  SKP {symbol} — мало данных")
                    return
                res = scan_signals(df15, df4h, symbol)
                n_total   = len(res)
                n_blocked = res["gate_blocked"].sum() if not res.empty else 0
                n_gated   = n_total - n_blocked
                wr_all    = res["win"].mean() * 100 if not res.empty else 0.0
                wr_gated  = res[~res["gate_blocked"]]["win"].mean() * 100 if n_gated > 0 else 0.0
                print(f"  OK  {symbol:<12} | {len(df15):4} баров 15m | сигналов={n_total} blocked={n_blocked} | "
                      f"WR_all={wr_all:.0f}% WR_gated={wr_gated:.0f}%")
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
    print_report(df, days, symbols)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--days",    type=int, default=45)
    args = parser.parse_args()
    asyncio.run(main(args.symbols, args.days))
