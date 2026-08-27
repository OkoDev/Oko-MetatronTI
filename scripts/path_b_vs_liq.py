# -*- coding: utf-8 -*-
"""ПУТЬ B × ЛИКВИДАЦИИ: следствие ли прокси шорт-сквиза? (13.08.2026, DS).

Запрос Даата (DISCUSSION 13.08 09:30): «Проверь, не является ли путь B (funding<20 +
возвратный режим) следствием ЛИКВИДАЦИЙ: низкий funding + возвратный режим может быть
просто маркером "шорты выносят". Если да — прямой признак сильнее обоих прокси».

Ограничение данных: liq_events (oko_feed/external_data.db, bybit_ws + oi_synth) покрывает
только с 03.07.2026. История пути B (2024-25) ликвидациями НЕ покрыта → прямой тест
на историю невозможен. Делаем ЧАСТИЧНЫЙ тест на доступном окне:
  1. Для 4h-баров июля-августа 2026 считаем sum(liq USD) по стороне;
  2. Смотрим, как выглядят ликвидации в барах, где fund_pct<20 (путь B-прокси),
     против остальных;
  3. Корреляция fund_pct ↔ объём ликвидаций (если сильная — прокси избыточен).

Запуск: python scripts/path_b_vs_liq.py
"""
import csv
import datetime as dt
import sqlite3
import sys
from collections import defaultdict

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

DB_LIQ = "oko_feed/external_data.db"
CSV_SIG = "scripts/_fade_signals_4h_enriched.csv"

con = sqlite3.connect(DB_LIQ)
liq = defaultdict(lambda: {"buy": 0.0, "sell": 0.0, "n": 0})
for ts, _sym, side, usd in con.execute("SELECT ts, symbol, side, usd FROM liq_events"):
    bar = int(ts) // 14400 * 14400
    key = "buy" if str(side).upper() in ("BUY", "LONG", "B") else "sell"
    liq[bar][key] += float(usd or 0)
    liq[bar]["n"] += 1
con.close()

# сигналы из обогащённого дампа
rows = []
with open(CSV_SIG, encoding="utf-8") as f:
    for r in csv.DictReader(f):
        ts = int(r["ts"])
        if ts >= 1783036800000:  # >= 03.07.2026
            rows.append({
                "ts": ts, "bar": ts // 1000 // 14400 * 14400,  # мс→сек, как liq_events
                "side": r["side"], "net": float(r["net"]),
                "fund_pct": float(r["fund_pct"]),
                "ac": float(r["ac"]),
                "liquid": r["liquid"] == "True",
            })
print(f"сигналов с 03.07.2026: {len(rows)} (баров с ликвидациями: {len(liq)})")

# 1) fund_pct в барах с ликвидациями vs без
sig_liq = [r for r in rows if r["bar"] in liq]
sig_noliq = [r for r in rows if r["bar"] not in liq]
def med(x):
    return float(np.median(x)) if x else float("nan")
print(f"\nfund_pct: в барах с ликвидациями {med([r['fund_pct'] for r in sig_liq]):.1f} (n={len(sig_liq)}) "
      f"· без ликвидаций {med([r['fund_pct'] for r in sig_noliq]):.1f} (n={len(sig_noliq)})")

# 2) корреляция fund_pct ↔ объём ликвидаций (по барам)
bars_common = sorted(set(r["bar"] for r in rows) & set(liq))
X, Y = [], []
for b in bars_common:
    tot = liq[b]["buy"] + liq[b]["sell"]
    fp = med([r["fund_pct"] for r in rows if r["bar"] == b])
    X.append(fp)
    Y.append(tot)
X = np.array(X); Y = np.array(Y)
ok = np.isfinite(X) & np.isfinite(Y)
if ok.sum() >= 10:
    r_p = np.corrcoef(X[ok], Y[ok])[0, 1]
    print(f"\nкорр(fund_pct, sum_liq_usd) = {r_p:+.3f} (баров {ok.sum()})")
else:
    print("\nбаров с общим покрытием мало — корреляция не считается")

# 3) Путь B (fund_pct<20 + ac<0) — что с ликвидациями в этих барах
path_b = [r for r in rows if r["fund_pct"] < 20 and r["ac"] < 0]
not_b = [r for r in rows if not (r["fund_pct"] < 20 and r["ac"] < 0)]
def liq_med(rs):
    vals = [liq[r["bar"]]["buy"] + liq[r["bar"]]["sell"] for r in rs if r["bar"] in liq]
    return float(np.median(vals)) if vals else float("nan")
print(f"\nмедиана sum_liq_usd/бар: путь B {liq_med(path_b)/1000:.0f}k (n={len(path_b)}) "
      f"· НЕ B {liq_med(not_b)/1000:.0f}k (n={len(not_b)})")

# 4) направление ликвидаций в барах пути B (доля sell-ликвидаций)
for tag, rs in (("путь B", path_b), ("НЕ B", not_b)):
    bs = [r["bar"] for r in rs if r["bar"] in liq]
    if not bs:
        print(f"  {tag}: нет ликвидаций в барах")
        continue
    sells = sum(liq[b]["sell"] for b in bs)
    buys = sum(liq[b]["buy"] for b in bs)
    tot = sells + buys
    print(f"  {tag}: {len(bs)} баров · sell-liq {100*sells/tot:.0f}% / buy-liq {100*buys/tot:.0f}% "
          f"(${sells/1e3:.0f}k / ${buys/1e3:.0f}k)")

print("\n⚠️ Ограничение: ликвидации только с 03.07.2026 (Bybit WS + oi_synth). Путь B на 2024-25")
print("этим окном НЕ покрыт — полный тест невозможен, результат частичный.")
