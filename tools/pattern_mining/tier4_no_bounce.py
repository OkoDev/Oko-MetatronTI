"""Tier-4: persistent-only patterns (без pivot_bounce_*) для часто-срабатывающих setups.

Источник: data/research/2026-05-20--ph1/walkforward_full_mht.csv (12K BH-FDR-валидных).

Фильтр:
  - mht_passed=True, stable=True
  - test_n ≥ 50, test_avgR ≥ 0.5, test_WR ≥ 60%
  - НЕ содержит pivot_bounce_up/down (event-based, редко TRUE в live scan)
  - Может содержать pivot_above_/pivot_near_/pivot_below_ (persistent уровни)
  - Не дублирует существующие 109 patterns в registry

Топ-15 LONG + Топ-15 SHORT по composite_score → tier-4 в yaml.
"""
from __future__ import annotations

import sys
from pathlib import Path
from collections import Counter
import pandas as pd
import yaml
import re

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

PROJECT_ROOT = Path("E:/MTF BOT/CURSOR/crypto_volume_bot")
CSV = PROJECT_ROOT / "data/research/2026-05-20--ph1/walkforward_full_mht.csv"
CONFIG_PATH = PROJECT_ROOT / "config/arch104_patterns.yaml"

MIN_N = 50
MIN_AVG_R = 0.5
MIN_WR = 60.0
TOP_LONG = 15
TOP_SHORT = 15


def parse_anchors(s: str) -> frozenset:
    return frozenset(x.strip() for x in s.split('+'))


