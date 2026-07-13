"""atr_change Слой 2 — недельный central pivot как фильтр НАПРАВЛЕНИЯ, мера в % net (ЗАКОН №1).

Концепция Егора (приоритет): средняя недельная pivot линия определяет направление —
цена ВЫШЕ central pivot → только LONG, НИЖЕ → только SHORT. Вход = Supertrend флип В сторону bias.
Слой 1 показал: WT-фильтр без направления → SHORT систематически минусит. Здесь проверяем, лечит ли
pivot-bias направленность.

Выход = close обратного флипа (НЕ intrabar-touch — [[stop_on_line_is_liquidity_sweep]]).
Без lookahead: pivot из ПРОШЛОЙ недели, вход/выход по close закрытых баров.
Запуск: python scripts/atr_change_layer2_pivot.py [4h|1h] [factor]
"""
import os, sys, sqlite3, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "e:/MTF BOT/CURSOR/crypto_volume_bot"); os.chdir("e:/MTF BOT/CURSOR/crypto_volume_bot")
import numpy as np
import pandas as pd
from core.indicators.indicators import calculate_trend, calculate_wt

CACHE = "ohlcv_cache.db"
COST = 0.20            # fee+slip round-trip, %
WT_ZONE = 50.0
LOOKBACK = 3


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
    d["dt"] = pd.to_datetime(d["time"], unit="ms", utc=True)
    return d


def weekly_pivot(d):
    """central pivot P=(H+L+C)/3 прошлой недели, бродкаст на каждый бар. Без lookahead."""
    g = d.set_index("dt")
    wk = g.resample("W").agg(H=("high", "max"), L=("low", "min"), C=("close", "last"))
    wk["P"] = (wk["H"] + wk["L"] + wk["C"]) / 3.0
    wk["P_prev"] = wk["P"].shift(1)          # пивот прошлой недели → для текущей
    # сопоставить каждому бару P его недели
    d = d.copy()
    d["wk"] = d["dt"].dt.to_period("W").dt.start_time
    pmap = {p.start_time: v for p, v in zip(wk.index.to_period("W"), wk["P_prev"].values)}
    # to_period("W") у resample('W') даёт week ending Sun; выровняем через merge по неделе
    d["P"] = d["dt"].dt.to_period("W").map(lambda p: pmap.get(p.start_time, np.nan))
    return d["P"].values


def backtest(tf, factor):
    conn = sqlite3.connect(CACHE, timeout=60)
    syms = load_symbols(conn, tf)
    variants = {"pivot": [], "pivot+WT": []}
    n_sym = 0
    for sym in syms:
        d = load_df(conn, sym, tf)
        if d is None:
            continue
        df = calculate_trend(d[["open", "high", "low", "close"]].copy(), atr_period=43, factor=factor)
        df = calculate_wt(df, 10, 21)
        tr = df["trend"].values; cl = df["close"].values; wt = df["wt1"].values
        P = weekly_pivot(d)
        flips = np.where(tr[1:] != tr[:-1])[0] + 1
        flips = [i for i in flips if not np.isnan(tr[i]) and not np.isnan(tr[i-1])]
        if len(flips) < 2:
            continue
        n_sym += 1
        for k in range(len(flips) - 1):
            i, j = flips[k], flips[k + 1]
            dirn = tr[i]
            p = P[i]
            if np.isnan(p):
                continue
            bias = 1 if cl[i] > p else -1     # цена выше central pivot → long-bias
            if dirn != bias:                  # флип должен совпасть с pivot-направлением
                continue
            entry, exit_ = cl[i], cl[j]
            yr = int(d["dt"].values[i].astype("datetime64[Y]").astype(int) + 1970)
            move = (exit_ - entry) / entry * 100.0 * (1.0 if dirn > 0 else -1.0)
            variants["pivot"].append((move, dirn, yr))
            lo = max(0, i - LOOKBACK)
            w_win = wt[lo:i + 1]
            wt_ok = (np.nanmin(w_win) <= -WT_ZONE) if dirn > 0 else (np.nanmax(w_win) >= WT_ZONE)
            if wt_ok:
                variants["pivot+WT"].append((move, dirn, yr))
    conn.close()
    return variants, n_sym, len(syms)


def report(variants, n_sym, n_total, tf, factor):
    print(f"\n{'='*68}\natr_change Слой 2 (недельный pivot-bias) · {tf} · factor={factor} · "
          f"символов {n_sym}/{n_total} · costs={COST:.2f}% · WT-зона ±{WT_ZONE:.0f}")
    print("  baseline Слой 0: mean≈-0.06 WR36% med≈-1.9 | Слой 1 LONG≈0 SHORT минус")
    for name, lst in variants.items():
        arr = np.array([t[0] for t in lst]); dirs = np.array([t[1] for t in lst])
        yrs = np.array([t[2] for t in lst])
        if not len(arr):
            print(f"  [{name}] нет сделок"); continue
        net = arr - COST
        print(f"  [{name}] n={len(net):6d}  sum%net={net.sum():+8.1f}  mean={net.mean():+.3f}  "
              f"WR={100*(net>0).mean():.0f}%  median={np.median(net):+.3f}")
        for lbl, mask in (("L", dirs > 0), ("S", dirs < 0)):
            m = arr[mask] - COST
            if len(m):
                print(f"        {lbl}: n={len(m):6d} sum={m.sum():+8.1f} mean={m.mean():+.3f} WR={100*(m>0).mean():.0f}%")
    # SHORT-pivot устойчивость по годам + costs-чувствительность
    s = [t for t in variants["pivot"] if t[1] < 0]
    if s:
        arr = np.array([t[0] for t in s]); yrs = np.array([t[2] for t in s])
        print("  --- SHORT-pivot по годам (costs 0.2%) ---")
        for y in sorted(set(yrs.tolist())):
            mm = arr[yrs == y] - COST
            print(f"      {y}: n={len(mm):5d} sum%net={mm.sum():+7.1f} mean={mm.mean():+.3f} WR={100*(mm>0).mean():.0f}%")
        print("  --- SHORT-pivot costs-чувствительность ---")
        for c in (0.10, 0.20, 0.30, 0.40):
            mm = arr - c
            print(f"      costs={c:.2f}%: sum%net={mm.sum():+7.1f} mean={mm.mean():+.3f} WR={100*(mm>0).mean():.0f}%")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    tf = sys.argv[1] if len(sys.argv) > 1 else "4h"
    factors = [float(sys.argv[2])] if len(sys.argv) > 2 else [1.0]
    for factor in factors:
        variants, n_sym, n_total = backtest(tf, factor)
        report(variants, n_sym, n_total, tf, factor)


if __name__ == "__main__":
    main()
