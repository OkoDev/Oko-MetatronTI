# -*- coding: utf-8 -*-
"""ЧТО В features_json РЕАЛЬНО РАЗДЕЛЯЕТ ПРИБЫЛЬ И УБЫТОК (13.08.2026, Даат).

Егор: «у нас огромный JSON, в котором несколько сотен признаков на каждый сигнал.
И мы, похоже, опять этим не пользуемся. А мы опять ищем идеальный стоп».

Справедливо. В `simulated_trades.features_json` — 232 разных признака на сделку,
и ни один замер 13.08 их не использовал. Здесь СПЛОШНОЙ перебор вместо гипотез:
для каждого признака считается, насколько он разделяет прибыльные и убыточные сделки.

Метрика — ДЕНЬГИ, не R и не WR: разница `%/сделку net` между лучшей и худшей группой
(косты 0.35% вычтены). Для числовых — разрез по терцилям, для категориальных — по классам.
Значимость — Mann–Whitney между крайними группами.

Осторожно с интерпретацией: это НЕ причинность. Найденное — кандидаты в гейты,
которые обязаны пройти протокол вердикта (разрезы, хрупкость, перенос).

Запуск:  python scripts/features_discriminative_power.py [--limit 40000] [--min-n 200]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

COST = 0.35
SKIP = {"detector_ts", "register_ts", "entry_ts", "closed_at", "symbol", "trade_id",
        "features_version", "router_version", "data_era"}


def flatten(obj, prefix="", out=None, depth=0):
    """Разворачивает вложенные dict в плоские ключи (phase.macro, gate_features.x.y)."""
    if out is None:
        out = {}
    if depth > 2:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                flatten(v, key, out, depth + 1)
            elif isinstance(v, list):
                out[key + ".len"] = len(v)
                if v and all(isinstance(x, str) for x in v):
                    out[key + ".first"] = v[0]
            else:
                out[key] = v
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40000)
    ap.add_argument("--min-n", type=int, default=200)
    ap.add_argument("--exchange-only", action="store_true", help="только реальные биржевые")
    a = ap.parse_args()

    con = sqlite3.connect("file:subscriptions.db?mode=ro", uri=True)
    where = "AND exchange_order_id IS NOT NULL" if a.exchange_only else ""
    d = pd.read_sql(f"""
        SELECT features_json, profit_pct pnl, entry_price, stop_loss, source_router src,
               signal_type, created_at
        FROM simulated_trades
        WHERE status IN ('TP','SL','TSL','EXPIRED') AND profit_pct IS NOT NULL
          AND features_json IS NOT NULL AND length(features_json) > 50 {where}
        ORDER BY id DESC LIMIT ?""", con, params=(a.limit,))
    con.close()

    print("═" * 108)
    print(f"РАЗДЕЛЯЮЩАЯ СИЛА ПРИЗНАКОВ · сделок {len(d)} · "
          f"{'ТОЛЬКО БИРЖА' if a.exchange_only else 'все (SIM+VST)'} · метрика: % net с костами {COST}%")
    print("═" * 108)

    recs = []
    for js, pnl in zip(d.features_json, d.pnl):
        try:
            f = flatten(json.loads(js))
        except Exception:
            continue
        f["_net"] = pnl - COST
        recs.append(f)
    F = pd.DataFrame(recs)
    net = F["_net"]
    base = net.mean()
    print(f"\nпризнаков развёрнуто: {F.shape[1] - 1} · база: {base:+.3f}%/сделку "
          f"(PF {net[net > 0].sum() / abs(net[net < 0].sum()):.2f})")

    results = []
    for col in F.columns:
        if col == "_net" or col in SKIP:
            continue
        s = F[col]
        nn = s.notna().sum()
        if nn < a.min_n * 2:
            continue
        try:
            if s.dtype == bool or set(s.dropna().unique()) <= {True, False, 0, 1}:
                g1 = net[s == True]; g0 = net[s == False]          # noqa: E712
                if len(g1) < a.min_n or len(g0) < a.min_n:
                    continue
                lo, hi = ("False", g0.mean()), ("True", g1.mean())
                p = stats.mannwhitneyu(g0, g1, alternative="two-sided").pvalue
                spread = abs(hi[1] - lo[1])
                best = hi if hi[1] > lo[1] else lo
                worst = lo if hi[1] > lo[1] else hi
                nbest = len(g1) if best[0] == "True" else len(g0)
            elif pd.api.types.is_numeric_dtype(s):
                q = s.quantile([0.33, 0.66]).values
                if q[0] == q[1]:
                    continue
                low = net[s <= q[0]]; high = net[s >= q[1]]
                if len(low) < a.min_n or len(high) < a.min_n:
                    continue
                p = stats.mannwhitneyu(low, high, alternative="two-sided").pvalue
                lo, hi = (f"≤{q[0]:.3g}", low.mean()), (f"≥{q[1]:.3g}", high.mean())
                spread = abs(hi[1] - lo[1])
                best = hi if hi[1] > lo[1] else lo
                worst = lo if hi[1] > lo[1] else hi
                nbest = len(high) if best[0].startswith("≥") else len(low)
            else:
                vc = s.value_counts()
                vals = [v for v in vc.index if vc[v] >= a.min_n][:8]
                if len(vals) < 2:
                    continue
                means = {v: net[s == v].mean() for v in vals}
                best_v = max(means, key=means.get); worst_v = min(means, key=means.get)
                p = stats.mannwhitneyu(net[s == worst_v], net[s == best_v],
                                       alternative="two-sided").pvalue
                best, worst = (str(best_v)[:18], means[best_v]), (str(worst_v)[:18], means[worst_v])
                spread = best[1] - worst[1]
                nbest = int(vc[best_v])
            results.append((col, spread, best, worst, p, nbest))
        except Exception:
            continue

    results.sort(key=lambda x: -x[1])
    print(f"\n{'признак':<38} {'разброс':>9} {'лучшая группа':>26} {'худшая':>24} {'p':>9}")
    print("─" * 108)
    shown = 0
    for col, spread, best, worst, p, nbest in results:
        if p > 0.01 or spread < 0.15:
            continue
        print(f"{col[:36]:<38} {spread:>+8.3f}% "
              f"{best[0][:14]:>14}={best[1]:>+7.3f}%(n={nbest:>5}) "
              f"{worst[0][:12]:>12}={worst[1]:>+7.3f}% {p:>9.1e}")
        shown += 1
        if shown >= 30:
            break
    if shown == 0:
        print("  ни один признак не разделяет значимо (p<0.01, разброс >0.15%)")

    print("\n" + "═" * 108)
    print("Разброс = разница %/сделку между лучшей и худшей группой. Это КАНДИДАТЫ, не эдж:")
    print("каждый обязан пройти протокол вердикта (год · сторона · размер · хрупкость · перенос).")
    print("═" * 108)
    return 0


if __name__ == "__main__":
    sys.exit(main())
