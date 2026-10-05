#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Замер конфлюэнции SMC: платят ли НЕСКОЛЬКО подтверждений (бэклог N25).

Постановка Егора 05.10: «концепция Smart Money подразумевает наличие нескольких
подтверждений для входа — именно поэтому и вводились адаптивные веса».

🔴 ЧТО СЧИТАТЬ ПОДТВЕРЖДЕНИЕМ. Булевы поля снимка («зона есть») НЕ ГОДЯТСЯ: они
горят почти всегда — медиана 12 активных из 32, `fvg_open` на 2+ ТФ у 99.8% сделок.
Это записано ещё 02.09 в ARCH-137.6 (`mtf_smc_specialist.py:244`): «булевы
вырождаются тем сильнее, чем ЛУЧШЕ работает детектор». Поэтому подтверждение здесь —
попадание НЕПРЕРЫВНОГО признака в свой сильный дециль (ближе/свежее/крупнее, чем
у 90% сделок). Порог ОТНОСИТЕЛЬНЫЙ: абсолютный «ближе 1 ATR» снова делает
подтверждение нормой, а не редкостью.

🔴 МЕРИМ В % NET (ЗАКОН №1), не в R и не в доле побед. Контроль — перестановка
счётчика между сделками, на среднем И на медиане: среднее у нас держится на хвосте.

Результат прогона 05.10 (2593 сделки VST, апр→окт, 496 монет):
    среднее: n_conf≥4 против ≤1 → +0.392 п.п., контроль 1.3% — проходит
    медиана: p=0.138, контроль 13.8% — НЕ проходит
    σ по корзинам: 2.33 → 3.28 → 3.53 → 4.56, растут ОБА хвоста
    n_conf ↔ strength: rho=−0.0007 — живая шкала о конфлюэнции не знает ничего
Вывод: подтверждения маркируют режим высокой дисперсии, а не качество сетапа.
Подробно: obsidian/Research/2026-10-05-SMC-Confluence-Variance.md

Требует пересчитанных снимков: python scripts/smc_backfill_snaps.py --limit N

Запуск:
    python scripts/measure_smc_confluence.py            # базовый прогон
    python scripts/measure_smc_confluence.py --decile 0.05   # строже порог редкости
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

import core.ml.mtf_smc_specialist as M

OUT = ROOT / "oko_feed" / "smc_backfill.db"
DB = ROOT / "subscriptions.db"
TFS = ["1d", "4h", "1h", "15m"]
MISS = M._MISS

# Направление «сильного» конца: -1 → сильным считаем МАЛОЕ значение (близко/свежо),
# +1 → БОЛЬШОЕ (крупная зона, сильный слом). Поля-признаки направления и доли пропущены:
# fib_dir_long/brk_internal булевы по смыслу, fib_pos — позиция, не сила.
STRONG = {
    "ob_bull_dist_atr": -1, "ob_bear_dist_atr": -1, "fvg_dist_atr": -1,
    "ote_dist_atr": -1, "eqh_dist_atr": -1, "eql_dist_atr": -1,
    "liq_buy_dist_atr": -1, "liq_sell_dist_atr": -1, "brk_dist_atr": -1,
    "ob_bull_age": -1, "fvg_age": -1, "brk_age": -1,          # свежее = сильнее
    "fvg_size_atr": +1, "brk_strength": +1,                   # крупнее = сильнее
}
DECILE = 0.10          # «сильный дециль» — верхние/нижние 10% (меняется --decile)


def load() -> pd.DataFrame:
    con = sqlite3.connect(f"file:{OUT}?mode=ro", uri=True)
    rows = con.execute("SELECT trade_id, snap_json, y, created_at FROM smc_samples").fetchall()
    con.close()
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    meta = {r[0]: r[1:] for r in db.execute(
        "SELECT id, direction, profit_pct, symbol, execution_mode, "
        "       COALESCE(features_json,'') LIKE '%ledger_mismatch%' FROM simulated_trades")}
    db.close()

    recs = []
    for tid, sj, y, created in rows:
        m = meta.get(tid)
        if not m:
            continue
        direction, pnl, symbol, exmode, bad = m
        if bad or exmode != "VST" or pnl is None:
            continue
        snap = json.loads(sj)
        row = dict(trade_id=tid, y=int(y), pnl=float(pnl), symbol=symbol,
                   side=str(direction or "?").upper(), created=created)
        for tf in TFS:
            s = snap.get(tf) or {}
            for k in STRONG:
                v = s.get(k)
                row[f"{tf}:{k}"] = (float(v) if isinstance(v, (int, float))
                                    and float(v) != MISS else np.nan)
        recs.append(row)
    df = pd.DataFrame(recs)
    df["t"] = pd.to_datetime(df["created"], format="mixed", utc=True)
    df["month"] = df["t"].dt.to_period("M").astype(str)
    return df


