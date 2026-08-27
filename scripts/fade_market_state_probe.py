# -*- coding: utf-8 -*-
"""ПРИЗНАК ПЕРИОДА СНАРУЖИ МЕХАНИКИ: корреляционный режим и объём рынка
(13.08.2026, Даат).

Контекст. Ревизия 13.08 показала: все уцелевшие фильтры дают высокий PF в 2024–25
и проваливаются в 2022/2026, и ни один не отличает эти периоды заранее.
Признак изнутри механики (её собственная доходность) закрыт — знак не переносится
между ТФ ([[period_signal_self_adaptive_dead]]).

Здесь проверяются два признака СОСТОЯНИЯ РЫНКА, считаемые из наших же данных
(USDT.D в кэше покрывает только 2025-09+, для 2022–24 его нет):

  1. КОРРЕЛЯЦИОННЫЙ РЕЖИМ — средняя попарная корреляция доходностей монет на окне.
     Гипотеза: фейд живёт, когда рынок падает ЕДИНЫМ движением (системная паника,
     высокая корреляция), и умирает, когда монеты расходятся (идиосинкратия).
  2. ВСПЛЕСК ОБОРОТА РЫНКА — суммарный оборот вселенной к своей медиане.
     Гипотеза: капитуляция с объёмом выкупается, тихое сползание — нет.

Обе величины считаются ТОЛЬКО по прошлым барам и приклеиваются к сигналам по времени.

Запуск:  python scripts/fade_market_state_probe.py [--tf 4h]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DB = "ohlcv_cache.db"
DUMPS = {"4h": "scripts/_fade_signals_4h_mkt.csv", "15m": "scripts/_fade_signals_15m_full.csv"}
CORR_BARS = {"4h": 42, "15m": 672}      # ~7 дней
TURN_BARS = {"4h": 180, "15m": 2880}    # ~30 дней для медианы


def stat(v: np.ndarray):
    if len(v) == 0:
        return None
    pf = v[v > 0].sum() / abs(v[v < 0].sum()) if (v < 0).any() else 99.0
    srt = np.sort(v)
    cut = max(1, int(len(srt) * 0.10))
    return len(v), float(np.median(v)), 100.0 * float((v > 0).mean()), float(pf), float(srt[:-cut].sum())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="4h", choices=list(DUMPS))
    a = ap.parse_args()

    d = pd.read_csv(DUMPS[a.tf])
    d["t"] = pd.to_datetime(d.ts, unit="ms")
    d["year"] = d.t.dt.year

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    syms = tuple(d.symbol.unique())
    q = (f"SELECT symbol,time,close,volume FROM ohlcv_cache WHERE timeframe=? "
         f"AND symbol IN ({','.join(['?'] * len(syms))})")
    px = pd.read_sql(q, con, params=(a.tf,) + syms)
    con.close()
    px["t"] = pd.to_datetime(px.time, unit="ms")

    close = px.pivot_table(index="t", columns="symbol", values="close").sort_index()
    turn = (px.assign(v=px.close * px.volume)
              .pivot_table(index="t", columns="symbol", values="v").sort_index())

    # ── 1. корреляционный режим ────────────────────────────────────────────────
    ret = close.pct_change(fill_method=None)
    W = CORR_BARS[a.tf]
    print(f"считаю корреляционный режим (окно {W} баров ≈ 7 дней)...")
    idx = ret.index
    corr_vals = np.full(len(idx), np.nan)
    step = max(1, W // 6)                     # считаем с шагом, между точками — ffill
    for i in range(W, len(idx), step):
        block = ret.iloc[i - W:i]
        block = block.loc[:, block.notna().sum() >= W * 0.7]
        if block.shape[1] < 8:
            continue
        c = block.corr().values
        iu = np.triu_indices_from(c, k=1)
        vals = c[iu]
        vals = vals[np.isfinite(vals)]
        if len(vals):
            corr_vals[i] = float(vals.mean())
    corr_s = pd.Series(corr_vals, index=idx).ffill()

    # ── 2. всплеск оборота рынка ───────────────────────────────────────────────
    tot = turn.sum(axis=1)
    med = tot.rolling(TURN_BARS[a.tf], min_periods=TURN_BARS[a.tf] // 3).median()
    turn_ratio = (tot / med).shift(1)          # сдвиг: значение бара t известно с t+1

    d["mkt_corr"] = d.t.map(corr_s.shift(1).to_dict())
    d["turn_x"] = d.t.map(turn_ratio.to_dict())

    L = d[(d.side == "LONG") & (d.stop_pct > 8) & (d.stop_pct <= 12)].copy()
    print(f"\n{'═' * 96}")
    print(f"ПРИЗНАК ПЕРИОДА СНАРУЖИ · {a.tf} · фейд LONG · стоп 8–12% · n={len(L)}")
    print("═" * 96)

    for col, title, bins in (
        ("mkt_corr", "1️⃣ КОРРЕЛЯЦИОННЫЙ РЕЖИМ (средняя попарная корреляция монет)",
         [("низкая <0.30", -1, .30), ("0.30–0.45", .30, .45),
          ("0.45–0.60", .45, .60), ("высокая >0.60", .60, 2)]),
        ("turn_x", "2️⃣ ВСПЛЕСК ОБОРОТА РЫНКА (к медиане 30 дней)",
         [("тихо <0.9×", 0, .9), ("0.9–1.2×", .9, 1.2),
          ("1.2–1.8×", 1.2, 1.8), ("капитуляция >1.8×", 1.8, 99)]),
    ):
        sub = L[L[col].notna()]
        print(f"\n{title}   (посчитано для {len(sub)} из {len(L)})")
        print(f"{'корзина':<22} {'n':>6} {'медиана':>10} {'WR%':>7} {'PF':>7} {'безтоп10%':>11}")
        cells = []
        for nm, lo, hi in bins:
            r = stat(sub[(sub[col] > lo) & (sub[col] <= hi)].net.values)
            if r and r[0] >= 25:
                cells.append((nm, r))
                print(f"{nm:<22} {r[0]:>6} {r[1]:>+9.2f}% {r[2]:>6.1f}% {r[3]:>7.2f} {r[4]:>+10.1f}")
        if len(cells) >= 2:
            sp = stats.spearmanr(sub[col], sub.net)
            print(f"  Spearman({col}, результат) = {sp[0]:+.3f} (p={sp[1]:.5f})")

        # ключевая проверка: разделяет ли признак ПРОВАЛЬНЫЕ и УСПЕШНЫЕ годы
        print(f"  среднее по годам: ", end="")
        parts = []
        for y in sorted(sub.year.unique()):
            g = sub[sub.year == y]
            if len(g) < 15:
                continue
            r = stat(g.net.values)
            parts.append(f"{y}: {g[col].median():.2f} (PF {r[3]:.2f})")
        print(" · ".join(parts))

    d.to_csv(f"scripts/_fade_signals_{a.tf}_state.csv", index=False)
    print(f"\n[dump] → scripts/_fade_signals_{a.tf}_state.csv")
    print("═" * 96)
    return 0


if __name__ == "__main__":
    sys.exit(main())
