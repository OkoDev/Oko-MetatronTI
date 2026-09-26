# -*- coding: utf-8 -*-
"""ВЛИЯЕТ ЛИ ВЕРНОСТЬ ИМПУЛЬСА НА РЕЗУЛЬТАТ ЖИВЫХ СДЕЛОК ote_nested (13.08.2026, Даат).

Запрос Егора: «всё, что касается OTE, перепроверять — импульс мы возможно определяли неверно».

Известно ([[ote_detector_wrong_leg_measured]]): детектор бота
(`zigzag_atr(depth=11, dev=3.0)` → `select_significant_impulse`) совпадает с эталоном
(`run_structure(swing_len=50, internal_len=5)` → `current_leg`) по НАПРАВЛЕНИЮ лишь в 62%,
а зоны OTE не пересекаются в 66% случаев.

Но открытым остался главный вопрос: **это вообще влияет на деньги?**
Возможны три исхода, и они требуют разных действий:
  • сделки с ВЕРНЫМ импульсом заметно лучше → чинить детектор = прямая прибыль;
  • одинаково → импульс не несёт информации, OTE работает по другой причине;
  • хуже → «неверный» импульс на деле ловит что-то иное, и эталон здесь не эталон.

Проверка causal: структура считается на срезе баров СТРОГО ДО входа в сделку.

Запуск:  python scripts/ote_impulse_vs_outcome.py [--limit 1200]
"""
from __future__ import annotations

import argparse
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

from core.smc.oko_sm_engine import run_structure, current_leg  # noqa: E402

DB_TRADES = "subscriptions.db"
DB_PX = "ohlcv_cache.db"
COST = 0.35
LOOKBACK = 1000        # баров истории для структуры (окно-эталон из памяти)


