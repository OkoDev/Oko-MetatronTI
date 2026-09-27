# -*- coding: utf-8 -*-
"""ПОЛНЫЙ СНИМОК ПРИЗНАКОВ В ЭТАЛОНЕ: HYPE, 02.08.2026, минимум 51.107.

Все флаги compute_flags + числовые индикаторы, на КАЖДОМ ТФ лестницы,
в трёх точках: дно · момент CHoCH на 1m (вход) · +6 часов.
Каузально: берётся последний ЗАКРЫТЫЙ бар ТФ на указанный момент.
"""
import os, sys, bisect, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.calculators.combinator_core import compute_flags
from core.indicators.indicators import calculate_wt

TFS = [1, 3, 5, 15, 30, 60, 240]
d1 = pd.read_parquet(r"C:\oko_history\1m\HYPEUSDT.parquet")
w = d1.loc["2026-08-01":"2026-08-03"]
T_LOW = w["low"].idxmin(); P_LOW = w["low"].min()
POINTS = [(T_LOW, "ДНО"),
          (T_LOW + pd.Timedelta(hours=2, minutes=12), "ВХОД (CHoCH 1m)"),
          (T_LOW + pd.Timedelta(hours=6), "+6 часов")]
print(f"HYPE · дно {P_LOW:.3f} в {T_LOW}\n")


def resample(tf):
    if tf == 1:
        return d1[["open", "high", "low", "close", "volume"]]
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last(),
                         "volume": r["volume"].sum()}).dropna()


cache = {}
for tf in TFS:
    d = resample(tf)
    d.index.name = "ts"
    fl = compute_flags(d, label="x")
    fl.columns = [c[:-2] if c.endswith("_x") else c for c in fl.columns]
    wd = calculate_wt(d.reset_index(drop=True))
    cache[tf] = (d, fl, wd)
    print(f"  {tf}m: {len(d):,} баров, признаков {len(fl.columns)}", flush=True)

for tpoint, lbl in POINTS:
    print(f"\n{'='*100}")
    px = d1["close"].asof(tpoint)
    print(f"{lbl}   {tpoint}   цена {px:.3f}   ({(px-P_LOW)/P_LOW*100:+.2f}% от дна)")
    print("=" * 100)
    for tf in TFS:
        d, fl, wd = cache[tf]
        ct = list(d.index + pd.Timedelta(minutes=tf))
        k = bisect.bisect_right(ct, tpoint) - 1
        if k < 5:
            continue
        row = fl.iloc[k]
        true_flags = []
        for c in fl.columns:
            v = row[c]
            if isinstance(v, (bool, np.bool_)) and bool(v):
                true_flags.append(c)
            elif isinstance(v, (int, np.integer, float, np.floating)) and \
                    not isinstance(v, (bool, np.bool_)):
                pass
        nums = {}
        for c in ["wt1", "wt2"]:
            if c in wd.columns:
                nums[c] = wd[c].values[k]
        for c in fl.columns:
            v = row[c]
            if isinstance(v, (float, np.floating)) and not np.isnan(v) and \
                    c.startswith(("rsi", "atr_prank", "atr_p")):
                nums[c] = float(v)
        print(f"\n  ── {tf}m (окно {tf*10} мин) · бар {d.index[k]:%d.%m %H:%M} · "
              f"close {d['close'].values[k]:.3f}")
        if nums:
            print("     числовые: " + " · ".join(
                f"{k_}={v_:+.1f}" if abs(v_) > 1 else f"{k_}={v_:+.3f}"
                for k_, v_ in nums.items()))
        if true_flags:
            for i in range(0, len(true_flags), 4):
                print("     " + " · ".join(f"{x:<26}" for x in true_flags[i:i+4]))
        else:
            print("     (ни один флаг не взведён)")
