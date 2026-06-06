"""
DS: Re-mine discount/premium паттернов после ARCH-118 fix (6063816).
Discount изменился: глобальный high/low → ROLLING dealing range (swing_bridge.py L167).

Таргетированный: только 39 паттернов с discount/premium, не все 22K.
Источник OHLCV: data/history/1h/*.parquet (те же что walkforward_full.py).
Output: data/research/2026-06-06--ds-discount-remine/metrics.csv
"""
from __future__ import annotations
import sys, os, time, warnings, math, json
from pathlib import Path
warnings.filterwarnings("ignore")
try: sys.stdout.reconfigure(encoding='utf-8')
except: pass

import numpy as np
import pandas as pd
import yaml
from multiprocessing import Pool, cpu_count

PROJECT_ROOT = Path("E:/MTF BOT/CURSOR/crypto_volume_bot")
sys.path.insert(0, str(PROJECT_ROOT / "tools" / "pattern_mining"))
import combinator_v2 as cb

HISTORY_1H = PROJECT_ROOT / "data" / "history" / "1h"
PATTERNS_YAML = PROJECT_ROOT / "config" / "arch104_patterns.yaml"
OUTPUT_DIR = PROJECT_ROOT / "data" / "research" / "2026-06-06--ds-discount-remine"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TRAIN_END = pd.Timestamp("2026-03-01", tz="UTC")
MIN_N_TRAIN = 30

# ── Глобальное состояние для воркеров ──
_DATA: dict = {}
_TRAIN_MASKS: dict = {}
_TEST_MASKS: dict = {}


def _init_worker(history_dir: str):
    global _DATA, _TRAIN_MASKS, _TEST_MASKS
    files = sorted(Path(history_dir).glob("*.parquet"))
    print(f"[worker] загружаю {len(files)} файлов...")
    for path in files:
        res = cb.process_symbol(path)
        if res is None:
            continue
        flags, r_long, r_short = res
        _DATA[path.stem] = (flags, r_long, r_short)
        idx = flags.index
        _TRAIN_MASKS[path.stem] = np.asarray(idx < TRAIN_END)
        _TEST_MASKS[path.stem] = np.asarray(idx >= TRAIN_END)
    print(f"[worker] готово: {len(_DATA)} символов")


def _evaluate_one(args):
    pattern_str, direction = args
    factors = tuple(f.strip() for f in pattern_str.split(" + "))

    tr_rs = []
    te_rs = []
    for sym, (flags, r_long, r_short) in _DATA.items():
        mask = np.ones(len(flags), dtype=bool)
        for f in factors:
            if f not in flags.columns:
                mask[:] = False
                break
            mask = mask & flags[f].values
        if not mask.any():
            continue
        r = r_long if direction == "LONG" else r_short
        tr_rs.append(r[_TRAIN_MASKS[sym] & mask])
        te_rs.append(r[_TEST_MASKS[sym] & mask])

    if not tr_rs or not te_rs:
        return (pattern_str, direction, 0, 0.0, 0.0, 0, 0.0, 0.0, 0.0, 0.0)

    tr_all = np.concatenate(tr_rs) if tr_rs else np.array([])
    te_all = np.concatenate(te_rs) if te_rs else np.array([])

    train_n = len(tr_all)
    train_avgR = float(tr_all.mean()) if train_n > 0 else 0.0
    train_WR = float((tr_all > 0).mean() * 100) if train_n > 0 else 0.0
    test_n = len(te_all)
    test_avgR = float(te_all.mean()) if test_n > 0 else 0.0
    test_WR = float((te_all > 0).mean() * 100) if test_n > 0 else 0.0
    test_sumR = float(te_all.sum()) if test_n > 0 else 0.0
    test_maxR = float(te_all.max()) if test_n > 0 else 0.0

    # t-test p-value
    if test_n >= 3:
        t = test_avgR / (te_all.std(ddof=1) / math.sqrt(test_n)) if te_all.std() > 0 else 0.0
        df = test_n - 1
        if df > 30:
            p_value = 0.5 * math.erfc(t / math.sqrt(2))
        else:
            x = df / (df + t * t)
            log_beta = math.lgamma(df/2) + math.lgamma(0.5) - math.lgamma(df/2 + 0.5)
            n_steps = 100
            dx = x / n_steps
            integral = sum((((i+0.5)*dx) ** (df/2 - 1)) * ((1 - (i+0.5)*dx) ** (-0.5)) * dx for i in range(n_steps) if (i+0.5)*dx > 0 and (i+0.5)*dx < 1)
            p_value = min(max(math.exp(math.log(max(integral, 1e-300)) - log_beta) / 2.0, 0.0), 1.0)
    else:
        p_value = 1.0

    return (pattern_str, direction, train_n, train_avgR, train_WR,
            test_n, test_avgR, test_WR, test_sumR, test_maxR, p_value)


