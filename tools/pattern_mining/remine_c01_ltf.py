"""C-01 LTF: Re-mine 11 LTF-паттернов на MTF (5m+15m+1h) с length=5.

1h-parquet ремайнинг ложно убил 11 LTF-паттернов — их anchor_factors 
содержат 5m/15m флаги, которых нет в 1h-данных.
Этот скрипт грузит 5m+15m+1h parquet, compute_flags на каждом TF,
мёрджит, пересчитывает только LTF-паттерны.

Usage: python tools/pattern_mining/remine_c01_ltf.py
"""
from __future__ import annotations
import sys, os, time, warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tools" / "pattern_mining"))

from core.infra.config_loader import config as _cfg
_cfg.set("arch104.choch_length", 5)
print(f"C-01 LTF: choch_length = 5")

from core.calculators.combinator_core import compute_flags, aggregate_tf
from core.indicators.indicators import calculate_wt, calculate_trend

HISTORY_5M = PROJECT_ROOT / "data" / "history" / "5m"
HISTORY_15M = PROJECT_ROOT / "data" / "history" / "15m"
HISTORY_1H = PROJECT_ROOT / "data" / "history" / "1h"
PATTERNS = PROJECT_ROOT / "config" / "arch104_patterns.yaml"
OUT = PROJECT_ROOT / "data" / "research" / "2026-06-11--c01-choch-remine-ltf"
OUT.mkdir(parents=True, exist_ok=True)

TRAIN_END = pd.Timestamp("2026-03-01", tz="UTC")
MIN_BARS = {"5m": 500, "15m": 200, "1h": 100}

_DATA = {}
_TRAIN_M = {}
_TEST_M = {}

AFFECTED_KEYS = {"ob_mitigated", "ob_near", "ob", "bos", "choch",
                 "ote_long", "ote_short", "premium", "discount"}


def _has_ltf(pattern: dict) -> bool:
    """Паттерн содержит 5m/15m факторы (не только 1h/4h/1d)."""
    anchors = pattern.get("anchor_factors", [])
    for a in anchors:
        a_str = str(a)
        if "_5m" in a_str or "_15m" in a_str:
            return True
    return False


def _is_affected(pattern: dict) -> bool:
    """Затронут CHoCH-слепотой: OB/discount/premium/bos/choch/ote в anchor."""
    anchors = pattern.get("anchor_factors", [])
    return any(k in str(a).lower() for a in anchors for k in AFFECTED_KEYS)


def _load_and_flags(path_1h: Path) -> dict | None:
    """Загружает 1h+5m+15m для символа, вычисляет флаги на каждом TF, мёрджит."""
    sym = path_1h.stem

    # 1h
    df_1h = pd.read_parquet(path_1h)
    df_1h.columns = [c.lower() for c in df_1h.columns]
    if len(df_1h) < MIN_BARS["1h"]:
        return None
    # Preserve DatetimeIndex (calculate_wt/trend destroys it → RangeIndex)
    _idx = df_1h.index
    df_1h = calculate_wt(df_1h)
    df_1h = calculate_trend(df_1h)
    df_1h.index = _idx  # restore DatetimeIndex for aggregate_tf
    f_1h = compute_flags(df_1h, "1h", include_pivots=False)
    f_1h.index = df_1h.index

    # 4h + 1d (aggregate from 1h)
    df_4h = aggregate_tf(df_1h, "4h")
    df_1d = aggregate_tf(df_1h, "1d")
    if len(df_4h) < 30 or len(df_1d) < 20:
        return None
    f_4h = compute_flags(df_4h, "4h")
    f_4h.index = f_4h.index + pd.Timedelta(hours=4)
    f_4h = f_4h.reindex(df_1h.index, method="ffill").fillna(False)
    f_1d_raw = compute_flags(df_1d, "1d")
    f_1d_raw.index = f_1d_raw.index + pd.Timedelta(days=1)
    f_1d = f_1d_raw.reindex(df_1h.index, method="ffill").fillna(False)

    # 15m only (5m skipped: all 11 LTF patterns use _15m factors, none use _5m)
    path_15m = HISTORY_15M / f"{sym}.parquet"
    f_15m_df = None

    if path_15m.exists():
        df_15m = pd.read_parquet(path_15m)
        df_15m.columns = [c.lower() for c in df_15m.columns]
        if len(df_15m) >= MIN_BARS["15m"]:
            _i15 = df_15m.index
            df_15m = calculate_wt(df_15m)
            df_15m = calculate_trend(df_15m)
            df_15m.index = _i15
            f_15m_raw = compute_flags(df_15m, "15m")
            f_15m_raw.index = df_15m.index
            f_15m_df = f_15m_raw.reindex(df_1h.index, method="ffill").fillna(False)

    # Merge all TF flags
    all_parts = [f_1h, f_4h, f_1d]
    if f_15m_df is not None:
        all_parts.append(f_15m_df)
    all_flags = pd.concat(all_parts, axis=1).astype(bool)

    # Forward returns (same as combinator_v2: 1h-forward, 4h-forward)
    close = df_1h["close"].values
    r_long = np.full(len(close), np.nan)
    r_short = np.full(len(close), np.nan)
    # Simple: 4-bar forward return approx (same as combinator_v2)
    for i in range(len(close) - 4):
        entry = close[i]
        r_long[i] = (close[i + 4] - entry) / (entry * 0.02 + 1e-8)
        r_short[i] = (entry - close[i + 4]) / (entry * 0.02 + 1e-8)

    return {"flags": all_flags, "r_long": r_long, "r_short": r_short}


