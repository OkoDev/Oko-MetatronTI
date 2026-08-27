# -*- coding: utf-8 -*-
"""ЭКОНОМИКА ЦЕЛИ ПО ТАЙМФРЕЙМАМ: какой TP окупает косты на каком ТФ (13.08.2026, Даат).

Постановка Егора: «идти ОТ ЭКОНОМИКИ, нужен поток сделок с хорошей экономикой».

Экономическая граница при TP=k·R: net = P(дошло до k)·k·SL − P(SL)·SL − costs.
Из живых данных получено: на 15m до 1R доходит 20.7% сделок, до 2R — 12.0%.
При таком WR цель 1R убыточна (−0.277%/сделку), а 2R выходит в плюс (+0.112%).

НО в боевой базе ТОЛЬКО 15m — среза по ТФ там нет. Здесь он считается бэктестом
на механике фейда (ATRTrend↑ + WT<−60 + разворот), одинаковой на всех ТФ.

Ключевая поправка к прошлым замерам: дальняя цель требует БОЛЬШЕГО TTL —
иначе сделка закрывается по времени, не дойдя. Поэтому меряется сетка TP × TTL.

Запуск:  python scripts/tp_economics_by_tf.py [--coins 60]
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
COST = 0.35
COOL = {"5m": 72, "15m": 24, "1h": 6, "4h": 2}
TFS = ["15m", "1h", "4h"]
TP_LEVELS = [1.0, 1.5, 2.0, 3.0]
TTL_MULT = [1, 2, 4]          # множитель к базовому TTL=24 бара


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
    up, dn = hl2 - factor * atr, hl2 + factor * atr
    n, cv = len(c), c.values
    u = np.zeros(n); d_ = np.zeros(n); dirn = np.zeros(n)
    u[0], d_[0], dirn[0] = up[0], dn[0], 1
    for i in range(1, n):
        u[i] = max(up[i], u[i - 1]) if cv[i - 1] > u[i - 1] else up[i]
        d_[i] = min(dn[i], d_[i - 1]) if cv[i - 1] < d_[i - 1] else dn[i]
        dirn[i] = 1 if cv[i] > d_[i - 1] else (-1 if cv[i] < u[i - 1] else dirn[i - 1])
    return dirn


def exit_tp(i, H, L, C, sl, tp_r, ttl):
    """LONG: цель = entry + tp_r·(entry−sl). SL проверяется первым на баре (консервативно)."""
    e = C[i]
    risk = e - sl
    tp = e + tp_r * risk
    end = min(i + ttl, len(C) - 1)
    for j in range(i + 1, end + 1):
        if L[j] <= sl:
            return (sl - e) / e * 100, "SL"
        if H[j] >= tp:
            return (tp - e) / e * 100, "TP"
    return (C[end] - e) / e * 100, "TTL"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", type=int, default=60)
    ap.add_argument("--since", type=int, default=2024)
    a = ap.parse_args()

    t0 = int(dt.datetime(a.since, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    print("═" * 104)
    print(f"ЭКОНОМИКА ЦЕЛИ ПО ТФ · фейд LONG · косты {COST}% · окно с {a.since} · монет ≤{a.coins}")
    print("сетка: TP ∈ {1, 1.5, 2, 3}R × TTL ∈ {24, 48, 96} баров. Стоп по структуре 3 баров.")
    print("═" * 104)

    for tf in TFS:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        syms = [r[0] for r in con.execute(
            "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe=? AND time>=? "
            "GROUP BY symbol HAVING n>500 ORDER BY n DESC LIMIT ?", (tf, t0, a.coins)).fetchall()]
        con.close()

        rows = []          # (stop_pct, {(tp,ttl): net})
        for s in syms:
            c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
            d = pd.read_sql("SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? "
                            "AND timeframe=? AND time>=? ORDER BY time", c, params=(s, tf, t0))
            c.close()
            if len(d) < 300:
                continue
            w_, tr_ = wt(d), atrt(d)
            H, L, C = d.high.values, d.low.values, d.close.values
            last = -10 ** 9
            for i in range(210, len(d) - 1):
                if i - last < COOL[tf]:
                    continue
                if not (tr_[i] > 0 and w_[i] < -60 and w_[i] > w_[i - 1]):
                    continue
                sl = L[max(0, i - 3):i + 1].min() * 0.997
                if sl >= C[i]:
                    continue
                sp = (C[i] - sl) / C[i] * 100
                if not (4.0 < sp <= 12.0):     # боевая зона размера
                    continue
                last = i
                cell = {}
                for tp_r in TP_LEVELS:
                    for m in TTL_MULT:
                        r, _ = exit_tp(i, H, L, C, sl, tp_r, 24 * m)
                        cell[(tp_r, m)] = r - COST
                rows.append((sp, cell))

        if len(rows) < 60:
            print(f"\n[{tf}] сигналов {len(rows)} — мало")
            continue

        print(f"\n── {tf} ── сигналов {len(rows)} · медиана стопа "
              f"{np.median([r[0] for r in rows]):.2f}% · монет {len(syms)}")
        print(f"{'TTL':>6} " + "".join(f"{'TP=' + str(k) + 'R':>22}" for k in TP_LEVELS))
        for m in TTL_MULT:
            line = f"{24 * m:>4}б "
            for tp_r in TP_LEVELS:
                v = np.array([r[1][(tp_r, m)] for r in rows])
                pf = v[v > 0].sum() / abs(v[v < 0].sum()) if (v < 0).any() else 99.0
                line += f"{v.mean():>+9.3f}%/PF{pf:>5.2f}    "
            print(line)
        # лучший вариант
        best, bv = None, -99
        for tp_r in TP_LEVELS:
            for m in TTL_MULT:
                mv = np.mean([r[1][(tp_r, m)] for r in rows])
                if mv > bv:
                    bv, best = mv, (tp_r, m)
        print(f"    ➜ лучший: TP={best[0]}R, TTL={24 * best[1]} баров → {bv:+.3f}%/сделку")

    print("\n" + "═" * 104)
    print("В ячейке: средний % net на сделку / PF. Косты уже вычтены.")
    print("═" * 104)
    return 0


if __name__ == "__main__":
    sys.exit(main())
