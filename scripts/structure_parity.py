# -*- coding: utf-8 -*-
"""Сверка структурного ядра (core/structure) с прежним API (core.smc.oko_sm_engine) на данных кэша.

Фазы 1–2 сверяли ядро со старым портом (100%, 26.09.2026). После фазы 4 прежний API — фасад
над ядром, и скрипт проверяет, что фасад отдаёт то же, что ядро.

Критерий фазы 1 (docs/STRUCTURE_KERNEL_SPEC.md → «Паритет»): сломы, итоговое состояние и нога
на каждом баре совпадают со старым каноном не менее чем на 95% пар «символ × ТФ × масштаб».
Старый канон здесь — только внешний эталон; новое ядро его не импортирует.

Запуск:  python scripts/structure_parity.py            # 12 монет на ТФ
         python scripts/structure_parity.py --n 30 --tf 1h,4h
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from research_harness import load, universe                     # noqa: E402
from core.structure import MINOR, confirmed_pivots, trace_structure  # noqa: E402
from core.smc import oko_sm_engine as reference                    # noqa: E402
from core.smc.smc_engine import confirmed_swings as reference_swings  # noqa: E402

SCALES = [(50, 5), (15, 4), (60, 15)]


def _old_events(st):
    return [(e.i, e.kind, e.bull, e.level, e.internal, e.level_i) for e in st.events]


def _new_events(tr):
    return [(b.bar, b.kind, b.bullish, b.level, b.scale == MINOR, b.level_bar) for b in tr.breaks]


def _old_final(st):
    return (st.trend, st.minor_trend, st.last_high, st.last_high_bar, st.last_low, st.last_low_bar,
            st.leg_top, st.leg_top_bar, st.leg_bottom, st.leg_bottom_bar)


def _new_final(tr):
    hi, lo, lh, ll = tr.major.high, tr.major.low, tr.leg_high, tr.leg_low
    return (tr.major.direction, tr.minor.direction,
            hi.price if hi else None, hi.bar if hi else None,
            lo.price if lo else None, lo.bar if lo else None,
            lh.price if lh else None, lh.bar if lh else None,
            ll.price if ll else None, ll.bar if ll else None)


def _first_diff(a, b):
    for k, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return k, x, y
    return (min(len(a), len(b)), a[len(b):len(b) + 1], b[len(a):len(a) + 1]) if len(a) != len(b) else None


def compare(df, major, minor):
    t0 = time.perf_counter()
    st = reference.run_structure(df, swing_len=major, internal_len=minor, record_legs=True)
    t_old = time.perf_counter() - t0
    t0 = time.perf_counter()
    tr = trace_structure(df, major=major, minor=minor, keep_legs=True)
    t_new = time.perf_counter() - t0

    old_ev, new_ev = _old_events(st), _new_events(tr)
    res = {
        "events": len(old_ev),
        "events_ok": old_ev == new_ev,
        "final_ok": _old_final(st) == _new_final(tr),
        "legs_ok": st.leg_history == tr.legs,
        "t_old": t_old, "t_new": t_new,
        "diff": None if old_ev == new_ev else _first_diff(old_ev, new_ev),
    }
    pivots_ok = True
    for w in (major, minor):
        old_p = [(c, s, p, top) for c, s, p, top in reference.pivot_points(df["high"], df["low"], w)]
        new_p = [(p.confirmed_at, p.bar, p.price, p.is_high)
                 for p in confirmed_pivots(df["high"], df["low"], w)]
        pivots_ok &= old_p == new_p
        if len(df) >= 2 * w + 2:                              # короткие ряды эталон smc_engine отсекает
            eng_p = [(i, p, k == "H") for i, p, k in reference_swings(df, w)]
            pivots_ok &= eng_p == [(p.bar, p.price, p.is_high)
                                   for p in confirmed_pivots(df["high"], df["low"], w)]
    res["pivots_ok"] = pivots_ok
    res["ok"] = res["events_ok"] and res["final_ok"] and res["legs_ok"] and pivots_ok
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--tf", default="15m,1h,4h")
    args = ap.parse_args()

    total = passed = 0
    t_old = t_new = 0.0
    by_cell = defaultdict(lambda: [0, 0, 0])
    failures = []
    for tf in args.tf.split(","):
        syms = universe(tf, n=args.n)
        print(f"== {tf}: {len(syms)} монет", flush=True)
        for sym in syms:
            df = load(sym, tf).reset_index(drop=True)
            if df.empty:
                continue
            for major, minor in SCALES:
                r = compare(df, major, minor)
                total += 1
                passed += r["ok"]
                t_old += r["t_old"]
                t_new += r["t_new"]
                cell = by_cell[(tf, major, minor)]
                cell[0] += 1
                cell[1] += r["ok"]
                cell[2] += r["events"]
                if not r["ok"]:
                    failures.append((sym, tf, major, minor, r))

    print("\nТФ   масштаб   пар  совпало  сломов")
    for (tf, major, minor), (n, ok, ev) in sorted(by_cell.items()):
        print(f"{tf:4s} {major:>3d}/{minor:<3d}  {n:4d}  {ok:6d}  {ev:8d}")
    share = passed / total * 100 if total else 0.0
    print(f"\nИТОГО: {passed}/{total} пар совпали полностью ({share:.1f}%) · "
          f"время старого {t_old:.1f} с, нового {t_new:.1f} с")
    for sym, tf, major, minor, r in failures[:10]:
        print(f"  ✗ {sym} {tf} {major}/{minor}: events={r['events_ok']} final={r['final_ok']} "
              f"legs={r['legs_ok']} pivots={r['pivots_ok']} первое расхождение={r['diff']}")
    verdict = "ПРОЙДЕН" if share >= 95 else "НЕ ПРОЙДЕН"
    print(f"\nКритерий фазы 1 (≥95%): {verdict}")
    return 0 if share >= 95 else 1


if __name__ == "__main__":
    sys.exit(main())
