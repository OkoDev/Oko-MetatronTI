# -*- coding: utf-8 -*-
"""Сверка Pine-порта OKO Wave против Python-движка на ОДНИХ И ТЕХ ЖЕ барах.

Бары выгружены из TradingView (BINGX:SEIUSDT.P, 1h, 500 шт).
Считаем то же, что панель индикатора, и печатаем для построчного сравнения.
"""
import json
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")

from core.smc.oko_sm_engine import run_structure                      # noqa: E402
from core.indicators.indicators import (find_swing_highs, find_swing_lows,  # noqa: E402
                                        calculate_n_down, calculate_n_up)

SRC = (r"C:\Users\yogoru\.claude\projects\e--MTF-BOT-CURSOR-crypto-volume-bot"
       r"\b9292ecd-40bf-480f-b583-11c47310bf19\tool-results"
       r"\mcp-tradingview-data_get_ohlcv-1788837988893.txt")

raw = json.load(open(SRC, encoding="utf-8"))
df = pd.DataFrame(raw["bars"])[["open", "high", "low", "close"]].astype(float)
n = len(df)
print(f"баров: {n}")


def atr_ewm(d, alpha=1 / 43):
    tr = pd.concat([d.high - d.low, (d.high - d.close.shift()).abs(),
                    (d.low - d.close.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=alpha, adjust=False).mean()


st = run_structure(df, swing_len=50, internal_len=5, record_legs=True)
lg = st.leg_history[-1]
atr = float(atr_ewm(df).iloc[-1])
close = float(df.close.iloc[-1])

print(f"trend={st.trend}  itrend={st.itrend}")
if not lg:
    print("НОГИ НЕТ")
else:
    o, e = float(lg["origin"]), float(lg["extreme"])
    oi, ei = int(lg["origin_i"]), int(lg["extreme_i"])
    span = e - o
    pos = (close - o) / span
    minor = sum(1 for ev in st.events
                if getattr(ev, "internal", False) and oi < getattr(ev, "i", -1) <= n - 1)
    age_o = (n - 1) - oi
    print(f"leg_dir        = {1 if lg['trend'] == 'long' else -1}")
    print(f"leg_pos        = {pos:.5f}")
    print(f"leg_retr       = {1 - pos:.5f}")
    print(f"leg_span_bars  = {ei - oi}")
    print(f"leg_age_origin = {age_o}")
    print(f"leg_age_extreme= {(n - 1) - ei}")
    print(f"leg_amp_pct    = {abs(span) / o * 100:.5f}")
    print(f"leg_amp_atr    = {abs(span) / atr:.5f}")
    print(f"leg_speed_atr  = {abs(span) / atr / (ei - oi):.5f}" if ei != oi else "leg_speed_atr = na")
    print(f"leg_minor_breaks = {minor}")
    print(f"leg_minor_per100 = {minor / age_o * 100:.5f}" if age_o else "")

# счёт волн на этом же ряду (period 5) — в индикаторе это MTF 1h = сам график
nd = calculate_n_down(find_swing_highs(df["high"], period=5))
nu = calculate_n_up(find_swing_lows(df["low"], period=5))
print(f"n_down / n_up (period 5, этот ряд) = {nd} / {nu}")

# htf_dir по определению WaveService._htf_dir на этом ряду
c = df["close"].values
hi, lo = df["high"].values, df["low"].values
move = float(c[-1] - c[-1 - 5])
rng = float(np.mean(hi[-5:] - lo[-5:]))
print(f"htf_dir(этот ряд) = {'up' if move > 0.5 * rng else 'down' if move < -0.5 * rng else 'flat'}"
      f"  (move={move:.6f} rng={rng:.6f})")
