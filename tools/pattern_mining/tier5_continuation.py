"""Tier-5 continuation: паттерны без HTF 1d-факторов и без reversal markers.

Цель: закрыть mid-cycle/trend-continuation покрытие. Текущий registry молчит
потому что все 139 paterns требуют HTF reversal (bull_div_1d / bear_bos_1d / wt_os_4h).
На trending рынке без daily reversal все они молчат.

Source: walkforward_full_mht.csv (12K BH-FDR-валидных).

Фильтр:
  - mht_passed=True, stable=True, n ≥ 50, avgR ≥ 0.5, WR ≥ 55%
  - НЕТ `_1d` факторов (не нужен дневной режим)
  - НЕТ pivot_bounce_* (event-based)
  - НЕТ reversal markers: `_os_`, `_ob_`, `_div_`, `eqh_sweep`, `eql_sweep`
  - НЕ дублирует registry

Top 15 LONG + 15 SHORT по composite_score.
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
CSV = PROJECT_ROOT / "data/research/2026-05-20--ph1/walkforward_full_mht.csv"
CONFIG_PATH = PROJECT_ROOT / "config/arch104_patterns.yaml"

MIN_N = 50
MIN_AVG_R = 0.5
MIN_WR = 55.0
TOP_LONG = 15
TOP_SHORT = 15

# Markers reversal (excluded)
REVERSAL_PATTERNS = re.compile(r'(_os_|_ob_|_div_|eqh_sweep|eql_sweep|wt_cross_up|wt_cross_down|rsi_os|rsi_ob)')


def parse_anchors(s: str) -> frozenset:
    return frozenset(x.strip() for x in s.split('+'))


def load_existing() -> set[frozenset]:
    with open(CONFIG_PATH, encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return {frozenset(cfg.get('anchor_factors') or [])
            for cfg in (data.get('patterns') or {}).values()}


def detect_tf(anchors: list) -> str:
    if any('_5m' in a for a in anchors): return '5m'
    if any('_15m' in a for a in anchors): return '15m'
    if any('_1h' in a for a in anchors): return '1h'
    return '4h'


def main():
    df = pd.read_csv(CSV)
    print(f"Loaded {len(df)} rows")

    base = df[(df['mht_passed']) & (df['stable']) & (df['test_n'] >= MIN_N)]
    print(f"BH-FDR + stable + n≥{MIN_N}: {len(base)}")

    # Исключить 1d-факторы
    no_1d = base[~base['pattern'].str.contains('_1d', na=False)]
    print(f"Без _1d факторов: {len(no_1d)}")

    # Исключить pivot_bounce
    no_bounce = no_1d[~no_1d['pattern'].str.contains('pivot_bounce', na=False)]
    print(f"+ Без pivot_bounce: {len(no_bounce)}")

    # Исключить reversal markers
    no_reversal = no_bounce[~no_bounce['pattern'].str.contains(REVERSAL_PATTERNS, na=False, regex=True)]
    print(f"+ Без reversal markers (os/ob/div/sweep/cross): {len(no_reversal)}")

    # Quality
    qual = no_reversal[(no_reversal['test_avgR'] >= MIN_AVG_R) & (no_reversal['test_WR'] >= MIN_WR)]
    print(f"После avgR≥{MIN_AVG_R}, WR≥{MIN_WR}: {len(qual)}")

    if len(qual) == 0:
        print()
        print("⚠️ НИ ОДНОГО continuation паттерна не прошло BH-FDR!")
        print("Это значит что trend-following без HTF context в combinator не имеет edge.")
        print("Нужен новый walkforward с continuation-specific anchors.")
        return

    # Уже в registry?
    existing = load_existing()
    qual = qual.copy()
    qual['anchors_set'] = qual['pattern'].apply(parse_anchors)
    new_only = qual[qual['anchors_set'].apply(lambda a: a not in existing)]
    print(f"Не в registry: {len(new_only)}")
    print()

    # Dedup keep_smaller
    new_only = new_only.sort_values('composite_score', ascending=False).reset_index(drop=True)
    keep, kept_a = [], []
    for i, row in new_only.iterrows():
        a = row['anchors_set']
        if any(a.issuperset(k) for k in kept_a):
            continue
        rm = [j for j, k in enumerate(kept_a) if k.issuperset(a) and len(k) > len(a)]
        for j in sorted(rm, reverse=True):
            kept_a.pop(j); keep.pop(j)
        keep.append(i); kept_a.append(a)
    dedup = new_only.iloc[keep]
    print(f"После dedup: {len(dedup)}")

    sel_long = dedup[dedup['direction'] == 'LONG'].nlargest(TOP_LONG, 'composite_score')
    sel_short = dedup[dedup['direction'] == 'SHORT'].nlargest(TOP_SHORT, 'composite_score')
    sel = pd.concat([sel_long, sel_short])
    print(f"Финальный отбор: {len(sel_long)} LONG + {len(sel_short)} SHORT = {len(sel)}")
    print()

    print("=== Top-5 LONG (continuation) ===")
    for _, r in sel_long.head(5).iterrows():
        print(f"  n={int(r['test_n']):>4} avgR={r['test_avgR']:>+.2f} WR={r['test_WR']:>4.1f}%  {r['pattern']}")
    print()
    print("=== Top-5 SHORT (continuation) ===")
    for _, r in sel_short.head(5).iterrows():
        print(f"  n={int(r['test_n']):>4} avgR={r['test_avgR']:>+.2f} WR={r['test_WR']:>4.1f}%  {r['pattern']}")
    print()

    # YAML
    lines = []
    lines.append("")
    lines.append("  # ─────────── TIER 5 CONTINUATION (D-038, 2026-05-22) ───────────")
    lines.append("  # Continuation/trend-following patterns. БЕЗ 1d-факторов,")
    lines.append("  # БЕЗ reversal markers (os/ob/div/sweep), БЕЗ pivot_bounce.")
    lines.append(f"  # Фильтр: BH-FDR, n≥{MIN_N}, avgR≥{MIN_AVG_R}, WR≥{MIN_WR}.")
    lines.append("")

    counters = Counter()
    for direction, sl in [('LONG', sel_long), ('SHORT', sel_short)]:
        if sl.empty:
            continue
        lines.append(f"  # ─── T5 {direction} ───")
        lines.append("")
        for i, (_, row) in enumerate(sl.iterrows(), 1):
            tf = detect_tf(list(row['anchors_set']))
            counters[(direction, tf)] += 1
            pid = f"T5_{direction[0]}_{i:02d}"
            weight = max(10, min(13, int(row['composite_score'] * 2.5)))
            anchors_sorted = sorted(row['anchors_set'])
            lines.append(f"  {pid}:")
            lines.append(f"    direction: {direction}")
            lines.append(f"    anchor_factors:")
            for a in anchors_sorted:
                lines.append(f"      - {a}")
            lines.append(f"    test_n: {int(row['test_n'])}")
            lines.append(f"    test_avgR: {row['test_avgR']:.3f}")
            lines.append(f"    test_WR: {row['test_WR']:.1f}")
            lines.append(f"    mht_p_adj: {row['p_value_adj_bh']:.4f}")
            lines.append(f"    weight: {weight}")
            lines.append(f"    priority: 5")
            lines.append(f"    detection_tf: {tf}")
            lines.append(f"    tp:")
            lines.append(f"      strategy: no_trail")
            lines.append(f"      fallback_tp_r: 2.0")
            lines.append(f"    time_exit_hours: 24")
            lines.append("")

    # Append/replace
    with open(CONFIG_PATH, encoding='utf-8') as f:
        main_text = f.read()
    marker = "# Defaults для всех patterns\ndefaults:"
    t5_re = re.compile(r"\n  # ─{3,} TIER 5 CONTINUATION.*?(?=# Defaults для всех patterns)", re.DOTALL)
    if t5_re.search(main_text):
        main_text = t5_re.sub("\n", main_text)
        print("🔄 Старый T5 блок удалён")
    fragment = "\n".join(lines) + "\n"
    new_text = main_text.replace(marker, fragment + marker)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        f.write(new_text)
    print(f"✅ config обновлён")

    print()
    print("Распределение T5:")
    for k, v in sorted(counters.items()):
        print(f"  {k[0]:<5} {k[1]}: {v}")


if __name__ == "__main__":
    main()