def mark_strong(df: pd.DataFrame) -> pd.DataFrame:
    """Отмечает для каждого (ТФ, признак) попадание в сильный дециль."""
    cols = []
    print(f"\nПОРОГИ СИЛЬНОГО ДЕЦИЛЯ (доля сработок должна быть ≈{DECILE*100:.0f}%):")
    print(f"  {'признак':<28}{'порог':>10}{'сработок':>11}{'доля':>8}")
    for tf in TFS:
        for k, direction in STRONG.items():
            c = f"{tf}:{k}"
            s = df[c]
            if s.notna().sum() < 200:
                continue
            q = s.quantile(DECILE if direction < 0 else 1 - DECILE)
            hit = (s <= q) if direction < 0 else (s >= q)
            hit = hit.fillna(False)
            if not (0.02 <= hit.mean() <= 0.35):     # вырожденное распределение — пропуск
                continue
            df[f"S|{c}"] = hit.astype(int)
            cols.append(f"S|{c}")
            if tf == "4h":                            # печатаем один ТФ для компактности
                print(f"  4h:{k:<25}{q:>10.2f}{int(hit.sum()):>11}{hit.mean()*100:>7.1f}%")
    df["n_conf"] = df[cols].sum(axis=1)
    print(f"\nвсего условий-подтверждений: {len(cols)} (4 ТФ × признаки)")
    return df


def table(df, col, title, bins=None, min_n=40):
    base = df["pnl"].mean()
    print(f"\n{title}   база % net {base:+.3f}, n={len(df)}")
    g = df.copy()
    g["_k"] = pd.cut(g[col], bins=bins, include_lowest=True) if bins is not None else g[col]
    print(f"  {'корзина':<16}{'n':>6}{'% net':>9}{'медиана':>9}{'побед':>8}"
          f"{'Δ база':>9}{'без топ10%':>11}{'монет':>7}")
    for k, grp in g.groupby("_k", observed=True):
        if len(grp) < min_n:
            continue
        p = grp["pnl"]
        frail = p.sort_values().iloc[:max(1, int(len(p) * 0.9))].mean()
        print(f"  {str(k):<16}{len(grp):>6}{p.mean():>+9.3f}{p.median():>+9.3f}"
              f"{grp['y'].mean()*100:>7.1f}%{p.mean()-base:>+9.3f}{frail:>+11.3f}"
              f"{grp['symbol'].nunique():>7}")


def control(df, col, hi, lo, label, n=300):
    a = df.loc[df[col] >= hi, "pnl"]
    b = df.loc[df[col] <= lo, "pnl"]
    if len(a) < 30 or len(b) < 30:
        print(f"  {label}: мало данных (hi={len(a)}, lo={len(b)})")
        return
    real = a.mean() - b.mean()
    rng = np.random.default_rng(42)
    v, pnl = df[col].values, df["pnl"].values
    sp = np.array([pnl[(p := rng.permutation(v)) >= hi].mean() - pnl[p <= lo].mean()
                   for _ in range(n)])
    print(f"  {label}: факт {real:+.3f} п.п. [{a.mean():+.3f} n={len(a)} против "
          f"{b.mean():+.3f} n={len(b)}] · контроль {sp.mean():+.3f} ± {sp.std():.3f} · "
          f"прогонов ≥ факта: {(sp >= real).mean()*100:.1f}%")


