# -*- coding: utf-8 -*-
"""BUILD → ПРОБОЙНАЯ: ретро гипотезы Егора (14.07 «build похож на пробойную! какой триггер дать?»).

OI-набор = ПОДГОТОВКА движения (накопление). Старый вход «в момент набора» ≈ 0− (3 оценки).
Проверяем: диапазон набора (N часов до BUILD) → ЖДАТЬ пробоя края → вход в сторону пробоя.

На живых build_signals (03-14.07, n≈1000, дедуп серий 4ч):
  вход A: close 15m-бара ЗА краем диапазона (пробой подтверждён закрытием)
  вход B (ретест): после пробоя ждать возврата к краю ±0.15% → вход от края
  SL = противоположный край диапазона; TP: 1.5R | фикс 2.5%. Touch, тай-брейк=SL, costs 0.11.
  Ожидание пробоя ≤24ч (нет — сетап истёк). Контроль: вход СРАЗУ по px в side из сигнала.
Данные: BingX 15m klines (сигналы свежие, истории хватает).
"""
import sys
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
import json
import sqlite3
import time
import urllib.request

RANGE_H = 4          # окно диапазона набора, часов до сигнала
WAIT_H = 24          # ждать пробоя, часов
HOLD_BARS = 192      # держать после входа max (48ч на 15m)
COSTS = 0.11
DEDUP_S = 4 * 3600

def klines(base, start_ms, limit=480):
    url = (f"https://open-api.bingx.com/openApi/swap/v3/quote/klines?symbol={base}-USDT"
           f"&interval=15m&startTime={start_ms}&limit={limit}")
    req = urllib.request.Request(url, headers={"User-Agent": "M"})
    for _ in range(2):
        try:
            d = json.load(urllib.request.urlopen(req, timeout=12)).get("data") or []
            return sorted(([int(k["time"]), float(k["open"]), float(k["high"]), float(k["low"]),
                            float(k["close"])] for k in d), key=lambda x: x[0])
        except Exception:
            time.sleep(0.6)
    return []

def sim(entry, sl, side, bars, tp_mode):
    risk = abs(entry - sl) / entry
    if risk <= 0.001 or risk > 0.12:
        return None
    tp = (entry + 1.5 * (entry - sl)) if (side == "LONG" and tp_mode == "rr15") else \
         (entry - 1.5 * (sl - entry)) if (side == "SHORT" and tp_mode == "rr15") else \
         entry * (1.025 if side == "LONG" else 0.975)
    for _, o, h, l, c in bars:
        hs, ht = (l <= sl, h >= tp) if side == "LONG" else (h >= sl, l <= tp)
        if hs:
            return (sl / entry - 1) * 100 * (1 if side == "LONG" else -1) - COSTS
        if ht:
            return (tp / entry - 1) * 100 * (1 if side == "LONG" else -1) - COSTS
    if bars:
        c = bars[-1][4]
        return (c / entry - 1) * 100 * (1 if side == "LONG" else -1) - COSTS
    return None

e = sqlite3.connect("oko_feed/external_data.db")
rows = e.execute("SELECT ts, symbol, side, px FROM build_signals ORDER BY ts").fetchall()
# дедуп серий: первый BUILD монеты в 4ч-окне
last = {}
sigs = []
for ts, sym, side, px in rows:
    if ts - last.get(sym, 0) >= DEDUP_S:
        sigs.append((ts, sym, side, px))
    last[sym] = ts
print(f"BUILD-сигналов {len(rows)} → после дедупа серий {len(sigs)}")

