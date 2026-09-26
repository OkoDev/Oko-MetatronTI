"""Pivot behavior study — КАК цена реально ведёт себя относительно недельных пивотов. Измерение, не стратегия.

Вопрос Егора: как работают недельные пивоты, где закономерности, какие частые связки?
Меряем на 461 символе, 4h, 2022-2026:
  1. Reach rate: % недель, где цена коснулась каждого уровня (R1..R3 / S1..S3).
  2. Bounce vs Break: коснувшись уровня, цена раньше вернулась к P (bounce) или прошла к следующему (break)?
  3. Close position: где неделя закрылась относительно P (открытия сетки).
  4. Split BULL/BEAR (наклон недельного central P: P_w > P_{w-1}).
Уровни недели из ПРОШЛОЙ недели (торгуемо, без lookahead). Reference = open недели.
Запуск: python scripts/pivot_behavior_study.py
"""
import os, sys, sqlite3, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "e:/MTF BOT/CURSOR/crypto_volume_bot"); os.chdir("e:/MTF BOT/CURSOR/crypto_volume_bot")
import numpy as np, pandas as pd
from collections import defaultdict

CACHE = "ohlcv_cache.db"
LEVELS_UP = ["R1", "R2", "R3"]
LEVELS_DN = ["S1", "S2", "S3"]


def load_symbols(conn):
    return [r[0] for r in conn.execute(
        "SELECT symbol,COUNT(*) c FROM ohlcv_cache WHERE timeframe='4h' GROUP BY symbol HAVING c>=300 ORDER BY symbol")]


def load_4h(conn, sym):
    d = pd.read_sql_query("SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe='4h' ORDER BY time",
                          conn, params=(sym,))
    if d is None or len(d) < 300:
        return None
    d["dt"] = pd.to_datetime(d["time"], unit="ms", utc=True)
    d["wk"] = d["dt"].dt.to_period("W")
    return d


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    conn = sqlite3.connect(CACHE, timeout=60)
    syms = load_symbols(conn)
    # агрегаты: reach[regime][level] = [hits, total]; bb[regime][level] = [bounce, break_]
    reach = {r: defaultdict(lambda: [0, 0]) for r in ("ALL", "BULL", "BEAR")}
    bb = {r: defaultdict(lambda: [0, 0]) for r in ("ALL", "BULL", "BEAR")}
    close_pos = {r: [0, 0] for r in ("ALL", "BULL", "BEAR")}   # [above_P, total]
    n_weeks = 0
    for sym in syms:
        d = load_4h(conn, sym)
        if d is None:
            continue
        g = d.set_index("dt")
        wk = g.resample("W").agg(H=("high", "max"), L=("low", "min"), C=("close", "last"), O=("open", "first"))
        P = (wk["H"] + wk["L"] + wk["C"]) / 3.0
        rng = wk["H"] - wk["L"]
        lv = pd.DataFrame({
            "P": P, "R1": 2 * P - wk["L"], "R2": P + rng, "R3": wk["H"] + 2 * (P - wk["L"]),
            "S1": 2 * P - wk["H"], "S2": P - rng, "S3": wk["L"] - 2 * (wk["H"] - P)}).shift(1)
        P_prev = P.shift(1); P_prev2 = P.shift(2)
        weeks = list(wk.index.to_period("W"))
        for wi, w in enumerate(weeks):
            row = lv.iloc[wi]
            if row.isna().any():
                continue
            bars = d[d["wk"] == w]
            if len(bars) < 3:
                continue
            regime = "BULL" if (not np.isnan(P_prev.iloc[wi]) and not np.isnan(P_prev2.iloc[wi])
                                and P_prev.iloc[wi] > P_prev2.iloc[wi]) else "BEAR"
            hi = bars["high"].values; lo = bars["low"].values
            wk_hi = hi.max(); wk_lo = lo.min(); wk_close = bars["close"].values[-1]
            Pv = row["P"]
            n_weeks += 1
            for rg in ("ALL", regime):
                close_pos[rg][1] += 1
                if wk_close > Pv:
                    close_pos[rg][0] += 1
                for L in LEVELS_UP:
                    reach[rg][L][1] += 1
                    if wk_hi >= row[L]:
                        reach[rg][L][0] += 1
                for L in LEVELS_DN:
                    reach[rg][L][1] += 1
                    if wk_lo <= row[L]:
                        reach[rg][L][0] += 1
            # bounce/break: первое касание R1(S1) → раньше R2(S2) [break] или P [bounce]?
            _bounce_break(bars, row, "R1", "R2", "P", up=True, bb=bb, regime=regime)
            _bounce_break(bars, row, "R2", "R3", "R1", up=True, bb=bb, regime=regime)
            _bounce_break(bars, row, "S1", "S2", "P", up=False, bb=bb, regime=regime)
            _bounce_break(bars, row, "S2", "S3", "S1", up=False, bb=bb, regime=regime)
    conn.close()

    print(f"\n{'='*70}\nPIVOT BEHAVIOR · {len(syms)} символов · {n_weeks} недель · 4h · 2022-2026")
    for rg in ("ALL", "BULL", "BEAR"):
        print(f"\n--- {rg} ---")
        print("  Reach rate (% недель коснулись уровня):")
        for L in LEVELS_UP + LEVELS_DN:
            h, t = reach[rg][L]
            if t:
                print(f"     {L}: {100*h/t:4.1f}%  (n={t})")
        cp = close_pos[rg]
        if cp[1]:
            print(f"  Неделя закрылась ВЫШЕ P: {100*cp[0]/cp[1]:.1f}%")
        print("  Bounce vs Break (коснувшись уровня, вернулась к внутр. [bounce] / прошла к внешн. [break]):")
        for L in ("R1", "R2", "S1", "S2"):
            bo, br = bb[rg][L]
            tot = bo + br
            if tot:
                print(f"     {L}: bounce {100*bo/tot:4.1f}%  break {100*br/tot:4.1f}%  (n={tot})")


def _bounce_break(bars, row, lvl, outer, inner, up, bb, regime):
    """первое касание lvl → что раньше: outer (break) или inner (bounce)."""
    hi = bars["high"].values; lo = bars["low"].values
    Lp, Op, Ip = row[lvl], row[outer], row[inner]
    if np.isnan(Lp) or np.isnan(Op) or np.isnan(Ip):
        return
    n = len(bars)
    # индекс первого касания уровня
    ti = None
    for i in range(n):
        if (up and hi[i] >= Lp) or (not up and lo[i] <= Lp):
            ti = i; break
    if ti is None:
        return
    for i in range(ti, n):
        hit_outer = (hi[i] >= Op) if up else (lo[i] <= Op)
        hit_inner = (lo[i] <= Ip) if up else (hi[i] >= Ip)
        if hit_outer and not hit_inner:
            for rg in ("ALL", regime):
                bb[rg][lvl][1] += 1
            return
        if hit_inner and not hit_outer:
            for rg in ("ALL", regime):
                bb[rg][lvl][0] += 1
            return
        if hit_inner and hit_outer:      # оба в баре — неоднозначно, пропуск
            return


if __name__ == "__main__":
    main()
