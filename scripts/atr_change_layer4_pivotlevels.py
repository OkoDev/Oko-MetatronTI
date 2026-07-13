"""atr_change Слой 4 — SHORT-флип У недельного сопротивления R1/R2/R3, мера в % net (ЗАКОН №1).

Уточнение Егора: учитывать НЕ только central pivot, а всю сетку недельных уровней (R1/R2/R3).
Смена тренда (4h SHORT-флип) в близости к недельному сопротивлению = отбой = сильный знак
(«связь с уровнями пивотов»). Гипотеза: смена У уровня отсекает пилу лучше, чем central-P-bias
и чем FVG@15m (Слой 3 показал — FVG почти не помог).

Недельные классические пивоты из ПРОШЛОЙ недели (без lookahead). Выход = close обратного флипа.
Запуск: python scripts/atr_change_layer4_pivotlevels.py [factor]
"""
import os, sys, sqlite3, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "e:/MTF BOT/CURSOR/crypto_volume_bot"); os.chdir("e:/MTF BOT/CURSOR/crypto_volume_bot")
import numpy as np
import pandas as pd
from core.indicators.indicators import calculate_trend

CACHE = "ohlcv_cache.db"
COST = 0.20
DISTS = (0.5, 1.0, 2.0)      # близость к уровню, %


def load_symbols(conn, min_bars=300):
    return [r[0] for r in conn.execute(
        "SELECT symbol, COUNT(*) c FROM ohlcv_cache WHERE timeframe='4h' GROUP BY symbol HAVING c>=? ORDER BY symbol",
        (min_bars,)).fetchall()]


def load_4h(conn, sym):
    d = pd.read_sql_query(
        "SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe='4h' ORDER BY time",
        conn, params=(sym,))
    if d is None or len(d) < 300:
        return None
    d["dt"] = pd.to_datetime(d["time"], unit="ms", utc=True)
    return d


def weekly_levels(d):
    """P, R1/R2/R3, S1/S2/S3 из ПРОШЛОЙ недели, бродкаст на каждый бар. Без lookahead."""
    g = d.set_index("dt")
    wk = g.resample("W").agg(H=("high", "max"), L=("low", "min"), C=("close", "last"))
    P = (wk["H"] + wk["L"] + wk["C"]) / 3.0
    rng = wk["H"] - wk["L"]
    lv = pd.DataFrame({
        "P":  P, "R1": 2 * P - wk["L"], "S1": 2 * P - wk["H"],
        "R2": P + rng, "S2": P - rng,
        "R3": wk["H"] + 2 * (P - wk["L"]), "S3": wk["L"] - 2 * (wk["H"] - P),
    }).shift(1)                          # уровни прошлой недели
    per = d["dt"].dt.to_period("W")
    out = {}
    for col in lv.columns:
        m = {p: v for p, v in zip(lv.index.to_period("W"), lv[col].values)}
        out[col] = per.map(m).values
    return out


def backtest(factor):
    conn = sqlite3.connect(CACHE, timeout=60)
    syms = load_symbols(conn)
    # варианты: baseline(cl<P) | near-R(любой dist) с/без bias
    res = {"baseline_cl<P": []}
    for dist in DISTS:
        res[f"nearR_{dist}"] = []          # флип near R1/R2/R3 (без bias-требования)
        res[f"nearR_{dist}_bias"] = []     # + cl<P
    n_sym = 0
    for sym in syms:
        d = load_4h(conn, sym)
        if d is None:
            continue
        df = calculate_trend(d[["open", "high", "low", "close"]].copy(), atr_period=43, factor=factor)
        tr = df["trend"].values; cl = df["close"].values
        L = weekly_levels(d)
        flips = np.where(tr[1:] != tr[:-1])[0] + 1
        flips = [i for i in flips if not np.isnan(tr[i]) and not np.isnan(tr[i-1])]
        if len(flips) < 2:
            continue
        n_sym += 1
        for k in range(len(flips) - 1):
            i, j = flips[k], flips[k + 1]
            if tr[i] > 0:                  # только SHORT
                continue
            p = L["P"][i]
            if np.isnan(p):
                continue
            entry, exit_ = cl[i], cl[j]
            move = -((exit_ - entry) / entry * 100.0)   # short profit%
            yr = int(d["dt"].values[i].astype("datetime64[Y]").astype(int) + 1970)
            bias = cl[i] < p
            if bias:
                res["baseline_cl<P"].append((move, yr))
            # расстояние до ближайшего сопротивления R1/R2/R3
            rs = [L["R1"][i], L["R2"][i], L["R3"][i]]
            dmin = min(abs(cl[i] - r) / cl[i] * 100.0 for r in rs if not np.isnan(r)) if any(
                not np.isnan(r) for r in rs) else 999
            for dist in DISTS:
                if dmin <= dist:
                    res[f"nearR_{dist}"].append((move, yr))
                    if bias:
                        res[f"nearR_{dist}_bias"].append((move, yr))
    conn.close()
    return res, n_sym, len(syms)


def stat(lst):
    if not lst:
        return None
    arr = np.array([x[0] for x in lst]) - COST
    return len(arr), arr.sum(), arr.mean(), 100 * (arr > 0).mean(), np.median(arr)


def by_year(lst):
    out = {}
    for move, yr in lst:
        out.setdefault(yr, []).append(move)
    return {y: (len(v), np.array(v).mean() - COST) for y, v in sorted(out.items())}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    factor = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
    res, n_sym, n_total = backtest(factor)
    print(f"\n{'='*72}\natr_change Слой 4 (SHORT-флип У недельного R1/R2/R3) · factor={factor} · "
          f"символов {n_sym}/{n_total} · costs={COST:.2f}%")
    print("  baseline Слой 2: SHORT+cl<P mean+0.118 median−1.9")
    def line(name, s):
        if s is None:
            print(f"  [{name:22s}] нет сделок"); return
        n, sm, mn, wr, md = s
        print(f"  [{name:22s}] n={n:6d}  sum%net={sm:+8.1f}  mean={mn:+.3f}  WR={wr:.0f}%  median={md:+.3f}")
    line("baseline_cl<P", stat(res["baseline_cl<P"]))
    for dist in DISTS:
        line(f"nearR ±{dist}%", stat(res[f"nearR_{dist}"]))
        line(f"nearR ±{dist}% +bias", stat(res[f"nearR_{dist}_bias"]))
    # по годам для nearR 1.0 +bias
    key = "nearR_1.0_bias"
    if res[key]:
        print(f"  --- {key} по годам ---")
        for y, (n, mn) in by_year(res[key]).items():
            print(f"      {y}: n={n:5d} mean%net={mn:+.3f}")


if __name__ == "__main__":
    main()
