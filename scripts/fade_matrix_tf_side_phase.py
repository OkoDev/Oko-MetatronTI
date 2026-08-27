# -*- coding: utf-8 -*-
"""МАТРИЦА ФЕЙДА: ТФ × СТОРОНА × ФАЗА (12.08.2026).

Требование Егора: «у тебя всегда должно быть два направления в данных» +
«исследования нужно проводить на всех доступных TF». Полнота разреза =
СТОРОНА × ФАЗА × ТФ ([[feedback_always_both_sides_and_phases]]).

Повод: bigflush15 три недели считали мёртвым — мерили ТОЛЬКО 15m и ТОЛЬКО LONG.
На 1h тот же сигнал даёт медиану втрое выше. Здесь строим полную матрицу.

ЗЕРКАЛО ШОРТА (механика фейда односторонняя по конструкции):
  LONG  = фейд ПРОЛИВА: ATRTrend↑ + WT < −60, SL = min(low[-3:]) × 0.997
  SHORT = фейд ПАМПА:   ATRTrend↓ + WT > +60, SL = max(high[-3:]) × 1.003
Выход у обеих сторон одинаков: TP1R, TTL 24 бара. Косты 0.35% round-trip.

ФАЗА — причинно, без заглядывания вперёд: дрейф самой монеты за 200 баров ДО входа
(перцентиль не нужен — берём знак и величину): >+3% БЫК, <−3% МЕДВЕДЬ, иначе НЕЙТРАЛЬ.

Запуск:  python scripts/fade_matrix_tf_side_phase.py [n_монет=60] [год=2023]
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
SINCE_Y = int(sys.argv[2]) if len(sys.argv) > 2 else 2023
COST = 0.35
TFS = (sys.argv[3].split(",") if len(sys.argv) > 3 else ["5m", "15m", "1h", "4h"])
# REQ_REV: требовать разворот WT (как БЭКТЕСТ) или нет (как БОЙ) — цена дефекта входа
REQ_REV = (sys.argv[4] != "norev") if len(sys.argv) > 4 else True
# UNIV_Y: по какому году отбирать ВСЕЛЕННУЮ (может отличаться от окна торговли) —
# разделяет SURVIVORSHIP (состав монет) от ПЕРИОДА (окно сделок)
UNIV_Y = int(sys.argv[5]) if len(sys.argv) > 5 else SINCE_Y
BPM = {"5m": 8760, "15m": 2920, "1h": 730, "4h": 182}   # баров в месяце
DRIFT_LB = 200          # баров назад для фазы


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


t0 = int(dt.datetime(SINCE_Y, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
t_univ = int(dt.datetime(UNIV_Y, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
res = defaultdict(list)          # (tf, side, phase) -> [net, ...]
cover = defaultdict(set)         # охват монет
months_of = {}

for tf in TFS:
    con = sqlite3.connect(DB)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe=? AND time>=? "
        "GROUP BY symbol HAVING n>? ORDER BY n DESC LIMIT ?",
        (tf, t_univ, BPM[tf] * 6, NCOIN)).fetchall()]
    con.close()
    if not syms:
        print(f"[{tf}] нет данных — пропуск")
        continue
    DATA, turn = {}, {}
    for s in syms:
        c = sqlite3.connect(DB)
        d = pd.read_sql("SELECT time,high,low,close,volume FROM ohlcv_cache WHERE symbol=? "
                        "AND timeframe=? AND time>=? ORDER BY time", c, params=(s, tf, t0))
        c.close()
        if len(d) >= BPM[tf] * 4:
            DATA[s] = d
            turn[s] = float(np.nanmedian((d.close * d.volume).values))
    if not DATA:
        continue
    mt = np.nanmedian(list(turn.values()))
    liq = [s for s in DATA if turn[s] >= mt]
    span = pd.to_datetime(DATA[liq[0]].time, unit="ms")
    months_of[tf] = max(1.0, (span.max() - span.min()).days / 30.44)

    for s in liq:
        d = DATA[s]
        w = wt(d); tr_ = atrt(d)
        H, L, C = d.high.values, d.low.values, d.close.values
        n = len(d)
        last_fire = {"LONG": -10**9, "SHORT": -10**9}
        cool = {"5m": 72, "15m": 24, "1h": 6, "4h": 2}[tf]      # кулдаун 6ч в барах
        for i in range(max(120, DRIFT_LB + 5), n - 1):
            # фаза причинно: дрейф ДО входа
            drift = (C[i] - C[i - DRIFT_LB]) / C[i - DRIFT_LB] * 100
            phase = "БЫК" if drift > 3 else ("МЕДВ" if drift < -3 else "НЕЙТР")
            for side in ("LONG", "SHORT"):
                if i - last_fire[side] < cool:
                    continue
                if side == "LONG":
                    if not (tr_[i] > 0 and w[i] < -60 and (w[i] > w[i-1] or not REQ_REV)):
                        continue
                    sl = L[max(0, i-3):i+1].min() * 0.997
                    if sl >= C[i]:
                        continue
                    stop_pct = (C[i] - sl) / C[i] * 100
                else:
                    if not (tr_[i] < 0 and w[i] > 60 and (w[i] < w[i-1] or not REQ_REV)):
                        continue
                    sl = H[max(0, i-3):i+1].max() * 1.003
                    if sl <= C[i]:
                        continue
                    stop_pct = (sl - C[i]) / C[i] * 100
                if not (4.0 < stop_pct <= 12.0):
                    continue
                last_fire[side] = i
                net = ex_tp1r(i, H, L, C, sl, side) - COST
                res[(tf, side, phase)].append(net)
                res[(tf, side, "ВСЕ")].append(net)
                cover[(tf, side, "ВСЕ")].add(s)
    print(f"[{tf}] монет {len(DATA)} / ликвидных {len(liq)} · окно {months_of[tf]:.1f} мес", file=sys.stderr)


def line(tag, v, syms=None, mo=1.0):
    if len(v) < 30:
        return f"  {tag:<26} n={len(v):<5} — мало"
    a = np.array(v); s = np.sort(a); cut = max(1, len(a)//10)
    pf = (a[a > 0].sum() / abs(a[a < 0].sum())) if (a < 0).any() else 9.9
    med = float(np.median(a))
    per_m = len(a) / mo
    return (f"  {tag:<26} n={len(a):<5} WR{100*(a>0).mean():3.0f}% МЕД{med:+6.2f}% PF{pf:5.2f} "
            f"безтоп10%{s[:-cut].sum():+8.0f}% сд/мес{per_m:6.1f} → {per_m*med:+7.1f}%/мес"
            + (f" монет{len(syms):3}" if syms else ""))


print("\n" + "=" * 118)
print("МАТРИЦА ФЕЙДА: ТФ × СТОРОНА × ФАЗА   (LONG = фейд пролива · SHORT = фейд пампа, зеркало)")
print(f"окно с {SINCE_Y}-01 · косты {COST}% · TP1R · TTL 24 бара · стоп 4-12% · вход: {'РАЗВОРОТ WT (бэктест)' if REQ_REV else 'БЕЗ разворота (как БОЙ)'}")
print("=" * 118)
for tf in TFS:
    if tf not in months_of:
        continue
    print(f"\n── {tf} ── (окно {months_of[tf]:.1f} мес)")
    for side in ("LONG", "SHORT"):
        print(line(f"{side} · ВСЕ фазы", res[(tf, side, "ВСЕ")], cover[(tf, side, "ВСЕ")], months_of[tf]))
        for ph in ("БЫК", "НЕЙТР", "МЕДВ"):
            print(line(f"   {side} · {ph}", res[(tf, side, ph)], None, months_of[tf]))

print("\nПРИМЕЧАНИЕ: SHORT — построенное ЗЕРКАЛО (ATRTrend↓ + WT>+60), а не боевой источник.")
print("Боевой bigflush15 торгует только LONG. Зеркало нужно, чтобы вывод не был односторонним.")
