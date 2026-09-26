# -*- coding: utf-8 -*-
"""Отпечатки поведения структурного канона до и после фазы 4 (перевод на core/structure).

Хеширует выход публичного API `core.smc.smc_engine` и `core.smc.oko_sm_engine`, всех ETL
`core.calculators.swing_bridge` и `combinator_core.compute_flags` на фиксированной выборке кэша.
Снимок ДО замены сохраняется в JSON, после замены сравнивается ключ в ключ.

Запуск:  python scripts/structure_migration_check.py --save baseline.json
         python scripts/structure_migration_check.py --compare baseline.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from research_harness import load, universe  # noqa: E402


def _h(obj) -> str:
    """Хеш значения: массивы и таблицы — по байтам, остальное — по repr (repr float точный)."""
    m = hashlib.sha256()

    def feed(x):
        if isinstance(x, np.ndarray):
            m.update(str((x.dtype, x.shape)).encode())
            m.update(x.tobytes() if x.dtype != object else repr(x.tolist()).encode())
        elif isinstance(x, pd.DataFrame):
            m.update(repr(list(x.columns)).encode())
            for c in x.columns:
                feed(x[c].to_numpy())
        elif isinstance(x, dict):
            for k in sorted(x, key=str):
                m.update(repr(k).encode())
                feed(x[k])
        elif isinstance(x, (list, tuple)):
            m.update(b"[")
            for v in x:
                feed(v)
            m.update(b"]")
        else:
            m.update(repr(x).encode())

    feed(obj)
    return m.hexdigest()[:16]


def _state(st):
    g = lambda *names: next((getattr(st, n) for n in names if hasattr(st, n)), "MISSING")
    return (g("trend"), g("minor_trend", "itrend"), g("last_high", "top_y"), g("last_high_bar", "top_x"),
            g("last_low", "btm_y"), g("last_low_bar", "btm_x"), g("leg_top", "trail_up"),
            g("leg_top_bar", "trail_up_x"), g("leg_bottom", "trail_dn"), g("leg_bottom_bar", "trail_dn_x"))


def fingerprints(df: pd.DataFrame, tf: str) -> dict:
    from core.smc import oko_sm_engine as oko
    from core.smc import smc_engine as eng
    from core.calculators import swing_bridge as sb
    from core.calculators.combinator_core import compute_flags

    out = {}

    def rec(key, fn):
        try:
            out[key] = _h(fn())
        except Exception as e:                       # падение тоже часть поведения
            out[key] = f"ERR:{type(e).__name__}"

    swings = getattr(eng, "confirmed_swings", None) or getattr(eng, "_swings_luxalgo")
    for w in (50, 5):
        rec(f"swings{w}", lambda w=w: swings(df, w))
        rec(f"breaks{w}", lambda w=w: [(b.ts, b.idx, b.price, b.kind, b.direction, b.has_volume, b.from_idx)
                                       for b in eng.detect_structure_breaks(df, length=w)])
    rec("detect_swings", lambda: [(s.idx, s.ts, s.price, s.kind, s.level) for s in eng.detect_swings(df)])
    brk = eng.detect_structure_breaks(df, length=50)
    obs = eng.detect_order_blocks(df, brk)
    rec("order_blocks", lambda: [tuple(o.__dict__.values()) for o in obs])
    rec("active_obs", lambda: [tuple(o.__dict__.values()) for o in eng.active_order_blocks(obs, len(df))])
    rec("classify50", lambda: eng.classify_structure(df, 50))
    hi, lo = df["high"].to_numpy(), df["low"].to_numpy()
    rec("premium_discount", lambda: [eng.premium_discount(float(hi[k:k + 50].max()), float(lo[k:k + 50].min()))
                                     for k in range(0, len(df) - 50, max(1, len(df) // 50))])
    rec("equal_default", lambda: eng.detect_equal_levels(df))
    rec("equal_05", lambda: eng.detect_equal_levels(df, threshold=0.5))
    rec("fvg_auto", lambda: eng.detect_fvg(df))
    rec("fvg_0", lambda: eng.detect_fvg(df, 0.0))
    rec("fvg_overlap", lambda: eng.detect_fvg_overlap(df))
    rec("pivots3", lambda: (eng._pivots(df, 3, True), eng._pivots(df, 3, False)))

    for major, minor in ((50, 5), (15, 4)):
        def run(major=major, minor=minor):
            st = oko.run_structure(df, swing_len=major, internal_len=minor, record_legs=True)
            ev = [(e.i, e.kind, e.bull, e.level, e.internal, e.level_i) for e in st.events]
            return ev, st.leg_history, _state(st), oko.current_leg(st)
        rec(f"oko{major}_{minor}", run)
    pp = getattr(oko, "pivot_points", None) or getattr(oko, "_swings")
    rec("oko_pivots50", lambda: pp(df["high"], df["low"], 50))

    for name in sorted(n for n in dir(sb) if n.startswith("etl_")):
        rec(f"sb.{name}", lambda name=name: getattr(sb, name)(df))
    rec("compute_flags", lambda: compute_flags(df, tf))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save")
    ap.add_argument("--compare")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--bars", type=int, default=8000)
    args = ap.parse_args()

    t0 = time.perf_counter()
    snap = {}
    for tf in ("15m", "1h", "4h"):
        for sym in universe(tf, n=args.n):
            df = load(sym, tf).tail(args.bars)
            for k, v in fingerprints(df, tf).items():
                snap[f"{tf}|{sym}|{k}"] = v
    print(f"отпечатков: {len(snap)} · {time.perf_counter() - t0:.0f} с")

    if args.save:
        Path(args.save).write_text(json.dumps(snap, ensure_ascii=False, indent=0), encoding="utf-8")
        errs = sum(1 for v in snap.values() if v.startswith("ERR"))
        print(f"сохранено в {args.save} (из них падений: {errs})")
    if args.compare:
        base = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        diff = sorted(k for k in base if snap.get(k) != base[k])
        extra = sorted(set(snap) - set(base))
        print(f"совпало {len(base) - len(diff)}/{len(base)}" + (f" · новых ключей {len(extra)}" if extra else ""))
        for k in diff[:25]:
            print(f"  ✗ {k}: было {base[k]} стало {snap.get(k)}")
        print("ПОВЕДЕНИЕ", "НЕ ИЗМЕНИЛОСЬ" if not diff else "ИЗМЕНИЛОСЬ")
        return 0 if not diff else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
