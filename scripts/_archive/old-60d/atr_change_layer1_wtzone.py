"""atr_change Слой 1 — флип ОТ КРАЙНОСТИ (WT OB/OS), мера в % net (ЗАКОН №1).

Слой 0 показал: чистый Supertrend-flip = пила (WR37%, median −1.785%, edge тоньше costs).
Концепция Егора: брать НЕ каждый флип, а флип ОТ перекупленности/перепроданности.
Фильтр: long-флип проходит только если WT был в OS (перепроданность) в окне перед флипом;
short-флип — только если WT был в OB (перекупленность). Резкое сокращение n; если концепция
верна — median/WR прыгают вверх.

Без lookahead: вход=close бара флипа, выход=close обратного флипа. WT/trend на закрытых барах.
Запуск: python scripts/atr_change_layer1_wtzone.py [4h|1h] [factor]
"""
import os, sys, sqlite3
sys.path.insert(0, "e:/MTF BOT/CURSOR/crypto_volume_bot"); os.chdir("e:/MTF BOT/CURSOR/crypto_volume_bot")
import numpy as np
import pandas as pd
from core.indicators.indicators import calculate_trend, calculate_wt

CACHE = "ohlcv_cache.db"
FEE_RT = 0.10
COST = FEE_RT + 0.10           # базовый costs 0.2% (fee+slip), как реалистичный на 4h
LOOKBACK = 3                   # окно баров до флипа (вкл.), где ищем крайность WT
ZONES = (40.0, 50.0, 60.0)     # пороги OB/OS для перебора


def load_symbols(conn, tf, min_bars=300):
    return [r[0] for r in conn.execute(
        "SELECT symbol, COUNT(*) c FROM ohlcv_cache WHERE timeframe=? GROUP BY symbol HAVING c>=? ORDER BY symbol",
        (tf, min_bars)).fetchall()]


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
    # для каждой зоны: список (move_pct_gross, dir)
    res = {z: [] for z in ZONES}
    n_sym = 0
    for sym in syms:
        df = load_df(conn, sym, tf)
        if df is None:
            continue
        df = calculate_trend(df, atr_period=43, factor=factor)
        df = calculate_wt(df, 10, 21)
        tr = df["trend"].values
        cl = df["close"].values
        wt = df["wt1"].values
        flips = np.where(tr[1:] != tr[:-1])[0] + 1
        flips = [i for i in flips if not np.isnan(tr[i]) and not np.isnan(tr[i-1])]
        if len(flips) < 2:
            continue
        n_sym += 1
        for k in range(len(flips) - 1):
            i, j = flips[k], flips[k + 1]
            d = tr[i]
            lo = max(0, i - LOOKBACK)
            w_win = wt[lo:i + 1]
            if not len(w_win):
                continue
            entry, exit_ = cl[i], cl[j]
            move = (exit_ - entry) / entry * 100.0 * (1.0 if d > 0 else -1.0)
            for z in ZONES:
                # long-флип ← перепроданность (wt окунался <= -z); short-флип ← перекупленность (>= +z)
                ok = (np.nanmin(w_win) <= -z) if d > 0 else (np.nanmax(w_win) >= z)
                if ok:
                    res[z].append((move, d))
    conn.close()
    return res, n_sym, len(syms)


def report(res, n_sym, n_total, tf, factor):
    print(f"\n{'='*68}\natr_change Слой 1 (флип от WT-крайности) · {tf} · factor={factor} · "
          f"символов {n_sym}/{n_total} · costs={COST:.2f}% · lookback={LOOKBACK}")
    print(f"  (baseline Слой 0: mean%net≈-0.06 WR36% median≈-1.9 при costs 0.2%)")
    for z in ZONES:
        arr = np.array([t[0] for t in res[z]])
        dirs = np.array([t[1] for t in res[z]])
        if not len(arr):
            print(f"  OB/OS=±{z:.0f}: нет сделок"); continue
        net = arr - COST
        print(f"  OB/OS=±{z:.0f}: n={len(net):6d}  sum%net={net.sum():+8.1f}  mean={net.mean():+.3f}  "
              f"WR={100*(net>0).mean():.0f}%  median={np.median(net):+.3f}")
        for lbl, mask in (("L", dirs > 0), ("S", dirs < 0)):
            m = arr[mask] - COST
            if len(m):
                print(f"        {lbl}: n={len(m):6d}  sum={m.sum():+8.1f}  mean={m.mean():+.3f}  WR={100*(m>0).mean():.0f}%")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    tf = sys.argv[1] if len(sys.argv) > 1 else "4h"
    factors = [float(sys.argv[2])] if len(sys.argv) > 2 else [1.0]
    for factor in factors:
        res, n_sym, n_total = backtest(tf, factor)
        report(res, n_sym, n_total, tf, factor)


if __name__ == "__main__":
    main()
