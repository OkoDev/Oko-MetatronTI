"""ARCH-105 integration: hidden divergence patterns → Tier-7 в registry.

Запускается ПОСЛЕ nested_arch105_hidden.py — читает CSV из
data/research/2026-05-22--arch105/.

Idempotent — replace T7 block при повторном запуске.
"""
from __future__ import annotations

import sys
import re
from pathlib import Path
from collections import Counter
import pandas as pd
import yaml

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

PROJECT_ROOT = Path("E:/MTF BOT/CURSOR/crypto_volume_bot")
INPUT_DIR = PROJECT_ROOT / "data" / "research" / "2026-05-22--arch105"
CONFIG_PATH = PROJECT_ROOT / "config" / "arch104_patterns.yaml"

# Anchor определения (зеркало nested_arch105_hidden.py)
ANCHORS = {
    "A1_bull_hidden_4h":  {"f": ["wt_div_bull_hidden_4h", "bull_fvg_4h", "above_ema200_4h"],   "d": "LONG"},
    "A2_bull_reg_4h":     {"f": ["wt_div_bull_reg_4h", "wt_os_4h", "bull_fvg_4h"],             "d": "LONG"},
    "A3_bear_hidden_4h":  {"f": ["wt_div_bear_hidden_4h", "bear_ob_4h", "below_ema200_4h"],    "d": "SHORT"},
    "A4_bear_reg_4h":     {"f": ["wt_div_bear_reg_4h", "wt_ob_4h", "bear_ob_4h"],              "d": "SHORT"},
}

# Фильтр (ARCH-105 — новые flags, средняя строгость)
MIN_N = 50
MIN_AVG_R = 0.5
MIN_WR = 60.0
TOP_PER_PAIR = 5   # 4 anchors × 2 LTF × 5 = max 40 patterns


