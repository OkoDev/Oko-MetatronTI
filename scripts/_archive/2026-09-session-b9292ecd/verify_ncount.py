# -*- coding: utf-8 -*-
"""Почему n_up разошёлся: смотрим сами пивоты."""
import json
import sys

import pandas as pd

sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
from core.indicators.indicators import find_swing_highs, find_swing_lows  # noqa: E402

SRC = (r"C:\Users\yogoru\.claude\projects\e--MTF-BOT-CURSOR-crypto-volume-bot"
       r"\b9292ecd-40bf-480f-b583-11c47310bf19\tool-results"
       r"\mcp-tradingview-data_get_ohlcv-1788837988893.txt")
raw = json.load(open(SRC, encoding="utf-8"))
df = pd.DataFrame(raw["bars"])[["open", "high", "low", "close"]].astype(float)
n = len(df)

sh = find_swing_highs(df["high"], period=5)
sl = find_swing_lows(df["low"], period=5)
print("последние swing highs:", [(p["index"], p["value"]) for p in sh[-6:]])
print("последние swing lows :", [(p["index"], p["value"]) for p in sl[-6:]])
print("баров:", n)

# инкрементальный счёт — так считает Pine (var-состояние), должен совпасть с calculate_n_*
nd = nu = 0
prev = None
for p in sh:
    nd = nd + 1 if prev is not None and p["value"] < prev else 0
    prev = p["value"]
prev = None
for p in sl:
    nu = nu + 1 if prev is not None and p["value"] > prev else 0
    prev = p["value"]
print(f"инкрементально: n_down={nd}  n_up={nu}")
