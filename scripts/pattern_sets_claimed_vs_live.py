# -*- coding: utf-8 -*-
"""НАБОРЫ arch104 И ote_nested: ЗАЯВЛЕНО ПРОТИВ БОЯ (13.08.2026, Даат).

Егор: «копай всё! у нас куча сетапов из комбинатора и пр. исследований лежат без дела»,
«наборы arch104 и ote_nested».

Наборы лежат готовые и размеченные:
  • config/arch104_patterns.yaml — 200 паттернов (101 enabled), метрика test_avgR/test_WR
  • config/ote_setups.yaml       — 18 сетапов + ds_patterns, метрика avgR/wr

Обе метрики — В R И БЕЗ КОСТОВ (`tools/pattern_mining/combinator_v2.py::simulate`
возвращает ровно tp_r или −1.0, косты не вычитаются). 92 из 200 паттернов arch104
заявлены с WR > 90% — числа, невозможные в торговле.

Здесь сверка с ЖИВЫМ результатом: в `simulated_trades.features_json` каждая сделка
несёт `arch104_pattern_id` / `ote_setup_id`. Метрика — % net с костами (ЗАКОН №1).
Это форвард на реальных данных, а не пересчёт того же бэктеста.

Запуск:  python scripts/pattern_sets_claimed_vs_live.py [--min-n 20]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

COST = 0.35


def stat(v):
    v = np.asarray(v, dtype=float)
    if len(v) == 0:
        return None
    pos, neg = v[v > 0].sum(), abs(v[v < 0].sum())
    pf = pos / neg if neg > 0 else 99.0
    srt = np.sort(v)
    cut = max(1, int(len(srt) * 0.10))
    return dict(n=len(v), wr=100.0 * (v > 0).mean(), pf=pf,
                mean=float(v.mean()), med=float(np.median(v)),
                frag=float(srt[:-cut].sum()), total=float(v.sum()))


def load_live(limit: int) -> pd.DataFrame:
    con = sqlite3.connect("file:subscriptions.db?mode=ro", uri=True)
    d = pd.read_sql("""
        SELECT features_json, profit_pct pnl, direction, created_at, symbol,
               entry_price, stop_loss, source_router src, status
        FROM simulated_trades
        WHERE status IN ('TP','SL','TSL','EXPIRED') AND profit_pct IS NOT NULL
          AND features_json IS NOT NULL AND length(features_json) > 50
        ORDER BY id DESC LIMIT ?""", con, params=(limit,))
    con.close()
    rows = []
    for js, pnl, dirn, ts, sym, ep, sl in zip(
            d.features_json, d.pnl, d.direction, d.created_at, d.symbol,
            d.entry_price, d.stop_loss):
        try:
            f = json.loads(js)
        except Exception:
            continue
        stop_pct = abs(ep - sl) / ep * 100 if ep and sl and ep > 0 else np.nan
        rows.append(dict(
            a104=f.get("arch104_pattern_id"),
            a104m=f.get("arch104_matched_patterns"),
            ote=f.get("ote_setup_id"), ote_ltf=f.get("ote_ltf"),
            net=pnl - COST, dirn=(dirn or "").upper(), ts=ts,
            symbol=str(sym).split(":")[0], stop_pct=stop_pct))
    return pd.DataFrame(rows)


def report_group(df: pd.DataFrame, col: str, claimed: dict, title: str, min_n: int):
    print("\n" + "═" * 118)
    print(title)
    print("═" * 118)
    g = df[df[col].notna()]
    if len(g) == 0:
        print("  в живых сделках разметки нет")
        return
    base = stat(g.net.values)
    print(f"живых сделок с разметкой: {base['n']} · база {base['mean']:+.3f}%/сд · "
          f"WR {base['wr']:.1f}% · PF {base['pf']:.2f}")
    print(f"\n{'id':<30} {'ЗАЯВЛЕНО':>18} {'n':>6} {'WR бой':>8} {'PF':>7} "
          f"{'%/сд net':>10} {'медиана':>9} {'безтоп10%':>10} {'Δ WR':>8}")
    print("─" * 118)
    rows = []
    for pid, sub in g.groupby(col):
        s = stat(sub.net.values)
        if s["n"] < min_n:
            continue
        c = claimed.get(pid, {})
        rows.append((pid, c, s))
    rows.sort(key=lambda x: -x[2]["mean"])
    for pid, c, s in rows[:28]:
        cl = (f"R{c.get('avgR', float('nan')):.2f}/WR{c.get('wr', float('nan')):.0f}"
              if c else "—")
        dwr = s["wr"] - c["wr"] if c.get("wr") else float("nan")
        print(f"{str(pid)[:28]:<30} {cl:>18} {s['n']:>6} {s['wr']:>7.1f}% {s['pf']:>7.2f} "
              f"{s['mean']:>+9.3f}% {s['med']:>+8.3f}% {s['frag']:>+9.1f} "
              f"{dwr:>+7.1f}" if c.get("wr") else
              f"{str(pid)[:28]:<30} {cl:>18} {s['n']:>6} {s['wr']:>7.1f}% {s['pf']:>7.2f} "
              f"{s['mean']:>+9.3f}% {s['med']:>+8.3f}% {s['frag']:>+9.1f} {'—':>8}")
    if not rows:
        print(f"  ни одной группы с n ≥ {min_n}")
        return

    # ── срез по стороне (протокол вердикта) ──
    print(f"\n  срез по СТОРОНЕ (все {col}):")
    for d_ in ("LONG", "SHORT"):
        s = stat(g[g.dirn == d_].net.values)
        if s and s["n"] >= min_n:
            print(f"    {d_:<6} n={s['n']:>6} WR {s['wr']:>5.1f}% PF {s['pf']:>5.2f} "
                  f"{s['mean']:>+8.3f}%/сд  безтоп10% {s['frag']:>+9.1f}")
    # ── срез по размеру стопа (закон размера) ──
    print(f"  срез по РАЗМЕРУ стопа:")
    for lo, hi in ((0, 1), (1, 2), (2, 4), (4, 100)):
        s = stat(g[(g.stop_pct > lo) & (g.stop_pct <= hi)].net.values)
        if s and s["n"] >= min_n:
            print(f"    стоп {lo}–{hi}% n={s['n']:>6} WR {s['wr']:>5.1f}% PF {s['pf']:>5.2f} "
                  f"{s['mean']:>+8.3f}%/сд")
    # ── охват монет ──
    per = g.groupby("symbol").net.mean()
    print(f"  охват монет: плюс на {int((per > 0).sum())} из {len(per)} "
          f"({100 * (per > 0).mean():.0f}%)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60000)
    ap.add_argument("--min-n", type=int, default=20)
    a = ap.parse_args()

    # ── заявленные метрики наборов ──
    a104 = yaml.safe_load(open("config/arch104_patterns.yaml", encoding="utf-8"))["patterns"]
    claimed_a104 = {k: {"avgR": v.get("test_avgR"), "wr": v.get("test_WR"),
                        "n": v.get("test_n"), "tf": v.get("detection_tf"),
                        "enabled": v.get("enabled")}
                    for k, v in a104.items()}
    ote = yaml.safe_load(open("config/ote_setups.yaml", encoding="utf-8"))
    claimed_ote = {}
    for tier in ("tier1", "tier2", "tier3"):
        for s in ote.get(tier, []):
            claimed_ote[s["id"]] = {"avgR": s.get("avgR"), "wr": s.get("wr"),
                                    "n": s.get("n"), "post_avgR": s.get("post_avgR"),
                                    "post_n": s.get("post_n"), "tier": tier,
                                    "enabled": s.get("enabled")}

    df = load_live(a.limit)
    print("═" * 118)
    print(f"НАБОРЫ arch104 / ote_nested: ЗАЯВЛЕНО ↔ БОЙ · живых сделок {len(df)} · "
          f"метрика % net (косты {COST}%)")
    print(f"заявленные метрики наборов — в R и БЕЗ костов (combinator_v2.simulate)")
    print("═" * 118)

    report_group(df, "a104", claimed_a104, "▌ НАБОР arch104 — 200 паттернов "
                 f"({sum(1 for v in claimed_a104.values() if v['enabled'])} enabled)",
                 a.min_n)
    report_group(df, "ote", claimed_ote, "▌ НАБОР ote_nested — 18 сетапов "
                 f"({sum(1 for v in claimed_ote.values() if v['enabled'])} enabled)",
                 a.min_n)

    # ── ЗАЯВЛЕННОЕ ПРОТИВ ФОРВАРДА, записанного в самом файле ote ──
    print("\n" + "═" * 118)
    print("▌ ote_setups.yaml: КОЛОНКА ФОРВАРДА УЖЕ В ФАЙЛЕ (post_avgR) — просадка заявленного")
    print("═" * 118)
    print(f"{'id':<16} {'tier':<7} {'avgR':>7} {'post_avgR':>11} {'post_n':>7} "
          f"{'просадка':>10} {'enabled':>9}")
    for k, v in sorted(claimed_ote.items(), key=lambda x: -(x[1]["avgR"] or 0)):
        if v["post_avgR"] is None:
            continue
        drop = (v["post_avgR"] - v["avgR"]) / abs(v["avgR"]) * 100 if v["avgR"] else float("nan")
        print(f"{k:<16} {v['tier']:<7} {v['avgR']:>7.3f} {v['post_avgR']:>11.2f} "
              f"{v['post_n']:>7} {drop:>+9.0f}% {str(v['enabled']):>9}")

    print("\n" + "═" * 118)
    print("Заявленные avgR/WR несопоставимы с боем: R без костов против % net.")
    print("Сравнивать можно только ЗНАК и РАНГ — держится ли порядок паттернов.")
    print("═" * 118)
    return 0


if __name__ == "__main__":
    sys.exit(main())
