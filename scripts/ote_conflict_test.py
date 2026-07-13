# -*- coding: utf-8 -*-
"""ФИЛЬТР «не входить в разные стороны» — эмпирически (не на предположениях).

Для каждого LTF-входа (из 4h/1h сетапа) флаг conflict = активна ПРОТИВОПОЛОЖНАЯ HTF-зона
(4h ИЛИ 1h другого направления) в момент входа. Сравниваем net@3R: чистые vs конфликтные.
Если чистые лучше → фильтр направления валиден → вводим.
Запуск: python scripts/ote_conflict_test.py --pairs 150
"""
import argparse, sqlite3, sys
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa

CACHE = ROOT / "ohlcv_cache.db"
TF_MIN = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}
BUF, SL_LB, FWD, ZONE_HTF, RT = 0.0015, 6, 240, 14, 0.10
NEST = {"4h": ["15m", "5m"], "1h": ["15m", "5m"]}


def _load(conn, sym, tf):
    df = pd.read_sql_query("SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? ORDER BY time",
                           conn, params=(sym, tf))
    if df.empty: return None
    df.index = pd.to_datetime(df["time"], unit="ms", utc=True); return df


def _entry(dfl, d, lo, hi, a, e):
    win = dfl.loc[(dfl.index >= a) & (dfl.index <= e)]
    if len(win) < SL_LB + 2: return None
    for i in range(SL_LB, len(win)):
        b = win.iloc[i]
        if not (b["low"] <= hi and b["high"] >= lo): continue
        seg = win.iloc[i - SL_LB:i + 1]
        if d == "long":
            en = min(float(b["close"]), hi); sl = float(seg["low"].min()) * (1 - BUF)
            if en > sl: return en, sl, win.index[i]
        else:
            en = max(float(b["close"]), lo); sl = float(seg["high"].max()) * (1 + BUF)
            if sl > en: return en, sl, win.index[i]
    return None


def _mfe(dfl, d, en, sl, ts):
    fwd = dfl.loc[dfl.index > ts].head(FWD)
    if fwd.empty: return None
    one = abs(en - sl)
    if one <= 0: return None
    best = 0.0
    for h, l in zip(fwd["high"].values, fwd["low"].values):
        if d == "long":
            if l <= sl: break
            best = max(best, float(h) - en)
        else:
            if h >= sl: break
            best = max(best, en - float(l))
    return best / one


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(); ap.add_argument("--pairs", type=int, default=150); a = ap.parse_args()
    from core.smc.smc_engine import zigzag_atr, find_setups_zz
    conn = sqlite3.connect(CACHE, timeout=60)
    syms = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM ohlcv_cache WHERE timeframe='1h' ORDER BY symbol")][:a.pairs]
    print(f"[conflict] пар: {len(syms)}", flush=True)
    rows = []  # (conflict, mfe_r, sl_pct)
    for idx, sym in enumerate(syms):
        try:
            dfs = {tf: _load(conn, sym, tf) for tf in ("4h", "1h", "15m", "5m")}
            if any(dfs[t] is None for t in ("4h", "1h", "15m", "5m")): continue
            # все HTF-зоны (4h+1h) с направлением и окном (для конфликт-проверки)
            zones = []
            for htf in ("4h", "1h"):
                for s in find_setups_zz(zigzag_atr(dfs[htf]), dfs[htf]):
                    if s.get("ote") and s.get("direction") and s.get("choch_ts") is not None:
                        z = pd.Timestamp(s["choch_ts"])
                        zones.append((z, z + pd.Timedelta(minutes=TF_MIN[htf] * ZONE_HTF), s["direction"]))
            # входы
            for htf, ltfs in NEST.items():
                span = pd.Timedelta(minutes=TF_MIN[htf] * ZONE_HTF)
                for s in find_setups_zz(zigzag_atr(dfs[htf]), dfs[htf]):
                    d = s.get("direction"); ote = s.get("ote"); ts = s.get("choch_ts")
                    if not ote or d not in ("long", "short") or ts is None: continue
                    az = pd.Timestamp(ts)
                    for ltf in ltfs:
                        ent = _entry(dfs[ltf], d, ote[0], ote[1], az, az + span)
                        if not ent: continue
                        en, sl, ets = ent
                        mr = _mfe(dfs[ltf], d, en, sl, ets)
                        if mr is None: continue
                        opp = "short" if d == "long" else "long"
                        conflict = any(zs <= ets <= ze and zd == opp for (zs, ze, zd) in zones)
                        rows.append((conflict, mr, abs(en - sl) / en * 100))
        except Exception:
            pass
        if (idx + 1) % 30 == 0: print(f"[conflict] {idx+1}/{len(syms)} | {len(rows)}", flush=True)
    conn.close()

    def netwr(sub, T=3.0):
        n = len(sub)
        if n == 0: return None
        w = sum(1 for c, m, _ in sub if m >= T); tot = 0
        for c, m, sl in sub:
            fee = RT / sl if sl > 0 else .5
            tot += (T - fee) if m >= T else (-1 - fee)
        return round(100 * w / n), round(tot / n, 3), n
    clean = [r for r in rows if not r[0]]; conf = [r for r in rows if r[0]]
    print(f"\nВСЕГО входов: {len(rows)} | КОНФЛИКТ (активна противоположная HTF-зона): {len(conf)} ({round(100*len(conf)/max(len(rows),1))}%) | ЧИСТЫХ: {len(clean)}\n")
    print("группа                      | WR@3R | net E[R]@3R | n")
    for lbl, sub in [("ЧИСТЫЕ (нет конфликта)", clean), ("КОНФЛИКТ (разные стороны)", conf)]:
        r = netwr(sub)
        if r: print(f"{lbl:27s} | {r[0]}%   | {r[1]:+.3f}     | {r[2]}")


if __name__ == "__main__":
    main()
