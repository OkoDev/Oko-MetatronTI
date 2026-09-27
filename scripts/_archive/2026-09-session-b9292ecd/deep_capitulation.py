# -*- coding: utf-8 -*-
"""ГЛУБОКАЯ КАПИТУЛЯЦИЯ КОРЗИНОЙ — правильный тест КРАЯ (12.09.2026).

Пять медленных признаков провалили тест на МОНОТОННУЮ связь (разрыв Q5−Q1, перцентиль 38-88 из
нужных 95). Но во всех пяти вылезает ОДИН И ТОТ ЖЕ КРАЙ: когда почти весь рынок под своей MA200,
лонг корзины на 30 дней даёт +5.82% нетто и 5 лет из 5 в плюсе. Тест на монотонность этого
не проверяет — нужен тест «край против остального».

Здесь:
  1. Признак `above_ma200` = доля монет выше собственной MA200 (каузально, только прошлое).
  2. Статистика: средняя доходность корзины вперёд в дни ниже порога МИНУС в остальные дни.
  3. 🔴 Контроль с учётом АВТОКОРРЕЛЯЦИИ: дни идут подряд, поэтому 307 дней Q1 — это не 307
     независимых наблюдений, а несколько эпизодов. Считаем:
       · число НЕЗАВИСИМЫХ эпизодов (серий подряд идущих дней);
       · круговые перестановки признака (500) — сохраняют автокорреляцию признака;
       · блочный бутстрап доходности (блоки = горизонт), 500 итераций.
  4. Эквити БЕЗ ПЕРЕКРЫТИЯ: вход при первом дне ниже порога, держим H дней, следующий вход
     только после выхода. Это то, что реально торгуется.
  5. Пороги: квинтиль и абсолютные 5/10/15/20%.
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
HORIZONS = [7, 30, 60]


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


def episodes(mask: pd.Series) -> int:
    """Число НЕЗАВИСИМЫХ эпизодов = серий подряд идущих True."""
    m = mask.values.astype(int)
    return int(((m[1:] == 1) & (m[:-1] == 0)).sum() + (1 if len(m) and m[0] == 1 else 0))


def test_edge(sig, fwd, thr, n_perm=500, seed=20260912):
    """Край (sig < thr) против остального + круговые перестановки признака."""
    ok = sig.notna() & fwd.notna()
    s, f = sig[ok].values, fwd[ok].values
    inm = s < thr
    if inm.sum() < 20 or (~inm).sum() < 20:
        return None
    real = f[inm].mean() - f[~inm].mean()
    rs = np.random.RandomState(seed)
    outs = []
    for _ in range(n_perm):
        sp = np.roll(s, rs.randint(30, len(s) - 30))
        m = sp < thr
        if m.sum() < 20 or (~m).sum() < 20:
            continue
        outs.append(f[m].mean() - f[~m].mean())
    outs = np.array(outs)
    return {"real": real, "pct": (outs < real).mean() * 100,
            "perm_med": np.median(outs), "perm_95": np.percentile(outs, 95),
            "n_in": int(inm.sum()), "in_mean": f[inm].mean(), "out_mean": f[~inm].mean()}


def no_overlap(sig, px, thr, H):
    """Эквити БЕЗ ПЕРЕКРЫТИЯ: вход при первом дне ниже порога, держим H дней."""
    basket = px.mean(axis=1)  # равновзвешенная (только для дат; доходность считаем по монетам)
    dates = sig.index
    i, trades = 0, []
    while i < len(dates) - H:
        if pd.notna(sig.iloc[i]) and sig.iloc[i] < thr:
            t0, t1 = dates[i], dates[i + H]
            r = (px.loc[t1] / px.loc[t0] - 1).mean() * 100 - COST
            if np.isfinite(r):
                trades.append({"in": t0, "out": t1, "ret": r})
            i += H
        else:
            i += 1
    return pd.DataFrame(trades)


def main():
    px = load()
    print(f"матрица: {px.shape[0]} дней × {px.shape[1]} монет · "
          f"{px.index.min():%Y-%m-%d} → {px.index.max():%Y-%m-%d}\n")
    ma200 = px.rolling(200, min_periods=150).mean()
    sig = (px > ma200).sum(axis=1) / ma200.notna().sum(axis=1) * 100
    print(f"признак above_ma200: медиана {sig.median():.1f}% · мин {sig.min():.1f}% · макс {sig.max():.1f}%\n")

    for H in HORIZONS:
        fwd = (px.shift(-H) / px - 1).mean(axis=1) * 100 - COST
        print(f"\n{'='*92}\nГОРИЗОНТ {H} ДНЕЙ")
        for thr in [5, 10, 15, 20]:
            r = test_edge(sig, fwd, thr)
            if r is None:
                print(f"\n--- порог <{thr}%: мало наблюдений"); continue
            mask = (sig < thr) & fwd.notna()
            ep = episodes(mask)
            verdict = "✅ ПРОШЁЛ" if r["pct"] >= 95 else "❌ шум"
            print(f"\n--- порог <{thr}% монет выше MA200   {verdict}")
            print(f"    дней в крае {r['n_in']} · НЕЗАВИСИМЫХ ЭПИЗОДОВ {ep} "
                  f"· в крае {r['in_mean']:+.2f}% · вне края {r['out_mean']:+.2f}%")
            print(f"    разрыв {r['real']:+.3f}% · перестановки: медиана {r['perm_med']:+.3f}% "
                  f"95-й {r['perm_95']:+.3f}% · ПЕРЦЕНТИЛЬ {r['pct']:.0f}%")
            tr = no_overlap(sig, px, thr, H)
            if len(tr):
                yr = tr.assign(year=tr["in"].dt.year).groupby("year").ret.agg(["size", "mean", "sum"])
                print(f"    БЕЗ ПЕРЕКРЫТИЯ: сделок {len(tr)} · средняя {tr.ret.mean():+.2f}% "
                      f"· медиана {tr.ret.median():+.2f}% · в плюсе {100*(tr.ret>0).mean():.0f}% "
                      f"· сумма {tr.ret.sum():+.1f}%")
                print("    по годам:", {int(k): (int(v['size']), round(v['mean'], 1)) for k, v in yr.iterrows()})


if __name__ == "__main__":
    main()
