# -*- coding: utf-8 -*-
"""Схема 1h→15m по GRT на барах, выгруженных с графика Егора: контекст часовика,
все кроссы 15m за последние сутки, и где схема вошла/вышла."""
import sys, json, os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
import pandas as pd
from core.indicators.indicators import calculate_wt

R = (r"C:\Users\yogoru\.claude\projects\e--MTF-BOT-CURSOR-crypto-volume-bot"
     r"\b9292ecd-40bf-480f-b583-11c47310bf19\tool-results")
F1 = os.path.join(R, "mcp-tradingview-data_get_ohlcv-1789098355195.txt")    # 1h
F15 = os.path.join(R, "mcp-tradingview-data_get_ohlcv-1789098715467.txt")   # 15m
MSK = pd.Timedelta(hours=3)


def load(f):
    j = json.load(open(f, encoding="utf-8"))
    d = pd.DataFrame(j["bars"])
    d["ts"] = pd.to_datetime(d.time, unit="s" if d.time.max() < 1e11 else "ms")
    d = d.sort_values("ts").reset_index(drop=True)
    w = calculate_wt(d[["open", "high", "low", "close"]])
    d["wt1"], d["wt2"] = w.wt1.values, w.wt2.values
    d["ma200"] = d.wt1.ewm(span=200, adjust=False).mean()
    x = d.wt1 - d.wt2
    d["cu"] = (x.shift(1) <= 0) & (x > 0)
    d["cd"] = (x.shift(1) >= 0) & (x < 0)
    return d


h1, m15 = load(F1), load(F15)
print(f"1h: {h1.ts.iloc[0]+MSK:%d.%m %H:%M} … {h1.ts.iloc[-1]+MSK:%d.%m %H:%M} МСК · "
      f"15m: {m15.ts.iloc[0]+MSK:%d.%m %H:%M} … {m15.ts.iloc[-1]+MSK:%d.%m %H:%M} МСК\n")

print("КРОССЫ НА 1h за период 15m-данных:")
t15_0 = m15.ts.iloc[0]
for _, r in h1[h1.ts >= t15_0 - pd.Timedelta(hours=12)].iterrows():
    if r.cu or r.cd:
        z = " ← в зоне OS (КОНТЕКСТ для лонга, если wt1<−70)" if (r.cu and r.wt1 < -60) else (
            " ← в зоне OB" if (r.cd and r.wt1 > 60) else "")
        print(f"  {r.ts+MSK:%d.%m %H:%M}  {'▲' if r.cu else '▼'}  wt1={r.wt1:+.1f}  "
              f"медиана200={r.ma200:+.1f}{z}")

print("\nКРОССЫ НА 15m (последние 96 баров = сутки):")
for _, r in m15.tail(96).iterrows():
    if r.cu or r.cd:
        z = " ←OS" if (r.cu and r.wt1 < -60) else (" ←OB" if (r.cd and r.wt1 > 60) else "")
        side = "над" if r.wt1 > r.ma200 else "под"
        print(f"  {r.ts+MSK:%d.%m %H:%M}  {'▲' if r.cu else '▼'}  wt1={r.wt1:+6.1f}  "
              f"({side} медианой {r.ma200:+.1f}){z}")

print("\nСХЕМА 1h→15m (контекст: ▲ на 1h при wt1<−70, жив 12 ч; вход: первый ▲ на 15m; "
      "выход: wt1 15m ≥ +60):")
ct1 = h1.ts + pd.Timedelta(hours=1)
ct15 = m15.ts + pd.Timedelta(minutes=15)
found = False
for i in h1.index[h1.cu & (h1.wt1 < -70)]:
    t0, t1 = ct1[i], ct1[i] + pd.Timedelta(hours=12)
    if t1 < m15.ts.iloc[0]:
        continue
    found = True
    ins = m15[(ct15 >= t0) & (ct15 <= t1) & m15.cu]
    head = f"  контекст 1h {h1.ts[i]+MSK:%d.%m %H:%M} (wt1={h1.wt1[i]:+.1f})"
    if not len(ins):
        print(head + " — на 15m не было ▲ в окне"); continue
    e = ins.index[0] + 1
    if e >= len(m15):
        print(head + " — вход на следующем баре"); continue
    ex = m15[(m15.index > e) & (m15.wt1 >= 60)]
    j = ex.index[0] if len(ex) else len(m15) - 1
    pnl = (m15.close[j] - m15.open[e]) / m15.open[e] * 100 - 0.35
    print(f"{head} → ВХОД {m15.ts[e]+MSK:%d.%m %H:%M} по {m15.open[e]:.5f} → "
          f"{'ВЫХОД ' + format(m15.ts[j]+MSK, '%d.%m %H:%M') if len(ex) else 'ОТКРЫТА, сейчас'} "
          f"{m15.close[j]:.5f} · {pnl:+.2f}%")
if not found:
    print("  за период 15m-данных контекста не было")
print(f"\nСЕЙЧАС: 1h wt1 {h1.wt1.iloc[-1]:+.1f} wt2 {h1.wt2.iloc[-1]:+.1f} · "
      f"15m wt1 {m15.wt1.iloc[-1]:+.1f} wt2 {m15.wt2.iloc[-1]:+.1f} медиана200 {m15.ma200.iloc[-1]:+.1f}")
