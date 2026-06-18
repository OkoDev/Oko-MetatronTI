#!/usr/bin/env python3
"""
Бэктест: WT-B LTF-вход (1h дивергенция → 15m кросс-триггер)
=============================================================
Baseline:  вход на 1h WT кросс (текущая логика бота)
LTF-вход:  1h дивергенция (div-only) → 15m WT кросс, фильтр 4h WT zone
SL:        calculate_trend(atr_period=43, factor=1.25) — единый калькулятор бота
           LONG SL = trenddown, SHORT SL = trendup

Запуск: python scripts/backtest_wt_b_ltf_entry.py [--symbols 45] [--rr 3] [--window 20]
"""
import sys, os, argparse, warnings
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
from pathlib import Path

from core.indicators.indicators import calculate_wt, calculate_trend

# ── Параметры ─────────────────────────────────────────────────────────────────
HIST_1H  = Path("data/history/1h")
HIST_15M = Path("data/history/15m")

WT_N1, WT_N2   = 10, 21
LOOKBACK_1H     = 35
DIV_MIN         = 3.0
DIV_MAX         = 20.0
OS_FLOOR        = -30.0
OB_FLOOR        =  30.0

LTF_WINDOW      = 20        # баров 15m после сигнала (= 5 часов)
ATR_PERIOD      = 43        # как в боте
ATR_FACTOR      = 1.25      # как в боте (1.25 для подтверждения)
MIN_SL_PCT      = 0.003
MAX_SL_PCT      = 0.08

RR_TARGET       = 3.0
TSL_ACTIVATE    = 1.0
MAX_BARS_SIM    = 300       # max 75h симуляции

# 4h WT фильтр: wt1 должен быть в этой зоне (статичный floor)
HTF_OS_FLOOR    = -30.0
HTF_OB_FLOOR    =  30.0


# ── SL через единый калькулятор бота ─────────────────────────────────────────

def _sl_from_trend(df: pd.DataFrame, bar_i: int, direction: str) -> float:
    """
    SL = trenddown (LONG) / trendup (SHORT) из calculate_trend.
    Нужно минимум ATR_PERIOD+1 баров контекста.
    """
    start = max(0, bar_i - ATR_PERIOD * 3)
    sub   = df.iloc[start: bar_i + 1].copy()
    tr    = calculate_trend(sub, atr_period=ATR_PERIOD, factor=ATR_FACTOR)
    tr.index = sub.index  # calculate_trend может сбрасывать индекс

    entry = float(df["close"].iloc[bar_i])
    if direction == "LONG":
        sl = float(tr["trenddown"].iloc[-1])
        sl = max(sl, entry * (1 - MAX_SL_PCT))
        sl = min(sl, entry * (1 - MIN_SL_PCT))
    else:
        sl = float(tr["trendup"].iloc[-1])
        sl = min(sl, entry * (1 + MAX_SL_PCT))
        sl = max(sl, entry * (1 + MIN_SL_PCT))
    return sl


# ── Детекторы дивергенции ────────────────────────────────────────────────────

def _bullish_div(wt1_vals: list, os_: float) -> dict:
    half = len(wt1_vals) // 2
    if half < 5:
        return {"found": False}
    os1 = [v for v in wt1_vals[:half] if v < os_]
    os2 = [v for v in wt1_vals[half:] if v < os_]
    if not os1 or not os2:
        return {"found": False}
    min1, min2 = min(os1), min(os2)
    if min2 <= min1:
        return {"found": False}
    return {"found": True, "div_strength": round(min2 - min1, 2)}


def _bearish_div(wt1_vals: list, ob: float) -> dict:
    half = len(wt1_vals) // 2
    if half < 5:
        return {"found": False}
    ob1 = [v for v in wt1_vals[:half] if v > ob]
    ob2 = [v for v in wt1_vals[half:] if v > ob]
    if not ob1 or not ob2:
        return {"found": False}
    max1, max2 = max(ob1), max(ob2)
    if max2 >= max1:
        return {"found": False}
    return {"found": True, "div_strength": round(max1 - max2, 2)}


# ── 4h WT контекст ───────────────────────────────────────────────────────────

def build_4h_wt(df1h: pd.DataFrame) -> pd.DataFrame:
    """Resample 1h → 4h, рассчитать WT. Возвращает df с wt1 по 4h барам."""
    df4 = df1h.resample("4h").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"), volume=("volume", "sum")
    ).dropna()
    if len(df4) < 20:
        return pd.DataFrame()
    wt4 = calculate_wt(df4.copy(), n1=WT_N1, n2=WT_N2)
    wt4.index = df4.index
    return wt4


