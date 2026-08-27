# -*- coding: utf-8 -*-
"""ПРИЧИННЫЙ ПРИЗНАК ПЕРЕВОРОТА СТОРОНЫ: проверка кандидатов DS (12.08.2026).

Установлено: механика фейда перевернула сторону в 08.2025 (роллинг 36 окон, 2 перелома,
инвариантно к 4 разным выходам) — [[fade_side_flip_2026_period_not_survivorship]].
Не хватает признака, который ловит переворот ПРИЧИННО, в реальном времени.
Дрейф-фаза не годится: при одной фазе МЕДВ ведут разные стороны.

Кандидаты (формулы DS, окно 200 баров 4h, всё считается ТОЛЬКО по прошлым барам):
  TAI — асимметрия хвостов: (P95−med)/(med−P05). Левый хвост толще → выкупают проливы → LONG
  RR  — скорость восстановления после шока |r|>2σ: median(return за 12 баров после)
  VTR — асимметрия объёма на хвостах: mean(vol|r<P10) / mean(vol|r>P90)
  ACS — автокорреляция 6-барных доходностей (известный ключ режима в проекте)

Признак годен, если РАЗДЕЛЯЕТ окна, где ведёт LONG, от окон, где ведёт SHORT.

Запуск:  python scripts/regime_detector_candidates.py [n_монет=60]
"""
import datetime as dt
import sqlite3
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

DB = "ohlcv_cache.db"
NCOIN = int(sys.argv[1]) if len(sys.argv) > 1 else 60
TF, COST, COOL, WIN_M, STEP_M = "4h", 0.35, 2, 7.0, 1.0
LB = 200                      # окно расчёта признаков (баров 4h ≈ 33 дня)


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


def ex(i, H, L, C, sl, side, ttl=24):
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


def feats(r, v, i):
    """Признаки ТОЛЬКО по прошлым барам [i-LB, i). Возвращает (TAI, RR, VTR, ACS)."""
    w = r[i - LB:i]
    vv = v[i - LB:i]
    w = w[np.isfinite(w)]
    if len(w) < LB * 0.8:
        return (np.nan,) * 4
    med = np.median(w)
    p95, p05, p90, p10 = np.percentile(w, [95, 5, 90, 10])
    up, dn = p95 - med, med - p05
    tai = up / dn if dn > 1e-9 else np.nan          # >1 правый хвост толще
    sd = w.std()
    shock = np.where(np.abs(w) > 2 * sd)[0]
    shock = shock[shock < len(w) - 12]
    rr = float(np.median([w[k + 1:k + 13].sum() for k in shock]) / sd) if len(shock) >= 5 and sd > 0 else np.nan
    lo_m = vv[:len(w)][w < p10].mean() if (w < p10).any() else np.nan
    hi_m = vv[:len(w)][w > p90].mean() if (w > p90).any() else np.nan
    vtr = lo_m / hi_m if (hi_m and np.isfinite(hi_m) and hi_m > 0) else np.nan
    a, b = w[6:], w[:-6]
    acs = float(np.corrcoef(a, b)[0, 1]) if len(a) > 30 else np.nan
    return tai, rr, vtr, acs


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
print(f"монет {len(DATA)} / ликвидных {len(liq)}", file=sys.stderr)

