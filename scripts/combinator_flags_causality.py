# -*- coding: utf-8 -*-
"""ПРИЧИННОСТЬ ФЛАГОВ КОМБИНАТОРА (13.08.2026, Даат).

Голая база механики simulate() даёт WR 41.5% (876k сигналов), а паттерны arch104
заявлены с WR до 99% — и в бою дают 16–44% с минусом на ВСЕХ 25 группах.
Механика объясняет лишь 4.4 п.п. Значит разрыв либо в отборе (подгонка), либо
в самих ФЛАГАХ — если флаг на баре i знает бары после i, WR 97% получается сам собой.

Тест из протокола вердикта, буквальный:
    compute_flags(df[:n])[i]  ==  compute_flags(df)[i]   для всех i < n
Если флаг переписывается задним числом при появлении новых баров — он ЗНАЕТ будущее.

Отдельно проверяются подозреваемые:
  • дивергенции (_calc_divergence через пивоты с окном ±prd — центрированное окно
    подтверждает пивот только через prd баров ВПЕРЁД);
  • fvg_overlap_held (известный незакрытый баг bug_fvg_overlap_held_lookahead);
  • пивот-флаги 1D/1W.

Запуск:  python scripts/combinator_flags_causality.py [--coins 5]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from core.calculators.combinator_core import compute_flags, DIV_PIVOT_PRD  # noqa: E402

DB = "ohlcv_cache.db"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", type=int, default=5)
    ap.add_argument("--cut", type=int, default=300, help="сколько баров отрезать с конца")
    a = ap.parse_args()

    t0 = int(dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? "
        "GROUP BY symbol HAVING n>3000 ORDER BY n DESC LIMIT ?", (t0, a.coins)).fetchall()]
    con.close()

    print("═" * 100)
    print(f"ПРИЧИННОСТЬ ФЛАГОВ КОМБИНАТОРА · {len(syms)} монет · ТФ 1h · "
          f"обрезка {a.cut} баров с конца")
    print(f"DIV_PIVOT_PRD = {DIV_PIVOT_PRD} (окно подтверждения пивота)")
    print("═" * 100)

    total = {}
    for sym in syms:
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        d = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache "
                        "WHERE symbol=? AND timeframe='1h' AND time>=? ORDER BY time",
                        c, params=(sym, t0))
        c.close()
        if len(d) < 1500:
            continue
        d["ts"] = pd.to_datetime(d.time, unit="ms", utc=True)
        d = d.set_index("ts")[["open", "high", "low", "close", "volume"]]

        n = len(d) - a.cut
        full = compute_flags(d, "1h", include_pivots=True)
        part = compute_flags(d.iloc[:n], "1h", include_pivots=True)

        for col in part.columns:
            if col not in full.columns:
                continue
            fv = full[col].iloc[:n]
            pv = part[col]
            try:
                fa = np.asarray(fv, dtype=float)
                pa = np.asarray(pv, dtype=float)
            except Exception:
                fa = np.asarray(fv.astype(str) == "True", dtype=float)
                pa = np.asarray(pv.astype(str) == "True", dtype=float)
            m = ~(np.isnan(fa) | np.isnan(pa))
            if m.sum() < 100:
                continue
            diff = int((fa[m] != pa[m]).sum())
            t = total.setdefault(col, [0, 0])
            t[0] += diff
            t[1] += int(m.sum())

    rows = [(c, d_, n_, 100.0 * d_ / n_) for c, (d_, n_) in total.items() if n_ > 0]
    rows.sort(key=lambda x: -x[3])
    bad = [r for r in rows if r[1] > 0]

    print(f"\nфлагов проверено: {len(rows)} · С РАСХОЖДЕНИЕМ: {len(bad)}")
    if bad:
        print(f"\n🔴 ФЛАГИ, КОТОРЫЕ ПЕРЕПИСЫВАЮТСЯ ЗАДНИМ ЧИСЛОМ (знают будущее):")
        print(f"{'флаг':<42} {'расхождений':>13} {'из':>9} {'доля':>9}")
        print("─" * 100)
        for col, d_, n_, pct in bad[:40]:
            print(f"{col[:40]:<42} {d_:>13} {n_:>9} {pct:>8.3f}%")
    else:
        print("\n✅ ни один флаг не переписывается — причинность флагов чистая")

    print(f"\n=== ЧИСТЫЕ ФЛАГИ (0 расхождений): {len(rows) - len(bad)} ===")
    clean = [r[0] for r in rows if r[1] == 0]
    print("  " + ", ".join(clean[:30]) + (" …" if len(clean) > 30 else ""))
    print("═" * 100)
    return 0


if __name__ == "__main__":
    sys.exit(main())
