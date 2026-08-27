# -*- coding: utf-8 -*-
"""РИСК-ОСТАНОВКА вместо предсказания периода (13.08.2026, Даат).

Контекст. Проверено три класса признаков периода (собственная доходность механики,
корреляционный режим, объём рынка) — ни один не отличает 2024 от 2026
([[period_signal_self_adaptive_dead]]). Вывод: период доступными данными не предсказывается.
Остаётся защита ПО ФАКТУ убытка, а не по прогнозу.

Здесь моделируются три правила остановки на реальной последовательности сделок.
Правила намеренно тупые — это защита, а не эдж, и она не должна ничего «угадывать»:

  A. СЕРИЯ: K убытков подряд → пауза на P дней.
  B. ПРОСАДКА: падение equity на D% от пика → пауза на P дней.
  C. ОКНО: сумма последних W закрытых сделок < 0 → пауза на P дней.

Учитывается TTL: сделка влияет на решение только после закрытия (ts + 24 бара).
Сделки в паузе пропускаются целиком — как если бы бот был выключен.

Ключевой вопрос замера — НЕ «вырастет ли итог», а «уменьшится ли потеря в плохие годы
и сколько это стоит в хорошие».

Запуск:  python scripts/fade_risk_halt_sim.py [--tf 4h]
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DUMPS = {"4h": "scripts/_fade_signals_4h_state.csv", "15m": "scripts/_fade_signals_15m_full.csv"}
BAR_MS = {"4h": 4 * 3600 * 1000, "15m": 15 * 60 * 1000}
TTL = 24
DAY = 86_400_000


def simulate(d: pd.DataFrame, rule: str, bar_ms: int, K=3, D=25.0, W=15, pause_days=14):
    """Возвращает маску сделок, которые бот РЕАЛЬНО взял бы, и число пауз."""
    ts = d.ts.values
    closed = ts + TTL * bar_ms
    net = d.net.values
    n = len(d)
    taken = np.zeros(n, dtype=bool)

    equity = 0.0
    peak = 0.0
    streak = 0
    paused_until = -1
    pauses = 0
    # результаты закрытых сделок в порядке закрытия
    hist_close_ts: list[int] = []
    hist_net: list[float] = []

    order = np.argsort(closed)
    ptr = 0

    for i in range(n):
        # применяем все сделки, закрывшиеся ДО открытия текущей
        while ptr < n and closed[order[ptr]] < ts[i]:
            j = order[ptr]
            if taken[j]:
                r = net[j]
                equity += r
                peak = max(peak, equity)
                streak = streak + 1 if r < 0 else 0
                hist_close_ts.append(closed[j])
                hist_net.append(r)
                # проверяем условие остановки ПОСЛЕ каждой закрытой сделки
                trigger = False
                if rule == "A":
                    trigger = streak >= K
                elif rule == "B":
                    trigger = peak > 0 and (peak - equity) >= D
                elif rule == "C":
                    if len(hist_net) >= W:
                        trigger = float(np.sum(hist_net[-W:])) < 0
                if trigger and closed[j] > paused_until:
                    paused_until = closed[j] + pause_days * DAY
                    pauses += 1
                    streak = 0
                    peak = equity          # сброс отсчёта просадки после паузы
            ptr += 1
        if ts[i] >= paused_until:
            taken[i] = True

    return taken, pauses


def summary(v: np.ndarray):
    if len(v) == 0:
        return 0, 0.0, 0.0, 0.0
    pf = v[v > 0].sum() / abs(v[v < 0].sum()) if (v < 0).any() else 99.0
    eq = np.cumsum(v)
    dd = float(np.max(np.maximum.accumulate(eq) - eq)) if len(eq) else 0.0
    return len(v), float(v.sum()), float(pf), dd


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="4h", choices=list(DUMPS))
    ap.add_argument("--pause", type=int, default=14)
    a = ap.parse_args()

    d = pd.read_csv(DUMPS[a.tf])
    d = d[(d.side == "LONG") & (d.stop_pct > 8) & (d.stop_pct <= 12)].sort_values("ts").reset_index(drop=True)
    d["t"] = pd.to_datetime(d.ts, unit="ms")
    d["year"] = d.t.dt.year
    bar = BAR_MS[a.tf]

    print("═" * 100)
    print(f"РИСК-ОСТАНОВКА · {a.tf} · фейд LONG · стоп 8–12% · n={len(d)} · пауза {a.pause} дней")
    print("вопрос: уменьшает ли потерю в ПЛОХИЕ годы и сколько это стоит в хорошие")
    print("═" * 100)

    n0, s0, pf0, dd0 = summary(d.net.values)
    print(f"\n{'вариант':<34} {'сделок':>7} {'сумма':>10} {'PF':>7} {'макс. просадка':>15} {'пауз':>6}")
    print(f"{'БЕЗ ОСТАНОВКИ':<34} {n0:>7} {s0:>+9.1f} {pf0:>7.2f} {dd0:>15.1f} {'—':>6}")

    variants = [
        ("A: 3 убытка подряд", "A", dict(K=3)),
        ("A: 5 убытков подряд", "A", dict(K=5)),
        ("B: просадка ≥25 п.п.", "B", dict(D=25.0)),
        ("B: просадка ≥50 п.п.", "B", dict(D=50.0)),
        ("C: сумма 15 сделок < 0", "C", dict(W=15)),
    ]
    results = {}
    for name, rule, kw in variants:
        taken, pauses = simulate(d, rule, bar, pause_days=a.pause, **kw)
        v = d.net.values[taken]
        n1, s1, pf1, dd1 = summary(v)
        results[name] = (taken, s1, pf1, dd1)
        print(f"{name:<34} {n1:>7} {s1:>+9.1f} {pf1:>7.2f} {dd1:>15.1f} {pauses:>6}")

    print("\n" + "─" * 100)
    print("ПО ГОДАМ: сумма % net (главная проверка — плохие годы)")
    yrs = sorted(d.year.unique())
    head = f"{'вариант':<34}" + "".join(f"{y:>13}" for y in yrs)
    print(head)
    row = f"{'БЕЗ ОСТАНОВКИ':<34}"
    for y in yrs:
        row += f"{d[d.year == y].net.sum():>+13.1f}"
    print(row)
    for name, (taken, *_rest) in results.items():
        row = f"{name:<34}"
        sub = d[taken]
        for y in yrs:
            row += f"{sub[sub.year == y].net.sum():>+13.1f}"
        print(row)

    print("\n" + "─" * 100)
    print("СКОЛЬКО СДЕЛОК ПРОПУЩЕНО ПО ГОДАМ (цена защиты)")
    print(head)
    row = f"{'всего сделок':<34}"
    for y in yrs:
        row += f"{int((d.year == y).sum()):>13}"
    print(row)
    for name, (taken, *_rest) in results.items():
        row = f"{name:<34}"
        sub = d[taken]
        for y in yrs:
            row += f"{int((sub.year == y).sum()):>13}"
        print(row)
    print("═" * 100)
    return 0


if __name__ == "__main__":
    sys.exit(main())
