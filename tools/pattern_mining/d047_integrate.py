"""D-047 integration: Tier-8 trigger-gated patterns.

Source: data/research/2026-05-23--d047/nested_D047_*_{15m,5m}.csv

Anchor families (с triggers `wt_cross_*_1h`):
  L1_hidden_trig:  wt_div_bull_hidden_4h + bull_fvg_4h + above_ema200_4h + wt_cross_up_1h
  L2_reg_trig:     wt_div_bull_reg_4h + wt_os_4h + bull_fvg_4h + wt_cross_up_1h
  L3_golden_trig:  bull_div_1d + bull_fvg_4h + wt_os_4h + wt_cross_up_1h
  S1_hidden_trig:  wt_div_bear_hidden_4h + bear_ob_4h + below_ema200_4h + wt_cross_down_1h
  S2_reg_trig:     wt_div_bear_reg_4h + wt_ob_4h + bear_ob_4h + wt_cross_down_1h

Фильтр: n≥30, avgR≥0.7, WR≥65% (более строгий чем D-041 — trigger даёт лучше качество)
Top-5 per (anchor×ltf) = max 50 patterns
"""
from __future__ import annotations

import sys, re
from pathlib import Path
from collections import Counter
import pandas as pd
import yaml

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

PROJECT_ROOT = Path("E:/MTF BOT/CURSOR/crypto_volume_bot")
INPUT_DIR = PROJECT_ROOT / "data" / "research" / "2026-05-23--d047"
CONFIG_PATH = PROJECT_ROOT / "config" / "arch104_patterns.yaml"

ANCHORS = {
    "D047_L1_hidden_trig": {
        "f": ["wt_div_bull_hidden_4h", "bull_fvg_4h", "above_ema200_4h", "wt_cross_up_1h"],
        "d": "LONG",
    },
    "D047_L2_reg_trig": {
        "f": ["wt_div_bull_reg_4h", "wt_os_4h", "bull_fvg_4h", "wt_cross_up_1h"],
        "d": "LONG",
    },
    "D047_L3_golden_trig": {
        "f": ["bull_div_1d", "bull_fvg_4h", "wt_os_4h", "wt_cross_up_1h"],
        "d": "LONG",
    },
    "D047_S1_hidden_trig": {
        "f": ["wt_div_bear_hidden_4h", "bear_ob_4h", "below_ema200_4h", "wt_cross_down_1h"],
        "d": "SHORT",
    },
    "D047_S2_reg_trig": {
        "f": ["wt_div_bear_reg_4h", "wt_ob_4h", "bear_ob_4h", "wt_cross_down_1h"],
        "d": "SHORT",
    },
}

MIN_N = 30
MIN_AVG_R = 0.7
MIN_WR = 65.0
TOP_PER_PAIR = 5


