# -*- coding: utf-8 -*-
"""КАСКАД-ТЕСТ — 4h⊃1h→15m vs плоский 1h→15m. Помогает ли 4h-конфлюенция WR/net?

Гипотеза (память [[ote_nested_mtf_strategy]]): больше согласованных уровней (4h-зона ⊃ 1h-зона
→ 15m-вход) → выше WR. Тест: 15m-вход из 1h-сетапа, флаг casc=вход внутри АКТИВНОЙ 4h-зоны
ТОГО ЖЕ направления. Сравниваем casc vs no-casc по net E[R] + WR.
Запуск: python scripts/ote_cascade_test.py --pairs 80
"""
import argparse, sqlite3, sys
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa

CACHE = ROOT / "ohlcv_cache.db"
TF_MIN = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}
BUF, SL_LB, FWD, ZONE_HTF = 0.0015, 6, 240, 14
RT = 0.10
TPS = [2.0, 3.0, 5.0]


def _load(conn, sym, tf):
    df = pd.read_sql_query("SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? ORDER BY time",
                           conn, params=(sym, tf))
    if df.empty: return None
    df.index = pd.to_datetime(df["time"], unit="ms", utc=True)
    return df


def _entry(dfl, d, lo, hi, a, e):
    win = dfl.loc[(dfl.index >= a) & (dfl.index <= e)]
    if len(win) < SL_LB + 2: return None
    for i in range(SL_LB, len(win)):
        b = win.iloc[i]
        if not (b["low"] <= hi and b["high"] >= lo): continue
        seg = win.iloc[i - SL_LB:i + 1]
        if d == "long":
            entry = min(float(b["close"]), hi); sl = float(seg["low"].min()) * (1 - BUF)
            if entry > sl: return entry, sl, win.index[i]
        else:
            entry = max(float(b["close"]), lo); sl = float(seg["high"].max()) * (1 + BUF)
            if sl > entry: return entry, sl, win.index[i]
    return None


def _mfe(dfl, d, entry, sl, ts):
    fwd = dfl.loc[dfl.index > ts].head(FWD)
    if fwd.empty: return None
    one = abs(entry - sl)
    if one <= 0: return None
    best = 0.0
    for h, l in zip(fwd["high"].values, fwd["low"].values):
        if d == "long":
            if l <= sl: break
            best = max(best, float(h) - entry)
        else:
            if h >= sl: break
            best = max(best, entry - float(l))
    return best / one


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(); ap.add_argument("--pairs", type=int, default=80); a = ap.parse_args()
    from core.smc.smc_engine import zigzag_atr, find_setups_zz
    conn = sqlite3.connect(CACHE, timeout=60)
    syms = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM ohlcv_cache WHERE timeframe='1h' ORDER BY symbol")][:a.pairs]
    print(f"[casc] пар: {len(syms)}", flush=True)
    rows = []  # (casc:bool, dir, mfe_r, sl_pct)
    for i, sym in enumerate(syms):
        try:
            d4 = _load(conn, sym, "4h"); d1 = _load(conn, sym, "1h"); d15 = _load(conn, sym, "15m")
            if d4 is None or d1 is None or d15 is None: continue
            # 4h зоны (start,end,dir,lo,hi)
            z4 = []
            for s in find_setups_zz(zigzag_atr(d4), d4):
                if s.get("ote") and s.get("direction") and s.get("choch_ts") is not None:
                    a4 = pd.Timestamp(s["choch_ts"]); z4.append((a4, a4 + pd.Timedelta(minutes=TF_MIN["4h"] * ZONE_HTF), s["direction"], s["ote"][0], s["ote"][1]))
            # 1h сетапы → 15m вход
            span1 = pd.Timedelta(minutes=TF_MIN["1h"] * ZONE_HTF)
            for s in find_setups_zz(zigzag_atr(d1), d1):
                d = s.get("direction"); ote = s.get("ote"); ts = s.get("choch_ts")
                if not ote or d not in ("long", "short") or ts is None: continue
                a1 = pd.Timestamp(ts)
                ent = _entry(d15, d, ote[0], ote[1], a1, a1 + span1)
                if not ent: continue
                entry, sl, ets = ent
                mr = _mfe(d15, d, entry, sl, ets)
                if mr is None: continue
                casc = any(zs <= ets <= ze and zd == d for (zs, ze, zd, _, _) in z4)  # внутри 4h-зоны того же dir
                rows.append((casc, d, mr, abs(entry - sl) / entry * 100))
        except Exception:
            pass
        if (i + 1) % 20 == 0: print(f"[casc] {i+1}/{len(syms)} | {len(rows)}", flush=True)
    conn.close()

    def netwr(sub, T):
        n = len(sub)
        if n == 0: return None
        w = sum(1 for _, _, m, _ in sub if m >= T); tot = 0
        for _, _, m, sl in sub:
            fee = RT / sl if sl > 0 else .5
            tot += (T - fee) if m >= T else (-1 - fee)
        return round(100 * w / n), round(tot / n, 3), n
    casc = [r for r in rows if r[0]]; noc = [r for r in rows if not r[0]]
    print(f"\nВСЕГО 1h→15m: {len(rows)} | КАСКАД 4h⊃1h: {len(casc)} ({round(100*len(casc)/max(len(rows),1))}%) | плоских: {len(noc)}\n")
    print("группа        | TP   | WR  | net E[R] | n")
    for lbl, sub in [("КАСКАД 4h⊃1h→15m", casc), ("плоский 1h→15m", noc)]:
        for T in TPS:
            r = netwr(sub, T)
            if r: print(f"{lbl:20s} | +{T}R | {r[0]}% | {r[1]:+.3f} | {r[2]}")
        print()


if __name__ == "__main__":
    main()
