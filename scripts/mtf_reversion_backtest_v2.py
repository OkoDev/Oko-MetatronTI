# -*- coding: utf-8 -*-
"""ARCH-127 DS-311 — итерация-2: MTF Reversion backtest (улучшенный).

Улучшения vs v1:
  1. HTF-тренд через calculate_trend (supertrend) на 1h/4h, НЕ знак wt1.
  2. Вход из OS/OB + OTE-зона (Fib 0.618-0.786 отката от свинга).
  3. TP: сравнить ATR-кратность vs Fib-расширение.
  4. Data-era split (post-15.04.2026).

Запуск: python scripts/mtf_reversion_backtest_v2.py [--pairs N]
"""
import argparse
import glob
import os
import sys
from collections import defaultdict

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
import pandas as pd
import numpy as np
from core.indicators.indicators import (
    calculate_wt,
    compute_atr_values,
    calculate_trend,
    find_swing_highs,
    find_swing_lows,
)

H = "data/history"
DATA_ERA_CUT = pd.Timestamp("2026-04-15")


# ── helpers ──────────────────────────────────────────────────
def load(tf, sym, n=4000):
    f = os.path.join(H, tf, f"{sym}.parquet")
    if not os.path.exists(f):
        return None
    df = pd.read_parquet(f)
    df.columns = [c.lower() for c in df.columns]
    if "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True, errors="coerce")
        df = df.set_index("ts")
    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    return df[keep].dropna().tail(n)


def fib_levels(swing_high, swing_low):
    """Рассчитать сетку Фибоначчи между двумя точками."""
    diff = swing_high - swing_low
    return {
        "0.0": swing_low,
        "0.382": swing_low + 0.382 * diff,
        "0.5": swing_low + 0.5 * diff,
        "0.618": swing_low + 0.618 * diff,
        "0.786": swing_low + 0.786 * diff,
        "1.0": swing_high,
        "1.272": swing_high + 0.272 * diff,
        "1.618": swing_high + 0.618 * diff,
    }


def in_ote_zone(price, swing_a, swing_b, direction):
    """Цена в зоне 0.618-0.786 отката? Для LONG: откат вниз от high."""
    if swing_a is None or swing_b is None:
        return False
    if direction == "LONG":
        high, low = max(swing_a, swing_b), min(swing_a, swing_b)
        fib = fib_levels(high, low)
        return fib["0.618"] <= price <= fib["0.786"] and price < high
    else:
        high, low = max(swing_a, swing_b), min(swing_a, swing_b)
        fib = fib_levels(high, low)
        return fib["0.382"] <= price <= fib["0.618"]


def nearest_swing(df, i, lookback=50):
    """Ближайший свинг HIGH/LOW к бару i (только ЗАКРЫТЫЕ свечи)."""
    subset = df.iloc[max(0, i - lookback) : i]
    if len(subset) < 5:
        return None, None
    highs = find_swing_highs(subset["high"], period=5)
    lows = find_swing_lows(subset["low"], period=5)
    sh = max(h["value"] for h in highs) if len(highs) > 0 else None
    sl_ = min(l["value"] for l in lows) if len(lows) > 0 else None
    return sh, sl_


def simulate(df15, i, direction, atr, rr=2.0, sl_mult=1.5, horizon=48, tp_method="rr"):
    """Forward-симуляция. tp_method: 'rr' или 'fib'."""
    entry = df15["close"].iloc[i]
    if not atr or atr <= 0:
        return None, None
    sl_dist = sl_mult * atr
    tp_dist = rr * sl_dist

    if direction == "LONG":
        sl, tp = entry - sl_dist, entry + tp_dist
    else:
        sl, tp = entry + sl_dist, entry - tp_dist

    # Fib TP: используем свинг high/low для цели расширения
    if tp_method == "fib":
        sh, sl_ = nearest_swing(df15, i)
        if sh and sl_:
            fib = fib_levels(sh, sl_)
            if direction == "LONG":
                tp_fib = fib["1.618"]
                if tp_fib > entry:
                    tp = tp_fib
            else:
                tp_fib = fib["1.272"]  # shorter target for SHORT fib
                if tp_fib < entry:
                    tp = tp_fib

    for j in range(i + 1, min(i + 1 + horizon, len(df15))):
        hi, lo = df15["high"].iloc[j], df15["low"].iloc[j]
        if direction == "LONG":
            if lo <= sl:
                return -1.0, "SL"
            if hi >= tp:
                return rr if tp_method == "rr" else (tp - entry) / sl_dist, "TP"
        else:
            if hi >= sl:
                return -1.0, "SL"
            if lo <= tp:
                return rr if tp_method == "rr" else (entry - tp) / sl_dist, "TP"

    last = df15["close"].iloc[min(i + horizon, len(df15) - 1)]
    r = ((last - entry) if direction == "LONG" else (entry - last)) / sl_dist
    return r, "TIME"


