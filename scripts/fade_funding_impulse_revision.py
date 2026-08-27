# -*- coding: utf-8 -*-
"""РЕВИЗИЯ ДВУХ ФИЛЬТРОВ: funding-толпа и импульсный режим (13.08.2026, Даат).

Повод: сессионный фильтр, записанный как ASIA PF 5.49 / LONDON 0.45, при перепроверке
на полной базе дал 1.88 / 0.77 (втрое слабее), а на 4h вообще инвертировался.
Причина — исходные числа мерились на СУЖЕННОЙ подвыборке (bigflush + другие фильтры),
что нарушает наш закон «фильтр мерить против ПОЛНОЙ базы».

Эти два фильтра записаны с той же оговоркой («база big-flush PF 1.95»):
  • funding-толпа в шортах → заявлено PF 3.00, WR 70%
  • импульсный режим (автокорреляция) → заявлено PF 3.73 против 1.36 в возвратном

Здесь оба меряются на ПОЛНОЙ базе фейда (дамп сигналов), причинно:
  • автокорреляция — lag-1 корреляция доходностей на окне ДО сигнала;
  • funding — перцентиль ставки монеты относительно её собственной истории ДО сигнала
    (низкий перцентиль = толпа в шортах платит лонгам = топливо отскока).

Запуск:  python scripts/fade_funding_impulse_revision.py [--tf 4h]
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
DUMPS = {"4h": "scripts/_fade_signals_4h_2022_breadth.csv",
         "15m": "scripts/_fade_signals_15m_2024.csv"}
AC_BARS = {"4h": 120, "15m": 480}     # ~20 дней и ~5 дней истории на окно автокорреляции


def stat(s: pd.Series):
    if len(s) == 0:
        return None
    pf = s[s > 0].sum() / abs(s[s < 0].sum()) if (s < 0).any() else 99.0
    srt = np.sort(s.values)
    cut = max(1, int(len(srt) * 0.10))
    return len(s), float(s.median()), 100.0 * float((s > 0).mean()), float(pf), float(srt[:-cut].sum())


def add_autocorr(d: pd.DataFrame, tf: str) -> pd.DataFrame:
    """lag-1 автокорреляция доходностей по ПРОШЛЫМ барам до сигнала.
    ac<0 → возвратный (mean-reverting) режим; ac>0 → импульсный (trending)."""
    lb = AC_BARS[tf]
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    out = np.full(len(d), np.nan)
    for sym, grp in d.groupby("symbol"):
        px = pd.read_sql("SELECT time, close FROM ohlcv_cache WHERE symbol=? AND timeframe=? "
                         "ORDER BY time", con, params=(sym, tf))
        if len(px) < lb + 10:
            continue
        t = px.time.values
        r = np.concatenate([[np.nan], np.diff(px.close.values) / px.close.values[:-1]])
        for idx, ts in zip(grp.index, grp.ts.values):
            j = np.searchsorted(t, ts)          # бар сигнала
            if j < lb + 2:
                continue
            w = r[j - lb:j]                      # ТОЛЬКО прошлое
            w = w[np.isfinite(w)]
            if len(w) < lb * 0.8 or w.std() == 0:
                continue
            out[d.index.get_loc(idx)] = float(np.corrcoef(w[:-1], w[1:])[0, 1])
    con.close()
    d["ac"] = out
    return d


def add_funding(d: pd.DataFrame) -> pd.DataFrame:
    """Перцентиль ставки фондирования монеты относительно её СОБСТВЕННОЙ прошлой истории."""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    out = np.full(len(d), np.nan)
    for sym, grp in d.groupby("symbol"):
        f = pd.read_sql("SELECT time, rate FROM funding_rates WHERE symbol=? ORDER BY time",
                        con, params=(sym,))
        if len(f) < 60:
            continue
        ft, fr = f.time.values, f.rate.values
        for idx, ts in zip(grp.index, grp.ts.values):
            j = np.searchsorted(ft, ts)
            if j < 60:
                continue
            hist = fr[max(0, j - 500):j]         # ТОЛЬКО прошлое
            cur = fr[j - 1]
            out[d.index.get_loc(idx)] = float((hist < cur).mean() * 100)
    con.close()
    d["fund_pct"] = out
    return d


def report(d: pd.DataFrame, col: str, title: str, bins, claim: str):
    print("\n" + "═" * 100)
    print(f"{title}")
    print(f"ЗАЯВЛЕНО В ПАМЯТИ: {claim}")
    print("═" * 100)
    for side in ("LONG", "SHORT"):
        sub = d[(d.side == side) & d[col].notna()]
        if len(sub) < 60:
            continue
        print(f"\n--- {side} (полная база, без сужения) ---")
        print(f"{'корзина':<22} {'n':>6} {'медиана':>10} {'WR%':>7} {'PF':>7} {'безтоп10%':>11}")
        for nm, lo, hi in bins:
            r = stat(sub[(sub[col] > lo) & (sub[col] <= hi)].net)
            if r and r[0] >= 30:
                print(f"{nm:<22} {r[0]:>6} {r[1]:>+9.2f}% {r[2]:>6.1f}% {r[3]:>7.2f} {r[4]:>+10.1f}")
        # значимость крайних корзин
        lo_b, hi_b = bins[0], bins[-1]
        a = sub[(sub[col] > lo_b[1]) & (sub[col] <= lo_b[2])].net
        b = sub[(sub[col] > hi_b[1]) & (sub[col] <= hi_b[2])].net
        if len(a) >= 30 and len(b) >= 30:
            p = stats.mannwhitneyu(a, b, alternative="two-sided").pvalue
            print(f"  крайние корзины: p={p:.4f} {'✅ различаются' if p < 0.05 else '❌ НЕ различаются'}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="4h", choices=list(DUMPS))
    a = ap.parse_args()

    d = pd.read_csv(DUMPS[a.tf]).reset_index(drop=True)
    print(f"[{a.tf}] сигналов в полной базе: {len(d)} "
          f"(LONG {int((d.side == 'LONG').sum())} · SHORT {int((d.side == 'SHORT').sum())})")
    base = stat(d[d.side == "LONG"].net)
    print(f"БАЗА LONG без разрезов: n={base[0]} медиана {base[1]:+.2f}% WR {base[2]:.1f}% PF {base[3]:.2f}")

    print("\nсчитаю автокорреляцию (причинно, только прошлые бары)...")
    d = add_autocorr(d, a.tf)
    print(f"  посчитано для {int(d.ac.notna().sum())} сигналов")
    print("считаю перцентиль funding (причинно)...")
    d = add_funding(d)
    print(f"  посчитано для {int(d.fund_pct.notna().sum())} сигналов")

    report(d, "ac", "1️⃣ ИМПУЛЬСНЫЙ РЕЖИМ (автокорреляция lag-1)",
           [("возвратный ac<-0.05", -1.0, -0.05), ("нейтральный", -0.05, 0.05),
            ("импульсный ac>0.05", 0.05, 1.0)],
           "фейд PF 3.73 в импульсном против 1.36 в возвратном (база bigflush 1.95)")

    report(d, "fund_pct", "2️⃣ FUNDING-ТОЛПА (перцентиль ставки к своей истории)",
           [("толпа в шортах <20", -1, 20), ("20-50", 20, 50),
            ("50-80", 50, 80), ("толпа в лонгах >80", 80, 101)],
           "толпа в шортах (<20 перцентиль) PF 3.00 WR 70% (база bigflush 1.95)")

    d.to_csv(f"scripts/_fade_signals_{a.tf}_enriched.csv", index=False)
    print(f"\n[dump] обогащённые сигналы → scripts/_fade_signals_{a.tf}_enriched.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
