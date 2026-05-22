"""Tier-6: 4h-only reversal patterns (без 1d-уровней).

Гипотеза: bull_div_1d / wt_os_1d — очень редкие события (раз в неделю-две).
4h-варианты (bull_div_4h, wt_os_4h) случаются чаще (раз в день-два).
Может быть достаточный edge без 1d-context.

Source: walkforward_full_mht.csv (12K BH-FDR-валидных).

Фильтр:
  - mht_passed=True, stable=True, n ≥ 50, avgR ≥ 0.5, WR ≥ 60%
  - Содержит ОДИН ИЗ 4h reversal markers: bull_div_4h, bear_div_4h, wt_os_4h, wt_ob_4h
  - НЕ содержит 1d reversal markers: bull_div_1d, bear_div_1d, wt_os_1d, wt_ob_1d
  - НЕ содержит других _1d факторов (bear_bos_1d, atr_cross_*_1d и т.д.)
  - НЕ содержит pivot_bounce_*
  - НЕ дублирует existing registry

Top 15 LONG + 15 SHORT.
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
MIN_WR = 60.0
TOP_LONG = 15
TOP_SHORT = 15

# Markers
LONG_4H_RM = ['bull_div_4h', 'wt_os_4h']
SHORT_4H_RM = ['bear_div_4h', 'wt_ob_4h']
# Исключаем все 1d-факторы (lowercase, не trogая pivot _1D/_1W)
HAS_1D_FACTOR = re.compile(r'(bull_div_1d|bear_div_1d|wt_os_1d|wt_ob_1d|bear_bos_1d|bull_bos_1d|atr_cross_(?:up|down)_1d|atr_(?:up|down)_1d|premium_1d|discount_1d|ema50_(?:above|below)_ema200_1d|bull_fvg_1d|bear_fvg_1d|bull_ob_1d|bear_ob_1d|bull_ob_near_1d|bear_ob_near_1d|rsi_cross50_(?:up|down)_1d|rsi_os_1d|rsi_ob_1d|bull_mom_1d|bear_mom_1d|vol_spike_1d|eqh_sweep_1d|eql_sweep_1d|above_ema(?:50|200)_1d|below_ema(?:50|200)_1d|bull_choch_1d|bear_choch_1d|bear_fvg_in_1d|bull_fvg_in_1d)')


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

    # Исключить ВСЕ 1d-факторы (кроме pivot_*_1D — они с uppercase)
    no_1d = base[~base['pattern'].str.contains(HAS_1D_FACTOR, na=False, regex=True)]
    print(f"Без 1d-факторов (lowercase): {len(no_1d)}")

    # Исключить pivot_bounce
    no_bounce = no_1d[~no_1d['pattern'].str.contains('pivot_bounce', na=False)]
    print(f"+ Без pivot_bounce: {len(no_bounce)}")

    # Отдельно LONG / SHORT с 4h reversal marker
    long_4h = no_bounce[
        (no_bounce['direction'] == 'LONG') &
        (no_bounce['pattern'].str.contains('|'.join(LONG_4H_RM), na=False, regex=True))
    ]
    short_4h = no_bounce[
        (no_bounce['direction'] == 'SHORT') &
        (no_bounce['pattern'].str.contains('|'.join(SHORT_4H_RM), na=False, regex=True))
    ]
    print(f"С LONG 4h reversal markers ({'/'.join(LONG_4H_RM)}): {len(long_4h)}")
    print(f"С SHORT 4h reversal markers ({'/'.join(SHORT_4H_RM)}): {len(short_4h)}")

    # Quality фильтр
    long_q = long_4h[(long_4h['test_avgR'] >= MIN_AVG_R) & (long_4h['test_WR'] >= MIN_WR)]
    short_q = short_4h[(short_4h['test_avgR'] >= MIN_AVG_R) & (short_4h['test_WR'] >= MIN_WR)]
    print(f"После avgR≥{MIN_AVG_R}, WR≥{MIN_WR}: LONG={len(long_q)}, SHORT={len(short_q)}")

    # Existing
    existing = load_existing()
    long_q = long_q.copy()
    short_q = short_q.copy()
    long_q['anchors_set'] = long_q['pattern'].apply(parse_anchors)
    short_q['anchors_set'] = short_q['pattern'].apply(parse_anchors)
    long_new = long_q[long_q['anchors_set'].apply(lambda a: a not in existing)]
    short_new = short_q[short_q['anchors_set'].apply(lambda a: a not in existing)]
    print(f"Не в registry: LONG={len(long_new)}, SHORT={len(short_new)}")
    print()

    def dedup_sort(d):
        if d.empty:
            return d
        d = d.sort_values('composite_score', ascending=False).reset_index(drop=True)
        keep, kept = [], []
        for i, row in d.iterrows():
            a = row['anchors_set']
            if any(a.issuperset(k) for k in kept):
                continue
            rm = [j for j, k in enumerate(kept) if k.issuperset(a) and len(k) > len(a)]
            for j in sorted(rm, reverse=True):
                kept.pop(j); keep.pop(j)
            keep.append(i); kept.append(a)
        return d.iloc[keep]

    long_d = dedup_sort(long_new)
    short_d = dedup_sort(short_new)
    print(f"После dedup: LONG={len(long_d)}, SHORT={len(short_d)}")

    sel_long = long_d.nlargest(TOP_LONG, 'composite_score') if not long_d.empty else long_d
    sel_short = short_d.nlargest(TOP_SHORT, 'composite_score') if not short_d.empty else short_d
    print(f"Финальный отбор: {len(sel_long)} LONG + {len(sel_short)} SHORT")
    print()

    print("=== Top-7 LONG (4h reversal без 1d) ===")
    for _, r in sel_long.head(7).iterrows():
        print(f"  n={int(r['test_n']):>4} avgR={r['test_avgR']:>+.2f} WR={r['test_WR']:>4.1f}%  {r['pattern']}")
    print()
    print("=== Top-7 SHORT (4h reversal без 1d) ===")
    for _, r in sel_short.head(7).iterrows():
        print(f"  n={int(r['test_n']):>4} avgR={r['test_avgR']:>+.2f} WR={r['test_WR']:>4.1f}%  {r['pattern']}")
    print()

    if sel_long.empty and sel_short.empty:
        print("⚠️ Ничего не нашли — 4h-only reversal не имеет edge без 1d context")
        return

    # YAML
    lines = []
    lines.append("")
    lines.append("  # ─────────── TIER 6 4H-REVERSAL (D-039, 2026-05-22) ───────────")
    lines.append("  # 4h-only reversal patterns: bull_div_4h / wt_os_4h / bear_div_4h / wt_ob_4h.")
    lines.append("  # БЕЗ 1d-факторов (lowercase suffixes — все), БЕЗ pivot_bounce_*.")
    lines.append(f"  # Фильтр: BH-FDR, n≥{MIN_N}, avgR≥{MIN_AVG_R}, WR≥{MIN_WR}.")
    lines.append("")

    counters = Counter()
    for direction, sel in [('LONG', sel_long), ('SHORT', sel_short)]:
        if sel.empty:
            continue
        lines.append(f"  # ─── T6 {direction} ───")
        lines.append("")
        for i, (_, row) in enumerate(sel.iterrows(), 1):
            tf = detect_tf(list(row['anchors_set']))
            counters[(direction, tf)] += 1
            pid = f"T6_{direction[0]}_{i:02d}"
            weight = max(11, min(14, int(row['composite_score'] * 2.5)))
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
            lines.append(f"    priority: 4")
            lines.append(f"    detection_tf: {tf}")
            lines.append(f"    tp:")
            lines.append(f"      strategy: no_trail")
            lines.append(f"      fallback_tp_r: 2.0")
            lines.append(f"    time_exit_hours: 24")
            lines.append("")

    with open(CONFIG_PATH, encoding='utf-8') as f:
        main_text = f.read()
    marker = "# Defaults для всех patterns\ndefaults:"
    t6_re = re.compile(r"\n  # ─{3,} TIER 6 4H-REVERSAL.*?(?=# Defaults для всех patterns)", re.DOTALL)
    if t6_re.search(main_text):
        main_text = t6_re.sub("\n", main_text)
        print("🔄 Старый T6 блок удалён")
    fragment = "\n".join(lines) + "\n"
    new_text = main_text.replace(marker, fragment + marker)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        f.write(new_text)
    print(f"✅ config обновлён")

    print()
    print("Распределение T6:")
    for k, v in sorted(counters.items()):
        print(f"  {k[0]:<5} {k[1]}: {v}")


if __name__ == "__main__":
    main()