res = {"A_rr15": [], "A_fix25": [], "B_rr15": [], "C_atr_rr15": [], "CTRL_rr15": []}
import pandas as pd
from scripts.atr1h_wt_backtest import atr_trend
skipped = 0
for i, (ts, sym, side, px) in enumerate(sigs):
    start = (ts - 36 * 3600) * 1000   # 36ч назад: прогрев ATR-тренда (period=43) + диапазон
    bars = klines(sym, start)
    if len(bars) < RANGE_H * 4 + 8:
        skipped += 1
        continue
    sig_ms = ts * 1000
    pre = [b for b in bars if b[0] < sig_ms][-RANGE_H * 4:]
    post = [b for b in bars if b[0] >= sig_ms]
    if len(pre) < 8 or len(post) < 8:
        skipped += 1
        continue
    hi = max(b[2] for b in pre)
    lo = min(b[3] for b in pre)
    if hi <= lo:
        skipped += 1
        continue
    # контроль: вход сразу в side сигнала, SL = противокрай
    ctrl_sl = lo if side == "LONG" else hi
    n = sim(px, ctrl_sl, side, post[:HOLD_BARS], "rr15")
    if n is not None:
        res["CTRL_rr15"].append(n)
    # ждать пробоя (close за краем) в WAIT_H
    br_i, br_side = None, None
    for j, b in enumerate(post[:WAIT_H * 4]):
        if b[4] > hi:
            br_i, br_side, br_px = j, "LONG", b[4]
            break
        if b[4] < lo:
            br_i, br_side, br_px = j, "SHORT", b[4]
            break
    if br_i is None:
        continue
    sl_bo = lo if br_side == "LONG" else hi
    after = post[br_i + 1: br_i + 1 + HOLD_BARS]
    for mode, key in (("rr15", "A_rr15"), ("fix25", "A_fix25")):
        n = sim(br_px, sl_bo, br_side, after, mode)
        if n is not None:
            res[key].append(n)
    # B: ретест края после пробоя (±0.15%) в течение 8ч
    edge = hi if br_side == "LONG" else lo
    rt_i = None
    for j2, b in enumerate(after[:32]):
        if (br_side == "LONG" and b[3] <= edge * 1.0015) or (br_side == "SHORT" and b[2] >= edge * 0.9985):
            rt_i = j2
            break
    if rt_i is not None:
        n = sim(edge, sl_bo, br_side, after[rt_i + 1: rt_i + 1 + HOLD_BARS], "rr15")
        if n is not None:
            res["B_rr15"].append(n)
    # C (Егор 14.07 «смена atr тренда как триггер?»): после BUILD ждать ФЛИПА ATR-тренда
    # 15m (боевые 43/1.25) ≤24ч → вход close бара флипа в сторону флипа, SL=противокрай
    try:
        dfa = pd.DataFrame(bars, columns=["t", "open", "high", "low", "close"])
        tr = atr_trend(dfa)
        sig_idx = next((k for k, b in enumerate(bars) if b[0] >= sig_ms), None)
        if sig_idx and sig_idx > 50:
            fl_i = fl_side = None
            for k in range(sig_idx + 1, min(sig_idx + 1 + WAIT_H * 4, len(bars))):
                if tr[k] == 1 and tr[k - 1] == -1:
                    fl_i, fl_side = k, "LONG"; break
                if tr[k] == -1 and tr[k - 1] == 1:
                    fl_i, fl_side = k, "SHORT"; break
            if fl_i is not None:
                sl_c = lo if fl_side == "LONG" else hi
                n = sim(bars[fl_i][4], sl_c, fl_side, bars[fl_i + 1: fl_i + 1 + HOLD_BARS], "rr15")
                if n is not None:
                    res["C_atr_rr15"].append(n)
    except Exception:
        pass
    if i % 50 == 0:
        print(f"  …{i}/{len(sigs)}")
    time.sleep(0.12)

print(f"\nпропущено (нет данных/диапазона): {skipped}")
for k, v in res.items():
    if not v:
        continue
    wr = 100 * sum(1 for x in v if x > 0) / len(v)
    h25 = 100 * sum(1 for x in v if x >= 2.5) / len(v)
    print(f"{k:10} n={len(v):4} net={sum(v)/len(v):+.3f}%/сд WR={wr:.0f}% 2.5%+={h25:.0f}%")