def load_existing() -> set[frozenset]:
    with open(CONFIG_PATH, encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return {frozenset(cfg.get('anchor_factors') or [])
            for cfg in (data.get('patterns') or {}).values()}


def main():
    if not INPUT_DIR.exists():
        print(f"❌ Директория {INPUT_DIR} не существует — сначала nested_arch105_hidden.py")
        return

    csvs = sorted(INPUT_DIR.glob("nested_*.csv"))
    print(f"CSV найдено: {len(csvs)}")
    if not csvs:
        print("❌ Нет CSV — walkforward не завершён")
        return

    existing = load_existing()
    print(f"Existing patterns в registry: {len(existing)}")

    candidates = []
    for csv_path in csvs:
        df = pd.read_csv(csv_path)
        name = csv_path.stem  # nested_A1_bull_hidden_4h_15m
        # Парсим anchor_id и ltf
        m = re.match(r"^nested_(A\d_[a-z_4h0-9]+?)_(5m|15m)$", name)
        if not m:
            print(f"  ⚠️ skip unknown: {name}")
            continue
        anchor_id, ltf = m.group(1), m.group(2)
        if anchor_id not in ANCHORS:
            print(f"  ⚠️ unknown anchor: {anchor_id}")
            continue
        cfg = ANCHORS[anchor_id]
        df = df[(df['n'] >= MIN_N) & (df['avgR'] >= MIN_AVG_R) & (df['WR'] >= MIN_WR)]
        for _, row in df.iterrows():
            ltf_factors = [x.strip() for x in str(row['pattern']).split('+')]
            full_anchors = frozenset(cfg['f'] + ltf_factors)
            if full_anchors in existing:
                continue
            candidates.append({
                'anchor_id': anchor_id,
                'ltf': ltf,
                'full_anchors': full_anchors,
                'n': int(row['n']),
                'avgR': float(row['avgR']),
                'WR': float(row['WR']),
                'score': float(row['score']),
                'direction': cfg['d'],
            })

    print(f"Кандидатов после фильтра + dedup-existing: {len(candidates)}")

    # Dedup keep_smaller
    candidates.sort(key=lambda r: (-r['score'], len(r['full_anchors'])))
    keep = []
    for r in candidates:
        if any(r['full_anchors'].issuperset(k['full_anchors']) for k in keep):
            continue
        rm = [i for i, k in enumerate(keep)
              if k['full_anchors'].issuperset(r['full_anchors']) and len(k['full_anchors']) > len(r['full_anchors'])]
        for i in sorted(rm, reverse=True):
            keep.pop(i)
        keep.append(r)
    print(f"После dedup: {len(keep)}")

    # Top-N per (anchor × ltf)
    seen = Counter()
    selected = []
    keep.sort(key=lambda r: -r['score'])
    for r in keep:
        key = (r['anchor_id'], r['ltf'])
        if seen[key] >= TOP_PER_PAIR:
            continue
        seen[key] += 1
        selected.append(r)
    print(f"Финальный отбор (top-{TOP_PER_PAIR} per anchor×ltf): {len(selected)}")
    print()

    # Сводка
    by_a = Counter()
    for r in selected:
        by_a[(r['direction'], r['anchor_id'], r['ltf'])] += 1
    print("Распределение:")
    for k, v in sorted(by_a.items()):
        print(f"  {k[0]:<5} {k[1]:<22} {k[2]}: {v}")

    if not selected:
        print("⚠️ Ничего не прошло фильтр")
        return

    # Top-5 по каждому direction
    print()
    for direction in ('LONG', 'SHORT'):
        sel_d = [r for r in selected if r['direction'] == direction]
        sel_d.sort(key=lambda r: -r['score'])
        print(f"=== Top-5 {direction} ===")
        for r in sel_d[:5]:
            anchors_str = ' + '.join(sorted(r['full_anchors']))[:90]
            print(f"  n={r['n']:>4} avgR={r['avgR']:>+.2f} WR={r['WR']:>4.1f}%  {anchors_str}")
        print()

    # Generate YAML
    lines = []
    lines.append("")
    lines.append("  # ─────────── TIER 7 ARCH-105 (D-041, 2026-05-22) ───────────")
    lines.append("  # Hidden divergence patterns — continuation/reversal через WT div.")
    lines.append("  # 4 anchor families: A1/A2 (LONG hidden/reg), A3/A4 (SHORT hidden/reg).")
    lines.append(f"  # Фильтр: n≥{MIN_N}, avgR≥{MIN_AVG_R}, WR≥{MIN_WR}.")
    lines.append("  # Persistent на 10 баров (как pivot_bounce).")
    lines.append("")

    pids = Counter()
    for direction in ('LONG', 'SHORT'):
        sel_d = [r for r in selected if r['direction'] == direction]
        if not sel_d:
            continue
        lines.append(f"  # ─── T7 {direction} ───")
        lines.append("")
        for r in sel_d:
            pids[(direction, r['anchor_id'], r['ltf'])] += 1
            idx = pids[(direction, r['anchor_id'], r['ltf'])]
            short_a = r['anchor_id'].replace('_', '')[:8]  # A1bullhid…
            pid = f"T7_{direction[0]}_{r['anchor_id'].split('_')[0]}_{r['ltf']}_{idx:02d}"
            weight = max(11, min(15, int(r['score'] * 2.5)))
            anchors_sorted = sorted(r['full_anchors'])
            lines.append(f"  {pid}:")
            lines.append(f"    direction: {direction}")
            lines.append(f"    parent: {r['anchor_id']}")
            lines.append(f"    anchor_factors:")
            for a in anchors_sorted:
                lines.append(f"      - {a}")
            lines.append(f"    test_n: {r['n']}")
            lines.append(f"    test_avgR: {r['avgR']:.3f}")
            lines.append(f"    test_WR: {r['WR']:.1f}")
            lines.append(f"    weight: {weight}")
            lines.append(f"    priority: 3")
            lines.append(f"    detection_tf: {r['ltf']}")
            lines.append(f"    sl:")
            lines.append(f"      lookback_bars: {20 if r['ltf']=='5m' else 15}")
            lines.append(f"    tp:")
            lines.append(f"      strategy: no_trail")
            lines.append(f"      fallback_tp_r: 2.0")
            lines.append(f"    time_exit_hours: {12 if r['ltf']=='5m' else 24}")
            lines.append("")

    # Append/replace в config
    with open(CONFIG_PATH, encoding='utf-8') as f:
        main_text = f.read()
    marker = "# Defaults для всех patterns\ndefaults:"
    if marker not in main_text:
        print("❌ Маркер defaults не найден")
        return

    t7_re = re.compile(r"\n  # ─{3,} TIER 7 ARCH-105.*?(?=# Defaults для всех patterns)", re.DOTALL)
    if t7_re.search(main_text):
        main_text = t7_re.sub("\n", main_text)
        print("🔄 Старый T7 блок удалён")
    else:
        print("➕ T7 блок добавляется впервые")

    fragment = "\n".join(lines) + "\n"
    new_text = main_text.replace(marker, fragment + marker)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        f.write(new_text)
    print(f"✅ config обновлён, добавлено {len(selected)} T7 patterns")


if __name__ == "__main__":
    main()