def load_existing() -> set[frozenset]:
    with open(CONFIG_PATH, encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return {frozenset(cfg.get('anchor_factors') or [])
            for cfg in (data.get('patterns') or {}).values()}


def main():
    if not INPUT_DIR.exists():
        print(f"❌ Нет {INPUT_DIR}")
        return
    csvs = sorted(INPUT_DIR.glob("nested_D047_*.csv"))
    print(f"CSV найдено: {len(csvs)}")

    existing = load_existing()
    print(f"Existing patterns: {len(existing)}")

    candidates = []
    for csv_path in csvs:
        name = csv_path.stem
        m = re.match(r"^nested_(D047_[A-Z0-9_a-z]+?)_(5m|15m)$", name)
        if not m:
            print(f"  skip: {name}")
            continue
        anchor_id, ltf = m.group(1), m.group(2)
        if anchor_id not in ANCHORS:
            print(f"  unknown anchor: {anchor_id}")
            continue
        cfg = ANCHORS[anchor_id]
        df = pd.read_csv(csv_path)
        df = df[(df['n'] >= MIN_N) & (df['avgR'] >= MIN_AVG_R) & (df['WR'] >= MIN_WR)]
        for _, row in df.iterrows():
            ltf_factors = [x.strip() for x in str(row['pattern']).split('+')]
            full_anchors = frozenset(cfg['f'] + ltf_factors)
            if full_anchors in existing:
                continue
            candidates.append({
                'anchor_id': anchor_id, 'ltf': ltf, 'full_anchors': full_anchors,
                'n': int(row['n']), 'avgR': float(row['avgR']),
                'WR': float(row['WR']), 'score': float(row['score']),
                'direction': cfg['d'],
            })
    print(f"Кандидатов после фильтра: {len(candidates)}")

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

    seen = Counter()
    selected = []
    keep.sort(key=lambda r: -r['score'])
    for r in keep:
        key = (r['anchor_id'], r['ltf'])
        if seen[key] >= TOP_PER_PAIR:
            continue
        seen[key] += 1
        selected.append(r)
    print(f"Top-{TOP_PER_PAIR} per anchor×ltf: {len(selected)}")
    print()

    if not selected:
        print("⚠️ Ничего не прошло"); return

    by_a = Counter()
    for r in selected:
        by_a[(r['direction'], r['anchor_id'], r['ltf'])] += 1
    print("Распределение:")
    for k, v in sorted(by_a.items()):
        print(f"  {k[0]:<5} {k[1]:<25} {k[2]}: {v}")
    print()

    for direction in ('LONG', 'SHORT'):
        sel_d = [r for r in selected if r['direction'] == direction]
        sel_d.sort(key=lambda r: -r['score'])
        print(f"=== Top-5 {direction} ===")
        for r in sel_d[:5]:
            anch_str = ' + '.join(sorted(r['full_anchors']))[:90]
            print(f"  n={r['n']:>4} avgR={r['avgR']:>+.2f} WR={r['WR']:>4.1f}%  {anch_str}")
        print()

    # YAML
    lines = []
    lines.append("")
    lines.append("  # ─────────── TIER 8 D-047 TRIGGER-GATE (D-050, 2026-05-23) ───────────")
    lines.append("  # Trigger-gated patterns: anchors + wt_cross_*_1h как обязательное событие.")
    lines.append("  # Гипотеза пользователя подтверждена walkforward'ом — WR ↑ при ↓ false entries.")
    lines.append(f"  # Фильтр: n≥{MIN_N}, avgR≥{MIN_AVG_R}, WR≥{MIN_WR}.")
    lines.append("")

    pids = Counter()
    for direction in ('LONG', 'SHORT'):
        sel_d = [r for r in selected if r['direction'] == direction]
        if not sel_d:
            continue
        lines.append(f"  # ─── T8 {direction} ───")
        lines.append("")
        for r in sel_d:
            pids[(direction, r['anchor_id'], r['ltf'])] += 1
            idx = pids[(direction, r['anchor_id'], r['ltf'])]
            anchor_short = r['anchor_id'].replace('D047_', '').split('_')[0]
            pid = f"T8_{direction[0]}_{anchor_short}_{r['ltf']}_{idx:02d}"
            weight = max(12, min(16, int(r['score'] * 3)))
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
            lines.append(f"    priority: 2")
            lines.append(f"    detection_tf: {r['ltf']}")
            lines.append(f"    sl:")
            lines.append(f"      lookback_bars: {20 if r['ltf']=='5m' else 15}")
            lines.append(f"    tp:")
            lines.append(f"      strategy: no_trail")
            lines.append(f"      fallback_tp_r: 2.0")
            lines.append(f"    time_exit_hours: {12 if r['ltf']=='5m' else 24}")
            lines.append("")

    with open(CONFIG_PATH, encoding='utf-8') as f:
        main_text = f.read()
    marker = "# Defaults для всех patterns\ndefaults:"
    t8_re = re.compile(r"\n  # ─{3,} TIER 8 D-047.*?(?=# Defaults для всех patterns)", re.DOTALL)
    if t8_re.search(main_text):
        main_text = t8_re.sub("\n", main_text)
        print("🔄 Старый T8 блок удалён")
    else:
        print("➕ T8 блок добавляется впервые")
    fragment = "\n".join(lines) + "\n"
    new_text = main_text.replace(marker, fragment + marker)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        f.write(new_text)
    print(f"✅ config обновлён, добавлено {len(selected)} T8 patterns")


if __name__ == "__main__":
    main()
