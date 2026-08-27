# -*- coding: utf-8 -*-
"""RR-ПРИЗНАК НА ВСЕХ ТФ: рыночная ли характеристика? (13.08.2026, DS).

Открытый вопрос research [[2026-08-12-Fade-Side-Flip-Full-Data]]:
RR = median(сумма доходностей за 12 баров ПОСЛЕ шока |r|>2σ)/σ на окне 200 баров 4h
меняет знак на переломе fade-стороны (LONG-окна +0.340 vs SHORT-окна −0.314, z=7.87).
Но: перекрытие окон 86%, независимых 6, перелом ОДИН → FPR не оценить.

Если RR — РЫНОЧНАЯ характеристика (восстановление после шоков), то он обязан
разделять окна LONG/SHORT и на других ТФ (5m/15m/1h) для ТОЙ ЖЕ fade-механики,
на ОДНОМ календарном периоде. Здесь:
  - механика фейда 1:1 с [[fade_matrix_tf_side_phase]] (ATRTrend+WT, SL=swing, TP1R, TTL24);
  - LB = 33 календарных дня на каждом ТФ (эквивалент 200 баров 4h), горизонт шока 12 баров;
  - роллинг-окна 7 мес / шаг 1 мес — те же, что в [[fade_rolling_side_flip]].

Критерий: RR разделяет окна (диапазоны не пересекаются ИЛИ z>2) на КАЖДОМ ТФ,
и перелом стороны совпадает с переломом знака RR.

Запуск:  python scripts/fade_rr_by_tf.py [с 2024-01 по умолчанию]
"""
import datetime as dt
import sqlite3
import sys
import warnings
from collections import defaultdict

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

DB = "ohlcv_cache.db"
COST = 0.35
COOL = {"5m": 72, "15m": 24, "1h": 6, "4h": 2}
# 33 календарных дня в барах каждого ТФ (эквивалент 200×4h)
BARS_33D = {"5m": 9504, "15m": 3168, "1h": 792, "4h": 198}
NCOIN = {"5m": 12, "15m": 20, "1h": 30, "4h": 45}
TFS = ["5m", "15m", "1h", "4h"]
SINCE_Y = int(sys.argv[1]) if len(sys.argv) > 1 else 2024  # бычий контроль: 2022 (покрывает 2023)
WIN_M, STEP_M = 7.0, 1.0


def wt(df, n1=10, n2=21):
    hlc = (df.high + df.low + df.close) / 3
    esa = hlc.ewm(span=n1).mean()
    d = (hlc - esa).abs().ewm(span=n1).mean()
    return ((hlc - esa) / (0.015 * d.replace(0, np.nan))).ewm(span=n2).mean().fillna(0).values


def atrt(df, period=43, factor=1.25):
    h, l, c = df.high, df.low, df.close
    hl2 = ((h + l) / 2).values
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean().values
    up = hl2 - factor * atr; dn = hl2 + factor * atr
    n = len(c); cv = c.values
    u = np.zeros(n); d_ = np.zeros(n); dirn = np.zeros(n)
    u[0], d_[0], dirn[0] = up[0], dn[0], 1
    for i in range(1, n):
        u[i] = max(up[i], u[i-1]) if cv[i-1] > u[i-1] else up[i]
        d_[i] = min(dn[i], d_[i-1]) if cv[i-1] < d_[i-1] else dn[i]
        dirn[i] = 1 if cv[i] > d_[i-1] else (-1 if cv[i] < u[i-1] else dirn[i-1])
    return dirn


def ex_tp1r(i, H, L, C, sl, side, ttl=24):
    e = C[i]
    if side == "LONG":
        tp = e + (e - sl); end = min(i + ttl, len(C) - 1)
        for j in range(i + 1, end + 1):
            if L[j] <= sl: return (sl - e) / e * 100
            if H[j] >= tp: return (tp - e) / e * 100
        return (C[end] - e) / e * 100
    tp = e - (sl - e); end = min(i + ttl, len(C) - 1)
    for j in range(i + 1, end + 1):
        if H[j] >= sl: return (e - sl) / e * 100
        if L[j] <= tp: return (e - tp) / e * 100
    return (e - C[end]) / e * 100


def rr_feat(r, i, lb):
    """RR по прошлым барам [i-lb, i): медиана суммы 12-барных доходностей после шока |r|>2σ, /σ."""
    w = r[i - lb:i]
    w = w[np.isfinite(w)]
    if len(w) < lb * 0.8:
        return np.nan
    sd = w.std()
    if sd <= 0:
        return np.nan
    shock = np.where(np.abs(w) > 2 * sd)[0]
    shock = shock[shock < len(w) - 12]
    if len(shock) < 5:
        return np.nan
    return float(np.median([w[k + 1:k + 13].sum() for k in shock]) / sd)


