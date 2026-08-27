# -*- coding: utf-8 -*-
"""RR против ВЫКУПАЕМОСТИ ПРОЛИВОВ — правильная гипотеза (13.08.2026, DS).

Ответ на замечание Даата (DISCUSSION 13.08 02:10): «Тест (2) RR против buy&hold
проверяет не ту гипотезу. RR претендует на ВЫКУПАЕМОСТЬ ПРОЛИВОВ, а не на РОСТ РЫНКА».

Здесь меняем целевую переменную: не безусловная доходность (buy&hold), а УСЛОВНАЯ
доходность ПОСЛЕ ПРОЛИВОВ: для каждого окна — медиана (по монетам) суммы доходностей
за 12 баров ПОСЛЕ шока r<−2σ (пролив). Это ровно та величина, которую претендует
предсказывать RR («после шока рынок восстанавливается или продолжает падать»).

Сравниваем с RR (та же механика, что [[2026-08-12-Fade-Side-Flip-Full-Data]]):
  RR = median(сумма 12-барных доходностей после |r|>2σ)/σ по окну 200 баров 4h.

Если RR>0 согласуется с положительной «выкупаемостью» в том же окне и корреляция
значима — RR действительно измеряет выкупаемость проливов (гипотеза Даата верна),
и нулевая корреляция с buy&hold из прошлого теста ожидаема.

Запуск:  python scripts/fade_rr_vs_buyout.py
"""
import datetime as dt
import sqlite3
import sys
import warnings

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

DB = "ohlcv_cache.db"
TFS = ["4h", "1h"]
LB = {"4h": 200, "1h": 792}
NCOIN = {"4h": 45, "1h": 30}
WIN_M, STEP_M = 7.0, 1.0
SINCE_Y = 2022
MS_M = 30.44 * 24 * 3600 * 1000
t0 = int(dt.datetime(SINCE_Y, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
FWD = 12


def rr_feat(r, i, lb):
    """RR как в original: по прошлым [i-lb, i)."""
    w = r[i - lb:i]
    w = w[np.isfinite(w)]
    if len(w) < lb * 0.8:
        return np.nan
    sd = w.std()
    if sd <= 0:
        return np.nan
    shock = np.where(np.abs(w) > 2 * sd)[0]
    shock = shock[shock < len(w) - FWD]
    if len(shock) < 5:
        return np.nan
    return float(np.median([w[k + 1:k + 1 + FWD].sum() for k in shock]) / sd)


def buyout_feat(r, i, lb):
    """ВЫКУПАЕМОСТЬ ПРОЛИВОВ: median(сумма 12-барных доходностей ПОСЛЕ пролива r<−2σ)."""
    w = r[i - lb:i]
    w = w[np.isfinite(w)]
    if len(w) < lb * 0.8:
        return np.nan
    sd = w.std()
    if sd <= 0:
        return np.nan
    dips = np.where(w < -2 * sd)[0]
    dips = dips[dips < len(w) - FWD]
    if len(dips) < 5:
        return np.nan
    return float(np.median([w[k + 1:k + 1 + FWD].sum() for k in dips]) / sd)


for tf in TFS:
    lb = LB[tf]
    con = sqlite3.connect(DB)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe=? AND time>=? "
        "GROUP BY symbol HAVING n>? ORDER BY n DESC LIMIT ?",
        (tf, t0, lb * 2, NCOIN[tf])).fetchall()]
    con.close()

    DATA, turn = {}, {}
    for s in syms:
        c = sqlite3.connect(DB)
        d = pd.read_sql("SELECT time,close,volume FROM ohlcv_cache WHERE symbol=? "
                        "AND timeframe=? AND time>=? ORDER BY time", c, params=(s, tf, t0))
        c.close()
        if len(d) >= lb * 2:
            DATA[s] = d
            turn[s] = float(np.nanmedian((d.close * d.volume).values))
    if not DATA:
        print(f"[{tf}] нет данных")
        continue
    mt = np.nanmedian(list(turn.values()))
    liq = [s for s in DATA if turn[s] >= mt]

    rows = []   # (lo_ms, rr, buyout)
    for s in liq:
        d = DATA[s]
        C = d.close.values
        T = d.time.values
        r = np.concatenate([[np.nan], np.diff(C) / C[:-1] * 100])
        cur = int(d.time.iloc[0])
        t_max = int(d.time.iloc[-1])
        while cur + WIN_M * MS_M <= t_max:
            idx = np.where((T >= cur) & (T < cur + WIN_M * MS_M))[0]
            if len(idx) < 100:
                cur += STEP_M * MS_M
                continue
            j = idx[-1]
            rr = rr_feat(r, j, lb)
            bo = buyout_feat(r, j, lb)
            if np.isfinite(rr) and np.isfinite(bo):
                rows.append((cur, rr, bo))
            cur += STEP_M * MS_M

    agg = {}
    for lo, rr, bo in rows:
        agg.setdefault(lo, [[], []])[0].append(rr)
        agg.setdefault(lo, [[], []])[1].append(bo)
    out = sorted((lo, float(np.median(v[0])), float(np.median(v[1])))
                 for lo, v in agg.items() if len(v[0]) >= 10)

    rr_arr = np.array([x[1] for x in out])
    bo_arr = np.array([x[2] for x in out])
    print(f"\n── {tf} ── окон {len(out)} (вселенная {len(liq)}) · LB={lb} · forward {FWD} баров")
    print(f"  {'окно':<9} {'RR':>8} {'выкуп-проливов':>15}  знак совпал")
    agree = 0
    for lo, rr, bo in out:
        d0 = dt.datetime.fromtimestamp(lo / 1000, dt.timezone.utc).strftime("%Y-%m")
        ok = (rr > 0) == (bo > 0)
        agree += ok
        print(f"  {d0:<9} {rr:>+8.3f} {bo:>+14.3f}  {'✓' if ok else '✗'}")
    if len(out) >= 6:
        pr = stats.pearsonr(rr_arr, bo_arr)
        sp = stats.spearmanr(rr_arr, bo_arr)
        print(f"  согласованность знака {agree}/{len(out)} ({100*agree/len(out):.0f}%)")
        print(f"  Pearson corr(RR, выкупаемость) = {pr.statistic:+.3f} (p={pr.pvalue:.3f}) · "
              f"Spearman = {sp.statistic:+.3f} (p={sp.pvalue:.3f})")
        print(f"  ⟹ {'ГИПОТЕЗА ПОДТВЕРЖДЕНА: RR измеряет выкупаемость проливов' if pr.statistic > 0.5 and pr.pvalue < 0.05 else 'НЕ подтверждена напрямую (слабая связь RR ↔ выкупаемость)'}")

print("\nПримечание: «выкупаемость проливов» = median(сумма 12-барных доходностей ПОСЛЕ r<−2σ)")
print("в том же окне, нормированная на σ. RR — та же величина по |r|>2σ (обе стороны).")
print("Гипотеза Даата: RR претендует на выкупаемость проливов, НЕ на рост рынка.")
