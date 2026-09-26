"""atr_change Слой 3 — FVG на LTF (15m) ПЕРЕД сменой тренда 4h, мера в % net (ЗАКОН №1).

Концепция Егора: «если смене тренда предшествует FVG — входим на младшем ТФ». FVG (неэффективность
= намерение крупного игрока) = след импульса, толкнувшего смену тренда → отличает реальную смену
от пилы. Базовый сигнал = Слой 2 (4h SHORT-флип + цена < недельный central pivot). Доп-фильтр:
на 15m в окне ПЕРЕД моментом 4h-флипа был bear-FVG.

Без lookahead: 15m бары только до close 4h-бара флипа; pivot из прошлой недели.
Запуск: python scripts/atr_change_layer3_fvg.py [factor]
"""
import os, sys, sqlite3, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "e:/MTF BOT/CURSOR/crypto_volume_bot"); os.chdir("e:/MTF BOT/CURSOR/crypto_volume_bot")
import numpy as np
import pandas as pd
from core.indicators.indicators import calculate_trend

CACHE = "ohlcv_cache.db"
COST = 0.20
WINDOWS = (16, 32)      # баров 15m перед флипом (4h, 8h)


def load_symbols(conn, min_bars=300):
    return [r[0] for r in conn.execute(
        "SELECT symbol, COUNT(*) c FROM ohlcv_cache WHERE timeframe='4h' GROUP BY symbol HAVING c>=? ORDER BY symbol",
        (min_bars,)).fetchall()]


def load_tf(conn, sym, tf):
    d = pd.read_sql_query(
        "SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? ORDER BY time",
        conn, params=(sym, tf))
    if d is None or len(d) < 50:
        return None
    d["dt"] = pd.to_datetime(d["time"], unit="ms", utc=True)
    return d


def weekly_pivot_P(d):
    g = d.set_index("dt")
    wk = g.resample("W").agg(H=("high", "max"), L=("low", "min"), C=("close", "last"))
    wk["P"] = ((wk["H"] + wk["L"] + wk["C"]) / 3.0).shift(1)
    pmap = {p: v for p, v in zip(wk.index.to_period("W"), wk["P"].values)}
    return d["dt"].dt.to_period("W").map(pmap).values


def bear_fvg_times(d15):
    """timestamps (ms) 15m баров k, где bear-FVG: low[k-2] > high[k]. Векторно."""
    lo = d15["low"].values; hi = d15["high"].values; t = d15["time"].values
    if len(d15) < 3:
        return np.array([], dtype=np.int64)
    mask = np.zeros(len(d15), dtype=bool)
    mask[2:] = lo[:-2] > hi[2:]         # gap down на баре k относительно k-2
    return t[mask]


def backtest(factor):
    conn = sqlite3.connect(CACHE, timeout=60)
    syms = load_symbols(conn)
    base = []                            # SHORT+pivot без FVG (move, year)
    fvg = {w: [] for w in WINDOWS}       # +FVG в окне w
    n_sym = 0
    for sym in syms:
        d4 = load_tf(conn, sym, "4h")
        if d4 is None or len(d4) < 300:
            continue
        d15 = load_tf(conn, sym, "15m")
        if d15 is None:
            continue
        df = calculate_trend(d4[["open", "high", "low", "close"]].copy(), atr_period=43, factor=factor)
        tr = df["trend"].values; cl = df["close"].values
        t4 = d4["time"].values
        P = weekly_pivot_P(d4)
        fvg_t = bear_fvg_times(d15)      # ms времена bear-FVG на 15m
        flips = np.where(tr[1:] != tr[:-1])[0] + 1
        flips = [i for i in flips if not np.isnan(tr[i]) and not np.isnan(tr[i-1])]
        if len(flips) < 2:
            continue
        n_sym += 1
        step15 = 15 * 60 * 1000
        for k in range(len(flips) - 1):
            i, j = flips[k], flips[k + 1]
            if tr[i] > 0:                # только SHORT
                continue
            p = P[i]
            if np.isnan(p) or cl[i] >= p:   # short-bias: цена ниже недельного central pivot
                continue
            entry, exit_ = cl[i], cl[j]
            move = (exit_ - entry) / entry * 100.0   # short: (exit-entry)/entry уже отрицат. при падении → инвертируем
            move = -move
            yr = int(d4["dt"].values[i].astype("datetime64[Y]").astype(int) + 1970)
            base.append((move, yr))
            t_i = t4[i]
            for w in WINDOWS:
                # bear-FVG в 15m окне [t_i - w*15m, t_i]
                lo_t = t_i - w * step15
                if np.any((fvg_t >= lo_t) & (fvg_t <= t_i)):
                    fvg[w].append((move, yr))
    conn.close()
    return base, fvg, n_sym, len(syms)


def stat(lst):
    if not lst:
        return None
    arr = np.array([x[0] for x in lst]) - COST
    return len(arr), arr.sum(), arr.mean(), 100 * (arr > 0).mean(), np.median(arr)


def by_year(lst):
    out = {}
    for move, yr in lst:
        out.setdefault(yr, []).append(move)
    return {y: (len(v), np.array(v).sum() - COST * len(v), np.array(v).mean() - COST) for y, v in sorted(out.items())}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    factor = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
    base, fvg, n_sym, n_total = backtest(factor)
    print(f"\n{'='*70}\natr_change Слой 3 (SHORT + pivot + FVG@15m перед 4h-сменой) · factor={factor} · "
          f"символов {n_sym}/{n_total} · costs={COST:.2f}%")
    def line(name, s):
        if s is None:
            print(f"  [{name}] нет сделок"); return
        n, sm, mn, wr, md = s
        print(f"  [{name}] n={n:6d}  sum%net={sm:+8.1f}  mean={mn:+.3f}  WR={wr:.0f}%  median={md:+.3f}")
    line("SHORT+pivot (baseline, без FVG)", stat(base))
    for w in WINDOWS:
        line(f"+FVG@15m окно {w}бар({w//4}h)", stat(fvg[w]))
    # по годам для лучшего FVG-окна
    best_w = max(WINDOWS, key=lambda w: (stat(fvg[w]) or (0,0,-9))[2])
    print(f"  --- +FVG окно {best_w} по годам ---")
    for y, (n, sm, mn) in by_year(fvg[best_w]).items():
        print(f"      {y}: n={n:5d} sum%net={sm:+7.1f} mean={mn:+.3f}")


if __name__ == "__main__":
    main()
