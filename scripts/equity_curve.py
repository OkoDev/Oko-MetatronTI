# -*- coding: utf-8 -*-
"""Посуточная equity-кривая из balance_snapshots — РЕАЛЬНЫЙ доход в $ (не R).

R обманчив (fake-R от SL≈entry). Источник истины дохода = equity по счетам.
Показывает дневную динамику портфеля + data-era split вокруг рестарта с фиксами.

Запуск:
  python scripts/equity_curve.py
  python scripts/equity_curve.py --split 2026-06-15T16:08   # граница эры (UTC)
"""
from __future__ import annotations
import sqlite3, sys

sys.stdout.reconfigure(encoding="utf-8")

DB = "subscriptions.db"
# граница data-era: рестарт 15.06 ~16:08 UTC (активация фиксов min_sl_dist/l3/captured_R)
SPLIT = "2026-06-15T16:08"
if "--split" in sys.argv:
    SPLIT = sys.argv[sys.argv.index("--split") + 1]


def main():
    db = sqlite3.connect(DB)
    rows = db.execute(
        "SELECT account_id, timestamp, equity FROM balance_snapshots ORDER BY timestamp"
    ).fetchall()
    if not rows:
        print("balance_snapshots пуст"); return

    # last equity за день по счёту (отсортировано → последний перезаписывает)
    day_acc: dict[tuple[str, int], float] = {}
    for acc, ts, eq in rows:
        day_acc[(ts[:10], acc)] = eq

    dates = sorted({d for d, _ in day_acc})
    accs = sorted({a for _, a in day_acc})

    print(f"=== EQUITY-КРИВАЯ (реальный $, не R) | счетов: {len(accs)} | дней: {len(dates)} ===\n")
    hdr = "дата        " + "".join(f"acc{a:<8}" for a in accs) + "Σ портфель   Δ день"
    print(hdr); print("-" * len(hdr))

    prev = None
    for d in dates:
        parts, tot = "", 0.0
        for a in accs:
            eq = day_acc.get((d, a))
            parts += f"{eq:>7.0f} " if eq is not None else f"{'—':>7} "
            tot += eq or 0
        delta = f"{tot - prev:+.0f}" if prev is not None else "—"
        print(f"{d}  {parts}  Σ={tot:>7.0f}   {delta}")
        prev = tot

    # data-era split: средняя дневная Δ до/после рестарта
    print(f"\n=== DATA-ERA split вокруг рестарта {SPLIT} ===")
    first_ts = rows[0][1]
    last_ts = rows[-1][1]
    # портфель на первый/последний снимок каждой эры
    def portfolio_at(boundary, before):
        sub = {(t[:10], a): e for a, t, e in rows if (t < boundary) == before}
        if not sub:
            return None, None, None
        ds = sorted({d for d, _ in sub})
        def tot_on(day):
            return sum(sub.get((day, a), 0) for a in accs)
        return tot_on(ds[0]), tot_on(ds[-1]), (ds[0], ds[-1])

    for label, before in [("ДО фикса ", True), ("ПОСЛЕ    ", False)]:
        f, l, rng = portfolio_at(SPLIT, before)
        if f is None:
            print(f"  {label}: нет данных")
            continue
        print(f"  {label}: {rng[0]}→{rng[1]}  портфель {f:.0f}→{l:.0f}  Δ={l-f:+.0f} ({100*(l-f)/f:+.1f}%)")
    print(f"\n  (диапазон snapshots: {first_ts[:16]} .. {last_ts[:16]} UTC)")
    db.close()


if __name__ == "__main__":
    main()