def htf_in_zone(wt4: pd.DataFrame, signal_ts, direction: str) -> bool:
    """Проверяем что 4h wt1 в OS/OB зоне на момент сигнала."""
    if wt4.empty or "wt1" not in wt4.columns:
        return True  # нет данных → не блокируем
    # берём последний 4h бар до signal_ts
    before = wt4[wt4.index <= signal_ts]
    if before.empty:
        return True
    wt1_4h = float(before["wt1"].iloc[-1])
    if direction == "LONG":
        return wt1_4h <= HTF_OS_FLOOR
    else:
        return wt1_4h >= HTF_OB_FLOOR


# ── Сканер 1h ─────────────────────────────────────────────────────────────────

def scan_1h_signals(df1h: pd.DataFrame, wt4: pd.DataFrame) -> list:
    """
    Два типа:
    - 'cross': кросс+дивергенция → baseline вход (текущая логика бота)
    - 'div':   дивергенция без кросса → LTF-вход, с 4h-фильтром
    """
    if len(df1h) < 80:
        return []
    df = calculate_wt(df1h.copy(), n1=WT_N1, n2=WT_N2)
    if "wt1" not in df.columns:
        return []
    df.index = df1h.index

    wt1 = df["wt1"].values
    wt2 = df["wt2"].values

    os_ = min(float(np.percentile(wt1, 10)), OS_FLOOR)
    ob  = max(float(np.percentile(wt1, 90)), OB_FLOOR)

    signals        = []
    last_div_long  = -999
    last_div_short = -999

    for i in range(LOOKBACK_1H + 1, len(df) - 1):
        cross_up   = wt1[i-1] < wt2[i-1] and wt1[i] >= wt2[i]
        cross_down = wt1[i-1] > wt2[i-1] and wt1[i] <= wt2[i]

        # ── LONG ──
        if wt1[i] < os_:
            window = list(wt1[i - LOOKBACK_1H: i])
            d = _bullish_div(window, os_)
            if d["found"] and DIV_MIN <= d["div_strength"] <= DIV_MAX:
                entry = float(df["close"].iloc[i])
                sl_1h = _sl_from_trend(df1h, i, "LONG")

                if cross_up:
                    signals.append({
                        "ts": df.index[i], "direction": "LONG", "kind": "cross",
                        "entry_1h": entry, "sl_1h": sl_1h,
                        "os_": os_, "ob": ob,
                        "div_strength": d["div_strength"],
                        "htf_ok": True,  # baseline не фильтруем по 4h
                    })
                    last_div_long = i

                elif i - last_div_long > 10:
                    htf_ok = htf_in_zone(wt4, df.index[i], "LONG")
                    signals.append({
                        "ts": df.index[i], "direction": "LONG", "kind": "div",
                        "entry_1h": entry, "sl_1h": sl_1h,
                        "os_": os_, "ob": ob,
                        "div_strength": d["div_strength"],
                        "htf_ok": htf_ok,
                    })
                    last_div_long = i

        # ── SHORT ──
        if wt1[i] > ob:
            window = list(wt1[i - LOOKBACK_1H: i])
            d = _bearish_div(window, ob)
            if d["found"] and DIV_MIN <= d["div_strength"] <= DIV_MAX:
                entry = float(df["close"].iloc[i])
                sl_1h = _sl_from_trend(df1h, i, "SHORT")

                if cross_down:
                    signals.append({
                        "ts": df.index[i], "direction": "SHORT", "kind": "cross",
                        "entry_1h": entry, "sl_1h": sl_1h,
                        "os_": os_, "ob": ob,
                        "div_strength": d["div_strength"],
                        "htf_ok": True,
                    })
                    last_div_short = i

                elif i - last_div_short > 10:
                    htf_ok = htf_in_zone(wt4, df.index[i], "SHORT")
                    signals.append({
                        "ts": df.index[i], "direction": "SHORT", "kind": "div",
                        "entry_1h": entry, "sl_1h": sl_1h,
                        "os_": os_, "ob": ob,
                        "div_strength": d["div_strength"],
                        "htf_ok": htf_ok,
                    })
                    last_div_short = i

    return signals


# ── LTF-вход: 15m WT кросс ───────────────────────────────────────────────────

