# -*- coding: utf-8 -*-
"""ПЕРЕКЛЮЧАТЕЛЬ РЕЖИМА БЕЗ ДЕТЕКТОРОВ (12.09.2026).

Карта рамки показала: год бывает «сползают почти все» (доля растущих 3-9%) либо «растут две
трети» (60-65%). Вопрос: видно ли это ЗАРАНЕЕ по прошлым барам?

Метрика (каузальная, только прошлое): BREADTH = доля монет, у которых доходность за последние
7 дней > 0. Считается на дату T включительно по барам ≤ T.
Проверяем: предсказывает ли breadth(T) доходность РАВНОВЗВЕШЕННОЙ корзины за следующие 7 дней.

Выход: квинтили breadth → доходность корзины вперёд (лонг и шорт, с костом), доля положительных
недель, по годам. Если связь монотонная — получаем переключатель «лонг/шорт корзину» без сетапов.
Контроль: та же таблица на ПЕРЕМЕШАННЫХ метках времени (breadth случайно сдвинут) — закон
law_relative_threshold_and_permutation.
"""
from __future__ import annotations
import sqlite3, sys, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
CACHE = ROOT / "ohlcv_cache.db"
PAIRS = 150
LOOK = 7        # дней назад для breadth
FWD = 7         # дней вперёд — горизонт сделки
COST = 0.10     # % круг


def main():
    conn = sqlite3.connect(str(CACHE))
    syms = [r[0] for r in conn.execute(
        "SELECT symbol FROM ohlcv_cache WHERE timeframe='1h' GROUP BY symbol HAVING COUNT(*)>5000 "
        "ORDER BY COUNT(*) DESC")][:PAIRS]
    print(f"монет: {len(syms)} · breadth={LOOK}д назад · горизонт={FWD}д · кост {COST}%", flush=True)
    ser = {}
    for i, s in enumerate(syms, 1):
        df = pd.read_sql_query(
            "SELECT time,close FROM ohlcv_cache WHERE symbol=? AND timeframe='1h' ORDER BY time",
            conn, params=(s,))
        if len(df) < 2000:
            continue
        df["dt"] = pd.to_datetime(df.time, unit="ms", utc=True)
        d = df.set_index("dt").close.resample("1D").last().dropna()
        if len(d) > 400:
            ser[s] = d
        if i % 50 == 0:
            print(f"  {i}/{len(syms)}", flush=True)
    px = pd.DataFrame(ser).sort_index()
    print(f"матрица: {px.shape[0]} дней × {px.shape[1]} монет · {px.index.min():%Y-%m-%d} → {px.index.max():%Y-%m-%d}\n")

    past = px.pct_change(LOOK) * 100                     # доходность за прошедшие LOOK дней (на дату T)
    fwd = px.shift(-FWD) / px - 1                        # доходность ВПЕРЁД FWD дней
    fwd = fwd * 100

    breadth = (past > 0).sum(axis=1) / past.notna().sum(axis=1) * 100
    basket_fwd = fwd.mean(axis=1)                        # равновзвешенная корзина вперёд
    med_fwd = fwd.median(axis=1)

    d = pd.DataFrame({"breadth": breadth, "fwd_mean": basket_fwd, "fwd_med": med_fwd}).dropna()
    d = d[d.index >= d.index.min() + pd.Timedelta(days=LOOK)]
    d["year"] = d.index.year
    print(f"наблюдений (дней): {len(d)}\n")

    print("=== КВИНТИЛИ BREADTH (доля растущих за прошлые 7д) → КОРЗИНА СЛЕДУЮЩИЕ 7д")
    d["q"] = pd.qcut(d.breadth, 5, labels=["Q1 низ", "Q2", "Q3", "Q4", "Q5 верх"])
    t = d.groupby("q").agg(дней=("fwd_mean", "size"), breadth=("breadth", "median"),
                           корзина=("fwd_mean", "mean"), медиана=("fwd_med", "median"),
                           долядней_плюс=("fwd_mean", lambda x: (x > 0).mean() * 100))
    t["ЛОНГ нетто"] = t["корзина"] - COST
    t["ШОРТ нетто"] = -t["корзина"] - COST
    print(t.to_string(float_format=lambda x: f"{x:9.3f}"))

    print("\n=== ТО ЖЕ ПО ГОДАМ (лонг-нетто корзины по квинтилю breadth)")
    p = d.pivot_table(index="year", columns="q", values="fwd_mean", aggfunc="mean") - COST
    print(p.to_string(float_format=lambda x: f"{x:8.3f}"))

    print("\n=== КОНТРОЛЬ: перестановка (breadth сдвинут случайно, связь должна исчезнуть)")
    rs = np.random.RandomState(20260912)
    outs = []
    for _ in range(20):
        sh = rs.randint(30, len(d) - 30)
        dd = d.copy()
        dd["breadth"] = np.roll(d.breadth.values, sh)
        dd["q"] = pd.qcut(dd.breadth, 5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"])
        g = dd.groupby("q").fwd_mean.mean()
        outs.append(g["Q5"] - g["Q1"])
    real = t.корзина.iloc[-1] - t.корзина.iloc[0]
    print(f"реальный разрыв Q5−Q1: {real:+.3f}%")
    print(f"перестановки: медиана {np.median(outs):+.3f}% · 95-й перцентиль {np.percentile(outs, 95):+.3f}% "
          f"· макс {max(outs):+.3f}%")
    print(f"перцентиль реального среди перестановок: {(np.array(outs) < real).mean() * 100:.0f}%")

    print("\n=== ПОРОГ: где breadth переключает знак")
    for lo, hi in [(0, 20), (20, 35), (35, 50), (50, 65), (65, 100)]:
        g = d[(d.breadth >= lo) & (d.breadth < hi)]
        if len(g) < 30:
            continue
        print(f"  breadth {lo:3d}-{hi:3d}%: дней {len(g):5d} · корзина вперёд {g.fwd_mean.mean():+7.3f}% "
              f"· ЛОНГ нетто {g.fwd_mean.mean()-COST:+7.3f}% · ШОРТ нетто {-g.fwd_mean.mean()-COST:+7.3f}% "
              f"· дней в плюс {100*(g.fwd_mean>0).mean():5.1f}%")


if __name__ == "__main__":
    main()
