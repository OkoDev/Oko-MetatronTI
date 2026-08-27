# -*- coding: utf-8 -*-
"""ПРИЧИННОСТЬ ДВИЖКА ote_retest_setups — ядра ote_nested (13.08.2026, Даат).

Егор: «проверить наборы ote_nested на правильность детекции импульса».

Флаги `ote_long`/`ote_short` в features шли из `etl_ote_premium` — там найдена и починена
одна зона от последнего CHoCH, размазанная по всей истории (лаг >20 баров).

Но САМ набор `ote_setups.yaml` торгуется другим движком:
`core/smc/smc_engine.ote_retest_setups` (zigzag_atr → find_setups_zz → build_ote → ретест).
Его причинность не проверялась ни разу. Подозрения:
  • `zigzag_atr` пересматривает последнюю ногу при появлении новых баров;
  • параметр `provisional` дорисовывает текущую ногу ТОЛЬКО в live (`append_provisional_leg`),
    а в бэктесте нет — структурное расхождение бой↔бэктест.

Метод — тот же, что поймал FVG: сетап, найденный по данным до бара b,
обязан совпадать с сетапом, который полный расчёт приписывает бару b.

Запуск:  python scripts/ote_retest_causality.py [--coins 3] [--samples 12]
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

from core.smc.smc_engine import ote_retest_setups  # noqa: E402

DB = "ohlcv_cache.db"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", type=int, default=3)
    ap.add_argument("--samples", type=int, default=12)
    ap.add_argument("--bars", type=int, default=1500)
    ap.add_argument("--tf", type=str, default="1h")
    a = ap.parse_args()

    t0 = int(dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe=? AND time>=? "
        "GROUP BY symbol HAVING n>3000 ORDER BY n DESC LIMIT ?", (a.tf, t0, a.coins)).fetchall()]
    con.close()

    print("═" * 104)
    print(f"ПРИЧИННОСТЬ ote_retest_setups (ядро ote_nested) · {len(syms)} монет · {a.tf} · "
          f"окно {a.bars} баров")
    print("вопрос: сетап на баре b, найденный по данным ДО b, совпадает ли с полным расчётом")
    print("═" * 104)

    tot = dict(checked=0, missing=0, moved=0, entry_diff=0, sl_diff=0, dir_diff=0)
    prov_diff = 0
    prov_checked = 0

    for sym in syms:
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        d = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache "
                        "WHERE symbol=? AND timeframe=? AND time>=? ORDER BY time",
                        c, params=(sym, a.tf, t0))
        c.close()
        if len(d) < a.bars + 50:
            continue
        d["ts"] = pd.to_datetime(d.time, unit="ms", utc=True)
        d = d.set_index("ts")[["open", "high", "low", "close", "volume"]].iloc[:a.bars]

        full = ote_retest_setups(d)
        if not full:
            print(f"  {sym}: сетапов не найдено")
            continue
        pos = {ts: i for i, ts in enumerate(d.index)}
        cand = [s for s in full if s.get("entry_ts") in pos and 300 < pos[s["entry_ts"]] < len(d) - 5]
        if not cand:
            continue
        pick = [cand[i] for i in np.linspace(0, len(cand) - 1,
                                             min(a.samples, len(cand))).astype(int)]
        seen = set()
        for s in pick:
            b = pos[s["entry_ts"]]
            if b in seen:
                continue
            seen.add(b)
            part = ote_retest_setups(d.iloc[:b + 1])
            tot["checked"] += 1
            match = [p for p in part if p.get("entry_ts") == s["entry_ts"]]
            if not match:
                tot["missing"] += 1
                continue
            p = match[0]
            if p.get("direction") != s.get("direction"):
                tot["dir_diff"] += 1
            if abs(float(p.get("entry", 0)) - float(s.get("entry", 0))) > 1e-9 * max(1.0, abs(float(s.get("entry", 1)))):
                tot["entry_diff"] += 1
            if abs(float(p.get("sl", 0)) - float(s.get("sl", 0))) > 1e-9 * max(1.0, abs(float(s.get("sl", 1)))):
                tot["sl_diff"] += 1

            # provisional: живой режим дорисовывает текущую ногу — меняет ли это сетап?
            try:
                pp = ote_retest_setups(d.iloc[:b + 1], provisional=True)
                prov_checked += 1
                mm = [q for q in pp if q.get("entry_ts") == s.get("entry_ts")]
                if not mm or mm[0].get("direction") != p.get("direction") \
                        or abs(float(mm[0].get("entry", 0)) - float(p.get("entry", 0))) > 1e-9:
                    prov_diff += 1
            except Exception:
                pass

    n = max(1, tot["checked"])
    print(f"\nпроверено сетапов: {tot['checked']}")
    print(f"{'сетапа НЕТ при расчёте по данным до b':<50} {tot['missing']:>6} "
          f"({100 * tot['missing'] / n:>5.1f}%)")
    print(f"{'направление изменилось':<50} {tot['dir_diff']:>6} "
          f"({100 * tot['dir_diff'] / n:>5.1f}%)")
    print(f"{'цена входа изменилась':<50} {tot['entry_diff']:>6} "
          f"({100 * tot['entry_diff'] / n:>5.1f}%)")
    print(f"{'стоп изменился':<50} {tot['sl_diff']:>6} "
          f"({100 * tot['sl_diff'] / n:>5.1f}%)")
    bad = tot["missing"] + tot["dir_diff"] + tot["entry_diff"] + tot["sl_diff"]
    print(f"\n{'ИТОГО расхождений':<50} {bad:>6} ({100 * bad / n:>5.1f}%)")
    if prov_checked:
        print(f"\n=== provisional (живой режим дорисовывает текущую ногу) ===")
        print(f"сетап отличается от бэктестового: {prov_diff} из {prov_checked} "
              f"({100 * prov_diff / max(1, prov_checked):.1f}%)")
        print("это РАСХОЖДЕНИЕ БОЙ↔БЭКТЕСТ: в бою луп зовёт с provisional=True")

    print("\n" + "═" * 104)
    if bad == 0:
        print("✅ движок причинен: сетап, видимый по данным до b, совпадает с полным расчётом")
    else:
        print("🔴 движок НЕ причинен: часть сетапов существует только при знании будущего")
    print("═" * 104)
    return 0


if __name__ == "__main__":
    sys.exit(main())