def find_ltf_entry(df15m: pd.DataFrame, signal_ts, direction: str,
                   os_: float, ob: float, ltf_window: int):
    """15m WT кросс в OS/OB зоне в окне ltf_window баров после signal_ts."""
    ctx_pre  = df15m[df15m.index <= signal_ts].iloc[-(ATR_PERIOD * 3):]
    ctx_post = df15m[df15m.index >  signal_ts].iloc[:ltf_window]
    if len(ctx_post) < 3:
        return None

    ctx      = pd.concat([ctx_pre, ctx_post])
    orig_idx = ctx.index
    df       = calculate_wt(ctx.copy(), n1=WT_N1, n2=WT_N2)
    if "wt1" not in df.columns:
        return None
    df.index = orig_idx

    df_after = df[df.index > signal_ts]
    if len(df_after) < 2:
        return None

    wt1 = df_after["wt1"].values
    wt2 = df_after["wt2"].values

    for i in range(1, len(df_after)):
        if direction == "LONG" and wt1[i-1] < wt2[i-1] and wt1[i] >= wt2[i] and wt1[i] < os_:
            bar_ts = df_after.index[i]
            # SL через единый калькулятор
            ctx_to = ctx[ctx.index <= bar_ts]
            bar_i  = len(ctx_to) - 1
            sl = _sl_from_trend(ctx_to, bar_i, "LONG")
            return {"entry": float(df_after["close"].iloc[i]), "sl": sl, "ts": bar_ts}

        elif direction == "SHORT" and wt1[i-1] > wt2[i-1] and wt1[i] <= wt2[i] and wt1[i] > ob:
            bar_ts = df_after.index[i]
            ctx_to = ctx[ctx.index <= bar_ts]
            bar_i  = len(ctx_to) - 1
            sl = _sl_from_trend(ctx_to, bar_i, "SHORT")
            return {"entry": float(df_after["close"].iloc[i]), "sl": sl, "ts": bar_ts}

    return None


# ── Симуляция ─────────────────────────────────────────────────────────────────

def simulate_trade(df15m: pd.DataFrame, entry_ts, entry: float, sl: float,
                   direction: str, rr: float = RR_TARGET,
                   use_tsl: bool = True, tsl_trail: float = 0.5) -> float:
    """use_tsl=False → чистый SL/TP без трейлинга (для исследования влияния TSL).
    tsl_trail — дистанция трейла в R от close (бэктест-упрощение, НЕ боевой hybrid TSL)."""
    one_r = abs(entry - sl)
    if one_r < 1e-9:
        return 0.0

    tp = entry + one_r * rr if direction == "LONG" else entry - one_r * rr
    future = df15m[df15m.index > entry_ts].iloc[:MAX_BARS_SIM]

    tsl_active  = False
    trailing_sl = sl

    for _, bar in future.iterrows():
        h, l, c = bar["high"], bar["low"], bar["close"]
        if direction == "LONG":
            if l <= trailing_sl:
                return round((trailing_sl - entry) / one_r, 3)
            if h >= tp:
                return rr
            if use_tsl:
                if not tsl_active and h >= entry + one_r * TSL_ACTIVATE:
                    tsl_active  = True
                    trailing_sl = entry
                if tsl_active:
                    trailing_sl = max(trailing_sl, c - one_r * tsl_trail)
        else:
            if h >= trailing_sl:
                return round((entry - trailing_sl) / one_r, 3)
            if l <= tp:
                return rr
            if use_tsl:
                if not tsl_active and l <= entry - one_r * TSL_ACTIVATE:
                    tsl_active  = True
                    trailing_sl = entry
                if tsl_active:
                    trailing_sl = min(trailing_sl, c + one_r * tsl_trail)

    last = future["close"].iloc[-1] if len(future) > 0 else entry
    return round(((last - entry) if direction == "LONG" else (entry - last)) / one_r, 3)


# ── Прогон по символу ────────────────────────────────────────────────────────

