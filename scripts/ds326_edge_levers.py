"""DS-326 рычаги edge: на подвыборке ADX<25 тестируем
  1) TSL on/off (бэктест-трейл 0.5R, НЕ боевой hybrid)
  2) RR-скан {2, 2.5, 3, 4}
  3) LONG vs SHORT
  4) div_strength bucket
Переиспользует simulate_trade (с новым use_tsl) и сканеры базового скрипта.
"""
import sys, os, warnings
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings("ignore")
import pandas as pd, numpy as np

from ds326_all_filters import adx_value
from backtest_wt_b_ltf_entry import (
    build_4h_wt, scan_1h_signals, find_ltf_entry, simulate_trade,
    HIST_1H, HIST_15M, MAX_BARS_SIM,
)
from core.trading.tsl_engine import compute_hybrid_tsl, breakeven_sl, is_tighter, TSL_PROFILES

RRS = [2.0, 2.5, 3.0, 4.0]
ADX_MAX = 25.0
LTF_WINDOW = 20

# Боевой профиль wt_b: в TSL_PROFILES нет → default (как trade_simulator.py:2649)
WTB_PROFILE = TSL_PROFILES.get("wt_b", TSL_PROFILES["default"])


def sim_hybrid(df15m, entry_ts, entry, sl, direction, rr,
               be_act_r=0.5, tsl_act_r=0.8):
    """Воспроизводит боевой TSL wt_b: BE@+0.5R, hybrid TSL@+0.8R, default-профиль.
    mfe_atr НЕ передаётся (как в бою) → gear из current_price. Порядок intrabar SL→TP→TSL
    как в crude simulate_trade (честное сравнение)."""
    one_r = abs(entry - sl)
    if one_r < 1e-9:
        return 0.0
    LONG = direction == "LONG"
    tp = entry + one_r * rr if LONG else entry - one_r * rr
    future = df15m[df15m.index > entry_ts].iloc[:MAX_BARS_SIM]
    cur_sl = sl
    be_done = False
    for ts, bar in future.iterrows():
        h, l, c = bar["high"], bar["low"], bar["close"]
        if LONG:
            if l <= cur_sl:
                return round((cur_sl - entry) / one_r, 3)
            if h >= tp:
                return rr
        else:
            if h >= cur_sl:
                return round((entry - cur_sl) / one_r, 3)
            if l <= tp:
                return rr
        cur_r = (c - entry) / one_r if LONG else (entry - c) / one_r
        if not be_done and cur_r >= be_act_r:
            be = breakeven_sl(direction, entry)
            cur_sl = max(cur_sl, be) if LONG else min(cur_sl, be)
            be_done = True
        if cur_r >= tsl_act_r:
            dur_min = (ts - entry_ts).total_seconds() / 60.0
            dec = compute_hybrid_tsl(direction, entry, c, sl, dur_min, profile=WTB_PROFILE)
            if dec.new_sl and is_tighter(direction, dec.new_sl, cur_sl):
                cur_sl = dec.new_sl
    last = future["close"].iloc[-1] if len(future) > 0 else entry
    return round(((last - entry) if LONG else (entry - last)) / one_r, 3)


def collect_entries(symbol: str) -> list:
    p1h = HIST_1H / f"{symbol}.parquet"
    p15 = HIST_15M / f"{symbol}.parquet"
    if not p1h.exists() or not p15.exists():
        return []
    df1h = pd.read_parquet(p1h)
    df15m = pd.read_parquet(p15)
    wt4 = build_4h_wt(df1h)
    out = []
    for sig in scan_1h_signals(df1h, wt4):
        if sig["kind"] == "cross":
            continue
        ts, direction = sig["ts"], sig["direction"]
        av = adx_value(df1h, ts)
        if av >= ADX_MAX:          # подвыборка ADX<25
            continue
        ltf = find_ltf_entry(df15m, ts, direction, sig["os_"], sig["ob"], LTF_WINDOW)
        if not ltf:
            continue
        out.append({"symbol": symbol, "direction": direction, "df15m": df15m,
                    "entry_ts": ltf["ts"], "entry": ltf["entry"], "sl": ltf["sl"],
                    "div": sig["div_strength"], "adx": av})
    return out


HDR = f"{'variant':<26s} {'n':>4s} {'avgR':>7s} {'medR':>7s} {'WR':>6s} {'Sh':>6s} {'sumR':>7s}"


