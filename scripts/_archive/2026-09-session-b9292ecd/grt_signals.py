# -*- coding: utf-8 -*-
"""Мои сигналы по GRT на барах, выгруженных прямо с графика TradingView Егора."""
import sys, json, os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
import pandas as pd
from core.indicators.indicators import calculate_wt

R = (r"C:\Users\yogoru\.claude\projects\e--MTF-BOT-CURSOR-crypto-volume-bot"
     r"\b9292ecd-40bf-480f-b583-11c47310bf19\tool-results")
F4 = os.path.join(R, "mcp-tradingview-data_get_ohlcv-1789098559882.txt")
F1 = os.path.join(R, "mcp-tradingview-data_get_ohlcv-1789098355195.txt")
MSK = pd.Timedelta(hours=3)


def load(f):
    j = json.load(open(f, encoding="utf-8"))
    d = pd.DataFrame(j["bars"])
    d["ts"] = pd.to_datetime(d.time, unit="s" if d.time.max() < 1e11 else "ms")
    d = d.sort_values("ts").reset_index(drop=True)
    w = calculate_wt(d[["open", "high", "low", "close"]])
    d["wt1"], d["wt2"] = w.wt1.values, w.wt2.values
    x = d.wt1 - d.wt2
    d["cu"] = (x.shift(1) <= 0) & (x > 0)
    d["cd"] = (x.shift(1) >= 0) & (x < 0)
    return d


h4, h1 = load(F4), load(F1)
print("КРОССЫ НА 4h (последние 60 баров), время МСК открытия бара:")
for _, r in h4.tail(60).iterrows():
    if r.cu or r.cd:
        z = " ← в зоне OS" if (r.cu and r.wt1 < -60) else (" ← в зоне OB" if (r.cd and r.wt1 > 60) else "")
        print(f"  {r.ts + MSK:%d.%m %H:%M}  {'▲ вверх' if r.cu else '▼ вниз'}  wt1={r.wt1:+.1f}{z}")

print("\nСИГНАЛЫ СХЕМЫ 4h→1h (контекст: ▲ на 4h при wt1<−70, жив 12 баров 4h = 48 ч; "
      "вход: первый ▲ на 1h по open следующего бара; выход: wt1 1h ≥ +60):")
ct4 = h4.ts + pd.Timedelta(hours=4)
ct1 = h1.ts + pd.Timedelta(hours=1)
for i in h4.index[h4.cu & (h4.wt1 < -70)]:
    t0, t1 = ct4[i], ct4[i] + pd.Timedelta(hours=48)
    ins = h1[(ct1 >= t0) & (ct1 <= t1) & h1.cu]
    head = f"  контекст 4h {h4.ts[i] + MSK:%d.%m %H:%M} (wt1={h4.wt1[i]:+.1f})"
    if not len(ins):
        print(head + " — на 1h нет данных или не было кросса ▲ в окне"); continue
    e = ins.index[0] + 1
    if e >= len(h1):
        print(head + " — вход ещё не наступил"); continue
    ex = h1[(h1.index > e) & (h1.wt1 >= 60)]
    j = ex.index[0] if len(ex) else len(h1) - 1
    pnl = (h1.close[j] - h1.open[e]) / h1.open[e] * 100 - 0.35
    print(f"{head} → ВХОД 1h {h1.ts[e] + MSK:%d.%m %H:%M} по {h1.open[e]:.5f} → ВЫХОД "
          f"{h1.ts[j] + MSK:%d.%m %H:%M} по {h1.close[j]:.5f} "
          f"{'(зона +60)' if len(ex) else '(ещё открыта)'} · {pnl:+.2f}% после костов")

print(f"\nПоследний бар: 4h wt1 {h4.wt1.iloc[-1]:+.1f} / wt2 {h4.wt2.iloc[-1]:+.1f} · "
      f"1h wt1 {h1.wt1.iloc[-1]:+.1f} / wt2 {h1.wt2.iloc[-1]:+.1f}")
