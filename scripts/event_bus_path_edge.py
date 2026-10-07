# -*- coding: utf-8 -*-
"""ЭДЖ СДЕЛОК ПУТИ event_bus (Егор 07.10: «есть ли у этих SIM-сделок эдж — наверное нужно!»).

Событийная сеть живая: по логам с 02.10 — 73 типа событий от разных сфер → ~98 тыс. полных
анализов пары ([[bus_is_blackboard_not_mesh]]). Но выход сети на биржу закрыт
(`source_policies.event_bus.exchange_enabled: false`). Вопрос: правильно ли закрыт — есть ли
у сделок этого пути эдж?

Три сравнения:
  1. путь против ПОЛНОЙ базы того же периода ([[golden_keys_matrix_verdict]]);
  2. ЕСТЕСТВЕННЫЙ КОНТРОЛЬ — тот же тип сигнала, пришедший другими путями: так видно, что
     добавляет сам путь, а не сигнал;
  3. линейка коста: среднее на сделку должно быть > 0.35% ([[cost_is_amplifier_not_cause]]).

Запуск:  python scripts/event_bus_path_edge.py
"""
from __future__ import annotations

import sqlite3
import sys

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                        # noqa: BLE001
    pass

COST = 0.35
PATH = "event_bus"


def st(v: pd.DataFrame):
    p = v.profit_pct.values
    if len(p) < 30:
        return None
    pos, neg = p[p > 0].sum(), -p[p < 0].sum()
    return dict(n=len(p), wr=(p > 0).mean() * 100, pf=pos / neg if neg > 0 else 9.99,
                mean=p.mean(), med=float(np.median(p)),
                frail=float(np.sort(p)[:max(1, int(len(p) * 0.9))].sum()),
                cov=(v.groupby("symbol").profit_pct.sum() > 0).mean() * 100)


def pr(nm, s):
    if s is None:
        print(f"  {nm:<36} — мало")
        return
    print(f"  {nm:<36}{s['n']:>6}{s['wr']:>6.1f}%{s['pf']:>7.2f}{s['mean']:>+8.3f}"
          f"{s['med']:>+8.3f}{s['frail']:>+9.0f}{s['cov']:>6.0f}%{s['mean'] - COST:>+8.3f}")


def main() -> int:
    cx = sqlite3.connect("subscriptions.db")
    D = pd.read_sql_query(
        "SELECT symbol, direction, signal_type, source_router, execution_mode, profit_pct, "
        "substr(replace(created_at,'T',' '),1,19) AS ct FROM simulated_trades "
        "WHERE status NOT IN ('OPEN','PENDING_ENTRY') AND profit_pct IS NOT NULL", cx)
    cx.close()
    # формат времени нормализован: `T` против пробела ломает сравнение строк
    D["ct"] = pd.to_datetime(D.ct, errors="coerce")
    D["month"] = D.ct.dt.strftime("%Y-%m")
    EB = D[D.source_router == PATH]
    if EB.empty:
        print("🔴 сделок пути нет — отказ, а не вывод")
        return 1
    P = D[(D.ct >= EB.ct.min()) & (D.ct <= EB.ct.max())]
    BASE = P[P.source_router != PATH]

    print(f"путь {PATH}: {len(EB)} закрытых · {EB.symbol.nunique()} монет · "
          f"{EB.ct.min():%Y-%m-%d} → {EB.ct.max():%Y-%m-%d}")
    print(f"  месяцы {EB.month.value_counts().sort_index().to_dict()}")
    H = (f"  {'срез':<36}{'n':>6}{'WR':>7}{'PF':>7}{'средн':>8}{'медиана':>8}"
         f"{'безтоп':>9}{'монет+':>7}{'−кост':>8}")
    print("\n" + H)
    pr(f"ПУТЬ {PATH}", st(EB))
    pr("база того же периода", st(BASE))
    for s in ("LONG", "SHORT"):
        pr(f"  сторона {s}", st(EB[EB.direction == s]))
    for m in ("VST", "SIM"):
        pr(f"  исполнение {m}", st(EB[EB.execution_mode == m]))
    print("\n  тот же тип сигнала: путь против ДРУГИХ путей")
    for t in EB.signal_type.value_counts().index[:5]:
        pr(f"  {t} · {PATH}", st(EB[EB.signal_type == t]))
        pr(f"  {t} · другие пути", st(BASE[BASE.signal_type == t]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