def row(label: str, arr) -> None:
    arr = np.asarray(arr, float)
    if len(arr) == 0:
        print(f"{label:<26s}   n=0")
        return
    wr = (arr > 0).mean() * 100
    sh = arr.mean() / arr.std() if arr.std() > 0 else 0.0
    print(f"{label:<26s} {len(arr):>4d} {arr.mean():>+7.3f} {np.median(arr):>+7.3f} "
          f"{wr:>5.1f}% {sh:>+6.3f} {arr.sum():>+7.1f}")


def main():
    syms = sorted({p.stem for p in HIST_1H.glob('*.parquet')} &
                  {p.stem for p in HIST_15M.glob('*.parquet')})[:45]
    entries = []
    for s in syms:
        entries += collect_entries(s)
    print(f"ADX<25 LTF entries: {len(entries)} (45 pairs)\n")

    recs = []
    for e in entries:
        for rr in RRS:
            for tsl in (True, False):
                R = simulate_trade(e["df15m"], e["entry_ts"], e["entry"], e["sl"],
                                   e["direction"], rr, use_tsl=tsl)
                recs.append({"direction": e["direction"], "div": e["div"],
                             "rr": rr, "tsl": tsl, "R": R})
    df = pd.DataFrame(recs)

    print("=== A) TSL on/off (RR=3) ===")
    print(HDR)
    for tsl in (True, False):
        row(f"RR3 TSL={'ON' if tsl else 'OFF'}", df[(df.rr == 3.0) & (df.tsl == tsl)]["R"])

    print("\n=== B) RR-скан x TSL ===")
    print(HDR)
    for rr in RRS:
        for tsl in (True, False):
            row(f"RR{rr} TSL={'ON' if tsl else 'OFF'}", df[(df.rr == rr) & (df.tsl == tsl)]["R"])

    print("\n=== C) LONG vs SHORT (RR=3) ===")
    print(HDR)
    for tsl in (True, False):
        for d in ("LONG", "SHORT"):
            row(f"{d} TSL={'ON' if tsl else 'OFF'}",
                df[(df.rr == 3.0) & (df.tsl == tsl) & (df.direction == d)]["R"])

    print("\n=== D) div_strength bucket (RR=3) ===")
    print(HDR)
    for tsl in (True, False):
        sub = df[(df.rr == 3.0) & (df.tsl == tsl)].copy()
        sub["bucket"] = pd.cut(sub["div"], bins=[3, 5, 8, 12, 20], include_lowest=True)
        for b, g in sub.groupby("bucket", observed=True):
            row(f"div{b} {'ON' if tsl else 'OFF'}", g["R"])

    print("\n=== E) КОМБО лучших рычагов (SHORT + div 5-12 + TSL on) ===")
    print(HDR)
    # контроль: вся ADX<25 выборка (RR2.5, TSL on)
    row("baseline ADX<25 RR2.5", df[(df.rr == 2.5) & (df.tsl)]["R"])
    for rr in RRS:
        sub = df[(df.rr == rr) & (df.tsl) & (df.direction == "SHORT") &
                 (df["div"] > 5) & (df["div"] <= 12)]
        row(f"combo RR{rr}", sub["R"])

    # ── F) БОЕВОЙ hybrid TSL vs crude vs off ──
    hrecs = []
    for e in entries:
        is_combo = (e["direction"] == "SHORT") and (5 < e["div"] <= 12)
        for rr in (2.5, 3.0):
            r_off = simulate_trade(e["df15m"], e["entry_ts"], e["entry"], e["sl"],
                                   e["direction"], rr, use_tsl=False)
            r_crude = simulate_trade(e["df15m"], e["entry_ts"], e["entry"], e["sl"],
                                     e["direction"], rr, use_tsl=True)
            r_hyb = sim_hybrid(e["df15m"], e["entry_ts"], e["entry"], e["sl"],
                               e["direction"], rr)
            hrecs.append({"dir": e["direction"], "combo": is_combo, "rr": rr,
                          "off": r_off, "crude": r_crude, "hybrid": r_hyb})
    h = pd.DataFrame(hrecs)

    print("\n=== F) TSL-режимы: off / crude-0.5R / БОЕВОЙ hybrid (wt_b default profile) ===")
    print(HDR)
    for rr in (2.5, 3.0):
        for scope, mask in (("ALL", h.rr == rr),
                            ("SHORT", (h.rr == rr) & (h["dir"] == "SHORT")),
                            ("COMBO", (h.rr == rr) & (h["combo"]))):
            g = h[mask]
            for mode in ("off", "crude", "hybrid"):
                row(f"RR{rr} {scope} {mode}", g[mode])


if __name__ == "__main__":
    main()
