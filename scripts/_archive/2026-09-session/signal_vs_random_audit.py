# -*- coding: utf-8 -*-
"""СИГНАЛ ПРОТИВ СЛУЧАЙНОГО ВХОДА — ЧЕСТНОЕ СРАВНЕНИЕ (05.09.2026).

Из контрфакта выхода: при ОДИНАКОВОЙ геометрии (боевой стоп + выход через 6 ч) сигналы
проигрывают случайному входу почти на всех механиках. Прежде чем принять такой вывод,
проверяем невинное объяснение: сигналы срабатывают в ВОЛАТИЛЬНЫЕ моменты, а случайный
бар попадает в спокойные — тогда разница в среде, а не в качестве отбора.

Здесь контроль ВЫРАВНИВАЕТСЯ по волатильности: случайный бар берётся из того же окна
И с похожим ATR% (в пределах ±25%). Плюс проверяется кандидат oko_ote SHORT со стопом 6%
на слепой половине монет.

🔴 Санитайзер цен обязателен ([[law_check_db_cache_price_match]]), медиана рядом со средним.
"""
from __future__ import annotations

import argparse
import hashlib
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

COST = 0.35
HOLD = 24          # 6 ч на 15m


def atr_pct(H, L, C, i, n=14):
    """ATR в % цены на баре i, по прошлым барам."""
    a = max(0, i - n)
    tr = np.maximum(H[a:i + 1] - L[a:i + 1],
                    np.maximum(np.abs(H[a:i + 1] - C[a - 1 if a else 0:i]),
                               np.abs(L[a:i + 1] - C[a - 1 if a else 0:i])))
    if len(tr) == 0 or C[i] <= 0:
        return np.nan
    return float(np.mean(tr)) / float(C[i]) * 100.0


def run(H, L, C, pos, e, d, stop_pct, hold=HOLD):
    sl = e * (1 - d * stop_pct / 100.0)
    lo, hi = L[pos:pos + hold], H[pos:pos + hold]
    if len(lo) == 0:
        return None
    hit = (lo <= sl) if d > 0 else (hi >= sl)
    if hit.any():
        return -stop_pct
    return (float(C[min(pos + hold, len(C) - 1)]) - e) / e * 100.0 * d


