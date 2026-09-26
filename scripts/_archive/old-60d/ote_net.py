# -*- coding: utf-8 -*-
"""ЧИСТЫЙ NET-ЗАМЕР — убирает gross-оптимизм из ote_remine (signals.csv).

Модель выхода на каждой сделке: TP=T (win +T) ЕСЛИ mfe_r>=T (раннер дошёл до T ДО SL),
иначе SL (loss −1R). Минус комиссия в R: fee_R = ROUND_TRIP%/sl_pct (тугой SL → больше комса
в R — честная плата за тугость). E[net] = WR×T − (1−WR) − fee_R.

Свип TP-таргетов → оптимальный T net по каждому сетапу. БЕЗ gross-иллюзий.
⚠️ Аппрокс: mfe_r<T трактуется как −1R (SL/expiry). При тугом SL сделки резолвятся быстро → ок.

Запуск: python scripts/ote_net.py
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "data" / "research" / "2026-06-21--ote-remine" / "signals.csv"
ROUND_TRIP = 0.10      # % комиссия туда-обратно (taker 0.05×2). slippage добавит — консервативно.
TPS = [1.0, 1.5, 2.0, 3.0, 5.0]
MIN_N = 100


def load():
    rows = []
    with open(CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                rows.append({
                    "setup": r["setup"], "dir": r["dir"],
                    "mfe_r": float(r["mfe_r"]), "sl_pct": float(r["sl_pct"]),
                    "n_up": r.get("n_up"), "n_down": r.get("n_down"),
                })
            except Exception:
                continue
    return rows


def net_exp(rows, T):
    """E[net R] под выходом TP=T/SL=-1 минус комиссия. → (exp, wr, n)."""
    n = len(rows)
    if n == 0:
        return None
    tot = 0.0
    wins = 0
    for r in rows:
        fee = ROUND_TRIP / r["sl_pct"] if r["sl_pct"] > 0 else 0.5
        if r["mfe_r"] >= T:
            tot += T - fee
            wins += 1
        else:
            tot += -1.0 - fee
    return tot / n, round(100 * wins / n), n


def best_tp(rows):
    """Лучший TP по net-экспектанси. → (T, exp, wr, n)."""
    best = None
    for T in TPS:
        e = net_exp(rows, T)
        if e and (best is None or e[0] > best[1]):
            best = (T, e[0], e[1], e[2])
    return best


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rows = load()
    print(f"# ЧИСТЫЙ NET-ЗАМЕР (комиссия round-trip {ROUND_TRIP}%) — {len(rows)} сделок\n")
    print(f"> E[net R] = WR×T − (1−WR) − fee_R · fee_R = {ROUND_TRIP}%/sl_dist · выход TP=T/SL=−1R\n")

    base = best_tp(rows)
    print(f"**BASELINE:** best TP +{base[0]}R → **net E={base[1]:+.3f}R** WR{base[2]}% n={base[3]}\n")

    # по setup×dir
    print("## setup×dir (лучший TP net)\n")
    print("| сетап | n | лучший TP | net E[R] | WR | net vs base |")
    print("|---|---|---|---|---|---|")
    by = defaultdict(list)
    for r in rows:
        by[f"{r['setup']} {r['dir']}"].append(r)
    res = [(k, best_tp(v)) for k, v in by.items() if len(v) >= MIN_N]
    res.sort(key=lambda x: x[1][1], reverse=True)
    for k, b in res:
        lift = b[1] - base[1]
        flag = "🟢" if b[1] > 0 else "🔴"
        print(f"| {k} | {b[3]} | +{b[0]}R | **{b[1]:+.3f}** {flag} | {b[2]}% | {lift:+.3f} |")

    # по SL-tightness (ключевой: net «съедает» ли тугость комиссией?)
    print("\n## SL-tightness (net — выживает ли тугой SL после комиссии?)\n")
    print("| SL | n | лучший TP | net E[R] | WR |")
    print("|---|---|---|---|---|")
    def slb(r):
        return "SL<0.3%" if r["sl_pct"] < 0.3 else "SL0.3-0.5%" if r["sl_pct"] < 0.5 \
            else "SL0.5-1%" if r["sl_pct"] < 1 else "SL>1%"
    bt = defaultdict(list)
    for r in rows:
        bt[slb(r)].append(r)
    order = ["SL<0.3%", "SL0.3-0.5%", "SL0.5-1%", "SL>1%"]
    for k in order:
        v = bt.get(k, [])
        if len(v) >= MIN_N:
            b = best_tp(v)
            print(f"| {k} | {b[3]} | +{b[0]}R | **{b[1]:+.3f}** | {b[2]}% |")

    # топ setup × фикс TP=3 (хвост) net
    print("\n## setup×dir при TP=+3R (хвостовая стратегия) net\n")
    print("| сетап | n | net E[R] @3R | WR@3R |")
    print("|---|---|---|---|")
    r3 = []
    for k, v in by.items():
        if len(v) >= MIN_N:
            e = net_exp(v, 3.0)
            r3.append((k, e[0], e[1], e[2]))
    r3.sort(key=lambda x: x[1], reverse=True)
    for k, e, wr, n in r3[:8]:
        print(f"| {k} | {n} | **{e:+.3f}** | {wr}% |")


if __name__ == "__main__":
    main()