def main():
    # 1. Загружаем список discount-паттернов
    with open(PATTERNS_YAML) as f:
        config = yaml.safe_load(f)
    all_pats = config["patterns"]

    discount_patterns = []
    for name, p in all_pats.items():
        if not isinstance(p, dict):
            continue
        anchors = p.get("anchor_factors", [])
        if any("discount" in str(a) or "premium" in str(a) for a in anchors):
            pattern_str = " + ".join(anchors)
            direction = p.get("direction", "LONG")
            discount_patterns.append((name, pattern_str, direction, p))

    print(f"Discount паттернов для перемайнинга: {len(discount_patterns)}")
    for name, pstr, d, _ in discount_patterns:
        print(f"  {name}: {d} | {pstr}")

    # 2. Загружаем данные (single-process — multiprocessing для 39 паттернов overkill)
    print("\nЗагружаю OHLCV данные...")
    files = sorted(HISTORY_1H.glob("*.parquet"))
    print(f"  файлов: {len(files)}")

    _init_worker(str(HISTORY_1H))

    # 3. Оцениваем паттерны
    print("\nОцениваю паттерны...")
    results = []
    unique_tasks = list(set((pstr, d) for _, pstr, d, _ in discount_patterns))
    print(f"  уникальных комбинаций: {len(unique_tasks)}")

    for i, (pstr, d) in enumerate(unique_tasks):
        t0 = time.monotonic()
        res = _evaluate_one((pstr, d))
        results.append(res)
        print(f"  [{i+1}/{len(unique_tasks)}] {pstr[:60]:60s} n_train={res[2]} n_test={res[5]} avgR_test={res[6]:+.3f} WR_test={res[7]:.1f}% ({time.monotonic()-t0:.1f}s)")

    # 4. Save results
    df = pd.DataFrame(results, columns=[
        "pattern_str", "direction", "train_n", "train_avgR", "train_WR",
        "test_n", "test_avgR", "test_WR", "test_sumR", "test_maxR", "p_value"
    ])
    out_csv = OUTPUT_DIR / "discount_remine_metrics.csv"
    df.to_csv(out_csv, index=False)
    print(f"\nРезультаты сохранены: {out_csv}")

    # 5. Update arch104_patterns.yaml
    print("\nОбновляю config/arch104_patterns.yaml...")
    metric_map = {}
    for _, row in df.iterrows():
        key = (row["pattern_str"], row["direction"])
        metric_map[key] = row

    updated = 0
    degraded = 0
    for name, pstr, d, pat in discount_patterns:
        key = (pstr, d)
        if key in metric_map:
            m = metric_map[key]
            old_avgR = pat.get("test_avgR", 0)
            new_avgR = m["test_avgR"]
            pat["test_n"] = int(m["test_n"])
            pat["test_avgR"] = float(round(new_avgR, 3))
            pat["test_WR"] = float(round(m["test_WR"], 1))
            if new_avgR < 0.8:
                pat["enabled"] = False
                degraded += 1
                print(f"  ⛔ {name}: avgR {old_avgR:+.2f}→{new_avgR:+.2f} (ниже 0.8 — ОТКЛЮЧЁН)")
            else:
                updated += 1
                print(f"  ✅ {name}: avgR {old_avgR:+.2f}→{new_avgR:+.2f} n={int(m['test_n'])}")

    # Save updated config
    with open(PATTERNS_YAML, "w") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    print(f"\nИтого: {updated} обновлено, {degraded} отключено")
    print("Готово.")


if __name__ == "__main__":
    main()
