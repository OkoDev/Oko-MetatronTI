# -*- coding: utf-8 -*-
"""ВИДЕН ЛИ ФЛАГ В РЕАЛЬНОМ ВРЕМЕНИ НА СВОЁМ БАРЕ (13.08.2026, Даат).

Егор: «проверить у OB и Elliott».

Прошлый тест причинности (`combinator_flags_causality.py`) спрашивал: переписывается ли
флаг задним числом? Для FVG он дал 0.010% — и ПРОПУСТИЛ баг смещения на 2 бара.
Причина: флаг на баре i-2 не переписывается — он стабильно ставится на i-2, как только
в данных появляется бар i. Расхождение видно только у самого края обрезки.

Правильный вопрос другой: **в момент бара b знает ли детектор, что на b есть флаг?**
    compute_flags(df[:b+1]).iloc[-1][flag]  ==  compute_flags(df).iloc[b][flag]
Если полный расчёт ставит флаг на b, а расчёт «по состоянию на b» его не видит —
флаг физически недоступен в бою и является look-ahead в бэктесте.

Дополнительно меряется ЛАГ: через сколько баров после b флаг становится виден.
Для FVG ожидаем лаг = 2 (это и есть найденный баг). Для честного флага лаг = 0.

Запуск:  python scripts/flags_realtime_visibility.py [--coins 2] [--samples 12]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from core.calculators.combinator_core import compute_flags  # noqa: E402

DB = "ohlcv_cache.db"
MAX_LAG = 4          # насколько далеко искать момент появления флага (перекрывается --max-lag)


def main() -> int:
    global MAX_LAG
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", type=int, default=2)
    ap.add_argument("--samples", type=int, default=12, help="точек проверки на флаг")
    ap.add_argument("--bars", type=int, default=1200, help="длина окна истории")
    ap.add_argument("--only", type=str, default="", help="подстрока имени флага")
    ap.add_argument("--max-lag", type=int, default=MAX_LAG, help="докуда искать появление флага")
    a = ap.parse_args()
    MAX_LAG = a.max_lag

    t0 = int(dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? "
        "GROUP BY symbol HAVING n>3000 ORDER BY n DESC LIMIT ?", (t0, a.coins)).fetchall()]
    con.close()

    print("═" * 104)
    print(f"ВИДИМОСТЬ ФЛАГА В РЕАЛЬНОМ ВРЕМЕНИ · {len(syms)} монет · 1h · окно {a.bars} баров")
    print(f"вопрос: ставит ли compute_flags(df[:b+1]) флаг на бар b, если полный расчёт его ставит")
    print("═" * 104)

    # seen[flag] = [проверено, не видно сразу, сумма лага, гистограмма лагов]
    seen = defaultdict(lambda: [0, 0, 0, defaultdict(int)])

    for sym in syms:
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        d = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache "
                        "WHERE symbol=? AND timeframe='1h' AND time>=? ORDER BY time",
                        c, params=(sym, t0))
        c.close()
        if len(d) < a.bars + 100:
            continue
        d["ts"] = pd.to_datetime(d.time, unit="ms", utc=True)
        d = d.set_index("ts")[["open", "high", "low", "close", "volume"]].iloc[:a.bars]

        full = compute_flags(d, "1h", include_pivots=True)
        cols = [c_ for c_ in full.columns if (not a.only or a.only in c_)]

        # выбираем бары-события: до samples штук на флаг, не ближе 300 к началу
        targets = defaultdict(list)
        for col in cols:
            v = full[col]
            try:
                arr = np.asarray(v, dtype=bool)
            except Exception:
                continue
            idx = np.flatnonzero(arr)
            idx = idx[(idx > 300) & (idx < len(d) - MAX_LAG - 2)]
            if len(idx) == 0:
                continue
            pick = idx[np.linspace(0, len(idx) - 1, min(a.samples, len(idx))).astype(int)]
            for b in np.unique(pick):
                targets[int(b)].append(col)

        # для каждой точки b считаем флаги по состоянию на b, b+1, ... b+MAX_LAG
        cache = {}
        for b, flist in sorted(targets.items()):
            for lag in range(0, MAX_LAG + 1):
                cut = b + 1 + lag
                if cut not in cache:
                    if cut > len(d):
                        cache[cut] = None
                    else:
                        cache[cut] = compute_flags(d.iloc[:cut], "1h", include_pivots=True)
            for col in flist:
                st = seen[col]
                st[0] += 1
                lag_found = None
                for lag in range(0, MAX_LAG + 1):
                    part = cache.get(b + 1 + lag)
                    if part is None or col not in part.columns or b >= len(part):
                        continue
                    try:
                        if bool(np.asarray(part[col])[b]):
                            lag_found = lag
                            break
                    except Exception:
                        break
                if lag_found is None:
                    st[1] += 1
                    st[3][">%d" % MAX_LAG] += 1
                elif lag_found > 0:
                    st[1] += 1
                    st[2] += lag_found
                    st[3][lag_found] += 1
                else:
                    st[3][0] += 1

    rows = []
    for col, (tot, bad, lagsum, hist) in seen.items():
        if tot < 3:
            continue
        rows.append((col, tot, bad, 100.0 * bad / tot, dict(hist)))
    rows.sort(key=lambda x: (-x[3], -x[1]))
    bad_rows = [r for r in rows if r[2] > 0]

    print(f"\nфлагов проверено: {len(rows)} · СО СМЕЩЕНИЕМ: {len(bad_rows)}")
    if bad_rows:
        print(f"\n🔴 ФЛАГИ, НЕ ВИДНЫЕ НА СВОЁМ БАРЕ (в бэктесте look-ahead, в бою слепота):")
        print(f"{'флаг':<38} {'событий':>9} {'смещённых':>11} {'доля':>8}  распределение лага")
        print("─" * 104)
        for col, tot, bad, pct, hist in bad_rows:
            h = " ".join(f"лаг{k}:{v}" for k, v in sorted(hist.items(), key=lambda x: str(x[0])))
            print(f"{col[:36]:<38} {tot:>9} {bad:>11} {pct:>7.0f}%  {h}")
    else:
        print("\n✅ все проверенные флаги видны на своём баре")

    clean = [r[0] for r in rows if r[2] == 0]
    print(f"\n=== ЧИСТЫЕ (лаг 0 на всех событиях): {len(clean)} ===")
    print("  " + ", ".join(clean[:40]) + (" …" if len(clean) > 40 else ""))
    print("\n" + "═" * 104)
    print("Лаг k означает: флаг реально доступен только через k баров после того бара,")
    print("на который его ставит детектор. В бэктесте это k баров знания будущего.")
    print("═" * 104)
    return 0


if __name__ == "__main__":
    sys.exit(main())
