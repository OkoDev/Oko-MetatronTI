# -*- coding: utf-8 -*-
"""ЗАДЕРЖКА ВХОДА: помогает ли НЕ входить сразу по сигналу (05.09.2026).

Из `stop_geometry_lab`: медиана до срабатывания стопа — 2-4 бара, а у класса
«стоп в шуме» (ote_nested 72.1%, radar_pump 63.4%, radar_build 62.2%) цена ПОСЛЕ стопа
возвращается к цели. То есть направление угадано, но мы входим, пока ход ПРОТИВ ещё идёт.

Проверяем: тот же сигнал, вход через k баров. Если гипотеза верна, кривая net(k) имеет
максимум НЕ в нуле.

Три режима входа:
  · market  — по close бара (pos+k), безусловно;
  · better  — лимит: входим только если цена стала ЛУЧШЕ сигнальной (для long — ниже);
  · confirm — входим, если за k баров цена НЕ ушла против больше чем на adverse%.

🔴 Всё в % цены после костов. Геометрия взята лучшая из карты: стоп 6%, цель 3R, hold 24.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from research_harness import load                      # noqa: E402

DELAYS = [0, 1, 2, 3, 4, 6, 8, 12, 16, 24]
NOISE_CLASS = ("ote_nested", "radar_pump", "radar_build", "radar_spring")
BAD_CLASS = ("atr_change", "oko_ote")


def outcome(H, L, C, pos, e, d, stop_pct, tgt_r, hold):
    sl = e * (1 - d * stop_pct / 100.0)
    tp = e * (1 + d * stop_pct * tgt_r / 100.0)
    hi, lo = H[pos:pos + hold], L[pos:pos + hold]
    if len(hi) == 0:
        return None
    hit_sl = (lo <= sl) if d > 0 else (hi >= sl)
    hit_tp = (hi >= tp) if d > 0 else (lo <= tp)
    i_sl = int(np.argmax(hit_sl)) if hit_sl.any() else 10 ** 9
    i_tp = int(np.argmax(hit_tp)) if hit_tp.any() else 10 ** 9
    if i_sl == 10 ** 9 and i_tp == 10 ** 9:
        return (float(C[min(pos + hold, len(C) - 1)]) - e) / e * 100.0 * d
    return -stop_pct if i_sl <= i_tp else stop_pct * tgt_r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=6000)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--stop", type=float, default=6.0)
    ap.add_argument("--target", type=float, default=3.0)
    ap.add_argument("--hold", type=int, default=24)
    ap.add_argument("--cost", type=float, default=0.35)
    ap.add_argument("--adverse", type=float, default=1.0, help="порог confirm-режима, %%")
    a = ap.parse_args()

    c = sqlite3.connect(str(ROOT / "subscriptions.db"))
    c.row_factory = sqlite3.Row
    tr = [dict(r) for r in c.execute(
        f"""SELECT symbol, direction, entry_price, created_at, signal_type
            FROM simulated_trades WHERE execution_mode='VST' AND status NOT IN ('OPEN')
              AND entry_price>0 AND created_at > datetime('now','-{a.days} day')
            ORDER BY RANDOM() LIMIT {a.limit}""")]
    c.close()
    print(f"выборка {len(tr)} боевых входов · геометрия: стоп {a.stop}% · цель {a.target}R · "
          f"hold {a.hold} баров · косты {a.cost}%\n")

    by: dict[str, list] = {}
    for t in tr:
        by.setdefault(t["symbol"].split(":")[0], []).append(t)

    rows = []
    for sym, items in by.items():
        try:
            df = load(sym, "15m")
        except Exception:                       # noqa: BLE001
            continue
        if df is None or len(df) < 300:
            continue
        idx, H, L, C = df.index, df.high.values, df.low.values, df.close.values
        n = len(C)
        for t in items:
            try:
                ts = pd.Timestamp(t["created_at"], tz="UTC")
            except Exception:                   # noqa: BLE001
                continue
            p0 = int(idx.searchsorted(ts))
            if p0 <= 0 or p0 >= n - max(DELAYS) - a.hold - 1:
                continue
            d = 1 if t["direction"] == "LONG" else -1
            e0 = float(t["entry_price"])
            for k in DELAYS:
                pk = p0 + k
                ek = float(C[pk])
                # ход ПРОТИВ за время ожидания (для confirm)
                seg_h, seg_l = H[p0:pk + 1], L[p0:pk + 1]
                adv = ((e0 - seg_l.min()) / e0 * 100.0) if d > 0 else ((seg_h.max() - e0) / e0 * 100.0)
                r_market = outcome(H, L, C, pk, ek, d, a.stop, a.target, a.hold)
                better = (ek < e0) if d > 0 else (ek > e0)
                rows.append(dict(sym=sym, st=t["signal_type"], k=k, d=d,
                                 market=r_market,
                                 better=r_market if better else np.nan,
                                 confirm=r_market if adv <= a.adverse else np.nan))
    R = pd.DataFrame(rows)
    if R.empty:
        print("🔴 нет данных")
        return 1
    print(f"сопоставлено: {R.sym.nunique()} монет · {len(R[R.k == 0])} сделок\n")

    def table(sub: pd.DataFrame, title: str):
        print("=" * 96)
        print(title)
        print("=" * 96)
        print(f"{'задержка':>9} {'market net':>13} {'WR':>6} {'n':>6} | "
              f"{'better net':>12} {'n':>6} | {'confirm net':>12} {'n':>6}")
        for k in DELAYS:
            g = sub[sub.k == k]
            if len(g) < 80:
                continue
            m = g.market.dropna()
            b = g.better.dropna()
            cf = g.confirm.dropna()
            f = lambda v: (f"{v.mean() - a.cost:+8.3f}%" if len(v) >= 60 else "     —")  # noqa: E731
            print(f"{k:>7} б {f(m):>13} {100 * (m > 0).mean():>5.1f}% {len(m):>6} | "
                  f"{f(b):>12} {len(b):>6} | {f(cf):>12} {len(cf):>6}")
        print()

    table(R, "ВСЕ МЕХАНИКИ")
    table(R[R.st.isin(NOISE_CLASS)], "КЛАСС «СТОП В ШУМЕ» (вход верен: ote_nested/radar_*)")
    table(R[R.st.isin(BAD_CLASS)], "КЛАСС «ВХОД НЕВЕРЕН» (atr_change/oko_ote) — контроль")
    print("🔑 если максимум кривой НЕ в k=0 — входить сразу по сигналу ВРЕДНО.")
    print("🔴 отбор по одной выборке: это карта, вердикт требует слепой проверки.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
