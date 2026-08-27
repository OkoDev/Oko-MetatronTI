# -*- coding: utf-8 -*-
"""CHoCH-МЕХАНИКА В ПОРТФЕЛЕ С ЛИМИТОМ СЛОТОВ (17.08.2026, Даат).

Механика прошла OOS (`choch_oos_validation.py`): OOS-монеты × OOS-время →
WR 53.1%, PF 1.17, +0.50%/сд. Но все эти цифры посчитаны в мире с БЕСКОНЕЧНЫМ
капиталом: каждый сигнал берётся независимо.

Егор уже ловил меня на этом («удержание от 24 суток?! это так мы частоту нашли?»).
Здесь честная симуляция: сигналы идут в хронологическом порядке по всей вселенной,
вход возможен ТОЛЬКО при свободном слоте; слот освобождается при закрытии сделки.
Пропущенные сигналы теряются — как в бою.

Дополнительно считается ХРУПКОСТЬ при лимите (безтоп10%) — на полной выборке она
была отрицательной, и вопрос, останется ли плюс, когда крупные сделки не попадут
в портфель из-за занятых слотов.

Механика (зафиксирована): swing-CHoCH → структурная нога OKO-SM → откат 0.236 →
лимитный вход → стоп за origin → цель волна C ×1.0 → 1h, держим до 96 баров.

Запуск:  python scripts/choch_portfolio_slots.py [--coins 250] [--side short]
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

from core.smc.oko_sm_engine import run_structure  # noqa: E402

DB = "ohlcv_cache.db"
COST = 0.35
TTL = 96
WAIT = 12
PB, K = 0.236, 1.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", type=int, default=250)
    ap.add_argument("--since", type=int, default=2024)
    ap.add_argument("--side", type=str, default="short")
    a = ap.parse_args()

    t0 = int(dt.datetime(a.since, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? "
        "GROUP BY symbol HAVING n>3000 ORDER BY n DESC LIMIT ?", (t0, a.coins)).fetchall()]
    con.close()

    print("═" * 112)
    print(f"CHoCH → откат {PB} → волна C ×{K} · ПОРТФЕЛЬ С ЛИМИТОМ СЛОТОВ · "
          f"{a.side.upper()} · {len(syms)} монет с {a.since}")
    print(f"1h · держим до {TTL}б · косты {COST}% (лимитный вход)")
    print("═" * 112)

    trades = []          # (ts_open, ts_close, R, pct, symbol)
    for si, sym in enumerate(syms, 1):
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        raw = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache "
                          "WHERE symbol=? AND timeframe='1h' AND time>=? ORDER BY time",
                          c, params=(sym, t0))
        c.close()
        if len(raw) < 3000:
            continue
        raw["ts"] = pd.to_datetime(raw.time, unit="ms", utc=True)
        d = raw.set_index("ts")[["open", "high", "low", "close", "volume"]]
        dd = d.reset_index(drop=True)
        try:
            st = run_structure(dd, swing_len=50, internal_len=5, record_legs=True)
        except Exception:
            continue
        legs = st.leg_history
        if not legs or len(legs) != len(dd):
            continue
        H, L, C = dd.high.values, dd.low.values, dd.close.values
        n = len(dd)
        want_bull = (a.side == "long")

        for ev in st.events:
            if ev.kind != "CHoCH" or ev.internal or ev.bull != want_bull:
                continue
            i = int(ev.i)
            if i < 60 or i >= n - TTL - WAIT - 2:
                continue
            leg = legs[i]
            if not leg or (leg["trend"] == "long") != ev.bull:
                continue
            origin, extreme = float(leg["origin"]), float(leg["extreme"])
            A_len = abs(extreme - origin)
            if A_len <= 0:
                continue
            entry = extreme - A_len * PB if want_bull else extreme + A_len * PB
            jf = None
            for j in range(i + 1, min(i + 1 + WAIT, n)):
                if (want_bull and L[j] <= entry) or ((not want_bull) and H[j] >= entry):
                    jf = j; break
            if jf is None:
                continue
            sl = origin * 0.999 if want_bull else origin * 1.001
            sp = abs(entry - sl) / entry * 100
            if sp <= 0 or sp > 25:
                continue
            tp = entry + A_len * K if want_bull else entry - A_len * K
            end = min(jf + TTL, n - 1)
            fl, fh = L[jf + 1:end + 1], H[jf + 1:end + 1]
            if len(fl) == 0:
                continue
            if want_bull:
                hs, ht = fl <= sl, fh >= tp
                lo, hi_ = (sl - entry) / entry * 100, (tp - entry) / entry * 100
                tail = (C[end] - entry) / entry * 100
            else:
                hs, ht = fh >= sl, fl <= tp
                lo, hi_ = (entry - sl) / entry * 100, (entry - tp) / entry * 100
                tail = (entry - C[end]) / entry * 100
            js = int(np.argmax(hs)) if hs.any() else 10 ** 9
            jt = int(np.argmax(ht)) if ht.any() else 10 ** 9
            if js <= jt and js < 10 ** 9:
                pr, dur = lo, js + 1
            elif jt < 10 ** 9:
                pr, dur = hi_, jt + 1
            else:
                pr, dur = tail, end - jf
            net = pr - COST
            trades.append((d.index[jf], d.index[min(jf + dur, n - 1)], net / sp, net, sym))
        if si % 40 == 0:
            print(f"  … монет: {si}/{len(syms)}")

    if not trades:
        print("\nсигналов нет")
        return 1
    T = pd.DataFrame(trades, columns=["open", "close", "R", "pct", "sym"]).sort_values("open")
    days = max((T["open"].max() - T["open"].min()).days, 1)
    hold = (T["close"] - T["open"])
    print(f"\nсигналов: {len(T)} за {days} дней = {len(T) / days:.2f}/день")
    print(f"медиана удержания: {hold.median()} · p90 {hold.quantile(0.9)}")
    print(f"БЕЗ ЛИМИТА: {T.R.mean():+.4f}R/сд × {len(T) / days:.2f} = "
          f"{T.R.mean() * len(T) / days:+.3f}R/день · {T.pct.mean():+.3f}%/сд")

    print(f"\n=== С ЛИМИТОМ ОДНОВРЕМЕННЫХ ПОЗИЦИЙ ===")
    print(f"{'слотов':>7} {'взято':>7} {'доля':>7} {'WR':>7} {'PF':>7} {'R/сд':>9} "
          f"{'сд/день':>9} {'R/день':>9} {'безтоп10%':>11} {'%депо/мес':>11}")
    print("─" * 112)
    for cap in (5, 10, 20, 30, 50, 100, 10 ** 6):
        free_at, taken = [], []
        for _, row in T.iterrows():
            free_at = [t for t in free_at if t > row["open"]]
            if len(free_at) < cap:
                free_at.append(row["close"])
                taken.append((row["R"], row["pct"]))
        if not taken:
            continue
        R = np.array([x[0] for x in taken]); P = np.array([x[1] for x in taken])
        neg = abs(P[P < 0].sum())
        pf = P[P > 0].sum() / neg if neg > 0 else 99.0
        s = np.sort(R); cut = max(1, int(len(s) * 0.10))
        rday = R.mean() * len(R) / days
        nm = "∞" if cap > 10 ** 5 else str(cap)
        mark = "🟢" if rday > 0 else "🔴"
        print(f"{mark}{nm:>5} {len(R):>7} {100 * len(R) / len(T):>6.1f}% "
              f"{100 * (P > 0).mean():>6.1f}% {pf:>7.2f} {R.mean():>+8.4f} "
              f"{len(R) / days:>8.2f} {rday:>+8.3f} {s[:-cut].sum():>+10.1f} "
              f"{rday * 30:>+10.2f}%")

    print(f"\n=== ЧТО РЕАЛЬНО ОСТАЁТСЯ (риск 1% депозита на сделку) ===")
    for cap in (10, 20, 30):
        free_at, taken = [], []
        for _, row in T.iterrows():
            free_at = [t for t in free_at if t > row["open"]]
            if len(free_at) < cap:
                free_at.append(row["close"])
                taken.append(row["R"])
        if taken:
            rday = float(np.mean(taken)) * len(taken) / days
            print(f"  {cap:>3} слотов (макс. риск {cap}% депо) → {rday:+.3f}R/день "
                  f"= {rday * 30:+.2f}% депозита/месяц · берём {100 * len(taken) / len(T):.0f}% сигналов")

    print("\n" + "═" * 112)
    print("Без лимита цифра завышена: капитал не бесконечен, слоты кончаются,")
    print("и часть сигналов в бою просто не будет взята.")
    print("═" * 112)
    return 0


if __name__ == "__main__":
    sys.exit(main())
