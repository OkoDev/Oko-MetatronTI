import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
import os
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
import pandas as pd
from core.calculators.combinator_core import _wtx_divergences
from core.indicators.indicators import calculate_wt
d = pd.read_parquet(r"C:\oko_history\1m\BCHUSDT.parquet")
for tf in (3, 15, 60):
    dd = d.resample(f"{tf}min", label="left", closed="left").agg(
        {"open":"first","high":"max","low":"min","close":"last"}).dropna()
    w = calculate_wt(dd.reset_index(drop=True))
    b, be, bh, beh = _wtx_divergences(w["wt1"].values, dd["low"].values, dd["high"].values)
    print(f"{tf:>3}m  bars {len(b):>7,}  R+ {b.mean()*100:5.2f}%  R- {be.mean()*100:5.2f}%  "
          f"H+ {bh.mean()*100:5.2f}%  bull(R+ or H+) {(b|bh).mean()*100:5.2f}%")
