# -*- coding: utf-8 -*-
"""Отрицательный leg_span_bars — артефакт Pine или свойство самого движка?

Индикатор показал minor_leg_span_bars = -9. Проверяем ПИТОНОВСКИЙ движок
на той же истории: бывает ли extreme_i < origin_i у ноги.
"""
import json
import sys

import pandas as pd

sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
from core.smc.oko_sm_engine import run_structure  # noqa: E402

SRC = (r"C:\Users\yogoru\.claude\projects\e--MTF-BOT-CURSOR-crypto-volume-bot"
       r"\b9292ecd-40bf-480f-b583-11c47310bf19\tool-results"
       r"\mcp-tradingview-data_get_ohlcv-1788837988893.txt")
raw = json.load(open(SRC, encoding="utf-8"))
df = pd.DataFrame(raw["bars"])[["open", "high", "low", "close"]].astype(float)

for sw, iv in ((50, 5), (5, 3)):
    st = run_structure(df, swing_len=sw, internal_len=iv, record_legs=True)
    spans = [int(l["extreme_i"]) - int(l["origin_i"]) for l in st.leg_history
             if l and l.get("origin_i") is not None and l.get("extreme_i") is not None]
    neg = [s for s in spans if s < 0]
    print(f"swing_len={sw:2d} internal={iv}: ног {len(spans)}, "
          f"отрицательных span {len(neg)} ({len(neg)/max(len(spans),1)*100:.1f}%), "
          f"min={min(spans) if spans else 'na'}")
