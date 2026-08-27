# -*- coding: utf-8 -*-
"""РОЛЛИНГ-ОКНА: когда и НАСКОЛЬКО устойчиво перевернулась сторона фейда (12.08.2026).

Повод: разделяющий тест показал, что в 2026 лонг-фейд мёртв (WR 17-26%), а шорт-фейд
живёт (WR 54-63%) — и это ПЕРИОД, а не состав монет
([[fade_side_flip_2026_period_not_survivorship]]). Но окно 2026 короткое (6.9 мес),
и «переворот» может быть шумом. Тест, предложенный DS и роем: скользящее окно
фиксированной длины со сдвигом 1 месяц по всей истории.

Если LONG стабильно хорош до 2026 и падает ровно в 2026 → смена режима.
Если знак скачет из окна в окно → шум, переключатель строить НЕЛЬЗЯ.

Сигналы собираются ОДИН раз, затем нарезаются по окнам — быстро.
Правила 1:1 с матрицей: 4h, TP1R, TTL 24, стоп 4-12%, косты 0.35%, вход на развороте WT.

Запуск:  python scripts/fade_rolling_side_flip.py [n_монет=60] [окно_мес=7] [шаг_мес=1]
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
NCOIN = int(sys.argv[1]) if len(sys.argv) > 1 else 60
WIN_M = float(sys.argv[2]) if len(sys.argv) > 2 else 7.0
STEP_M = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
TF, COST, COOL = "4h", 0.35, 2
# 🔑 Егор: «WR складывается из входа и выхода» → вывод о перевороте обязан держаться
# при РАЗНЫХ выходах, иначе это свойство связки, а не рынка.
EXIT_MODE = sys.argv[4] if len(sys.argv) > 4 else "tp1r"   # tp1r|tp2r|ttl|tp1r_ttl48


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


def ex_tp1r(i, H, L, C, sl, side, mode="tp1r"):
    """Выход. mode: tp1r (1R/TTL24) · tp2r (2R/TTL24) · ttl (без TP, только SL+TTL24) ·
    tp1r_ttl48 (1R, но держим вдвое дольше). Стоп есть всегда."""
    e = C[i]
    rr = {"tp1r": 1.0, "tp2r": 2.0, "ttl": None, "tp1r_ttl48": 1.0}[mode]
    ttl = 48 if mode == "tp1r_ttl48" else 24
    end = min(i + ttl, len(C) - 1)
    if side == "LONG":
        tp = e + rr * (e - sl) if rr else None
        for j in range(i + 1, end + 1):
            if L[j] <= sl: return (sl - e) / e * 100
            if tp and H[j] >= tp: return (tp - e) / e * 100
        return (C[end] - e) / e * 100
    tp = e - rr * (sl - e) if rr else None
    for j in range(i + 1, end + 1):
        if H[j] >= sl: return (e - sl) / e * 100
        if tp and L[j] <= tp: return (e - tp) / e * 100
    return (e - C[end]) / e * 100


t0 = int(dt.datetime(2023, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
con = sqlite3.connect(DB)
syms = [r[0] for r in con.execute(
    "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe=? AND time>=? "
    "GROUP BY symbol HAVING n>? ORDER BY n DESC LIMIT ?", (TF, t0, 182 * 6, NCOIN)).fetchall()]
con.close()

DATA, turn = {}, {}
for s in syms:
    c = sqlite3.connect(DB)
    d = pd.read_sql("SELECT time,high,low,close,volume FROM ohlcv_cache WHERE symbol=? "
                    "AND timeframe=? AND time>=? ORDER BY time", c, params=(s, TF, t0))
    c.close()
    if len(d) >= 182 * 4:
        DATA[s] = d
        turn[s] = float(np.nanmedian((d.close * d.volume).values))
mt = np.nanmedian(list(turn.values()))
liq = [s for s in DATA if turn[s] >= mt]
print(f"монет {len(DATA)} / ликвидных {len(liq)} · ТФ {TF} · окно {WIN_M} мес, шаг {STEP_M} мес\n",
      file=sys.stderr)

sig = []          # (ts_ms, side, net, phase)  phase — ПРИЧИННО (дрейф 200 баров ДО входа)
for s in liq:
    d = DATA[s]
    w = wt(d); tr_ = atrt(d)
    H, L, C, T = d.high.values, d.low.values, d.close.values, d.time.values
    last = {"LONG": -10**9, "SHORT": -10**9}
    for i in range(210, len(d) - 1):
        drift = (C[i] - C[i-200]) / C[i-200] * 100
        phase = 'БЫК' if drift > 3 else ('МЕДВ' if drift < -3 else 'НЕЙТР')
        for side in ("LONG", "SHORT"):
            if i - last[side] < COOL:
                continue
            if side == "LONG":
                if not (tr_[i] > 0 and w[i] < -60 and w[i] > w[i-1]):
                    continue
                sl = L[max(0, i-3):i+1].min() * 0.997
                if sl >= C[i]:
                    continue
                sp = (C[i] - sl) / C[i] * 100
            else:
                if not (tr_[i] < 0 and w[i] > 60 and w[i] < w[i-1]):
                    continue
                sl = H[max(0, i-3):i+1].max() * 1.003
                if sl <= C[i]:
                    continue
                sp = (sl - C[i]) / C[i] * 100
            if not (4.0 < sp <= 12.0):
                continue
            last[side] = i
            sig.append((int(T[i]), side, ex_tp1r(i, H, L, C, sl, side, EXIT_MODE) - COST, phase))

sig.sort()
print(f"сигналов собрано: {len(sig)} (LONG {sum(1 for x in sig if x[1]=='LONG')} · "
      f"SHORT {sum(1 for x in sig if x[1]=='SHORT')})\n")

MS_M = 30.44 * 24 * 3600 * 1000
t_min, t_max = sig[0][0], sig[-1][0]
print("═" * 96)
print(f"РОЛЛИНГ-ОКНА {WIN_M} мес, шаг {STEP_M} мес · ВЫХОД={EXIT_MODE} · медиана % net по стороне")
print("Стабильный знак = смена режима. Скачущий знак = шум, переключатель строить НЕЛЬЗЯ.")
print("═" * 96)
print(f"{'окно (начало)':<16} {'LONG n':>7} {'LONG мед':>10} {'SHORT n':>8} {'SHORT мед':>11}   ведёт  преобл.фаза")
flips = []
cur = t_min
while cur + WIN_M * MS_M <= t_max + STEP_M * MS_M:
    lo, hi = cur, cur + WIN_M * MS_M
    L_ = [x[2] for x in sig if lo <= x[0] < hi and x[1] == "LONG"]
    S_ = [x[2] for x in sig if lo <= x[0] < hi and x[1] == "SHORT"]
    d0 = dt.datetime.fromtimestamp(lo / 1000, dt.timezone.utc).strftime("%Y-%m")
    if len(L_) >= 20 and len(S_) >= 20:
        ml, ms = float(np.median(L_)), float(np.median(S_))
        lead = "LONG" if ml > ms else "SHORT"
        flips.append((d0, lead, ml, ms))
        ph = [x[3] for x in sig if lo <= x[0] < hi]
        dom = max(set(ph), key=ph.count) if ph else "?"
        share = 100*ph.count(dom)/len(ph) if ph else 0
        print(f"{d0:<16} {len(L_):>7} {ml:>+9.2f}% {len(S_):>8} {ms:>+10.2f}%   {lead:<6} фаза {dom} {share:.0f}%")
    else:
        print(f"{d0:<16} {len(L_):>7} {'—':>10} {len(S_):>8} {'—':>11}   мало данных")
    cur += STEP_M * MS_M

if flips:
    n_long = sum(1 for _, l, _, _ in flips if l == "LONG")
    print(f"\nокон всего {len(flips)}: ведёт LONG в {n_long}, SHORT в {len(flips)-n_long}")
    # где произошёл перелом
    prev = None
    for d0, lead, ml, ms in flips:
        if prev and lead != prev:
            print(f"  ⚡ ПЕРЕЛОМ на окне {d0}: {prev} → {lead}")
        prev = lead
    print("\nЕсли переломов 1-2 и они разделяют историю на большие куски — режим реален.")
    print("Если переломов много и они чередуются — это шум, переключатель НЕ строить.")
