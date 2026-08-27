# -*- coding: utf-8 -*-
"""ПРИЗНАК ПЕРИОДА: предсказывает ли недавняя работа механики её будущую работу?
(13.08.2026, Даат)

Главный вывод ревизии 13.08: все четыре уцелевших фильтра дают высокий PF в 2024–25
и проваливаются в 2022/2026. Ни один не отвечает на вопрос «работает ли механика СЕЙЧАС»
— все отвечают только «хорош ли этот сигнал».

Здесь проверяется единственный признак периода, который по определению доступен в бою
и не требует новых данных: **собственная недавняя доходность механики**.

Вопрос строго: если последние N закрытых сделок дали положительный результат,
прибыльны ли СЛЕДУЮЩИЕ сделки? Это тест на автокорреляцию доходности стратегии.
  • есть автокорреляция → адаптивный выключатель возможен (торгуем после хороших окон);
  • нет → периоды непредсказуемы изнутри, и вопрос закрыт для этого класса признаков.

Причинность: решение по сделке k принимается ТОЛЬКО по сделкам, закрытым до её открытия.
Учитывается TTL: сделка считается закрытой через TTL баров после входа.

Запуск:  python scripts/fade_regime_self_adaptive.py [--tf 4h]
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DUMPS = {"4h": "scripts/_fade_signals_4h_mkt.csv", "15m": "scripts/_fade_signals_15m_full.csv"}
BAR_MS = {"4h": 4 * 3600 * 1000, "15m": 15 * 60 * 1000}
TTL = 24


def stat(v: np.ndarray):
    if len(v) == 0:
        return None
    pf = v[v > 0].sum() / abs(v[v < 0].sum()) if (v < 0).any() else 99.0
    return len(v), float(np.median(v)), 100.0 * float((v > 0).mean()), float(pf), float(v.sum())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="4h", choices=list(DUMPS))
    ap.add_argument("--stop-lo", type=float, default=8.0)
    ap.add_argument("--stop-hi", type=float, default=12.0)
    a = ap.parse_args()

    d = pd.read_csv(DUMPS[a.tf])
    d = d[(d.side == "LONG") & (d.stop_pct > a.stop_lo) & (d.stop_pct <= a.stop_hi)].copy()
    d = d.sort_values("ts").reset_index(drop=True)
    d["closed_ts"] = d.ts + TTL * BAR_MS[a.tf]      # момент, когда результат становится известен
    d["t"] = pd.to_datetime(d.ts, unit="ms")

    print("═" * 96)
    print(f"ПРИЗНАК ПЕРИОДА · {a.tf} · фейд LONG · стоп {a.stop_lo:.0f}–{a.stop_hi:.0f}% · n={len(d)}")
    print("вопрос: предсказывает ли РЕЗУЛЬТАТ последних K закрытых сделок результат следующей?")
    print("═" * 96)

    ts = d.ts.values
    cts = d.closed_ts.values
    net = d.net.values

    for K in (10, 20, 40):
        prev_med = np.full(len(d), np.nan)
        prev_pf = np.full(len(d), np.nan)
        for i in range(len(d)):
            # только сделки, ЗАКРЫТЫЕ строго до открытия текущей
            mask = cts < ts[i]
            idx = np.where(mask)[0]
            if len(idx) < K:
                continue
            w = net[idx[-K:]]
            prev_med[i] = np.median(w)
            prev_pf[i] = w[w > 0].sum() / abs(w[w < 0].sum()) if (w < 0).any() else 99.0
        d[f"prev_med_{K}"] = prev_med
        d[f"prev_pf_{K}"] = prev_pf

        sub = d[d[f"prev_med_{K}"].notna()]
        if len(sub) < 60:
            print(f"\nK={K}: данных мало ({len(sub)})")
            continue

        good = sub[sub[f"prev_med_{K}"] > 0].net.values
        bad = sub[sub[f"prev_med_{K}"] <= 0].net.values
        print(f"\n── окно K={K} последних закрытых сделок ──")
        print(f"{'состояние':<34} {'n':>6} {'медиана':>10} {'WR%':>7} {'PF':>7} {'сумма':>10}")
        for nm, v in (("после ХОРОШИХ (медиана>0)", good), ("после ПЛОХИХ (медиана≤0)", bad)):
            r = stat(v)
            if r:
                print(f"{nm:<34} {r[0]:>6} {r[1]:>+9.2f}% {r[2]:>6.1f}% {r[3]:>7.2f} {r[4]:>+9.1f}")
        if len(good) >= 30 and len(bad) >= 30:
            p = stats.mannwhitneyu(bad, good, alternative="less").pvalue
            sp = stats.spearmanr(sub[f"prev_med_{K}"], sub.net)
            print(f"  значимость (после хороших лучше): p={p:.5f} "
                  f"{'✅ ЕСТЬ автокорреляция' if p < 0.05 else '❌ НЕТ'}")
            print(f"  Spearman(прошлая медиана, результат) = {sp[0]:+.3f} (p={sp[1]:.4f})")

    # сравнение адаптивной схемы с «торговать всегда»
    print("\n" + "═" * 96)
    print("АДАПТИВНАЯ СХЕМА против «торговать всегда» (окно K=20)")
    print("─" * 96)
    sub = d[d["prev_med_20"].notna()]
    on = sub[sub["prev_med_20"] > 0].net.values
    allv = sub.net.values
    for nm, v in (("торговать всегда", allv), ("торговать после хороших окон", on)):
        r = stat(v)
        if r:
            print(f"{nm:<34} n={r[0]:>5} медиана {r[1]:>+7.2f}% WR {r[2]:>5.1f}% "
                  f"PF {r[3]:>6.2f} сумма {r[4]:>+9.1f}")

    print("\n" + "─" * 96)
    print("КОНТРОЛЬ ПО ГОДАМ: спасает ли адаптив провальные годы?")
    sub = sub.assign(year=pd.to_datetime(sub.ts, unit="ms").dt.year)
    print(f"{'год':<8} {'всегда: n / PF':>22} {'адаптив: n / PF':>24} {'спас?':>8}")
    for y in sorted(sub.year.unique()):
        g = sub[sub.year == y]
        if len(g) < 15:
            continue
        ra = stat(g.net.values)
        rb = stat(g[g["prev_med_20"] > 0].net.values)
        if not rb:
            print(f"{y:<8} {ra[0]:>8} / {ra[3]:>7.2f} {'—':>24}")
            continue
        better = "да" if rb[3] > ra[3] else "нет"
        print(f"{y:<8} {ra[0]:>8} / {ra[3]:>7.2f} {rb[0]:>12} / {rb[3]:>7.2f} {better:>8}")
    print("═" * 96)
    return 0


if __name__ == "__main__":
    sys.exit(main())
