"""Слой 10 — pivot level-to-level bounce + зависимость от OB/OS 1h. % net (ЗАКОН №1).

Идея Егора: вход = отбой от экстремального недельного уровня, цель = внутренний уровень.
LONG: S3→S1, S1→PP, S1→R2. SHORT (инверсия): R3→R1, R1→PP, R1→S2.
Вход-триггер = прокол уровня + возврат close (первое касание, дедуп). Стоп за входной уровень +буфер.
Доп-срез: WT1 на 1h в зоне OS (LONG) / OB (SHORT) на момент входа — усиливает ли отбой.

Отвязано от atr_change-флипа (чистый bounce). Недельные уровни из прошлой недели, без lookahead.
Запуск: python scripts/atr_change_layer10_levelbounce.py
"""
import os, sys, sqlite3, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "e:/MTF BOT/CURSOR/crypto_volume_bot"); os.chdir("e:/MTF BOT/CURSOR/crypto_volume_bot")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_wt

CACHE = "ohlcv_cache.db"; COST = 0.20; BUF = 0.005; MAXHOLD = 180
OB = 60.0; OS = -60.0; H4_MS = 4 * 3600 * 1000
# (name, entry_level, target_level, direction)
PAIRS = [("L S3>S1", "S3", "S1", "long"), ("L S1>PP", "S1", "P", "long"), ("L S1>R2", "S1", "R2", "long"),
         ("S R3>R1", "R3", "R1", "short"), ("S R1>PP", "R1", "P", "short"), ("S R1>S2", "R1", "S2", "short")]


def load_symbols(conn):
    return [r[0] for r in conn.execute(
        "SELECT symbol,COUNT(*) c FROM ohlcv_cache WHERE timeframe='4h' GROUP BY symbol HAVING c>=300 ORDER BY symbol")]


def load_tf(conn, sym, tf):
    d = pd.read_sql_query("SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? ORDER BY time",
                          conn, params=(sym, tf))
    if d is None or len(d) < 300:
        return None
    d["dt"] = pd.to_datetime(d["time"], unit="ms", utc=True)
    return d


def weekly_levels(d):
    g = d.set_index("dt"); wk = g.resample("W").agg(H=("high", "max"), L=("low", "min"), C=("close", "last"))
    P = (wk["H"] + wk["L"] + wk["C"]) / 3.0; rng = wk["H"] - wk["L"]
    lv = pd.DataFrame({"P": P, "R1": 2 * P - wk["L"], "R2": P + rng, "R3": wk["H"] + 2 * (P - wk["L"]),
                       "S1": 2 * P - wk["H"], "S2": P - rng, "S3": wk["L"] - 2 * (wk["H"] - P)}).shift(1)
    per = d["dt"].dt.to_period("W")
    return {c: per.map({p: v for p, v in zip(lv.index.to_period("W"), lv[c].values)}).values for c in lv.columns}


def backtest():
    conn = sqlite3.connect(CACHE, timeout=60)
    syms = load_symbols(conn)
    res = {}
    for name, _, _, _ in PAIRS:
        res[name] = []; res[name + "|zone"] = []
    n_sym = 0
    for sym in syms:
        d = load_tf(conn, sym, "4h")
        if d is None:
            continue
        d1 = load_tf(conn, sym, "1h")
        cl = d["close"].values; hi = d["high"].values; lo = d["low"].values; t4 = d["time"].values
        L = weekly_levels(d)
        if d1 is not None:
            d1 = calculate_wt(d1, 10, 21); wt1 = d1["wt1"].values; t1 = d1["time"].values
        else:
            wt1 = None
        n_sym += 1
        N = len(cl)
        for name, elvl, tlvl, dirn in PAIRS:
            E = L[elvl]; T = L[tlvl]
            for i in range(1, N - 1):
                e = E[i]; tg = T[i]
                if np.isnan(e) or np.isnan(tg):
                    continue
                if dirn == "long":
                    # прокол снизу + возврат close выше; первое касание (дедуп)
                    if not (lo[i] <= e and cl[i] > e and lo[i-1] > e):
                        continue
                    entry = cl[i]; stop = e * (1 - BUF)
                    if tg <= entry or stop >= entry:
                        continue
                else:
                    if not (hi[i] >= e and cl[i] < e and hi[i-1] < e):
                        continue
                    entry = cl[i]; stop = e * (1 + BUF)
                    if tg >= entry or stop <= entry:
                        continue
                end = min(N, i + MAXHOLD + 1)
                exitp = None
                for m in range(i + 1, end):
                    if dirn == "long":
                        if lo[m] <= stop: exitp = stop; break
                        if hi[m] >= tg: exitp = tg; break
                    else:
                        if hi[m] >= stop: exitp = stop; break
                        if lo[m] <= tg: exitp = tg; break
                if exitp is None:
                    exitp = cl[end - 1]
                pnl = ((exitp - entry) if dirn == "long" else (entry - exitp)) / entry * 100.0
                yr = int(d["dt"].values[i].astype("datetime64[Y]").astype(int) + 1970)
                res[name].append((pnl, yr))
                # OB/OS 1h на момент закрытия 4h бара i
                if wt1 is not None:
                    idx1 = np.searchsorted(t1, t4[i] + H4_MS, side="right") - 1
                    if 0 <= idx1 < len(wt1):
                        z = wt1[idx1]
                        if (dirn == "long" and z <= OS) or (dirn == "short" and z >= OB):
                            res[name + "|zone"].append((pnl, yr))
    conn.close()
    return res, n_sym, len(syms)


def rep(name, lst):
    if not lst:
        print(f"  [{name:14s}] нет"); return
    a = np.array([x[0] for x in lst]) - COST; ys = {}
    for v, y in lst:
        ys.setdefault(y, []).append(v)
    ystr = " ".join(f"{y}:{np.array(v).mean()-COST:+.2f}" for y, v in sorted(ys.items()))
    print(f"  [{name:14s}] n={len(a):6d} mean={a.mean():+.3f} med={np.median(a):+.2f} WR={100*(a>0).mean():.0f}% | {ystr}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    res, n_sym, n_total = backtest()
    print(f"\n{'='*76}\nСлой 10 (pivot level-bounce + OB/OS 1h) · символов {n_sym}/{n_total} · costs={COST}% · buf={BUF*100}%")
    for name, _, _, _ in PAIRS:
        rep(name, res[name])
        rep(name + " +1h-зона", res[name + "|zone"])


if __name__ == "__main__":
    main()
