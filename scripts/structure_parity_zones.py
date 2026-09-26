# -*- coding: utf-8 -*-
"""Сверка зон и уровней core/structure с функциями smc_engine на данных кэша.

Фаза 2 сверяла ядро со старым портом (100%, 26.09.2026). После фазы 4 функции smc_engine — фасады
над ядром, и скрипт проверяет преобразование форматов (ts, строки видов, None вместо -1).

Критерий: для каждой функции совпадение на ≥95% пар «символ × ТФ × параметры», цель — 100%.
Старые функции здесь — только внешний эталон; новый код их не импортирует.

Запуск:  python scripts/structure_parity_zones.py            # 12 монет на ТФ
         python scripts/structure_parity_zones.py --n 30 --tf 1h
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

from research_harness import load, universe                                   # noqa: E402
from core.smc import smc_engine as ref                                          # noqa: E402
from core.structure import (equal_levels, fair_value_gaps, label_swings,       # noqa: E402
                            level_breaks, order_blocks, range_zones)


def check_breaks(df, pos, window):
    old = ref.detect_structure_breaks(df, length=window)
    new = level_breaks(df, window=window)
    a = [(b.idx, b.price, b.kind, b.direction == "bull", b.has_volume, b.from_idx) for b in old]
    b = [(x.bar, x.level, x.kind, x.bullish, x.heavy_volume, x.level_bar) for x in new]
    return a == b, len(a), (old, new)


def check_blocks(df, pos, old_breaks, new_breaks):
    old = ref.detect_order_blocks(df, old_breaks)
    new = order_blocks(df, new_breaks)
    a = [(o.left_idx, o.top, o.bottom, o.kind == "bull", o.break_idx, o.mitigated_idx, o.is_breaker) for o in old]
    b = [(x.origin_bar, x.top, x.bottom, x.bullish, x.break_bar, x.gone_bar, x.flipped) for x in new]
    return a == b, len(a)


def check_labels(df, pos, window):
    a = [(pos[ts], p, lab) for ts, p, lab in ref.classify_structure(df, window)]
    b = label_swings(df, window)
    return a == b, len(a)


def check_equal(df, pos):
    a = [(pos[t1], p1, pos[t2], p2, lab == "EQH") for t1, p1, t2, p2, lab in ref.detect_equal_levels(df)]
    b = [(x.first_bar, x.first_price, x.second_bar, x.second_price, x.highs) for x in equal_levels(df)]
    return a == b, len(a)


def check_gaps(df, pos, threshold):
    a = [(pos[tl], top, bot, kind == "bull", pos[ti], pos[m] if m is not None else -1)
         for tl, top, bot, kind, ti, m in ref.detect_fvg(df, threshold)]
    b = [(g.left_bar, g.top, g.bottom, g.bullish, g.bar, g.filled_bar) for g in fair_value_gaps(df, threshold)]
    return a == b, len(a)


def check_zones(df):
    hi, lo = df["high"].to_numpy(), df["low"].to_numpy()
    step = max(1, len(df) // 200)
    for k in range(0, len(df) - 50, step):
        top, bottom = float(hi[k:k + 50].max()), float(lo[k:k + 50].min())
        old, new = ref.premium_discount(top, bottom), range_zones(top, bottom)
        if (old["premium"], old["equilibrium"], old["discount"], old["eq_mid"]) != \
                (new["upper"], new["middle"], new["lower"], new["mid"]):
            return False, 1
    return True, 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--tf", default="15m,1h,4h")
    args = ap.parse_args()

    stats = defaultdict(lambda: [0, 0, 0])     # функция → [пар, совпало, объектов]
    fails = []
    t_all = time.perf_counter()
    for tf in args.tf.split(","):
        syms = universe(tf, n=args.n)
        print(f"== {tf}: {len(syms)} монет", flush=True)
        for sym in syms:
            df = load(sym, tf)
            if df.empty:
                continue
            pos = {ts: i for i, ts in enumerate(df.index)}
            results = {}
            for window in (50, 5):
                ok, cnt, (old_b, new_b) = check_breaks(df, pos, window)
                results[f"сломы w={window}"] = (ok, cnt)
                results[f"блоки w={window}"] = check_blocks(df, pos, old_b, new_b)
            results["подписи HH/HL w=50"] = check_labels(df, pos, 50)
            results["равные уровни"] = check_equal(df, pos)
            results["FVG авто-порог"] = check_gaps(df, pos, None)
            results["FVG порог 0"] = check_gaps(df, pos, 0.0)
            results["зоны диапазона"] = check_zones(df)
            for name, (ok, cnt) in results.items():
                s = stats[name]
                s[0] += 1
                s[1] += ok
                s[2] += cnt
                if not ok:
                    fails.append((sym, tf, name))

    print(f"\n{'функция':24s} {'пар':>5s} {'совпало':>8s} {'объектов':>10s}")
    total = passed = 0
    for name, (n, ok, cnt) in stats.items():
        print(f"{name:24s} {n:5d} {ok:8d} {cnt:10d}")
        total += n
        passed += ok
    share = passed / total * 100 if total else 0.0
    print(f"\nИТОГО: {passed}/{total} проверок совпали ({share:.1f}%) · {time.perf_counter() - t_all:.0f} с")
    for f in fails[:15]:
        print("  ✗", *f)
    worst = min((ok / n * 100 for n, ok, _ in stats.values()), default=0.0)
    verdict = "ПРОЙДЕН" if worst >= 95 else "НЕ ПРОЙДЕН"
    print(f"\nКритерий фазы 2 (каждая функция ≥95%): {verdict}")
    return 0 if worst >= 95 else 1


if __name__ == "__main__":
    sys.exit(main())