def _load_all():
    global _DATA, _TRAIN_M, _TEST_M
    files = sorted(HISTORY_1H.glob("*.parquet"))
    print(f"[load] {len(files)} symbols, 15m+1h per symbol (~{len(files)} min)...")
    t0 = time.monotonic()
    for i, path in enumerate(files):
        try:
            res = _load_and_flags(path)
            if res is None:
                continue
            sym = path.stem
            _DATA[sym] = res
            idx = res["flags"].index
            _TRAIN_M[sym] = np.asarray(idx < TRAIN_END)
            _TEST_M[sym] = np.asarray(idx >= TRAIN_END)
        except Exception as e:
            pass
        if (i+1) % 5 == 0 or i == len(files)-1:
            elapsed = time.monotonic() - t0
            eta = elapsed / (i+1) * len(files) / 60 if i > 0 else 0
            print(f"  [{i+1}/{len(files)}] {elapsed:.0f}s (~{eta:.0f}min total)", flush=True)
    print(f"[load] {len(_DATA)} symbols with full MTF")


def _eval_ltf(args):
    pstr, direction = args
    factors = tuple(f.strip() for f in pstr.split(" + "))
    tr, te = [], []
    for sym, res in _DATA.items():
        flags = res["flags"]
        mask = np.ones(len(flags), dtype=bool)
        for f in factors:
            if f not in flags.columns:
                mask[:] = False
                break
            mask &= flags[f].values
        if not mask.any():
            continue
        r = res["r_long"] if direction == "LONG" else res["r_short"]
        tr.append(r[_TRAIN_M[sym] & mask])
        te.append(r[_TEST_M[sym] & mask])
    if not tr or not te:
        return (pstr, direction, 0, 0.0, 0.0, 0, 0.0, 0.0, 0.0, 0.0)
    ta = np.concatenate(tr)
    ea = np.concatenate(te)
    tn, en = len(ta), len(ea)
    tavg = float(np.nanmean(ta)) if tn else 0.0
    twr = float((ta > 0).mean() * 100) if tn else 0.0
    eavg = float(np.nanmean(ea)) if en else 0.0
    ewr = float((ea > 0).mean() * 100) if en else 0.0
    esum = float(np.nansum(ea)) if en else 0.0
    emax = float(np.nanmax(ea)) if en else 0.0
    return (pstr, direction, tn, tavg, twr, en, eavg, ewr, esum, emax)


def main():
    with open(PATTERNS) as f:
        cfg = yaml.safe_load(f)
    pats = cfg["patterns"]

    # 11 LTF-затронутых паттернов
    ltf = [(n, " + ".join(p.get("anchor_factors", [])), p.get("direction", "LONG"), p)
           for n, p in pats.items()
           if isinstance(p, dict) and _is_affected(p) and _has_ltf(p)]

    print(f"LTF patterns to re-mine: {len(ltf)}")
    for n, ps, d, _ in ltf:
        print(f"  {n}: {d} | {ps[:80]}")

    _load_all()

    tasks = list(set((s, d) for _, s, d, _ in ltf))
    print(f"Unique tasks: {len(tasks)}")

    results = []
    for i, (ps, d) in enumerate(tasks):
        t0 = time.monotonic()
        r = _eval_ltf((ps, d))
        results.append(r)
        print(f"  [{i+1}/{len(tasks)}] n_test={r[5]} avgR={r[6]:+.3f} WR={r[7]:.1f}% ({time.monotonic()-t0:.1f}s)")

    df = pd.DataFrame(results, columns="pstr dir tn ta tw en ea ew es em".split())
    df.to_csv(OUT / "ltf_metrics.csv", index=False)
    print(f"Saved: {OUT / 'ltf_metrics.csv'}")

    # Update patterns
    mmap = {(r[0], r[1]): r for _, r in df.iterrows()}
    up, dg, rev = 0, 0, 0

    for name, ps, d, pat in ltf:
        k = (ps, d)
        if k in mmap:
            m = mmap[k]
            old = pat.get("test_avgR", 0)
            new = m["ea"]
            old_n = pat.get("test_n", 0)
            new_n = int(m["en"])
            pat["test_n"] = new_n
            pat["test_avgR"] = round(new, 3)   # avgR, не n!
            pat["test_WR"] = round(m["ew"], 1)
            dd = new_n - old_n
            if new_n > 0 and old_n == 0:
                # Pattern revived! Was falsely killed — но НЕ включаем авто
                rev += 1
                print(f"  REVIVED {name}: n {old_n}->{new_n} avgR {old:+.2f}->{new:+.2f} (РУЧНОЕ решение по включению)")
            elif new_n == 0 and old_n == 0:
                dg += 1
                print(f"  DEAD {name}: still en=0 on MTF")
            else:
                up += 1
                print(f"  OK {name}: n {old_n}->{new_n} avgR {old:+.2f}->{new:+.2f}")

    # Config save REMOVED — results in data/research/ only
    print(f"\nDone: {up} OK, {rev} REVIVED (были ложно убиты), {dg} dead (реально)")
    print(f"OLD metrics in archive. New in {OUT / 'ltf_metrics.csv'}")


if __name__ == "__main__":
    main()
