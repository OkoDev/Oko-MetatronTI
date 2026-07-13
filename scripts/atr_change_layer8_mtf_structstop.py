"""atr_change Слой 8 — 4h SHORT-флип + cl<P + 1h-подтверждение, выход S2, СТОП структурный. % net.

Комба Егора: MTF-подтверждение (4h флип + тренд 1h тоже short) + выход на недельной S2 (чемпион
Слоя 7) + стоп за СТРУКТУРУ (swing-high, НЕ линия Supertrend — [[stop_on_line_is_liquidity_sweep]]).
Закрывает 2 оговорки: (1) median −1.6 от выхода-на-линии → структурный стоп; (2) ложные флипы → 1h.

Стоп = swing-high последних K баров 4h × (1+buf), intrabar-touch (реалистично). Выход = S2 (low<=S2)
ИЛИ стоп (high>=stop), что раньше. Без lookahead: 1h-тренд на закрытый бар к моменту 4h-флипа.
Запуск: python scripts/atr_change_layer8_mtf_structstop.py [factor]
"""
import os, sys, sqlite3, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "e:/MTF BOT/CURSOR/crypto_volume_bot"); os.chdir("e:/MTF BOT/CURSOR/crypto_volume_bot")
import numpy as np
import pandas as pd
from core.indicators.indicators import calculate_trend

CACHE = "ohlcv_cache.db"
COST = 0.20
K_STOP = 10        # баров 4h для swing-high структурного стопа
BUF = 0.003        # буфер над структурой
MAXHOLD = 180      # баров 4h максимум
H4_MS = 4 * 3600 * 1000


def load_symbols(conn, min_bars=300):
    return [r[0] for r in conn.execute(
        "SELECT symbol, COUNT(*) c FROM ohlcv_cache WHERE timeframe='4h' GROUP BY symbol HAVING c>=? ORDER BY symbol",
        (min_bars,)).fetchall()]


def load_tf(conn, sym, tf, minb):
    d = pd.read_sql_query(
        "SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? ORDER BY time",
        conn, params=(sym, tf))
    if d is None or len(d) < minb:
        return None
    d["dt"] = pd.to_datetime(d["time"], unit="ms", utc=True)
    return d


def weekly_P_S2(d):
    g = d.set_index("dt")
    wk = g.resample("W").agg(H=("high", "max"), L=("low", "min"), C=("close", "last"))
    P = (wk["H"] + wk["L"] + wk["C"]) / 3.0
    rng = wk["H"] - wk["L"]
    lv = pd.DataFrame({"P": P, "S2": P - rng}).shift(1)
    per = d["dt"].dt.to_period("W")
    out = {}
    for col in lv.columns:
        m = {p: v for p, v in zip(lv.index.to_period("W"), lv[col].values)}
        out[col] = per.map(m).values
    return out


def sim(entry, s2, stop, cl, hi, lo, i, end):
    for m in range(i + 1, end):
        hit_stop = hi[m] >= stop
        hit_tp = lo[m] <= s2
        if hit_stop and hit_tp:            # оба в одном баре — консервативно считаем стоп
            return (entry - stop) / entry * 100.0
        if hit_stop:
            return (entry - stop) / entry * 100.0
        if hit_tp:
            return (entry - s2) / entry * 100.0
    return (entry - cl[end - 1]) / entry * 100.0


def backtest(factor):
    conn = sqlite3.connect(CACHE, timeout=60)
    syms = load_symbols(conn)
    res = {"S2_structstop": [], "S2_structstop_1h": []}
    n_sym = 0
    for sym in syms:
        d4 = load_tf(conn, sym, "4h", 300)
        if d4 is None:
            continue
        d1 = load_tf(conn, sym, "1h", 300)
        df4 = calculate_trend(d4[["open", "high", "low", "close"]].copy(), atr_period=43, factor=factor)
        tr = df4["trend"].values; cl = df4["close"].values
        hi = df4["high"].values; lo = df4["low"].values
        t4 = d4["time"].values
        L = weekly_P_S2(d4)
        # 1h тренд
        if d1 is not None:
            df1 = calculate_trend(d1[["open", "high", "low", "close"]].copy(), atr_period=43, factor=factor)
            tr1 = df1["trend"].values; t1 = d1["time"].values
        else:
            tr1 = None
        flips = np.where(tr[1:] != tr[:-1])[0] + 1
        flips = [x for x in flips if not np.isnan(tr[x]) and not np.isnan(tr[x-1])]
        if len(flips) < 2:
            continue
        n_sym += 1
        for k in range(len(flips) - 1):
            i = flips[k]
            if tr[i] > 0:
                continue
            p = L["P"][i]; s2 = L["S2"][i]
            if np.isnan(p) or np.isnan(s2) or cl[i] >= p or s2 >= cl[i]:
                continue
            entry = cl[i]
            yr = int(d4["dt"].values[i].astype("datetime64[Y]").astype(int) + 1970)
            klo = max(0, i - K_STOP)
            stop = hi[klo:i + 1].max() * (1 + BUF)
            if stop <= entry:              # структура ниже входа — некорректный стоп, пропуск
                continue
            end = min(len(tr), i + MAXHOLD + 1)
            pnl = sim(entry, s2, stop, cl, hi, lo, i, end)
            res["S2_structstop"].append((pnl, yr))
            # 1h-подтверждение: тренд 1h == short на закрытый бар к моменту закрытия 4h-бара i
            if tr1 is not None:
                t_close = t4[i] + H4_MS
                idx1 = np.searchsorted(t1, t_close, side="right") - 1
                if 0 <= idx1 < len(tr1) and tr1[idx1] < 0:
                    res["S2_structstop_1h"].append((pnl, yr))
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
    print(f"\n{'='*72}\natr_change Слой 8 (4h SHORT+cl<P, выход S2, СТОП структурный swing-high K={K_STOP}) · "
          f"factor={factor} · символов {n_sym}/{n_total} · costs={COST:.2f}%")
    print("  Слой7 (S2, защита=обратный флип): mean+0.248 median−1.60 4/5лет+")
    def line(name, s):
        if s is None:
            print(f"  [{name:20s}] нет сделок"); return
        n, sm, mn, wr, md = s
        print(f"  [{name:20s}] n={n:6d}  sum%net={sm:+9.1f}  mean={mn:+.3f}  WR={wr:.0f}%  median={md:+.3f}")
    line("S2+структ-стоп", stat(res["S2_structstop"]))
    line("S2+структ+1h подтв", stat(res["S2_structstop_1h"]))
    for key in ("S2_structstop", "S2_structstop_1h"):
        if res[key]:
            print(f"  --- {key} по годам ---")
            for y, (nn, mn) in by_year(res[key]).items():
                print(f"      {y}: n={nn:6d} mean%net={mn:+.3f}")


if __name__ == "__main__":
    main()
