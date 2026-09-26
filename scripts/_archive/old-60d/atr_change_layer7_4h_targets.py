"""atr_change Слой 6 — 1h SHORT-флип + cl<central P, выход по недельным S1/S2/S3, % net (ЗАКОН №1).

Идея Егора: ТФ=1h, выход по целям — недельные поддержки S1/S2/S3 (фикс-цели вместо ожидания
обратного флипа → бьёт median −1.7). Вход = 1h SHORT-флип при цене ниже недельного central pivot.
Выход = достижение поддержки (low<=S) ИЛИ обратный флип вверх (защитный, что раньше).

Недельные уровни из прошлой недели (без lookahead). Симуляция бар-за-баром после входа.
Запуск: python scripts/atr_change_layer6_1h_targets.py [factor]
"""
import os, sys, sqlite3, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "e:/MTF BOT/CURSOR/crypto_volume_bot"); os.chdir("e:/MTF BOT/CURSOR/crypto_volume_bot")
import numpy as np
import pandas as pd
from core.indicators.indicators import calculate_trend

CACHE = "ohlcv_cache.db"
COST = 0.20
MAXHOLD = 500      # баров 1h максимум держим (защита от вечных позиций)


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


def weekly_supports(d):
    """P, S1/S2/S3 из прошлой недели."""
    g = d.set_index("dt")
    wk = g.resample("W").agg(H=("high", "max"), L=("low", "min"), C=("close", "last"))
    P = (wk["H"] + wk["L"] + wk["C"]) / 3.0
    rng = wk["H"] - wk["L"]
    lv = pd.DataFrame({"P": P, "S1": 2 * P - wk["H"], "S2": P - rng,
                       "S3": wk["L"] - 2 * (wk["H"] - P)}).shift(1)
    per = d["dt"].dt.to_period("W")
    out = {}
    for col in lv.columns:
        m = {p: v for p, v in zip(lv.index.to_period("W"), lv[col].values)}
        out[col] = per.map(m).values
    return out


def sim_short(entry, targets, tr, cl, hi, lo, i, end):
    """Возвращает dict{policy: profit%}. targets = отсортированные поддержки ниже entry (ближняя первой)."""
    res = {}
    # single-target policies S1/S2/S3 (первая/вторая/третья поддержка ниже входа)
    for ti, tname in ((0, "S1"), (1, "S2"), (2, "S3")):
        if ti >= len(targets):
            res[tname] = None; continue
        tgt = targets[ti]
        exitp = None
        for m in range(i + 1, end):
            if tr[m] > 0:                     # обратный флип вверх → защитный выход
                exitp = cl[m]; break
            if lo[m] <= tgt:                  # достигли поддержки
                exitp = tgt; break
        if exitp is None:
            exitp = cl[min(end - 1, i + MAXHOLD)]
        res[tname] = (entry - exitp) / entry * 100.0
    # ladder 1/3 на каждой доступной поддержке, остаток — обратный флип
    filled = []
    remaining = list(targets[:3])
    exit_flip = None
    for m in range(i + 1, end):
        if tr[m] > 0:
            exit_flip = cl[m]; break
        while remaining and lo[m] <= remaining[0]:
            filled.append(remaining.pop(0))
    n_parts = max(3, len(targets[:3]) if targets else 3)
    parts = []
    for f in filled:
        parts.append((entry - f) / entry * 100.0)
    rest = 3 - len(filled)
    if rest > 0:
        close_rest = exit_flip if exit_flip is not None else cl[min(end - 1, i + MAXHOLD)]
        parts += [(entry - close_rest) / entry * 100.0] * rest
    res["ladder"] = sum(parts) / 3.0
    return res


def backtest(factor):
    conn = sqlite3.connect(CACHE, timeout=60)
    syms = load_symbols(conn)
    pols = ("baseline_flip", "S1", "S2", "S3", "ladder")
    res = {p: [] for p in pols}
    n_sym = 0
    for sym in syms:
        d = load_4h(conn, sym)
        if d is None:
            continue
        df = calculate_trend(d[["open", "high", "low", "close"]].copy(), atr_period=43, factor=factor)
        tr = df["trend"].values; cl = df["close"].values
        hi = df["high"].values; lo = df["low"].values
        L = weekly_supports(d)
        flips = np.where(tr[1:] != tr[:-1])[0] + 1
        flips = [i for i in flips if not np.isnan(tr[i]) and not np.isnan(tr[i-1])]
        if len(flips) < 2:
            continue
        n_sym += 1
        for k in range(len(flips) - 1):
            i, j = flips[k], flips[k + 1]
            if tr[i] > 0:
                continue
            p = L["P"][i]
            if np.isnan(p) or cl[i] >= p:      # short-bias: ниже central pivot
                continue
            entry = cl[i]
            yr = int(d["dt"].values[i].astype("datetime64[Y]").astype(int) + 1970)
            # baseline: held до обратного флипа
            res["baseline_flip"].append(((entry - cl[j]) / entry * 100.0, yr))
            # поддержки ниже входа, по близости
            supp = sorted([L[s][i] for s in ("S1", "S2", "S3")
                           if not np.isnan(L[s][i]) and L[s][i] < entry], reverse=True)
            end = min(len(tr), i + MAXHOLD + 1)
            # выход учитывает бары до следующего флипа ИЛИ MAXHOLD
            sim = sim_short(entry, supp, tr, cl, hi, lo, i, min(j + 1, end) if j > i else end)
            for tname in ("S1", "S2", "S3", "ladder"):
                v = sim.get(tname)
                if v is not None:
                    res[tname].append((v, yr))
    conn.close()
    return res, n_sym, len(syms)


def stat(lst):
    if not lst:
        return None
    arr = np.array([x[0] for x in lst]) - COST
    return len(arr), arr.sum(), arr.mean(), 100 * (arr > 0).mean(), np.median(arr)


def by_year(lst):
    out = {}
    for v, yr in lst:
        out.setdefault(yr, []).append(v)
    return {y: (len(a), np.array(a).mean() - COST) for y, a in sorted(out.items())}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    factor = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
    res, n_sym, n_total = backtest(factor)
    print(f"\n{'='*72}\natr_change Слой 7 (4h SHORT + cl<P, выход S1/S2/S3) · factor={factor} · "
          f"символов {n_sym}/{n_total} · costs={COST:.2f}%")
    def line(name, s):
        if s is None:
            print(f"  [{name:14s}] нет сделок"); return
        n, sm, mn, wr, md = s
        print(f"  [{name:14s}] n={n:6d}  sum%net={sm:+9.1f}  mean={mn:+.3f}  WR={wr:.0f}%  median={md:+.3f}")
    for p in ("baseline_flip", "S1", "S2", "S3", "ladder"):
        line(p, stat(res[p]))
    # по годам для лучшей политики
    best = max(("S1", "S2", "S3", "ladder"), key=lambda p: (stat(res[p]) or (0, 0, -9))[2])
    print(f"  --- {best} по годам ---")
    for y, (nn, mn) in by_year(res[best]).items():
        print(f"      {y}: n={nn:6d} mean%net={mn:+.3f}")


if __name__ == "__main__":
    main()