t0 = int(dt.datetime(SINCE_Y, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
MS_M = 30.44 * 24 * 3600 * 1000

print("═" * 108)
print("RR-ПРИЗНАК НА ВСЕХ ТФ (рыночная ли характеристика?) · fade-механика 1:1 · LB=33 календ. дня")
print(f"окно с {SINCE_Y}-01 · роллинг {WIN_M} мес / шаг {STEP_M} · горизонт восстановления 12 баров ТФ")
print("═" * 108)

summary = []
for tf in TFS:
    lb = BARS_33D[tf]
    con = sqlite3.connect(DB)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe=? AND time>=? "
        "GROUP BY symbol HAVING n>? ORDER BY n DESC LIMIT ?",
        (tf, t0, lb * 2, NCOIN[tf])).fetchall()]
    con.close()
    DATA, turn = {}, {}
    for s in syms:
        c = sqlite3.connect(DB)
        d = pd.read_sql("SELECT time,high,low,close,volume FROM ohlcv_cache WHERE symbol=? "
                        "AND timeframe=? AND time>=? ORDER BY time", c, params=(s, tf, t0))
        c.close()
        if len(d) >= lb * 2:
            DATA[s] = d
            turn[s] = float(np.nanmedian((d.close * d.volume).values))
    if not DATA:
        print(f"\n[{tf}] данных нет — пропуск")
        continue
    mt = np.nanmedian(list(turn.values()))
    liq = [s for s in DATA if turn[s] >= mt]

    sig = []  # (ts, side, net, rr)
    for s in liq:
        d = DATA[s]
        w_ = wt(d); tr_ = atrt(d)
        H, L, C, T = d.high.values, d.low.values, d.close.values, d.time.values
        r = np.concatenate([[np.nan], np.diff(C) / C[:-1] * 100])
        last = {"LONG": -10**9, "SHORT": -10**9}
        for i in range(max(lb + 5, 210), len(d) - 1):
            for side in ("LONG", "SHORT"):
                if i - last[side] < COOL[tf]:
                    continue
                if side == "LONG":
                    if not (tr_[i] > 0 and w_[i] < -60 and w_[i] > w_[i-1]):
                        continue
                    sl = L[max(0, i-3):i+1].min() * 0.997
                    if sl >= C[i]: continue
                    sp = (C[i] - sl) / C[i] * 100
                else:
                    if not (tr_[i] < 0 and w_[i] > 60 and w_[i] < w_[i-1]):
                        continue
                    sl = H[max(0, i-3):i+1].max() * 1.003
                    if sl <= C[i]: continue
                    sp = (sl - C[i]) / C[i] * 100
                if not (4.0 < sp <= 12.0):
                    continue
                last[side] = i
                sig.append((int(T[i]), side, ex_tp1r(i, H, L, C, sl, side) - COST, rr_feat(r, i, lb)))
    if len(sig) < 40:
        print(f"\n[{tf}] сигналов {len(sig)} — мало, пропуск")
        continue
    sig.sort()
    print(f"\n── {tf} ── сигналов {len(sig)} (LONG {sum(1 for x in sig if x[1]=='LONG')} · "
          f"SHORT {sum(1 for x in sig if x[1]=='SHORT')}) · монет {len(liq)}")

    rows = []
    cur = sig[0][0]
    t_max = sig[-1][0]
    while cur + WIN_M * MS_M <= t_max + STEP_M * MS_M:
        lo, hi = cur, cur + WIN_M * MS_M
        win = [x for x in sig if lo <= x[0] < hi]
        L_ = [x[2] for x in win if x[1] == "LONG"]
        S_ = [x[2] for x in win if x[1] == "SHORT"]
        if len(L_) >= 20 and len(S_) >= 20:
            lead = "LONG" if np.median(L_) > np.median(S_) else "SHORT"
            rr = float(np.nanmedian([x[3] for x in win]))
            rows.append((dt.datetime.fromtimestamp(lo/1000, dt.timezone.utc).strftime("%Y-%m"),
                         lead, float(np.median(L_)), float(np.median(S_)), rr))
        cur += STEP_M * MS_M

    n_long = sum(1 for _, l, *_ in rows if l == "LONG")
    n_short = len(rows) - n_long
    a = [x[4] for x in rows if x[1] == "LONG" and np.isfinite(x[4])]
    b = [x[4] for x in rows if x[1] == "SHORT" and np.isfinite(x[4])]
    line = f"[{tf}] окон {len(rows)}: LONG ведёт {n_long}, SHORT {n_short}"
    if len(a) >= 3 and len(b) >= 3:
        ma, mb = np.mean(a), np.mean(b)
        sd = np.sqrt(np.var(a)/len(a) + np.var(b)/len(b))
        z = (ma - mb) / sd if sd > 0 else 0
        sep = "РАЗДЕЛЯЕТ" if (min(a) > max(b) or min(b) > max(a)) else ("частично" if abs(z) > 2 else "НЕТ")
        line += f" · RR LONG-окна {ma:+.3f} vs SHORT-окна {mb:+.3f} · z={z:+.2f} → {sep}"
    print(line)
    # переломы
    prev = None
    for d0, lead, *_ in rows:
        if prev and lead != prev:
            print(f"    ⚡ перелом {d0}: {prev} → {lead}")
        prev = lead
    summary.append((tf, rows))
    # печать окна вокруг перелома 2025-08 (если есть)
    for d0, lead, ml, ms, rr in rows:
        if d0 in ("2025-06", "2025-07", "2025-08", "2025-09", "2025-11", "2026-01"):
            print(f"    {d0}: {lead} · LONG {ml:+.2f}% SHORT {ms:+.2f}% · RR {rr:+.3f}")

print("\n" + "═" * 108)
print("ВЫВОД: если RR разделяет окна на ВСЕХ ТФ и перелом знака совпадает с 2025-08 — рыночный признак.")
print("Если только на 4h — артефакт связки 4h-fade, переключатель строить НЕЛЬЗЯ.")
print("═" * 108)