# ── main ─────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=int, default=50)
    ap.add_argument("--os", type=float, default=-53.0)
    ap.add_argument("--ob", type=float, default=53.0)
    ap.add_argument("--ote", action="store_true", default=False, help="Require OTE zone")
    ap.add_argument("--tp-fib", action="store_true", default=False, help="Use Fib TP instead of RR=2")
    args = ap.parse_args()

    syms = [os.path.basename(f)[:-8] for f in glob.glob(H + "/15m/*.parquet")][: args.pairs]
    res = defaultdict(list)

    for sym in syms:
        d15, d1h, d4h = load("15m", sym), load("1h", sym), load("4h", sym)
        if d15 is None or d1h is None or len(d15) < 200:
            continue
        d15_orig = d15  # сохранить до calculate_wt (меняет индекс)
        d15 = calculate_wt(d15.copy())
        # Восстановить индекс после calculate_wt (сбрасывает на RangeIndex)
        if not isinstance(d15.index, pd.DatetimeIndex) and isinstance(d15_orig.index, pd.DatetimeIndex):
            d15.index = d15_orig.index[-len(d15):]

        atrs = compute_atr_values(d15["high"].tolist(), d15["low"].tolist(), d15["close"].tolist(), 14)

        # ── HTF trend через supertrend (calculate_trend) ──
        if d1h is not None and len(d1h) >= 100:
            d1h_idx = d1h.index
            d1h = calculate_trend(d1h.copy(), atr_period=43, factor=1.0)
            if not isinstance(d1h.index, pd.DatetimeIndex):
                d1h.index = d1h_idx[-len(d1h):]
        if d4h is not None and len(d4h) >= 100:
            d4h_idx = d4h.index
            d4h = calculate_trend(d4h.copy(), atr_period=43, factor=1.0)
            if not isinstance(d4h.index, pd.DatetimeIndex):
                d4h.index = d4h_idx[-len(d4h):]

        # Выровнять HTF на 15m (asof merge)
        if d1h is not None:
            h1 = d1h[["trendup", "trenddown"]].rename(
                columns={"trendup": "sup_up_1h", "trenddown": "sup_dn_1h"}
            )
            d15 = pd.merge_asof(
                d15.sort_index(), h1.sort_index(),
                left_index=True, right_index=True, direction="backward",
            )
        if d4h is not None:
            h4 = d4h[["trendup", "trenddown"]].rename(
                columns={"trendup": "sup_up_4h", "trenddown": "sup_dn_4h"}
            )
            d15 = pd.merge_asof(
                d15.sort_index(), h4.sort_index(),
                left_index=True, right_index=True, direction="backward",
            )

        w1 = d15["wt1"].values
        w2 = d15["wt2"].values
        close = d15["close"].values

        for i in range(5, len(d15) - 2):
            atr_val = atrs[i] if i < len(atrs) else (atrs[-1] if atrs else None)
            if atr_val is None:
                continue

            # ── 1h supertrend direction ──
            htf_up_1h = d15["sup_up_1h"].iloc[i] if "sup_up_1h" in d15.columns else np.nan
            htf_dn_1h = d15["sup_dn_1h"].iloc[i] if "sup_dn_1h" in d15.columns else np.nan
            # Supertrend: если trendup > trenddown → восходящий
            htf_bull_1h = not pd.isna(htf_up_1h) and not pd.isna(htf_dn_1h) and htf_up_1h > htf_dn_1h

            # ── 4h supertrend direction ──
            htf_up_4h = d15["sup_up_4h"].iloc[i] if "sup_up_4h" in d15.columns else np.nan
            htf_dn_4h = d15["sup_dn_4h"].iloc[i] if "sup_dn_4h" in d15.columns else np.nan
            htf_bull_4h = not pd.isna(htf_up_4h) and not pd.isna(htf_dn_4h) and htf_up_4h > htf_dn_4h

            # ── WT cross in zone ──
            long_cross = w1[i - 1] <= w2[i - 1] and w1[i] > w2[i] and w1[i] < args.os
            short_cross = w1[i - 1] >= w2[i - 1] and w1[i] < w2[i] and w1[i] > args.ob

            direction = None
            if long_cross:
                direction = "LONG"
            elif short_cross:
                direction = "SHORT"
            else:
                continue

            # ── OTE filter (опционально) ──
            if args.ote:
                sh, sl_ = nearest_swing(d15, i, lookback=50)
                if direction == "LONG":
                    if not in_ote_zone(close[i], sh, sl_, "LONG"):
                        continue
                else:
                    if not in_ote_zone(close[i], sh, sl_, "SHORT"):
                        continue

            tp_method = "fib" if args.tp_fib else "rr"
            r, exit_type = simulate(d15, i, direction, atr_val, tp_method=tp_method)
            if r is None:
                continue

            # ── Data era ──
            ts = pd.Timestamp(d15.index[i])
            if ts.tz is not None:
                ts = ts.tz_localize(None)
            era = "post_15apr" if ts >= DATA_ERA_CUT else "pre_15apr"

            # ── HTF context labels ──
            if direction == "LONG":
                res[("B", "LONG", era)].append(r)  # baseline
                if htf_bull_1h:
                    res[("1h_bull", "LONG", era)].append(r)  # 1h supertrend UP
                else:
                    res[("1h_bear", "LONG", era)].append(r)
                if htf_bull_4h:
                    res[("4h_bull", "LONG", era)].append(r)
                else:
                    res[("4h_bear", "LONG", era)].append(r)
            else:
                res[("B", "SHORT", era)].append(r)
                if not htf_bull_1h:
                    res[("1h_bear", "SHORT", era)].append(r)  # 1h DOWN = SHORT согласован
                else:
                    res[("1h_bull", "SHORT", era)].append(r)
                if not htf_bull_4h:
                    res[("4h_bear", "SHORT", era)].append(r)
                else:
                    res[("4h_bull", "SHORT", era)].append(r)

    def stat(xs):
        if not xs:
            return "n=0"
        wr = sum(1 for x in xs if x > 0) / len(xs) * 100
        return f"n={len(xs):4} avgR={sum(xs)/len(xs):+.3f} WR={wr:.0f}%"

    ote_label = " +OTE" if args.ote else ""
    tp_label = " FibTP" if args.tp_fib else " RR2"
    print(f"ARCH-127 v2 | pairs={len(syms)} | OS<{args.os} OB>{args.ob}{ote_label}{tp_label}")
    print(f"HTF: supertrend (43/1.0) | SL=1.5ATR | OTE: {'ON' if args.ote else 'OFF'} | TP: {'Fib' if args.tp_fib else 'RR=2'}")
    print()

    for era in ("post_15apr", "pre_15apr"):
        print(f"=== {era.upper()} ===")
        for d in ("LONG", "SHORT"):
            b = stat(res[("B", d, era)])
            print(f"  {'baseline':<18} {b}")
            for tf_key, tf_label in [("1h_bull", "1h UP"), ("1h_bear", "1h DOWN"),
                                      ("4h_bull", "4h UP"), ("4h_bear", "4h DOWN")]:
                if (tf_key, d, era) in res:
                    s = stat(res[(tf_key, d, era)])
                    tag = " <<<" if (
                        (d == "LONG" and "bull" in tf_key) or (d == "SHORT" and "bear" in tf_key)
                    ) else ""
                    print(f"  {tf_label:<18} {s}{tag}")
            print()


if __name__ == "__main__":
    main()
