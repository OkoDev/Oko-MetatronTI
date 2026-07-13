"""atr_change Слой 5 — SHORT-флип = ОТБОЙ от недельного сопротивления R1/R2/R3, % net (ЗАКОН №1).

Уточнение Егора: отбой от сопротивления. Механика rejection (не близость):
high в окне последних N баров ДОТЯНУЛСЯ до уровня R (тест сопротивления), НО close бара флипа
ВЕРНУЛСЯ НИЖЕ R (отвергнут) + смена тренда вниз (4h SHORT-флип). Это «цена < уровень» после теста.
Слой 4 (близость close к R) дал минус — тестируем ПРАВИЛЬНУЮ механику отбоя.

Недельные уровни из прошлой недели (без lookahead). Выход = close обратного флипа.
Запуск: python scripts/atr_change_layer5_rejection.py [factor]
"""
import os, sys, sqlite3, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "e:/MTF BOT/CURSOR/crypto_volume_bot"); os.chdir("e:/MTF BOT/CURSOR/crypto_volume_bot")
import numpy as np
import pandas as pd
from core.indicators.indicators import calculate_trend

CACHE = "ohlcv_cache.db"
COST = 0.20
BAND = 0.003          # допуск касания уровня (0.3%)
NS = (1, 3, 5)        # окно баров теста сопротивления


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


def weekly_res_levels(d):
    """R1/R2/R3 (+P) из прошлой недели → сопротивления."""
    g = d.set_index("dt")
    wk = g.resample("W").agg(H=("high", "max"), L=("low", "min"), C=("close", "last"))
    P = (wk["H"] + wk["L"] + wk["C"]) / 3.0
    rng = wk["H"] - wk["L"]
    lv = pd.DataFrame({"P": P, "R1": 2 * P - wk["L"], "R2": P + rng,
                       "R3": wk["H"] + 2 * (P - wk["L"])}).shift(1)
    per = d["dt"].dt.to_period("W")
    out = {}
    for col in lv.columns:
        m = {p: v for p, v in zip(lv.index.to_period("W"), lv[col].values)}
        out[col] = per.map(m).values
    return out


def backtest(factor):
    conn = sqlite3.connect(CACHE, timeout=60)
    syms = load_symbols(conn)
    res = {f"reject_N{n}": [] for n in NS}
    n_sym = 0
    for sym in syms:
        d = load_4h(conn, sym)
        if d is None:
            continue
        df = calculate_trend(d[["open", "high", "low", "close"]].copy(), atr_period=43, factor=factor)
        tr = df["trend"].values; cl = df["close"].values; hi = df["high"].values
        L = weekly_res_levels(d)
        levels = [L["R1"], L["R2"], L["R3"], L["P"]]
        flips = np.where(tr[1:] != tr[:-1])[0] + 1
        flips = [i for i in flips if not np.isnan(tr[i]) and not np.isnan(tr[i-1])]
        if len(flips) < 2:
            continue
        n_sym += 1
        for k in range(len(flips) - 1):
            i, j = flips[k], flips[k + 1]
            if tr[i] > 0:                     # только SHORT
                continue
            entry, exit_ = cl[i], cl[j]
            move = -((exit_ - entry) / entry * 100.0)
            yr = int(d["dt"].values[i].astype("datetime64[Y]").astype(int) + 1970)
            for n in NS:
                lo = max(0, i - n + 1)
                win_hi = hi[lo:i + 1].max()
                ok = False
                for lvl_arr in levels:
                    R = lvl_arr[i]
                    if np.isnan(R):
                        continue
                    # тест: high дотянулся до R (в пределах band снизу/сверху); отбой: close ниже R
                    if win_hi >= R * (1 - BAND) and cl[i] < R:
                        ok = True
                        break
                if ok:
                    res[f"reject_N{n}"].append((move, yr))
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
    print(f"\n{'='*72}\natr_change Слой 5 (SHORT = ОТБОЙ от недельного R1/R2/R3/P) · factor={factor} · "
          f"символов {n_sym}/{n_total} · costs={COST:.2f}% · band={BAND*100:.1f}%")
    print("  baseline Слой 2: SHORT+cl<P mean+0.118 median−1.67 | Слой4 nearR минус")
    def line(name, s):
        if s is None:
            print(f"  [{name:12s}] нет сделок"); return
        n, sm, mn, wr, md = s
        print(f"  [{name:12s}] n={n:6d}  sum%net={sm:+8.1f}  mean={mn:+.3f}  WR={wr:.0f}%  median={md:+.3f}")
    best = None
    for n in NS:
        s = stat(res[f"reject_N{n}"])
        line(f"reject N{n}", s)
        if s and (best is None or s[2] > best[1]):
            best = (n, s[2])
    if best:
        key = f"reject_N{best[0]}"
        print(f"  --- {key} по годам ---")
        for y, (nn, mn) in by_year(res[key]).items():
            print(f"      {y}: n={nn:5d} mean%net={mn:+.3f}")


if __name__ == "__main__":
    main()
