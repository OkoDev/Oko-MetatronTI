# -*- coding: utf-8 -*-
"""ВСЕ ТФ + ЕДИНЫЙ ЭКОНОМИЧЕСКИЙ ФИЛЬТР + КОНФЛЮЭНЦИЯ ТФ (13.08.2026, Даат).

Постановка Егора: «если ввести ограничения по экономике сделки, но открыть ВСЕ таймфреймы
для торговли — что получим? Признаки SMC одинаковы для всех ТФ. И почему мультитаймфрейм
мы сейчас не рассматриваем?»

Снимает ложный выбор «какой ТФ лучше». Логика:
  • сетап ищем на КАЖДОМ ТФ (5m/15m/1h/4h) одной и той же механикой;
  • отбираем НЕ по ТФ, а по ЭКОНОМИКЕ: стоп должен быть кратно больше костов;
  • считаем суммарный поток и его экономику.

Плюс проверяется вторая гипотеза MTF, которую ранее не мерили:
  • КОНФЛЮЭНЦИЯ — сетап на нескольких ТФ ОДНОВРЕМЕННО (в окне ±N часов).
    Раньше меряли только «вход на младшем ТФ» (3 варианта, все хуже прямого входа).
    Здесь: не вход, а СИЛА сигнала от согласия таймфреймов.

Запуск:  python scripts/all_tf_economic_gate.py [--coins 40] [--min-stop 4]
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
TFS = ["15m", "1h", "4h"]
BAR_MS = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}
COOL = {"5m": 72, "15m": 24, "1h": 6, "4h": 2}
TTL_BARS = 96          # единый горизонт удержания в барах своего ТФ


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
    e = C[i]
    tp = e + tp_r * (e - sl)
    end = min(i + ttl, len(C) - 1)
    for j in range(i + 1, end + 1):
        if L[j] <= sl:
            return (sl - e) / e * 100
        if H[j] >= tp:
            return (tp - e) / e * 100
    return (C[end] - e) / e * 100


def stat(v):
    v = np.asarray(v, dtype=float)
    if len(v) == 0:
        return None
    pf = v[v > 0].sum() / abs(v[v < 0].sum()) if (v < 0).any() else 99.0
    srt = np.sort(v)
    cut = max(1, int(len(srt) * 0.10))
    return len(v), float(np.median(v)), 100.0 * float((v > 0).mean()), float(pf), \
        float(v.mean()), float(srt[:-cut].sum())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", type=int, default=40)
    ap.add_argument("--since", type=int, default=2024)
    ap.add_argument("--min-stop", type=float, default=4.0)
    ap.add_argument("--max-stop", type=float, default=12.0)
    ap.add_argument("--tp", type=float, default=2.0)
    ap.add_argument("--conf-window-h", type=float, default=8.0, help="окно согласия ТФ, часов")
    a = ap.parse_args()

    t0 = int(dt.datetime(a.since, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? "
        "GROUP BY symbol HAVING n>2000 ORDER BY n DESC LIMIT ?", (t0, a.coins)).fetchall()]
    con.close()

    print("═" * 104)
    print(f"ВСЕ ТФ + ЭКОНОМИЧЕСКИЙ ФИЛЬТР · стоп {a.min_stop}–{a.max_stop}% · TP={a.tp}R · "
          f"TTL {TTL_BARS} баров · косты {COST}%")
    print(f"вселенная {len(syms)} монет · окно с {a.since} · механика фейда одна на всех ТФ")
    print("═" * 104)

    all_sig = []      # (ts, tf, symbol, stop_pct, net)
    for sym in syms:
        per_tf = {}
        for tf in TFS:
            c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
            d = pd.read_sql("SELECT time,high,low,close FROM ohlcv_cache WHERE symbol=? "
                            "AND timeframe=? AND time>=? ORDER BY time", c, params=(sym, tf, t0))
            c.close()
            if len(d) < 300:
                continue
            w_, tr_ = wt(d), atrt(d)
            H, L, C, T = d.high.values, d.low.values, d.close.values, d.time.values
            last = -10 ** 9
            sigs = []
            for i in range(210, len(d) - 1):
                if i - last < COOL[tf]:
                    continue
                if not (tr_[i] > 0 and w_[i] < -60 and w_[i] > w_[i - 1]):
                    continue
                sl = L[max(0, i - 3):i + 1].min() * 0.997
                if sl >= C[i]:
                    continue
                sp = (C[i] - sl) / C[i] * 100
                if not (a.min_stop < sp <= a.max_stop):     # ЭКОНОМИЧЕСКИЙ ФИЛЬТР
                    continue
                last = i
                net = exit_tp(i, H, L, C, sl, a.tp, TTL_BARS) - COST
                sigs.append((int(T[i]), sp, net))
                all_sig.append((int(T[i]), tf, sym, sp, net))
            per_tf[tf] = sigs

        # ── КОНФЛЮЭНЦИЯ: у сигнала на ТФ есть ли согласие другого ТФ в окне ±conf_window ──
        win = a.conf_window_h * 3_600_000
        for tf, sigs in per_tf.items():
            others = [s for t2, ss in per_tf.items() if t2 != tf for s in ss]
            if not others:
                continue
            ot = np.array([s[0] for s in others])
            for k, (ts, sp, net) in enumerate(sigs):
                # ПРИЧИННОЕ окно: только сигналы ДО текущего момента.
                # Симметричное ±win считало бы согласие из будущего — look-ahead.
                n_conf = int(((ot >= ts - win) & (ot <= ts)).sum())
                all_sig[[i for i, x in enumerate(all_sig)
                         if x[0] == ts and x[1] == tf and x[2] == sym][0]] = \
                    (ts, tf, sym, sp, net, n_conf)

    rows = [x for x in all_sig if len(x) == 6]
    if len(rows) < 100:
        print(f"\nсигналов с разметкой конфлюэнции: {len(rows)} — мало")
        return 1
    df = pd.DataFrame(rows, columns=["ts", "tf", "symbol", "stop_pct", "net", "n_conf"])
    df["t"] = pd.to_datetime(df.ts, unit="ms")
    days = max((df.t.max() - df.t.min()).days, 1)

    print(f"\n=== ПОТОК СО ВСЕХ ТФ (после экономического фильтра) ===")
    print(f"{'ТФ':<8} {'сигналов':>9} {'в день':>8} {'мед стоп':>10} {'WR%':>7} {'PF':>7} "
          f"{'%/сделку':>11} {'безтоп10%':>11}")
    for tf in TFS:
        r = stat(df[df.tf == tf].net.values)
        if r:
            print(f"{tf:<8} {r[0]:>9} {r[0] / days:>7.2f} "
                  f"{df[df.tf == tf].stop_pct.median():>9.2f}% {r[2]:>6.1f}% {r[3]:>7.2f} "
                  f"{r[4]:>+10.3f}% {r[5]:>+10.1f}")
    r = stat(df.net.values)
    print(f"{'ВСЕ ВМЕСТЕ':<8} {r[0]:>9} {r[0] / days:>7.2f} {df.stop_pct.median():>9.2f}% "
          f"{r[2]:>6.1f}% {r[3]:>7.2f} {r[4]:>+10.3f}% {r[5]:>+10.1f}")
    print(f"\n➜ суммарно {r[0] / days:.2f} сделки/день × {r[4]:+.3f}% = "
          f"{r[0] / days * r[4]:+.3f}%/день ({r[0] / days * r[4] * 30:+.1f}%/месяц) на {len(syms)} монетах")

    print(f"\n=== КОНФЛЮЭНЦИЯ ТФ (окно ±{a.conf_window_h:.0f}ч) — вторая гипотеза MTF ===")
    print(f"{'согласие':<22} {'n':>8} {'доля':>7} {'WR%':>7} {'PF':>7} {'%/сделку':>11}")
    for nm, cond in (("нет согласия (0)", df.n_conf == 0),
                     ("1 другой ТФ", df.n_conf == 1),
                     ("2+ других ТФ", df.n_conf >= 2)):
        r = stat(df[cond].net.values)
        if r:
            print(f"{nm:<22} {r[0]:>8} {100 * r[0] / len(df):>6.1f}% {r[2]:>6.1f}% {r[3]:>7.2f} "
                  f"{r[4]:>+10.3f}%")
    a0 = df[df.n_conf == 0].net.values
    a1 = df[df.n_conf >= 1].net.values
    if len(a0) > 30 and len(a1) > 30:
        from scipy import stats as st
        p = st.mannwhitneyu(a0, a1, alternative="less").pvalue
        print(f"\nзначимость (с согласием лучше): p={p:.5f} "
              f"{'✅ конфлюэнция РАБОТАЕТ' if p < 0.05 else '❌ конфлюэнция НЕ помогает'}")

    print(f"\n=== ПО ГОДАМ (все ТФ вместе) ===")
    df["year"] = df.t.dt.year
    print(f"{'год':<8} {'n':>7} {'WR%':>7} {'PF':>7} {'%/сделку':>11}")
    for y, g in df.groupby("year"):
        r = stat(g.net.values)
        if r and r[0] >= 25:
            print(f"{y:<8} {r[0]:>7} {r[2]:>6.1f}% {r[3]:>7.2f} {r[4]:>+10.3f}%")

    df.to_csv("scripts/_all_tf_signals.csv", index=False)
    print("\n[dump] → scripts/_all_tf_signals.csv")
    print("═" * 104)
    return 0


if __name__ == "__main__":
    sys.exit(main())