def load_existing_anchors() -> set[frozenset]:
    with open(CONFIG_PATH, encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return {frozenset(cfg.get('anchor_factors') or [])
            for cfg in (data.get('patterns') or {}).values()}


def detect_tf(anchors: list) -> str:
    """Detect TF из anchor set — самый низкий TF определяет detection."""
    if any('_5m' in a for a in anchors): return '5m'
    if any('_15m' in a for a in anchors): return '15m'
    if any('_1h' in a for a in anchors): return '1h'
    return '4h'


def main():
    df = pd.read_csv(CSV)
    print(f"Loaded {len(df)} rows из walkforward_full_mht.csv")

    # Фильтр базовый
    base = df[(df['mht_passed']) & (df['stable']) & (df['test_n'] >= MIN_N)]
    print(f"BH-FDR passed + stable + n≥{MIN_N}: {len(base)}")

    # Исключить bounce events
    no_bounce = base[~base['pattern'].str.contains('pivot_bounce', na=False)]
    print(f"Без pivot_bounce: {len(no_bounce)}")

    # Quality фильтр
    qual = no_bounce[(no_bounce['test_avgR'] >= MIN_AVG_R) & (no_bounce['test_WR'] >= MIN_WR)]
    print(f"После avgR≥{MIN_AVG_R}, WR≥{MIN_WR}: {len(qual)}")

    # Уже в registry — исключить
    existing = load_existing_anchors()
    qual = qual.copy()
    qual['anchors_set'] = qual['pattern'].apply(parse_anchors)
    qual['is_new'] = qual['anchors_set'].apply(lambda a: a not in existing)
    new_only = qual[qual['is_new']]
    print(f"Не дублирует registry: {len(new_only)}")
    print()

    # Dedup (keep_smaller)
    new_only = new_only.sort_values('composite_score', ascending=False).reset_index(drop=True)
    keep = []
    kept_anchors = []
    for i, row in new_only.iterrows():
        a = row['anchors_set']
        is_super = any(a.issuperset(k) for k in kept_anchors)
        if is_super:
            continue
        smaller_to_remove = [j for j, k in enumerate(kept_anchors)
                             if k.issuperset(a) and len(k) > len(a)]
        for j in sorted(smaller_to_remove, reverse=True):
            kept_anchors.pop(j)
            keep.pop(j)
        keep.append(i)
        kept_anchors.append(a)
    dedup = new_only.iloc[keep].copy()
    print(f"После dedup (keep_smaller): {len(dedup)}")

    # Top-15 LONG + Top-15 SHORT
    selected_long = dedup[dedup['direction'] == 'LONG'].nlargest(TOP_LONG, 'composite_score')
    selected_short = dedup[dedup['direction'] == 'SHORT'].nlargest(TOP_SHORT, 'composite_score')
    selected = pd.concat([selected_long, selected_short])
    print(f"Финальный отбор: {len(selected_long)} LONG + {len(selected_short)} SHORT = {len(selected)}")
    print()

    # Сводка
    print("=== Top-5 LONG ===")
    for _, r in selected_long.head(5).iterrows():
        print(f"  n={int(r['test_n']):>4} avgR={r['test_avgR']:>+.2f} WR={r['test_WR']:>4.1f}%  {r['pattern'][:90]}")
    print()
    print("=== Top-5 SHORT ===")
    for _, r in selected_short.head(5).iterrows():
        print(f"  n={int(r['test_n']):>4} avgR={r['test_avgR']:>+.2f} WR={r['test_WR']:>4.1f}%  {r['pattern'][:90]}")
    print()

    # Generate YAML
    yaml_lines = []
    yaml_lines.append("")
    yaml_lines.append("  # ─────────── TIER 4 NO-BOUNCE (D-037, 2026-05-22) ───────────")
    yaml_lines.append("  # Persistent-only patterns (без pivot_bounce_*) для часто-срабатывающих setups.")
    yaml_lines.append("  # Цель: закрыть mid-cycle покрытие без зависимости от event-based pivot bounces.")
    yaml_lines.append(f"  # Фильтр: BH-FDR прошли, n≥{MIN_N}, avgR≥{MIN_AVG_R}, WR≥{MIN_WR}, без pivot_bounce_*")
    yaml_lines.append("")

    counters = Counter()
    for direction, sel in [('LONG', selected_long), ('SHORT', selected_short)]:
        yaml_lines.append(f"  # ─── T4 {direction} ───")
        yaml_lines.append("")
        for i, (_, row) in enumerate(sel.iterrows(), 1):
            tf = detect_tf(list(row['anchors_set']))
            counters[(direction, tf)] += 1
            pid = f"T4_{direction[0]}_{i:02d}"
            weight = max(10, min(13, int(row['composite_score'] * 2)))
            anchors_sorted = sorted(row['anchors_set'])
            yaml_lines.append(f"  {pid}:")
            yaml_lines.append(f"    direction: {direction}")
            yaml_lines.append(f"    anchor_factors:")
            for a in anchors_sorted:
                yaml_lines.append(f"      - {a}")
            yaml_lines.append(f"    test_n: {int(row['test_n'])}")
            yaml_lines.append(f"    test_avgR: {row['test_avgR']:.3f}")
            yaml_lines.append(f"    test_WR: {row['test_WR']:.1f}")
            yaml_lines.append(f"    mht_p_adj: {row['p_value_adj_bh']:.4f}")
            yaml_lines.append(f"    weight: {weight}")
            yaml_lines.append(f"    priority: 4")
            yaml_lines.append(f"    detection_tf: {tf}")
            yaml_lines.append(f"    tp:")
            yaml_lines.append(f"      strategy: no_trail")
            yaml_lines.append(f"      fallback_tp_r: 2.0")
            yaml_lines.append(f"    time_exit_hours: 48")
            yaml_lines.append("")

    # Append to main yaml (idempotent — replace existing T4 block)
    with open(CONFIG_PATH, encoding='utf-8') as f:
        main_text = f.read()
    marker_end = "# Defaults для всех patterns\ndefaults:"
    if marker_end not in main_text:
        print("❌ Маркер defaults не найден")
        return

    t4_pattern = re.compile(r"\n  # ─{3,} TIER 4 NO-BOUNCE.*?(?=# Defaults для всех patterns)", re.DOTALL)
    if t4_pattern.search(main_text):
        main_text = t4_pattern.sub("\n", main_text)
        print("🔄 Старый T4 блок удалён")
    else:
        print("➕ T4 блок добавляется впервые")

    fragment = "\n".join(yaml_lines) + "\n"
    new_text = main_text.replace(marker_end, fragment + marker_end)
    with open(CONFIG_PATH, "w", encoding='utf-8') as f:
        f.write(new_text)
    print(f"✅ config/arch104_patterns.yaml обновлён")

    print()
    print("Распределение T4 по (direction, TF):")
    for k, v in sorted(counters.items()):
        print(f"  {k[0]:<5} {k[1]}: {v}")


if __name__ == "__main__":
    main()
