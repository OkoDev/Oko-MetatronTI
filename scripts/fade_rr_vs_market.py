# -*- coding: utf-8 -*-
"""RR ПРОТИВ РЫНКА: рыночный ли признак? (13.08.2026, DS).

Пункт плана [[2026-08-12-Fade-Side-Flip-Full-Data]] «проверить RR на других механиках».
Если RR — рыночная характеристика «восстановление после шоков», то он обязан
коррелировать с МЕДИАННОЙ доходностью buy&hold ликвидной вселенной в тех же окнах
(рынок восстанавливается → медиана растёт; шоки продолжаются → медиана падает).
Это НЕ зависит от fade-механики: buy&hold не использует ни ATRTrend, ни WT.

Считаем на 4h (как в original) и 1h:
  окно = 7 мес, шаг 1 мес (как [[fade_rolling_side_flip]]);
  RR   = median(сумма доходностей 12 баров ПОСЛЕ шока |r|>2σ)/σ, окно 200 баров 4h / 792 баров 1h;
  MRET = медианная доходность buy&hold ликвидных монет в том же окне (доходность за 7 мес).

Критерий: Pearson/Spearman corr(RR, MRET) > 0 и значима; знак RR совпадает со знаком MRET
в большинстве окон (таблица согласованности).

Запуск:  python scripts/fade_rr_vs_market.py
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
LB = {"4h": 200, "1h": 792}          # 33 календарных дня
NCOIN = {"4h": 45, "1h": 30}
WIN_M, STEP_M = 7.0, 1.0
SINCE_Y = 2024
MS_M = 30.44 * 24 * 3600 * 1000
t0 = int(dt.datetime(SINCE_Y, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)


def rr_feat(r, i, lb):
    w = r[i - lb:i]
    w = w[np.isfinite(w)]
    if len(w) < lb * 0.8:
        return np.nan
    sd = w.std()
    if sd <= 0:
        return np.nan
    shock = np.where(np.abs(w) > 2 * sd)[0]
    shock = shock[shock < len(w) - 12]
    if len(shock) < 5:
        return np.nan
    return float(np.median([w[k + 1:k + 13].sum() for k in shock]) / sd)


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

    # RR и цена по каждой монете, выровненные по времени.
    # ПРИЧИННАЯ проверка: RR по [j-lb, j), forward-ret = доходность СЛЕДУЮЩИХ 12 баров
    # (горизонт восстановления 2 дня на 4h / 12ч на 1h). Рынок 'восстанавливается' —
    # значит медиана монет растёт именно на этом горизонте.
    FWD = 12
    rows = []   # (ts_ms, rr, fwd_ret)
    for s in liq:
        d = DATA[s]
        C = d.close.values
        T = d.time.values
        r = np.concatenate([[np.nan], np.diff(C) / C[:-1] * 100])
        cur = int(d.time.iloc[0])
        t_max = int(d.time.iloc[-1])
        while cur + WIN_M * MS_M <= t_max:
            lo, hi = cur, cur + WIN_M * MS_M
            idx = np.where((T >= lo) & (T < hi))[0]
            if len(idx) < 100:
                cur += STEP_M * MS_M
                continue
            j = idx[-1]          # последний бар окна
            if j + FWD >= len(C):
                cur += STEP_M * MS_M
                continue
            fwd = (C[j + FWD] - C[j]) / C[j] * 100
            rr = rr_feat(r, j, lb)
            if np.isfinite(rr):
                rows.append((lo, rr, fwd))
            cur += STEP_M * MS_M

    # агрегация по окнам: медиана RR и медиана forward-доходности по вселенной
    agg = {}
    for lo, rr, fwd in rows:
        agg.setdefault(lo, [[], []])[0].append(rr)
        agg.setdefault(lo, [[], []])[1].append(fwd)
    out = sorted((lo, float(np.median(v[0])), float(np.median(v[1])))
                 for lo, v in agg.items() if len(v[0]) >= 10)

    rr_arr = np.array([x[1] for x in out])
    ret_arr = np.array([x[2] for x in out])
    print(f"\n── {tf} ── окон {len(out)} (вселенная {len(liq)} ликвидных) · forward-горизонт {FWD} баров")
    print(f"  {'окно':<9} {'RR (мед)':>9} {'fwd 12б (мед)':>13}  знак совпал")
    agree = 0
    for lo, rr, ret in out:
        d0 = dt.datetime.fromtimestamp(lo / 1000, dt.timezone.utc).strftime("%Y-%m")
        ok = (rr > 0) == (ret > 0)
        agree += ok
        print(f"  {d0:<9} {rr:>+9.3f} {ret:>+12.3f}%  {'✓' if ok else '✗'}")
    if len(out) >= 6:
        pr = stats.pearsonr(rr_arr, ret_arr)
        sp = stats.spearmanr(rr_arr, ret_arr)
        print(f"  согласованность знака {agree}/{len(out)} ({100*agree/len(out):.0f}%)")
        print(f"  Pearson corr = {pr.statistic:+.3f} (p={pr.pvalue:.3f}) · "
              f"Spearman corr = {sp.statistic:+.3f} (p={sp.pvalue:.3f})")
        print(f"  ⟹ {'РЫНОЧНЫЙ признак: RR предсказывает короткий отскок медианного рынка' if pr.statistic > 0.4 and pr.pvalue < 0.05 else 'НЕ подтверждён как рыночный (нужна другая проверка)'}")

print("\nПримечание: fwd 12б = медианная доходность монет за СЛЕДУЮЩИЕ 12 баров (горизонт восстановления);")
print("RR — медиана по вселенной, окно 200 баров 4h / 792 баров 1h (33 календарных дня) до конца окна. Всё причинно.")
