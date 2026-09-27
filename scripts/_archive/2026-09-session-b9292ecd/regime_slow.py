# -*- coding: utf-8 -*-
"""МЕДЛЕННЫЙ РЕЖИМ: ловится ли годовой переключатель каузальным признаком? (12.09.2026)

Недельная breadth провалила перестановочный контроль (65-й перцентиль вместо 95-го) — она ловит
рябь, а не режим. Но годовой режим в данных железный: 2022/2025/2026 корзина в минусе во ВСЕХ
квинтилях, 2023/2024 в плюсе. Значит признак нужен МЕДЛЕННЫЙ.

Кандидаты (все считаются ТОЛЬКО по прошлым барам, на дату T включительно):
  · breadth30 / breadth90 — доля монет выше своей цены 30/90 дней назад;
  · above_ma200 — доля монет выше своей 200-дневной средней;
  · btc_ma200 — BTC выше/ниже своей 200-дневной (классика);
  · basket_mom90 — медианная доходность корзины за прошлые 90 дней.

Проверяем: предсказывает ли признак знак корзины на 7 и 30 дней вперёд.
Контроль: 200 случайных круговых сдвигов признака (перестановка). Нужен перцентиль ≥95.
Плюс: разбивка по годам (устойчивость) и порог переключения знака.
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
COST = 0.10
FWDS = [7, 30]


def load():
    conn = sqlite3.connect(str(CACHE))
    syms = [r[0] for r in conn.execute(
        "SELECT symbol FROM ohlcv_cache WHERE timeframe='1h' GROUP BY symbol HAVING COUNT(*)>5000 "
        "ORDER BY COUNT(*) DESC")][:PAIRS]
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
            print(f"  загрузка {i}/{len(syms)}", flush=True)
    return pd.DataFrame(ser).sort_index()


def perm_test(sig, fwd, n=200, seed=20260912):
    """Разрыв верх-низ терциля признака против круговых сдвигов. → (real, перцентиль)."""
    ok = sig.notna() & fwd.notna()
    s, f = sig[ok].values, fwd[ok].values
    if len(s) < 200:
        return np.nan, np.nan
    def gap(sv):
        q1, q3 = np.nanpercentile(sv, 33), np.nanpercentile(sv, 67)
        lo, hi = f[sv <= q1], f[sv >= q3]
        if len(lo) < 20 or len(hi) < 20:
            return np.nan
        return np.nanmean(hi) - np.nanmean(lo)
    real = gap(s)
    rs = np.random.RandomState(seed)
    outs = [gap(np.roll(s, rs.randint(30, len(s) - 30))) for _ in range(n)]
    outs = np.array([o for o in outs if not np.isnan(o)])
    return real, (outs < real).mean() * 100 if len(outs) else np.nan


def main():
    px = load()
    print(f"матрица: {px.shape[0]} дней × {px.shape[1]} монет · "
          f"{px.index.min():%Y-%m-%d} → {px.index.max():%Y-%m-%d}\n")

    ma200 = px.rolling(200, min_periods=150).mean()
    sig = pd.DataFrame({
        "breadth30": (px.pct_change(30) > 0).sum(axis=1) / px.pct_change(30).notna().sum(axis=1) * 100,
        "breadth90": (px.pct_change(90) > 0).sum(axis=1) / px.pct_change(90).notna().sum(axis=1) * 100,
        "above_ma200": (px > ma200).sum(axis=1) / ma200.notna().sum(axis=1) * 100,
        "basket_mom90": px.pct_change(90).median(axis=1) * 100,
    })
    btc = [c for c in px.columns if c.startswith("BTC")]
    if btc:
        b = px[btc[0]]
        sig["btc_vs_ma200"] = (b / b.rolling(200, min_periods=150).mean() - 1) * 100

    for FWD in FWDS:
        fwd = (px.shift(-FWD) / px - 1).mean(axis=1) * 100
        print(f"\n{'='*90}\nГОРИЗОНТ {FWD} ДНЕЙ (доходность равновзвешенной корзины вперёд, кост {COST}%)")
        for name in sig.columns:
            s = sig[name]
            d = pd.DataFrame({"s": s, "f": fwd}).dropna()
            if len(d) < 300:
                print(f"\n--- {name}: мало данных ({len(d)})"); continue
            d["q"] = pd.qcut(d.s, 5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"], duplicates="drop")
            t = d.groupby("q").agg(дней=("f", "size"), признак=("s", "median"),
                                   корзина=("f", "mean"), медиана=("f", "median"),
                                   плюс_дней=("f", lambda x: (x > 0).mean() * 100))
            t["ЛОНГ нетто"] = t["корзина"] - COST
            t["ШОРТ нетто"] = -t["корзина"] - COST
            real, pct = perm_test(d.s, d.f)
            print(f"\n--- {name}   разрыв Q5−Q1 = {real:+.3f}% · перцентиль среди 200 перестановок = "
                  f"{pct:.0f}%  {'✅ ПРОШЁЛ' if pct >= 95 else '❌ шум'}")
            print(t.to_string(float_format=lambda x: f"{x:8.3f}"))
            d["year"] = d.index.year
            p = d.pivot_table(index="year", columns="q", values="f", aggfunc="mean") - COST
            print("  по годам (лонг-нетто):")
            print(p.to_string(float_format=lambda x: f"{x:7.2f}"))


if __name__ == "__main__":
    main()