def rep(v, name, extra=""):
    v = np.asarray([x for x in v if x == x])
    if len(v) < 25:
        print(f"   {name:34s} n={len(v)} — мало")
        return None
    s = np.sort(v)
    cut = s[:max(1, int(len(s) * 0.9))]
    print(f"   {name:34s} n={len(v):>5} среднее={v.mean():>+7.3f}% медиана={np.median(v):>+7.3f}% "
          f"WR={100*(v>0).mean():>4.1f}% безтоп10%={cut.mean():>+7.3f}% {extra}")
    return float(np.median(v))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--cost", type=float, default=COST)
    a = ap.parse_args()

    c = sqlite3.connect(str(ROOT / "subscriptions.db"))
    c.row_factory = sqlite3.Row
    tr = [dict(r) for r in c.execute(
        f"""SELECT symbol, direction, entry_price, stop_loss, created_at, signal_type
            FROM simulated_trades
            WHERE execution_mode='VST' AND status NOT IN ('OPEN') AND entry_price>0
              AND stop_loss>0 AND created_at > datetime('now','-{a.days} day')""")]
    c.close()
    by: dict[str, list] = {}
    for t in tr:
        by.setdefault(t["symbol"].split(":")[0], []).append(t)

    rng = np.random.default_rng(17)
    rows = []
    for sym, items in by.items():
        try:
            df = load(sym, "15m")
        except Exception:                               # noqa: BLE001
            continue
        if df is None or len(df) < 600:
            continue
        idx, H, L, C = df.index, df.high.values, df.low.values, df.close.values
        for t in items:
            try:
                ts = pd.Timestamp(t["created_at"], tz="UTC")
            except Exception:                           # noqa: BLE001
                continue
            p = int(idx.searchsorted(ts))
            if p <= 300 or p >= len(C) - HOLD - 1:
                continue
            e, sl = float(t["entry_price"]), float(t["stop_loss"])
            if abs(float(C[p]) - e) / e * 100.0 > 5.0:      # санитайзер данных
                continue
            d = 1 if t["direction"] == "LONG" else -1
            if (d > 0 and sl >= e) or (d < 0 and sl <= e):
                continue
            sp = abs(e - sl) / e * 100.0
            if not (0.1 < sp < 30):
                continue
            v_sig = atr_pct(H, L, C, p)
            r_sig = run(H, L, C, p, e, d, sp)
            if r_sig is None or v_sig != v_sig:
                continue
            # контроль 1: случайный бар в окне ±сутки
            q = int(np.clip(p + rng.integers(-96, 97), 300, len(C) - HOLD - 1))
            r_any = run(H, L, C, q, float(C[q]), d, sp)
            # контроль 2: ВЫРОВНЕННЫЙ по волатильности (ATR в пределах ±25%)
            r_vol = None
            for _ in range(40):
                q2 = int(rng.integers(300, len(C) - HOLD - 1))
                v2 = atr_pct(H, L, C, q2)
                if v2 == v2 and 0.75 * v_sig <= v2 <= 1.25 * v_sig:
                    r_vol = run(H, L, C, q2, float(C[q2]), d, sp)
                    break
            rows.append(dict(sym=sym, st=t["signal_type"], dir=t["direction"], stop=sp,
                             atr=v_sig,
                             сигнал=r_sig - a.cost,
                             контроль_окно=(r_any - a.cost) if r_any is not None else np.nan,
                             контроль_вола=(r_vol - a.cost) if r_vol is not None else np.nan))

    R = pd.DataFrame(rows)
    if R.empty:
        print("🔴 нет данных")
        return 1
    print(f"сопоставлено: {len(R)} сделок · {R.sym.nunique()} монет · косты {a.cost}% · "
          f"геометрия: БОЕВОЙ стоп + выход по рынку через 6 ч\n")

    print("=" * 118)
    print("1. СИГНАЛ ПРОТИВ СЛУЧАЙНОГО ВХОДА (одинаковая геометрия, одинаковый стоп)")
    print("=" * 118)
    rep(R["сигнал"], "СИГНАЛ (все механики)")
    rep(R["контроль_окно"], "контроль: случайный бар ±сутки")
    rep(R["контроль_вола"], "контроль: ВЫРОВНЕН по ATR ±25%")
    print(f"\n   ATR% в момент сигнала: медиана {R.atr.median():.3f}%")

    print("\n" + "=" * 118)
    print("2. ПО МЕХАНИКАМ: бьёт ли сигнал случайный вход (медиана, п.п.)")
    print("=" * 118)
    print(f"{'механика':22s} {'n':>5} {'сигнал':>10} {'контроль вола':>15} {'превышение':>12}")
    for st, g in sorted(R.groupby("st"), key=lambda x: -len(x[1])):
        if len(g) < 60:
            continue
        m_s = g["сигнал"].median()
        m_c = g["контроль_вола"].median()
        if m_c != m_c:
            continue
        mark = " 🟢" if m_s > m_c else ""
        print(f"{str(st)[:20]:22s} {len(g):>5} {m_s:>+9.3f}% {m_c:>+14.3f}% {m_s-m_c:>+11.3f}%{mark}")

    print("\n" + "=" * 118)
    print("3. КАНДИДАТ: oko_ote SHORT, ФИКСИРОВАННЫЙ стоп 6% — слепая половина монет")
    print("=" * 118)
    # пересобираем кандидата с фиксированным стопом 6%
    cand = []
    for sym, items in by.items():
        try:
            df = load(sym, "15m")
        except Exception:                               # noqa: BLE001
            continue
        if df is None or len(df) < 600:
            continue
        idx, H, L, C = df.index, df.high.values, df.low.values, df.close.values
        oos = int(hashlib.md5(sym.encode()).hexdigest(), 16) % 2 == 1
        for t in items:
            if t["signal_type"] != "oko_ote" or t["direction"] != "SHORT":
                continue
            try:
                ts = pd.Timestamp(t["created_at"], tz="UTC")
            except Exception:                           # noqa: BLE001
                continue
            p = int(idx.searchsorted(ts))
            if p <= 300 or p >= len(C) - HOLD - 1:
                continue
            e = float(t["entry_price"])
            if abs(float(C[p]) - e) / e * 100.0 > 5.0:
                continue
            r = run(H, L, C, p, e, -1, 6.0)
            q = int(np.clip(p + rng.integers(-96, 97), 300, len(C) - HOLD - 1))
            rc = run(H, L, C, q, float(C[q]), -1, 6.0)
            if r is None:
                continue
            cand.append(dict(sym=sym, oos=oos, месяц=str(ts)[:7],
                             сигнал=r - a.cost,
                             контроль=(rc - a.cost) if rc is not None else np.nan))
    K = pd.DataFrame(cand)
    if K.empty:
        print("   🔴 кандидат: сделок нет")
    else:
        rep(K["сигнал"], "кандидат ВСЕ")
        rep(K["контроль"], "контроль ВСЕ")
        print()
        rep(K[~K.oos]["сигнал"], "IS  (половина монет)")
        rep(K[K.oos]["сигнал"], "OOS (другая половина)")
        rep(K[K.oos]["контроль"], "OOS контроль")
        print()
        for m, g in K.groupby("месяц"):
            rep(g["сигнал"], f"месяц {m}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