def main():
    df = load()
    print(f"образцов: {len(df)} · окно {df['t'].min().date()}→{df['t'].max().date()} · "
          f"монет {df['symbol'].nunique()} · LONG {int((df.side=='LONG').sum())} / "
          f"SHORT {int((df.side=='SHORT').sum())}")
    df = mark_strong(df)
    d = df["n_conf"].describe()
    print(f"n_conf: мин {d['min']:.0f} · 25% {d['25%']:.0f} · медиана {d['50%']:.0f} · "
          f"75% {d['75%']:.0f} · макс {d['max']:.0f}")
    print("доля сделок с n_conf ≥ k:", {k: round((df.n_conf >= k).mean() * 100, 1)
                                        for k in (1, 2, 3, 4, 5, 6, 8, 10)})

    bins = [-0.1, 0, 1, 2, 3, 4, 6, 100]
    table(df, "n_conf", "ЧИСЛО РЕДКИХ ПОДТВЕРЖДЕНИЙ (сильный дециль)", bins=bins)
    for s in ("LONG", "SHORT"):
        sub = df[df.side == s]
        if len(sub) > 400:
            table(sub, "n_conf", f"РЕДКИЕ ПОДТВЕРЖДЕНИЯ — {s}", bins=bins)

    print("\nКОНТРОЛЬ (n_conf перемешан между сделками, 300 прогонов):")
    control(df, "n_conf", 3, 0, "n_conf ≥3 против 0")
    control(df, "n_conf", 4, 1, "n_conf ≥4 против ≤1")
    for s in ("LONG", "SHORT"):
        sub = df[df.side == s]
        if len(sub) > 400:
            control(sub, "n_conf", 3, 0, f"{s}: n_conf ≥3 против 0")

    print("\nПО МЕСЯЦАМ (n_conf ≥3 минус n_conf 0):")
    for m, grp in df.groupby("month"):
        a, b = grp[grp.n_conf >= 3], grp[grp.n_conf == 0]
        if len(a) < 25 or len(b) < 25:
            continue
        print(f"  {m}  n={len(grp):>5}  Δ={a['pnl'].mean()-b['pnl'].mean():+.3f}  "
              f"({a['pnl'].mean():+.3f}/{len(a)} против {b['pnl'].mean():+.3f}/{len(b)})")

    # какие именно условия платят поодиночке
    print("\nОТДЕЛЬНЫЕ УСЛОВИЯ (сработало против не сработало), топ по |Δ|:")
    base = df["pnl"].mean()
    rows = []
    for c in [c for c in df.columns if c.startswith("S|")]:
        a, b = df.loc[df[c] == 1, "pnl"], df.loc[df[c] == 0, "pnl"]
        if len(a) < 80:
            continue
        rows.append((a.mean() - b.mean(), c[2:], len(a), a.mean()))
    rows.sort(key=lambda x: -abs(x[0]))
    print(f"  {'условие':<34}{'n':>7}{'% net':>9}{'Δ к остальным':>15}")
    for d_, name, n, mean in rows[:14]:
        print(f"  {name:<34}{n:>7}{mean:>+9.3f}{d_:>+15.3f}")


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--decile", type=float, default=0.10,
                    help="порог редкости: 0.10 = сильные 10%% распределения")
    a = ap.parse_args()
    global DECILE
    DECILE = a.decile

    df = load()
    if df.empty:
        print("нет данных — сначала: python scripts/smc_backfill_snaps.py --limit 3000")
        return 1
    print(f"образцов: {len(df)} · окно {df['t'].min().date()}→{df['t'].max().date()} · "
          f"монет {df['symbol'].nunique()} · LONG {int((df.side=='LONG').sum())} / "
          f"SHORT {int((df.side=='SHORT').sum())}")
    df = mark_strong(df)
    print("доля сделок с n_conf >= k:",
          {k: round((df.n_conf >= k).mean() * 100, 1) for k in (1, 2, 3, 4, 6, 8)})

    bins = [-0.1, 0, 1, 2, 3, 4, 6, 100]
    table(df, "n_conf", "ЧИСЛО РЕДКИХ ПОДТВЕРЖДЕНИЙ", bins=bins)
    for s in ("LONG", "SHORT"):
        sub = df[df.side == s]
        if len(sub) > 400:
            table(sub, "n_conf", f"РЕДКИЕ ПОДТВЕРЖДЕНИЯ — {s}", bins=bins)

    print("\nКОНТРОЛЬ НА СРЕДНЕМ (перестановка n_conf, 300 прогонов):")
    control(df, "n_conf", 3, 0, "n_conf >=3 против 0")
    control(df, "n_conf", 4, 1, "n_conf >=4 против <=1")

    # 🔴 Контроль на МЕДИАНЕ обязателен: среднее у нас держится на правом хвосте.
    import numpy as _np
    rng = _np.random.default_rng(42)
    v, pnl = df["n_conf"].values, df["pnl"].values
    real = _np.median(pnl[v >= 4]) - _np.median(pnl[v <= 1])
    sp = _np.array([_np.median(pnl[(p := rng.permutation(v)) >= 4]) - _np.median(pnl[p <= 1])
                    for _ in range(300)])
    print(f"КОНТРОЛЬ НА МЕДИАНЕ: факт {real:+.3f} п.п. · контроль {sp.mean():+.3f} "
          f"± {sp.std():.3f} · прогонов >= факта: {(sp >= real).mean()*100:.1f}%")

    print("\nРАЗБРОС И ХВОСТЫ (главная находка — растут ОБА конца):")
    g = df.copy()
    g["_k"] = pd.cut(g["n_conf"], bins=[-0.1, 1, 3, 6, 100], include_lowest=True)
    print(f"  {'корзина':<16}{'n':>6}{'sigma':>9}{'>+2%':>8}{'<-2%':>8}{'медиана':>10}{'среднее':>10}")
    for k, grp in g.groupby("_k", observed=True):
        p = grp["pnl"]
        print(f"  {str(k):<16}{len(grp):>6}{p.std():>9.3f}{(p>2).mean()*100:>7.1f}%"
              f"{(p<-2).mean()*100:>7.1f}%{p.median():>+10.3f}{p.mean():>+10.3f}")

    print("\nПО МЕСЯЦАМ (среднее n_conf>=4 минус <=1):")
    plus = tot = 0
    for m, grp in df.groupby("month"):
        a_, b_ = grp[grp.n_conf >= 4], grp[grp.n_conf <= 1]
        if len(a_) < 15 or len(b_) < 15:
            continue
        d = a_["pnl"].mean() - b_["pnl"].mean()
        tot += 1
        plus += d > 0
        print(f"  {m}  n={len(grp):>5}  d={d:+.3f}  ({a_['pnl'].mean():+.3f}/{len(a_)} "
              f"против {b_['pnl'].mean():+.3f}/{len(b_)})")
    print(f"  -> месяцев со знаком '+': {plus} из {tot}")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                # noqa: BLE001
        pass
    sys.exit(main())
