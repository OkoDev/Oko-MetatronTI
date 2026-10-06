# -*- coding: utf-8 -*-
"""ФОРВАРД ТЕНЕВЫХ РЕАКЦИЙ КУБА против случайного момента (N12, Егор 07.10).

Что проверяем. 28.09 три из шести межсферных заглушек заменены на РЕАЛЬНЫХ
потребителей, но пока теневых: `core/context/shadow_consumers.py` пишет в
`cube_reactions_shadow` сам факт возникновения условия с ценой момента, решений
не принимает. Планировалось ждать 2–3 недели — к 07.10 накоплено **3225 событий
за 8.4 суток** (507 и 239 монет), цена есть у всех, то есть мерить можно.

Вопрос ровно один: **значит ли реакция что-нибудь для цены?** Если нет — шесть
заглушек честнее переименовать в «доску», а не достраивать до mesh
(расхождение ENCYCLOPEDIA и кода, разбор 26.09).

🔴 КОНТРОЛЬ ОБЯЗАТЕЛЕН ([[law_control_group_random_entry]]): сравниваем не с нулём,
а со СЛУЧАЙНЫМ моментом на той же монете в том же окне. Иначе померяем дрейф рынка.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                        # noqa: BLE001
    pass

from core.infra.market_store import closed_bars          # noqa: E402

DB = "oko_feed/external_data.db"
HORIZONS = {"1ч": 1, "4ч": 4, "24ч": 24}                 # баров 1h
N_CTL = 10                                               # случайных моментов на реакцию


def load() -> pd.DataFrame:
    cx = sqlite3.connect(DB)
    d = pd.read_sql_query(
        "SELECT ts, symbol, consumer, event, decision, px FROM cube_reactions_shadow "
        "WHERE px IS NOT NULL AND px > 0", cx)
    cx.close()
    d["dt"] = pd.to_datetime(d.ts, unit="s", utc=True)
    return d


def main() -> int:
    R = load()
    print(f"реакций: {len(R)} · монет: {R.symbol.nunique()} · "
          f"{R.dt.min():%m-%d %H:%M} → {R.dt.max():%m-%d %H:%M} UTC")
    print(f"потребители: {R.consumer.value_counts().to_dict()}\n")

    rng = np.random.default_rng(42)
    rows = []
    syms = R.symbol.unique()
    for i, s in enumerate(syms, 1):
        try:
            df = closed_bars(s, "1h", 420)
        except Exception:                                # noqa: BLE001
            continue
        if df is None or len(df) < 60:
            continue
        idx = df.index
        close = df.close.values
        g = R[R.symbol == s]
        for _, r in g.iterrows():
            # бар, ЗАКРЫТЫЙ строго до момента реакции
            # r["dt"], а НЕ r.dt: у Series `.dt` — это accessor pandas, не колонка
            k = int(idx.searchsorted(r["dt"], side="left")) - 1
            if k < 1 or k >= len(close) - max(HORIZONS.values()) - 1:
                continue
            base = close[k]
            if not np.isfinite(base) or base <= 0:
                continue
            rec = {"symbol": s, "consumer": r["consumer"], "dt": r["dt"]}
            for nm, h in HORIZONS.items():
                rec[f"fwd_{nm}"] = (close[k + h] / base - 1.0) * 100.0
            # КОНТРОЛЬ: случайные моменты на ТОЙ ЖЕ монете в том же окне
            lo, hi = 1, len(close) - max(HORIZONS.values()) - 1
            if hi > lo:
                qs = rng.integers(lo, hi, size=N_CTL)
                for nm, h in HORIZONS.items():
                    rec[f"ctl_{nm}"] = float(np.mean(
                        (close[qs + h] / close[qs] - 1.0) * 100.0))
            rows.append(rec)
        if i % 100 == 0:
            print(f"  ... {i}/{len(syms)} монет", flush=True)

    D = pd.DataFrame(rows)
    if D.empty:
        print("🔴 НЕТ сопоставленных строк — отказ, а не вывод")
        return 1
    print(f"\nсопоставлено {len(D)} реакций из {len(R)} ({len(D)/len(R)*100:.0f}%)\n")

    print("=" * 96)
    print("ФОРВАРД ПОСЛЕ РЕАКЦИИ против СЛУЧАЙНОГО МОМЕНТА (та же монета, то же окно)")
    print("=" * 96)
    print(f"  {'срез':<22}{'n':>6}" + "".join(f"{h:>22}" for h in HORIZONS))
    print(f"  {'':<22}{'':>6}" + "".join(f"{'реакц / контр / Δ':>22}" for _ in HORIZONS))

    def row(nm, g):
        if len(g) < 40:
            print(f"  {nm:<22}{len(g):>6}  — мало")
            return
        cells = ""
        for h in HORIZONS:
            a, c = g[f"fwd_{h}"].mean(), g[f"ctl_{h}"].mean()
            cells += f"{a:>+7.3f}/{c:>+6.3f}/{a - c:>+6.3f}"
        print(f"  {nm:<22}{len(g):>6}{cells}")

    row("ВСЕ реакции", D)
    for cns, g in D.groupby("consumer"):
        row(cns, g)

    print("\n  — то же по МЕДИАНЕ (деньги в медиане, не в среднем) —")
    def rowm(nm, g):
        if len(g) < 40:
            return
        cells = ""
        for h in HORIZONS:
            a, c = g[f"fwd_{h}"].median(), g[f"ctl_{h}"].median()
            cells += f"{a:>+7.3f}/{c:>+6.3f}/{a - c:>+6.3f}"
        print(f"  {nm:<22}{len(g):>6}{cells}")
    rowm("ВСЕ реакции", D)
    for cns, g in D.groupby("consumer"):
        rowm(cns, g)

    # перестановка: случайные подвыборки того же размера из контроля
    print("\n  — ПЕРЕСТАНОВКА по 4ч (400 розыгрышей) —")
    real = D["fwd_4ч"].mean() - D["ctl_4ч"].mean()
    sims = []
    pool = D["ctl_4ч"].values
    for _ in range(400):
        q = rng.choice(len(D), size=len(D), replace=True)
        sims.append(D["fwd_4ч"].values[q].mean() - pool[q].mean())
    sims = np.array(sims)
    print(f"  реальная Δ {real:+.4f} · бутстрэп: средн {sims.mean():+.4f}, "
          f"доля ≤0 = {(sims <= 0).mean():.3f}")
    print(f"  95% интервал: [{np.quantile(sims, .025):+.4f}; {np.quantile(sims, .975):+.4f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
