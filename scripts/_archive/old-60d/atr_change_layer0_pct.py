"""atr_change Слой 0 — чистый Supertrend-flip как trend-following, мера в % net (ЗАКОН №1).

Гипотеза Егора: смена тренда (atr_change = Supertrend flip) = собственный сигнал. Вход на флип,
выход на обратном флипе (линия Supertrend = встроенный трейлинг; «стоп при закрытии свечи за линией»
= момент флипа). НИ R, НИ тугого SL — держим тренд, мерим % движения цены за вычетом costs.

Если чистый флип не несёт edge в % — наслоения (pivot OB/OS, FVG, cascade-TSL) бессмысленны.
Без lookahead: вход=close бара флипа, выход=close обратного флипа.

Запуск:  python scripts/atr_change_layer0_pct.py [4h|1h] [factor]
"""
import os, sys, sqlite3
sys.path.insert(0, "e:/MTF BOT/CURSOR/crypto_volume_bot"); os.chdir("e:/MTF BOT/CURSOR/crypto_volume_bot")
import numpy as np
import pandas as pd
from core.indicators.indicators import calculate_trend

CACHE = "ohlcv_cache.db"
FEE_RT = 0.10          # round-trip taker fee, % от notional
SLIPS = (0.0, 0.10, 0.30)   # дополнительный slippage сценарии, % round-trip


def load_symbols(conn, tf, min_bars=300):
    syms = [r[0] for r in conn.execute(
        "SELECT symbol, COUNT(*) c FROM ohlcv_cache WHERE timeframe=? GROUP BY symbol HAVING c>=? ORDER BY symbol",
        (tf, min_bars)).fetchall()]
    return syms


def load_df(conn, sym, tf):
    d = pd.read_sql_query(
        "SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? ORDER BY time",
        conn, params=(sym, tf))
    if d is None or len(d) < 300:
        return None
    return d[["open", "high", "low", "close"]].astype(float).reset_index(drop=True)


def backtest(tf, factor):
    conn = sqlite3.connect(CACHE, timeout=60)
    syms = load_symbols(conn, tf)
    trades = []   # (move_pct_gross, direction)
    n_sym = 0
    for sym in syms:
        df = load_df(conn, sym, tf)
        if df is None:
            continue
        df = calculate_trend(df, atr_period=43, factor=factor)
        tr = df["trend"].values
        cl = df["close"].values
        # индексы баров, где тренд сменился (флип)
        flips = np.where(tr[1:] != tr[:-1])[0] + 1
        flips = [i for i in flips if not np.isnan(tr[i]) and not np.isnan(tr[i-1])]
        if len(flips) < 2:
            continue
        n_sym += 1
        for k in range(len(flips) - 1):
            i, j = flips[k], flips[k + 1]
            d = tr[i]                    # +1 long / -1 short — направление после флипа
            entry, exit_ = cl[i], cl[j]
            move = (exit_ - entry) / entry * 100.0 * (1.0 if d > 0 else -1.0)
            trades.append((move, d))
    conn.close()
    return trades, n_sym, len(syms)


def report(trades, n_sym, n_total, tf, factor):
    arr = np.array([t[0] for t in trades]) if trades else np.array([])
    dirs = np.array([t[1] for t in trades]) if trades else np.array([])
    print(f"\n{'='*64}\natr_change Слой 0 · {tf} · factor={factor} · символов {n_sym}/{n_total} · сделок {len(arr)}")
    if not len(arr):
        print("  нет сделок"); return
    for slip in SLIPS:
        cost = FEE_RT + slip
        net = arr - cost
        wr = 100 * (net > 0).mean()
        print(f"  costs={cost:.2f}%  | sum%net={net.sum():+8.1f}  mean%net={net.mean():+.3f}  "
              f"WR={wr:.0f}%  median={np.median(net):+.3f}")
    # разбивка long/short при базовом costs (fee+slip 0.1)
    cost = FEE_RT + 0.10
    for lbl, mask in (("LONG ", dirs > 0), ("SHORT", dirs < 0)):
        m = arr[mask] - cost
        if len(m):
            print(f"    {lbl}: n={len(m):5d}  sum%net={m.sum():+8.1f}  mean={m.mean():+.3f}  WR={100*(m>0).mean():.0f}%")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    tf = sys.argv[1] if len(sys.argv) > 1 else "4h"
    factors = [float(sys.argv[2])] if len(sys.argv) > 2 else [1.0, 1.25]
    for factor in factors:
        trades, n_sym, n_total = backtest(tf, factor)
        report(trades, n_sym, n_total, tf, factor)


if __name__ == "__main__":
    main()