sig = []      # (ts, side, net, tai, rr, vtr, acs)
for s in liq:
    d = DATA[s]
    w_ = wt(d); tr_ = atrt(d)
    H, L, C, V, T = d.high.values, d.low.values, d.close.values, d.volume.values, d.time.values
    r = np.concatenate([[np.nan], np.diff(C) / C[:-1] * 100])
    last = {"LONG": -10**9, "SHORT": -10**9}
    for i in range(max(210, LB + 5), len(d) - 1):
        for side in ("LONG", "SHORT"):
            if i - last[side] < COOL:
                continue
            if side == "LONG":
                if not (tr_[i] > 0 and w_[i] < -60 and w_[i] > w_[i-1]):
                    continue
                sl = L[max(0, i-3):i+1].min() * 0.997
                if sl >= C[i]:
                    continue
                sp = (C[i] - sl) / C[i] * 100
            else:
                if not (tr_[i] < 0 and w_[i] > 60 and w_[i] < w_[i-1]):
                    continue
                sl = H[max(0, i-3):i+1].max() * 1.003
                if sl <= C[i]:
                    continue
                sp = (sl - C[i]) / C[i] * 100
            if not (4.0 < sp <= 12.0):
                continue
            last[side] = i
            sig.append((int(T[i]), side, ex(i, H, L, C, sl, side) - COST) + feats(r, V, i))

sig.sort()
print(f"сигналов: {len(sig)}\n")

MS_M = 30.44 * 24 * 3600 * 1000
t_min, t_max = sig[0][0], sig[-1][0]
rows = []
cur = t_min
while cur + WIN_M * MS_M <= t_max + STEP_M * MS_M:
    lo, hi = cur, cur + WIN_M * MS_M
    win = [x for x in sig if lo <= x[0] < hi]
    L_ = [x[2] for x in win if x[1] == "LONG"]
    S_ = [x[2] for x in win if x[1] == "SHORT"]
    if len(L_) >= 20 and len(S_) >= 20:
        lead = "LONG" if np.median(L_) > np.median(S_) else "SHORT"
        f = [np.nanmedian([x[3 + k] for x in win]) for k in range(4)]
        rows.append((dt.datetime.fromtimestamp(lo / 1000, dt.timezone.utc).strftime("%Y-%m"),
                     lead, float(np.median(L_)), float(np.median(S_)), *f))
    cur += STEP_M * MS_M

print("═" * 104)
print("ПРИЗНАКИ ПО ОКНАМ (все причинные, окно 200 баров ДО входа) · медиана по вселенной")
print("═" * 104)
print(f"{'окно':<9} {'ведёт':<6} {'LONGмед':>8} {'SHORTмед':>9} {'TAI':>7} {'RR':>7} {'VTR':>7} {'ACS':>7}")
for d0, lead, ml, ms, tai, rr, vtr, acs in rows:
    print(f"{d0:<9} {lead:<6} {ml:>+7.2f}% {ms:>+8.2f}% {tai:>7.3f} {rr:>7.3f} {vtr:>7.3f} {acs:>7.3f}")

print("\n" + "═" * 104)
print("РАЗДЕЛЯЮЩАЯ СИЛА: среднее значение признака в окнах LONG против окон SHORT")
print("═" * 104)
names = ["TAI", "RR", "VTR", "ACS"]
for k, nm in enumerate(names):
    a = [r[4 + k] for r in rows if r[1] == "LONG" and np.isfinite(r[4 + k])]
    b = [r[4 + k] for r in rows if r[1] == "SHORT" and np.isfinite(r[4 + k])]
    if len(a) < 3 or len(b) < 3:
        print(f"  {nm:<5} мало данных")
        continue
    ma, mb = np.mean(a), np.mean(b)
    sd = np.sqrt(np.var(a) / len(a) + np.var(b) / len(b))
    z = (ma - mb) / sd if sd > 0 else 0
    # перекрытие диапазонов — годен ли как ПОРОГ
    sep = "РАЗДЕЛЯЕТ" if (min(a) > max(b) or min(b) > max(a)) else ("частично" if abs(z) > 2 else "НЕТ")
    print(f"  {nm:<5} LONG-окна {ma:+.3f} (n={len(a)}) · SHORT-окна {mb:+.3f} (n={len(b)}) · "
          f"z={z:+.2f} → {sep}")
print("\nПризнак годен как переключатель, только если РАЗДЕЛЯЕТ (диапазоны не пересекаются)")
print("или хотя бы z>2 И порог виден глазами в таблице выше.")
