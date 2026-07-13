"""C-01: Re-mine after CHoCH length=50->5 fix.

Usage: python tools/pattern_mining/remine_c01_choch.py
"""
from __future__ import annotations
import sys, os, time, warnings, math
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yaml

# ── Path setup ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # tools/pattern_mining/ -> root
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tools" / "pattern_mining"))

# Force length=5 BEFORE importing combinator_v2 (swing_bridge reads config)
from core.infra.config_loader import config as _cfg
_original = _cfg.get("arch104.choch_length", 50)
_cfg.set("arch104.choch_length", 5)  # ConfigLoader.set(key, value)
print(f"C-01: choch_length = {_original} -> 5")

import combinator_v2 as cb

HISTORY = PROJECT_ROOT / "data" / "history" / "1h"
PATTERNS = PROJECT_ROOT / "config" / "arch104_patterns.yaml"
OUT = PROJECT_ROOT / "data" / "research" / "2026-06-11--c01-choch-remine"
OUT.mkdir(parents=True, exist_ok=True)
TRAIN_END = pd.Timestamp("2026-03-01", tz="UTC")

AFFECTED = {"ob_mitigated", "ob_near", "ob", "bos", "choch", "ote_long", "ote_short", "premium", "discount"}

_DATA = {}
_TRAIN_M = {}
_TEST_M = {}


def _init():
    global _DATA, _TRAIN_M, _TEST_M
    files = sorted(HISTORY.glob("*.parquet"))
    print(f"[init] {len(files)} files...")
    for path in files:
        res = cb.process_symbol(path)
        if res is None:
            continue
        flags, rl, rs = res
        _DATA[path.stem] = (flags, rl, rs)
        idx = flags.index
        _TRAIN_M[path.stem] = np.asarray(idx < TRAIN_END)
        _TEST_M[path.stem] = np.asarray(idx >= TRAIN_END)
    print(f"[init] {len(_DATA)} symbols loaded")


def _eval(args):
    pstr, d = args
    factors = tuple(f.strip() for f in pstr.split(" + "))
    tr, te = [], []
    for sym, (flags, rl, rs) in _DATA.items():
        mask = np.ones(len(flags), dtype=bool)
        for f in factors:
            if f not in flags.columns:
                mask[:] = False
                break
            mask &= flags[f].values
        if not mask.any():
            continue
        r = rl if d == "LONG" else rs
        tr.append(r[_TRAIN_M[sym] & mask])
        te.append(r[_TEST_M[sym] & mask])
    if not tr or not te:
        return (pstr, d, 0, 0.0, 0.0, 0, 0.0, 0.0, 0.0, 0.0)
    ta = np.concatenate(tr)
    ea = np.concatenate(te)
    tn, en = len(ta), len(ea)
    tavg = float(ta.mean()) if tn else 0.0
    twr = float((ta > 0).mean() * 100) if tn else 0.0
    eavg = float(ea.mean()) if en else 0.0
    ewr = float((ea > 0).mean() * 100) if en else 0.0
    esum = float(ea.sum()) if en else 0.0
    emax = float(ea.max()) if en else 0.0
    return (pstr, d, tn, tavg, twr, en, eavg, ewr, esum, emax)


def affected(p):
    anchors = p.get("anchor_factors", [])
    return any(k in str(a).lower() for a in anchors for k in AFFECTED)


def main():
    with open(PATTERNS) as f:
        cfg = yaml.safe_load(f)
    pats = cfg["patterns"]
    aff = [(n, " + ".join(p.get("anchor_factors", [])), p.get("direction", "LONG"), p)
           for n, p in pats.items() if isinstance(p, dict) and affected(p)]
    clean = [n for n, p in pats.items() if isinstance(p, dict) and not affected(p)]
    print(f"Affected: {len(aff)}, Clean: {len(clean)}")
    for n, ps, d, _ in aff[:5]:
        print(f"  {n}: {d} | {ps[:70]}")

    _init()
    tasks = list(set((s, d) for _, s, d, _ in aff))
    print(f"Unique tasks: {len(tasks)}")

    results = []
    for i, (ps, d) in enumerate(tasks):
        t0 = time.monotonic()
        r = _eval((ps, d))
        results.append(r)
        print(f"  [{i+1}/{len(tasks)}] n_test={r[5]} avgR={r[6]:+.3f} WR={r[7]:.1f}% ({time.monotonic()-t0:.1f}s)")

    df = pd.DataFrame(results, columns="pstr dir tn ta tw en ea ew es em".split())
    df.to_csv(OUT / "metrics.csv", index=False)
    print(f"Saved: {OUT / 'metrics.csv'}")

    # Archive old
    arc = PROJECT_ROOT / "config" / "archive" / "arch104_patterns_len50.yaml"
    arc.parent.mkdir(parents=True, exist_ok=True)
    arc.write_text(open(PATTERNS).read())
    print(f"Archived: {arc}")

    # Update
    mmap = {(r[0], r[1]): r for _, r in df.iterrows()}
    up, dg = 0, 0
    for name, ps, d, pat in aff:
        k = (ps, d)
        if k in mmap:
            m = mmap[k]
            old = pat.get("test_avgR", 0)
            new = m["ea"]
            pat["test_n"] = int(m["en"])
            pat["test_avgR"] = round(new, 3)
            pat["test_WR"] = round(m["ew"], 1)
            dd = new - old
            if new < 0.3 and pat.get("enabled", True):
                pat["enabled"] = False
                dg += 1
                print(f"  X {name}: {old:+.2f}->{new:+.2f} d={dd:+.2f} DISABLED")
            else:
                up += 1
                print(f"  OK {name}: {old:+.2f}->{new:+.2f} d={dd:+.2f} n={int(m['en'])}")

    # НЕ пишем в боевой конфиг! Результаты в data/research/
    print(f"Done: {up} updated, {dg} disabled")
    print(f"Results: {OUT / 'metrics.csv'} — ручной мёрж в config/arch104_patterns.yaml")
    print("A/B backtest: compare choch_length=50 vs 5 on these metrics")


if __name__ == "__main__":
    main()
