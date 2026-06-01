# -*- coding: utf-8 -*-
"""ARCH-124 shadow — A/B regime (v1 синхронность) vs regime_v2 (HTF-доминант).

v1 (classify_from_dataframes): TREND требует синхронности 15m==1h==4h, иначе RANGE.
Аудит 30.05: 78% RANGE-сделок реально трендили (15m-шум рассинхронит с 4h).
v2 (classify_v2 HTF-доминант): 4h-supertrend главный, 15m/1h не блокируют.

regime_v2 пишется в shadow-поле (use_v2=false → НЕ влияет на торговлю). Здесь
сравниваем по закрытым сделкам: кто точнее предсказывает R, и ловит ли v2
вредные SHORT в мислейбленном аптренде (v1=RANGE, v2=TREND_UP).

Запуск: python scripts/regime_v2_ab.py [--db subscriptions.db]
"""
import argparse
import sqlite3
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
CLOSED = ("TP", "SL", "TSL", "EXPIRED")


def avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="subscriptions.db")
    args = ap.parse_args()
    c = sqlite3.connect(args.db)
    rows = c.execute(
        """SELECT regime, regime_v2, direction, signal_type, status, R_multiple
           FROM simulated_trades
           WHERE regime_v2 IS NOT NULL AND status IN ('TP','SL','TSL','EXPIRED')
                 AND R_multiple IS NOT NULL"""
    ).fetchall()
    c.close()

    n = len(rows)
    print(f"Закрытых сделок с regime_v2: {n}")
    if n < 5:
        print("Мало данных — ждём накопления (нужно ~30+ для вердикта).")
        return

    agree = [r for r in rows if r[0] == r[1]]
    disagree = [r for r in rows if r[0] != r[1]]
    print(f"\nСогласие v1==v2: {len(agree)} (avgR={avg([r[5] for r in agree]):+.3f})")
    print(f"Расхождение:     {len(disagree)} (avgR={avg([r[5] for r in disagree]):+.3f})")

    # Ключевой кейс: v1=RANGE (тренд НЕ виден) vs v2=TREND_* (тренд виден)
    print("\n=== РАСХОЖДЕНИЯ по типу (v1 → v2): avgR + n ===")
    buckets = defaultdict(list)
    for regime, rv2, direction, sig, status, r in disagree:
        buckets[f"{regime}→{rv2}"].append((direction, r))
    for k in sorted(buckets, key=lambda x: -len(buckets[x])):
        rs = [r for _, r in buckets[k]]
        print(f"  {k:<26} n={len(rs):3} avgR={avg(rs):+.3f}")

    # Гипотеза аудита: SHORT при v1=RANGE, но v2=TREND_UP = вредный шорт против тренда
    short_trap = [r for r in rows if r[2] == "SHORT" and r[0] == "RANGE" and r[1] == "TREND_UP"]
    short_ok_v2 = [r for r in rows if r[2] == "SHORT" and r[1] == "TREND_DOWN"]
    print("\n=== ГИПОТЕЗА АУДИТА (ловит ли v2 вредные шорты) ===")
    if short_trap:
        print(f"  SHORT [v1=RANGE → v2=TREND_UP] (v2: 'не шорти, аптренд'): "
              f"n={len(short_trap)} avgR={avg([r[5] for r in short_trap]):+.3f}")
        print("    → если avgR<0 — v2 ПРАВ, эти шорты были против скрытого аптренда")
    else:
        print("  SHORT [v1=RANGE→v2=TREND_UP]: пока нет")
    if short_ok_v2:
        print(f"  SHORT [v2=TREND_DOWN] (v2: 'шорти, нисходящий'): "
              f"n={len(short_ok_v2)} avgR={avg([r[5] for r in short_ok_v2]):+.3f}")

    # Дискриминация: насколько каждая метка разделяет хорошие/плохие сделки
    print("\n=== ДИСКРИМИНАЦИЯ (avgR по метке) ===")
    for tag, idx in (("v1 regime", 0), ("v2 regime_v2", 1)):
        d = defaultdict(list)
        for r in rows:
            d[r[idx]].append(r[5])
        parts = " | ".join(f"{k}:{avg(v):+.2f}(n{len(v)})" for k, v in sorted(d.items()))
        print(f"  {tag:<14} {parts}")


if __name__ == "__main__":
    main()
