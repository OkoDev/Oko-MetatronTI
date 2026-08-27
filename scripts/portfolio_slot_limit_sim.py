# -*- coding: utf-8 -*-
"""ЧЕСТНАЯ ЧАСТОТА ПРИ ЛИМИТЕ СЛОТОВ (14.08.2026, Даат).

Егор: «удержание от 24 суток?! это так мы частоту сделок нашли?!»

Он прав, и это дыра в моих замерах. 8.26 сделки/день × 24 суток удержания =
~200 одновременно открытых позиций. При риске 1% на сделку это 200% депозита —
физически невозможно. Все предыдущие R/день посчитаны в мире с БЕСКОНЕЧНЫМ капиталом.

Здесь портфельная симуляция: сигналы идут в хронологическом порядке по всей вселенной,
вход возможен ТОЛЬКО если есть свободный слот. Занятый слот освобождается, когда сделка
закрылась (TP/SL/TTL). Пропущенные сигналы теряются — как в бою.

Метрики:
  • сколько сигналов реально взято (доля от всех);
  • R/день при данном лимите — с учётом того, что капитал связан;
  • R на слот в день — эффективность использования капитала;
  • средняя занятость слотов.

Косты — реальные 0.79% (комиссия 0.35 + налог на исполнение 0.44,
измерен по 5796 ордерам, `real_execution_tax_doubles_costs`).

Запуск:  python scripts/portfolio_slot_limit_sim.py [--coins 120] [--cost 0.79]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DB = "ohlcv_cache.db"
TP_R = 2.0
SL_LOOKBACK = 10
RULE = {"1h": "1h", "4h": "4h", "1d": "1D"}
BAR_H = {"15m": 0.25, "1h": 1.0, "4h": 4.0, "1d": 24.0}


def atr_dir(df, period=43, factor=1.25):
    h, l, c = df.high, df.low, df.close
    hl2 = ((h + l) / 2).values
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean().values
    up, dn = hl2 - factor * atr, hl2 + factor * atr
    n, cv = len(c), c.values
    u = np.zeros(n); d_ = np.zeros(n); dirn = np.zeros(n)
    u[0], d_[0], dirn[0] = up[0], dn[0], 1
    for i in range(1, n):
        u[i] = max(up[i], u[i - 1]) if cv[i - 1] > u[i - 1] else up[i]
        d_[i] = min(dn[i], d_[i - 1]) if cv[i - 1] < d_[i - 1] else dn[i]
        dirn[i] = 1 if cv[i] > d_[i - 1] else (-1 if cv[i] < u[i - 1] else dirn[i - 1])
    return dirn


def fvg_flags(df):
    high, low, close = df.high.values, df.low.values, df.close.values
    n = len(df)
    bull = np.zeros(n, dtype=bool); bear = np.zeros(n, dtype=bool)
    gaps = [max(0.0, low[i] - high[i - 2], low[i - 2] - high[i]) / close[i] * 100
            for i in range(2, n)]
    thr = (sum(gaps) / len(gaps)) * 2 if gaps else 0.0
    for i in range(2, n):
        if low[i] > high[i - 2] and close[i - 1] > high[i - 2]:
            if (low[i] - high[i - 2]) / high[i - 2] * 100 > thr:
                bull[i] = True
        elif high[i] < low[i - 2] and close[i - 1] < low[i - 2]:
            if (low[i - 2] - high[i]) / high[i] * 100 > thr:
                bear[i] = True
    return bull, bear


def run(df, i, side, ttl, cost):
    """→ (R после костов, длительность в барах, stop%)."""
    H, L, C = df.high.values, df.low.values, df.close.values
    n = len(C)
    if i < SL_LOOKBACK + 1 or i >= n - 2:
        return None
    e = C[i]
    end = min(i + ttl, n - 1)
    fl, fh = L[i + 1:end + 1], H[i + 1:end + 1]
    if len(fl) == 0:
        return None
    if side == "long":
        sl = L[i - SL_LOOKBACK:i + 1].min() * 0.999
        if sl >= e:
            return None
        sp = (e - sl) / e * 100
        tp = e + TP_R * (e - sl)
        hs, ht = fl <= sl, fh >= tp
        lo, hi_ = (sl - e) / e * 100, (tp - e) / e * 100
        tail = (C[end] - e) / e * 100
    else:
        sl = H[i - SL_LOOKBACK:i + 1].max() * 1.001
        if sl <= e:
            return None
        sp = (sl - e) / e * 100
        tp = e - TP_R * (sl - e)
        hs, ht = fh >= sl, fl <= tp
        lo, hi_ = (e - sl) / e * 100, (e - tp) / e * 100
        tail = (e - C[end]) / e * 100
    if sp <= 0 or sp > 40:
        return None
    js = int(np.argmax(hs)) if hs.any() else 10 ** 9
    jt = int(np.argmax(ht)) if ht.any() else 10 ** 9
    if js <= jt and js < 10 ** 9:
        pr, dur = lo, js + 1
    elif jt < 10 ** 9:
        pr, dur = hi_, jt + 1
    else:
        pr, dur = tail, end - i
    return (pr - cost) / sp, dur, sp


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", type=int, default=120)
    ap.add_argument("--since", type=int, default=2024)
    ap.add_argument("--tf", type=str, default="4h")
    ap.add_argument("--cost", type=float, default=0.79)
    ap.add_argument("--ttl-bars", type=int, default=144, help="24 суток на 4h = 144 бара")
    ap.add_argument("--side", type=str, default="short")
    a = ap.parse_args()

    t0 = int(dt.datetime(a.since, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='15m' AND time>=? "
        "GROUP BY symbol HAVING n>8000 ORDER BY n DESC LIMIT ?", (t0, a.coins)).fetchall()]
    con.close()

    print("═" * 112)
    print(f"ПОРТФЕЛЬ С ЛИМИТОМ СЛОТОВ · {a.tf} · {a.side.upper()} · держим до {a.ttl_bars} баров "
          f"(~{a.ttl_bars * BAR_H[a.tf] / 24:.0f} сут)")
    print(f"{len(syms)} монет с {a.since} · косты {a.cost}% (реальные, с налогом на исполнение)")
    print("═" * 112)

    trades = []      # (ts_open, ts_close, R, symbol, stop%)
    for si, sym in enumerate(syms, 1):
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        raw = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache "
                          "WHERE symbol=? AND timeframe='15m' AND time>=? ORDER BY time",
                          c, params=(sym, t0))
        c.close()
        if len(raw) < 8000:
            continue
        raw["ts"] = pd.to_datetime(raw.time, unit="ms", utc=True)
        m15 = raw.set_index("ts")[["open", "high", "low", "close", "volume"]]
        d = m15 if a.tf == "15m" else m15.resample(RULE[a.tf]).agg(
            {"open": "first", "high": "max", "low": "min",
             "close": "last", "volume": "sum"}).dropna()
        if len(d) < 300:
            continue
        td = atr_dir(d)
        bull, bear = fvg_flags(d)
        want = 1 if a.side == "long" else -1
        fvg = bull if a.side == "long" else bear
        for i in range(1, len(d)):
            if td[i] != want or td[i - 1] == want:
                continue
            if not fvg[max(0, i - 8):i + 1].any():
                continue
            r = run(d, i, a.side, a.ttl_bars, a.cost)
            if r is None:
                continue
            R, dur, sp = r
            trades.append((d.index[i], d.index[min(i + dur, len(d) - 1)], R, sym, sp))
        if si % 30 == 0:
            print(f"  … монет: {si}/{len(syms)}")

    if not trades:
        print("\nсигналов нет")
        return 1
    T = pd.DataFrame(trades, columns=["open", "close", "R", "sym", "sp"]).sort_values("open")
    days = max((T["open"].max() - T["open"].min()).days, 1)
    print(f"\nвсего сигналов: {len(T)} за {days} дней = {len(T) / days:.2f}/день")
    print(f"медиана удержания: {(T['close'] - T['open']).median()}")
    print(f"БЕЗ ЛИМИТА: {T.R.mean():+.4f}R/сделку × {len(T) / days:.2f} = "
          f"{T.R.mean() * len(T) / days:+.3f}R/день")
    print(f"  ← это и есть цифра «в мире с бесконечным капиталом»")

    print(f"\n=== С ЛИМИТОМ ОДНОВРЕМЕННЫХ ПОЗИЦИЙ ===")
    print(f"{'слотов':>7} {'взято':>7} {'доля':>7} {'R/сделку':>10} {'сд/день':>9} "
          f"{'R/день':>9} {'R/слот/день':>13} {'занятость':>11}")
    print("─" * 112)
    for cap in (5, 10, 20, 30, 50, 100, 200, 10 ** 6):
        free_at = []          # времена освобождения слотов
        taken = []
        busy_sum = 0.0
        for _, row in T.iterrows():
            free_at = [t for t in free_at if t > row["open"]]
            busy_sum += len(free_at)
            if len(free_at) < cap:
                free_at.append(row["close"])
                taken.append(row["R"])
        if not taken:
            continue
        n = len(taken)
        rmean = float(np.mean(taken))
        rday = rmean * n / days
        occ = busy_sum / max(len(T), 1)
        nm = "∞" if cap > 10 ** 5 else str(cap)
        mark = "🟢" if rday > 0 else "  "
        print(f"{mark}{nm:>5} {n:>7} {100 * n / len(T):>6.1f}% {rmean:>+9.4f}R "
              f"{n / days:>8.2f} {rday:>+8.3f}R {rday / min(cap, 200):>12.4f}R "
              f"{occ:>10.1f}")

    print(f"\n=== ЧТО ЭТО ЗНАЧИТ ДЛЯ ДЕПОЗИТА (риск 1% на сделку) ===")
    for cap in (10, 20, 30, 50):
        free_at = []
        taken = []
        for _, row in T.iterrows():
            free_at = [t for t in free_at if t > row["open"]]
            if len(free_at) < cap:
                free_at.append(row["close"])
                taken.append(row["R"])
        if not taken:
            continue
        rday = float(np.mean(taken)) * len(taken) / days
        print(f"  {cap:>3} слотов → макс. риск {cap}% депозита одновременно · "
              f"{rday:+.3f}R/день = {rday:+.2f}% депозита/день = {rday * 30:+.1f}%/месяц")

    print("\n" + "═" * 112)
    print("«Занятость» — среднее число занятых слотов в момент прихода сигнала.")
    print("Если она упирается в лимит, значит сигналы теряются и частота в бою НИЖЕ заявленной.")
    print("═" * 112)
    return 0


if __name__ == "__main__":
    sys.exit(main())
