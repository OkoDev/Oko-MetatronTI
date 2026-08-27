# -*- coding: utf-8 -*-
"""РЕВИЗИЯ atr_change (trend-flip) НА ПОЛНОЙ ИСТОРИИ (13.08.2026, Даат).

Повод: [[atr_change_tf_4h_backlog]] заявляет 4h WR 54.3%, avgR +0.692, PF 3.21,
Sharpe 3.44, SHORT +0.860R PF 4.03 — и лежит в бэклоге НЕ проверенным.
Два дефекта заявки, оба названы в самом файле:
  • n=94 за 21 день — сам TODO требует n≥500 и 6 месяцев;
  • метрика в R, что нарушает наш ЗАКОН №1 (мерить % net, R обманывает при тугом стопе).

Плюс третий, обнаруженный при ревизии 13.08: три из трёх перепроверенных находок
оказались завышены, потому что мерились на суженной базе. Здесь база полная.

Механика (trend-following, НЕ фейд): вход на СМЕНЕ направления ATRTrend
(factor=1.25, period=43 — калибровка [[calib_atrtrend_factor]]).
Выход TP1R / TTL 24 бара, стоп по структуре 3 баров, косты 0.35% — единый стандарт
со всеми остальными замерами, чтобы числа были сопоставимы.

Запуск:  python scripts/atr_flip_full_history.py [--tf 4h] [--coins 140]
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
TTL = 24
REGIME = {2022: "медведь", 2023: "БЫК", 2024: "нейтраль", 2025: "медведь", 2026: "медведь"}


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


def ex_tp1r(i, H, L, C, sl, side):
    e = C[i]
    end = min(i + TTL, len(C) - 1)
    if side == "LONG":
        tp = e + (e - sl)
        for j in range(i + 1, end + 1):
            if L[j] <= sl:
                return (sl - e) / e * 100
            if H[j] >= tp:
                return (tp - e) / e * 100
        return (C[end] - e) / e * 100
    tp = e - (sl - e)
    for j in range(i + 1, end + 1):
        if H[j] >= sl:
            return (e - sl) / e * 100
        if L[j] <= tp:
            return (e - tp) / e * 100
    return (e - C[end]) / e * 100


def stat(s: np.ndarray):
    if len(s) == 0:
        return None
    pf = s[s > 0].sum() / abs(s[s < 0].sum()) if (s < 0).any() else 99.0
    srt = np.sort(s)
    cut = max(1, int(len(srt) * 0.10))
    sharpe = s.mean() / s.std() * np.sqrt(len(s)) if s.std() > 0 else 0
    return len(s), float(np.median(s)), 100.0 * float((s > 0).mean()), float(pf), \
        float(srt[:-cut].sum()), float(s.sum()), float(sharpe)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="4h")
    ap.add_argument("--coins", type=int, default=140)
    ap.add_argument("--since", type=int, default=2022)
    a = ap.parse_args()

    t0 = int(dt.datetime(a.since, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe=? AND time>=? "
        "GROUP BY symbol HAVING n>400 ORDER BY n DESC LIMIT ?", (a.tf, t0, a.coins)).fetchall()]
    con.close()

    rows = []
    for s in syms:
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        d = pd.read_sql("SELECT time,high,low,close,volume FROM ohlcv_cache WHERE symbol=? "
                        "AND timeframe=? AND time>=? ORDER BY time", c, params=(s, a.tf, t0))
        c.close()
        if len(d) < 300:
            continue
        dirn = atrt(d)
        H, L, C, T = d.high.values, d.low.values, d.close.values, d.time.values
        turn = float(np.nanmedian((d.close * d.volume).values))
        for i in range(60, len(d) - 1):
            if dirn[i] == dirn[i - 1]:
                continue                      # вход ТОЛЬКО на смене направления
            side = "LONG" if dirn[i] > 0 else "SHORT"
            if side == "LONG":
                sl = L[max(0, i - 3):i + 1].min() * 0.997
                if sl >= C[i]:
                    continue
                sp = (C[i] - sl) / C[i] * 100
            else:
                sl = H[max(0, i - 3):i + 1].max() * 1.003
                if sl <= C[i]:
                    continue
                sp = (sl - C[i]) / C[i] * 100
            if not (0.5 < sp <= 25.0):
                continue
            rows.append((int(T[i]), s, side, ex_tp1r(i, H, L, C, sl, side) - COST, sp, turn))

    if not rows:
        print("сигналов нет")
        return 1
    df = pd.DataFrame(rows, columns=["ts", "symbol", "side", "net", "stop_pct", "turn"])
    df["t"] = pd.to_datetime(df.ts, unit="ms")
    df["year"] = df.t.dt.year
    df["liquid"] = df.turn >= df.turn.median()

    print("═" * 104)
    print(f"РЕВИЗИЯ atr_change (trend-flip) · {a.tf} · с {a.since} · монет {df.symbol.nunique()}")
    print("ЗАЯВЛЕНО в бэклоге: 4h WR 54.3% avgR +0.692 PF 3.21 Sharpe 3.44 (n=94 за 21 день, метрика в R)")
    print("ЗДЕСЬ: % net с костами 0.35%, полная история, TP1R/TTL24 — единый стандарт проекта")
    print("═" * 104)

    print(f"\n{'срез':<26} {'n':>6} {'медиана':>10} {'WR%':>7} {'PF':>7} {'безтоп10%':>11} {'сумма':>10}")
    for side in ("LONG", "SHORT"):
        r = stat(df[df.side == side].net.values)
        print(f"{'ВСЯ ИСТОРИЯ ' + side:<26} {r[0]:>6} {r[1]:>+9.3f}% {r[2]:>6.1f}% {r[3]:>7.2f} "
              f"{r[4]:>+10.1f} {r[5]:>+9.1f}")

    print(f"\n{'год (режим) · сторона':<26} {'n':>6} {'медиана':>10} {'WR%':>7} {'PF':>7} {'безтоп10%':>11}")
    for y in sorted(df.year.unique()):
        for side in ("LONG", "SHORT"):
            sub = df[(df.year == y) & (df.side == side)]
            r = stat(sub.net.values)
            if r and r[0] >= 30:
                print(f"{str(y) + ' (' + REGIME.get(y, '?') + ') ' + side:<26} {r[0]:>6} "
                      f"{r[1]:>+9.3f}% {r[2]:>6.1f}% {r[3]:>7.2f} {r[4]:>+10.1f}")

    print(f"\n{'размер стопа · сторона':<26} {'n':>6} {'медиана':>10} {'WR%':>7} {'PF':>7}")
    for side in ("LONG", "SHORT"):
        for nm, lo, hi in (("<2%", 0, 2), ("2-4%", 2, 4), ("4-8%", 4, 8), (">8%", 8, 99)):
            r = stat(df[(df.side == side) & (df.stop_pct > lo) & (df.stop_pct <= hi)].net.values)
            if r and r[0] >= 40:
                print(f"{nm + ' ' + side:<26} {r[0]:>6} {r[1]:>+9.3f}% {r[2]:>6.1f}% {r[3]:>7.2f}")

    print(f"\n{'ликвидность · сторона':<26} {'n':>6} {'медиана':>10} {'PF':>7}")
    for side in ("LONG", "SHORT"):
        for lq in (True, False):
            r = stat(df[(df.side == side) & (df.liquid == lq)].net.values)
            if r:
                print(f"{('ликвид ' if lq else 'неликвид ') + side:<26} {r[0]:>6} {r[1]:>+9.3f}% {r[3]:>7.2f}")

    df.to_csv(f"scripts/_atr_flip_{a.tf}_{a.since}.csv", index=False)
    print(f"\n[dump] → scripts/_atr_flip_{a.tf}_{a.since}.csv")
    print("═" * 104)
    return 0


if __name__ == "__main__":
    sys.exit(main())
