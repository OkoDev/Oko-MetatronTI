"""DS-326 ТФ-матрица: edge wt_b (ADX<25) на разных связках сигнал-ТФ × вход-ТФ.
Сигнал {1h, 4h} × вход {5m, 15m, 1h}, контекст = ступень выше сигнала.
Логика та же (scan дивергенции + LTF-вход + crude TSL), меняются только ТФ данных.
RR=3, TSL=crude (лучший простой режим из ds326_edge_levers).
"""
import sys, os, warnings
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings("ignore")
import pandas as pd, numpy as np
from pathlib import Path

from core.indicators.indicators import calculate_wt
from ds326_all_filters import adx_value
from backtest_wt_b_ltf_entry import (
    scan_1h_signals, find_ltf_entry, simulate_trade, WT_N1, WT_N2, LTF_WINDOW,
)

NATIVE = {"5m": "data/history/5m", "15m": "data/history/15m", "1h": "data/history/1h"}
RESAMPLE_RULE = {"4h": "4h", "1d": "1D"}
CONTEXT_OF = {"1h": "4h", "4h": "1d"}
RANK = {"5m": 0, "15m": 1, "1h": 2, "4h": 3}
ADX_MAX = 25.0
RR = 3.0


def load_tf(symbol: str, tf: str, cache: dict):
    key = (symbol, tf)
    if key in cache:
        return cache[key]
    if tf in NATIVE:
        p = Path(NATIVE[tf]) / f"{symbol}.parquet"
        df = pd.read_parquet(p) if p.exists() else None
    else:  # resample из 1h
        p1 = Path(NATIVE["1h"]) / f"{symbol}.parquet"
        if not p1.exists():
            df = None
        else:
            d1 = pd.read_parquet(p1)
            df = d1.resample(RESAMPLE_RULE[tf]).agg(
                open=("open", "first"), high=("high", "max"),
                low=("low", "min"), close=("close", "last"), volume=("volume", "sum"),
            ).dropna()
    cache[key] = df
    return df


def htf_wt(df_ctx):
    if df_ctx is None or len(df_ctx) < 20:
        return pd.DataFrame()
    wt = calculate_wt(df_ctx.copy(), n1=WT_N1, n2=WT_N2)
    wt.index = df_ctx.index
    return wt


def run_cell(symbol: str, sig_tf: str, entry_tf: str, cache: dict) -> list:
    df_sig = load_tf(symbol, sig_tf, cache)
    df_entry = load_tf(symbol, entry_tf, cache)
    if df_sig is None or df_entry is None or len(df_sig) < 80:
        return []
    wt_ctx = htf_wt(load_tf(symbol, CONTEXT_OF[sig_tf], cache))
    rows = []
    for sig in scan_1h_signals(df_sig, wt_ctx):
        if sig["kind"] == "cross":
            continue
        if adx_value(df_sig, sig["ts"]) >= ADX_MAX:
            continue
        ltf = find_ltf_entry(df_entry, sig["ts"], sig["direction"], sig["os_"], sig["ob"], LTF_WINDOW)
        if not ltf:
            continue
        R = simulate_trade(df_entry, ltf["ts"], ltf["entry"], ltf["sl"], sig["direction"], RR, use_tsl=True)
        rows.append({"dir": sig["direction"], "R": R})
    return rows


def stat(arr):
    arr = np.asarray(arr, float)
    if len(arr) == 0:
        return None
    wr = (arr > 0).mean() * 100
    sh = arr.mean() / arr.std() if arr.std() > 0 else 0.0
    return len(arr), arr.mean(), wr, sh, arr.sum()


def main():
    syms = sorted(set(p.stem for p in Path(NATIVE["1h"]).glob("*.parquet")) &
                  set(p.stem for p in Path(NATIVE["15m"]).glob("*.parquet")) &
                  set(p.stem for p in Path(NATIVE["5m"]).glob("*.parquet")))[:45]
    print(f"ТФ-матрица wt_b ADX<25, RR={RR}, TSL=crude | пар={len(syms)}\n")

    cells = [(s, e) for s in ("1h", "4h") for e in ("5m", "15m", "1h") if RANK[e] < RANK[s]]
    hdr = f"{'сигнал→вход':<16s} {'scope':<6s} {'n':>4s} {'avgR':>7s} {'WR':>6s} {'Sh':>6s} {'sumR':>7s}"
    print(hdr); print("-" * len(hdr))
    for sig_tf, entry_tf in cells:
        cache = {}
        rows = []
        for s in syms:
            rows += run_cell(s, sig_tf, entry_tf, cache)
        df = pd.DataFrame(rows)
        label = f"{sig_tf}→{entry_tf}"
        for scope in ("ALL", "SHORT"):
            sub = df if scope == "ALL" else df[df["dir"] == "SHORT"]
            st = stat(sub["R"]) if len(sub) else None
            if st:
                n, a, wr, sh, sm = st
                mark = " ←база" if (sig_tf == "1h" and entry_tf == "15m" and scope == "ALL") else ""
                print(f"{label:<16s} {scope:<6s} {n:>4d} {a:>+7.3f} {wr:>5.1f}% {sh:>+6.3f} {sm:>+7.1f}{mark}")
            else:
                print(f"{label:<16s} {scope:<6s}   n=0")
        print()


if __name__ == "__main__":
    main()