def run_symbol(symbol: str, rr: float, ltf_window: int) -> list:
    path1h  = HIST_1H  / f"{symbol}.parquet"
    path15m = HIST_15M / f"{symbol}.parquet"
    if not path1h.exists() or not path15m.exists():
        return []

    df1h  = pd.read_parquet(path1h)
    df15m = pd.read_parquet(path15m)
    wt4   = build_4h_wt(df1h)

    signals = scan_1h_signals(df1h, wt4)
    rows = []
    for sig in signals:
        ts, direction, kind = sig["ts"], sig["direction"], sig["kind"]

        if kind == "cross":
            r = simulate_trade(df15m, ts, sig["entry_1h"], sig["sl_1h"], direction, rr)
            rows.append({
                "symbol": symbol, "ts": ts, "direction": direction,
                "kind": "baseline", "div_strength": sig["div_strength"], "R": r,
            })
        else:
            ltf = find_ltf_entry(df15m, ts, direction, sig["os_"], sig["ob"], ltf_window)
            if ltf:
                r = simulate_trade(df15m, ltf["ts"], ltf["entry"], ltf["sl"], direction, rr)
                rows.append({
                    "symbol": symbol, "ts": ts, "direction": direction,
                    "kind": "ltf_all", "div_strength": sig["div_strength"], "R": r,
                })
                if sig["htf_ok"]:
                    rows.append({
                        "symbol": symbol, "ts": ts, "direction": direction,
                        "kind": "ltf_4h", "div_strength": sig["div_strength"], "R": r,
                    })
    return rows


# ── Статистика ────────────────────────────────────────────────────────────────

def stats(r_list: list, label: str):
    if not r_list:
        print(f"  {label}: n=0")
        return
    arr = np.array(r_list)
    wr  = (arr > 0).mean() * 100
    print(f"  {label:<18}: n={len(arr):>4}  avgR={arr.mean():>+6.3f}  "
          f"medR={np.median(arr):>+6.3f}  WR={wr:>5.1f}%  sumR={arr.sum():>+8.1f}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", type=int,   default=45)
    parser.add_argument("--rr",      type=float, default=3.0)
    parser.add_argument("--window",  type=int,   default=20)
    args = parser.parse_args()

    syms_1h  = {p.stem for p in HIST_1H.glob("*.parquet")}
    syms_15m = {p.stem for p in HIST_15M.glob("*.parquet")}
    symbols  = sorted(syms_1h & syms_15m)[:args.symbols]

    print(f"WT-B LTF-Entry Backtest | пар={len(symbols)} | RR={args.rr} | "
          f"LTF_window={args.window} | ATR period={ATR_PERIOD} factor={ATR_FACTOR}")
    print(f"SL: calculate_trend (единый калькулятор бота), 4h-фильтр: wt1<={HTF_OS_FLOOR}/{HTF_OB_FLOOR}+")
    print("=" * 75)

    all_rows = []
    for sym in symbols:
        rows = run_symbol(sym, args.rr, args.window)
        all_rows.extend(rows)
        if rows:
            n_b = sum(1 for r in rows if r["kind"] == "baseline")
            n_l = sum(1 for r in rows if r["kind"] == "ltf_all")
            n_4 = sum(1 for r in rows if r["kind"] == "ltf_4h")
            print(f"  {sym:<22} base={n_b:>3}  ltf={n_l:>3}  ltf+4h={n_4:>3}")

    if not all_rows:
        print("Нет данных.")
        return

    df = pd.DataFrame(all_rows)

    base  = df[df["kind"] == "baseline"]["R"].tolist()
    ltf   = df[df["kind"] == "ltf_all"]["R"].tolist()
    ltf4h = df[df["kind"] == "ltf_4h"]["R"].tolist()

    print(f"\n── ИТОГО ───────────────────────────────────────────────────────────────")
    stats(base,  "Baseline 1h")
    stats(ltf,   "LTF 15m (все)")
    stats(ltf4h, "LTF 15m +4h-фильтр")
    print()

    print("── По направлению ──────────────────────────────────────────────────────")
    for kind, label in [("baseline","Base"), ("ltf_all","LTF "), ("ltf_4h","LTF+4h")]:
        sub = df[df["kind"] == kind]
        for d, grp in sub.groupby("direction"):
            stats(grp["R"].tolist(), f"{label} {d}")
    print()

    print("── По div_strength (LTF +4h) ───────────────────────────────────────────")
    df4 = df[df["kind"] == "ltf_4h"].copy()
    if not df4.empty:
        df4["div_bucket"] = pd.cut(df4["div_strength"],
                                    bins=[0, 6, 10, 20, 100],
                                    labels=["3-6", "6-10", "10-20", "20+"])
        for bucket, grp in df4.groupby("div_bucket", observed=True):
            stats(grp["R"].tolist(), f"div {bucket}")

    print("\n[OK]")


if __name__ == "__main__":
    main()