def stat(v: np.ndarray):
    if len(v) == 0:
        return None
    pf = v[v > 0].sum() / abs(v[v < 0].sum()) if (v < 0).any() else 99.0
    return len(v), float(np.median(v)), 100.0 * float((v > 0).mean()), float(pf), float(v.sum())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1200)
    a = ap.parse_args()

    con = sqlite3.connect(f"file:{DB_TRADES}?mode=ro", uri=True)
    tr = pd.read_sql("""
        SELECT symbol, direction, entry_price, stop_loss, profit_pct pnl, R_multiple r,
               status, created_at, timeframe
        FROM simulated_trades
        WHERE signal_type='ote_nested' AND exchange_order_id IS NOT NULL
          AND status IN ('TP','SL','TSL','EXPIRED') AND profit_pct IS NOT NULL
        ORDER BY created_at DESC LIMIT ?""", con, params=(a.limit,))
    con.close()
    # В сделках символ в формате ccxt-свопа ('OWL/USDT:USDT'), в кэше — спотовый ('OWL/USDT').
    tr["symbol"] = tr.symbol.astype(str).str.split(":").str[0]
    tr["ts"] = pd.to_datetime(tr.created_at, errors="coerce", utc=True, format="mixed")
    tr = tr[tr.ts.notna()].copy()
    tr["ms"] = (tr.ts.astype("int64") // 10**6)
    tr["stop_pct"] = (tr.entry_price - tr.stop_loss).abs() / tr.entry_price * 100

    print("═" * 96)
    print(f"ИМПУЛЬС OTE ПРОТИВ РЕЗУЛЬТАТА · живые сделки ote_nested · n={len(tr)}")
    print(f"период {tr.ts.min():%Y-%m-%d} → {tr.ts.max():%Y-%m-%d} · символов {tr.symbol.nunique()}")
    print("эталон: run_structure(50/5) → current_leg на срезе ДО входа (причинно)")
    print("═" * 96)

    px_con = sqlite3.connect(f"file:{DB_PX}?mode=ro", uri=True)
    agree = np.full(len(tr), np.nan)      # 1 = направление сделки совпало с ногой эталона
    have = 0
    for k, sym in enumerate(tr.symbol.unique()):
        d = pd.read_sql("SELECT time,open,high,low,close FROM ohlcv_cache "
                        "WHERE symbol=? AND timeframe='15m' ORDER BY time",
                        px_con, params=(sym,))
        if len(d) < 300:
            continue
        t = d.time.values
        grp = tr[tr.symbol == sym]
        for idx, ms, direction in zip(grp.index, grp.ms.values, grp.direction.values):
            j = int(np.searchsorted(t, ms))        # первый бар НЕ раньше входа
            if j < 300:
                continue
            lo = max(0, j - LOOKBACK)
            sl = d.iloc[lo:j][["open", "high", "low", "close"]].reset_index(drop=True)
            if len(sl) < 250:
                continue
            try:
                st = run_structure(sl)
                leg = current_leg(st)
            except Exception:
                continue
            if not leg:
                continue
            # current_leg отдаёт {'trend': 'long'|'short', origin, extreme, ...}
            # OTE-вход идёт В СТОРОНУ импульса, поэтому сравниваем напрямую.
            tv = str(leg.get("trend", "")).upper()
            if tv not in ("LONG", "SHORT"):
                continue
            ref_dir = tv
            pos = tr.index.get_loc(idx)
            agree[pos] = 1.0 if str(direction).upper() == ref_dir else 0.0
            have += 1
        if (k + 1) % 60 == 0:
            print(f"  ...{k + 1} символов, сопоставлено {have}", flush=True)
    px_con.close()

    tr["agree"] = agree
    sub = tr[tr.agree.notna()].copy()
    if len(sub) < 100:
        print(f"\nсопоставлено слишком мало сделок: {len(sub)}")
        return 1

    print(f"\nсопоставлено {len(sub)} сделок · совпадение направления с эталоном: "
          f"{100 * sub.agree.mean():.1f}%")

    print(f"\n{'группа':<34} {'n':>6} {'медиана %':>11} {'WR%':>7} {'PF':>7} {'сумма %':>10} "
          f"{'с костами':>11}")
    for nm, g in (("импульс СОВПАЛ с эталоном", sub[sub.agree == 1]),
                  ("импульс НЕ совпал", sub[sub.agree == 0])):
        r = stat(g.pnl.values)
        if r:
            per = r[4] / r[0] - COST
            print(f"{nm:<34} {r[0]:>6} {r[1]:>+10.3f}% {r[2]:>6.1f}% {r[3]:>7.2f} "
                  f"{r[4]:>+9.1f} {per * r[0]:>+10.1f}")

    a1 = sub[sub.agree == 1].pnl.values
    a0 = sub[sub.agree == 0].pnl.values
    if len(a1) >= 30 and len(a0) >= 30:
        p = stats.mannwhitneyu(a0, a1, alternative="less").pvalue
        print(f"\nзначимость (совпал лучше): p={p:.5f} "
              f"{'✅ импульс ВАЖЕН' if p < 0.05 else '❌ импульс НЕ влияет на результат'}")

    print(f"\n{'разрез по стороне':<34} {'n':>6} {'медиана %':>11} {'PF':>7}")
    for side in ("LONG", "SHORT"):
        for nm, val in (("совпал", 1), ("не совпал", 0)):
            g = sub[(sub.direction == side) & (sub.agree == val)]
            r = stat(g.pnl.values)
            if r and r[0] >= 25:
                print(f"{side + ' · ' + nm:<34} {r[0]:>6} {r[1]:>+10.3f}% {r[3]:>7.2f}")

    print(f"\n{'разрез по размеру стопа':<34} {'n':>6} {'медиана %':>11} {'PF':>7}")
    for nm, lo, hi in (("<1%", 0, 1), ("1-2%", 1, 2), (">2%", 2, 99)):
        for an, val in (("совпал", 1), ("не совпал", 0)):
            g = sub[(sub.stop_pct > lo) & (sub.stop_pct <= hi) & (sub.agree == val)]
            r = stat(g.pnl.values)
            if r and r[0] >= 25:
                print(f"{'стоп ' + nm + ' · ' + an:<34} {r[0]:>6} {r[1]:>+10.3f}% {r[3]:>7.2f}")

    sub.to_csv("scripts/_ote_impulse_check.csv", index=False)
    print("\n[dump] → scripts/_ote_impulse_check.csv")
    print("═" * 96)
    return 0


if __name__ == "__main__":
    sys.exit(main())
