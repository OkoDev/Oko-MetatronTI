"""D2 integration: фильтр + dedup + добавление в config/arch104_patterns.yaml.

Запускается ПОСЛЕ nested_d2_4h1h.py — читает CSV из data/research/2026-05-21--d2/.
"""
from __future__ import annotations

import sys
from pathlib import Path
from collections import Counter
import pandas as pd
import yaml

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

PROJECT_ROOT = Path("E:/MTF BOT/CURSOR/crypto_volume_bot")
INPUT_DIR = PROJECT_ROOT / "data" / "research" / "2026-05-21--d2"
CONFIG_PATH = PROJECT_ROOT / "config" / "arch104_patterns.yaml"

# Anchor definitions (синхронно с nested_d2_4h1h.py)
ANCHORS = {
    "D2_L1_revival_4h":  {"f": ["atr_up_4h", "bull_fvg_1h", "bull_ob_1h"],          "d": "LONG"},
    "D2_L2_bounce_1h":   {"f": ["wt_os_1h", "bull_fvg_1h", "discount_1h"],          "d": "LONG"},
    "D2_L3_ema_bounce":  {"f": ["below_ema200_1h", "bull_fvg_1h", "atr_up_4h"],     "d": "LONG"},
    "D2_S1_exhaust_4h":  {"f": ["atr_down_4h", "bear_ob_1h", "premium_1h"],         "d": "SHORT"},
    "D2_S2_fade_1h":     {"f": ["wt_ob_1h", "bear_ob_1h", "premium_1h"],            "d": "SHORT"},
    "D2_S3_ema_reject":  {"f": ["above_ema200_1h", "bear_ob_1h", "atr_down_4h"],    "d": "SHORT"},
}

# Фильтр (D2 = mid-cycle, более мягкий чем tier-2)
MIN_N = 50
MIN_AVG_R = 0.5
MIN_WR = 60.0

# Top-N per (anchor × ltf)
TOP_PER_PAIR = 3


def load_existing_anchors() -> set:
    """Frozenset существующих anchor_factors из текущего yaml — для exclude."""
    with open(CONFIG_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    existing = set()
    for pid, cfg in (data.get("patterns") or {}).items():
        existing.add(frozenset(cfg.get("anchor_factors") or []))
    return existing


def main():
    if not INPUT_DIR.exists():
        print(f"❌ Нет директории {INPUT_DIR} — сначала запусти nested_d2_4h1h.py")
        return

    csvs = sorted(INPUT_DIR.glob("nested_v3_*.csv"))
    print(f"CSV найдено: {len(csvs)}")
    if not csvs:
        print("❌ Нет CSV")
        return

    existing = load_existing_anchors()
    print(f"Уже в registry: {len(existing)} anchor sets")

    # Загрузка + фильтр
    candidates = []
    for csv_path in csvs:
        df = pd.read_csv(csv_path)
        # Определяем anchor_id и ltf из имени файла
        name = csv_path.stem  # nested_v3_D2_L1_revival_4h_15m
        parts = name.replace("nested_v3_", "").rsplit("_", 1)
        anchor_id, ltf = parts[0], parts[1]
        if anchor_id not in ANCHORS:
            print(f"  ⚠️ Неизвестный anchor: {anchor_id}")
            continue
        cfg = ANCHORS[anchor_id]

        df = df[(df["n"] >= MIN_N) & (df["avgR"] >= MIN_AVG_R) & (df["WR"] >= MIN_WR)]
        for _, row in df.iterrows():
            ltf_factors = [x.strip() for x in str(row["pattern"]).split("+")]
            full_anchors = frozenset(cfg["f"] + ltf_factors)
            if full_anchors in existing:
                continue
            candidates.append({
                "anchor_id": anchor_id,
                "ltf": ltf,
                "full_anchors": full_anchors,
                "ltf_pattern": ltf_factors,
                "n": int(row["n"]),
                "avgR": float(row["avgR"]),
                "WR": float(row["WR"]),
                "score": float(row["score"]),
                "direction": cfg["d"],
            })

    print(f"После фильтра (n≥{MIN_N}, avgR≥{MIN_AVG_R}, WR≥{MIN_WR}, не в registry): {len(candidates)}")

    # Dedup: keep_smaller (более общий subset)
    candidates.sort(key=lambda r: (-r["score"], len(r["full_anchors"])))
    keep = []
    for r in candidates:
        is_super = any(r["full_anchors"].issuperset(k["full_anchors"]) for k in keep)
        if is_super:
            continue
        smaller_to_remove = [i for i, k in enumerate(keep)
                             if k["full_anchors"].issuperset(r["full_anchors"])
                             and len(k["full_anchors"]) > len(r["full_anchors"])]
        for i in sorted(smaller_to_remove, reverse=True):
            keep.pop(i)
        keep.append(r)
    print(f"После dedup: {len(keep)}")

    # Top-N per (anchor × ltf)
    selected = []
    seen = Counter()
    keep.sort(key=lambda r: -r["score"])
    for r in keep:
        key = (r["anchor_id"], r["ltf"])
        if seen[key] >= TOP_PER_PAIR:
            continue
        seen[key] += 1
        selected.append(r)
    print(f"Финальный отбор (top-{TOP_PER_PAIR} per anchor×ltf): {len(selected)}")

    if not selected:
        print("⚠️ Ничего не прошло фильтр — D2 не выдал паттернов для текущих порогов")
        return

    # Generate YAML lines
    by_dir_ltf = Counter()
    lines = []
    lines.append("")
    lines.append("  # ─────────── TIER 3 D2 (D-033, 2026-05-21) ───────────")
    lines.append("  # 4h+1h HTF base, intraday/mid-cycle паттерны")
    lines.append(f"  # Фильтр: n≥{MIN_N}, avgR≥{MIN_AVG_R}, WR≥{MIN_WR}")
    lines.append("  # Anchors предложены роем (mistral lead, 2026-05-21)")
    lines.append("")

    for direction in ("LONG", "SHORT"):
        sel_d = [r for r in selected if r["direction"] == direction]
        if not sel_d:
            continue
        lines.append(f"  # ─── D2 {direction} ───")
        lines.append("")
        for r in sel_d:
            by_dir_ltf[(direction, r["ltf"])] += 1
            idx = by_dir_ltf[(direction, r["ltf"])]
            pid = f"D2_{direction[0]}_{r['anchor_id'].split('_')[1]}_{r['ltf']}_{idx:02d}"
            weight = max(10, min(13, int(r["score"] * 2)))
            anchors_sorted = sorted(r["full_anchors"])
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
            lines.append(f"    priority: 4")
            lines.append(f"    detection_tf: {r['ltf']}")
            lines.append(f"    sl:")
            lines.append(f"      lookback_bars: {20 if r['ltf']=='5m' else 15}")
            lines.append(f"    tp:")
            lines.append(f"      strategy: no_trail")
            lines.append(f"      fallback_tp_r: 2.0")
            lines.append(f"    time_exit_hours: {6 if r['ltf']=='5m' else 12}")
            lines.append("")

    # Replace D2 block in main config (idempotent — повторный запуск переписывает)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        main_text = f.read()
    marker_end = "# Defaults для всех patterns\ndefaults:"
    if marker_end not in main_text:
        print("❌ Маркер defaults не найден в config")
        return

    # Удаляем старый D2 блок если есть (между маркером TIER 3 D2 и Defaults)
    import re
    d2_start_pattern = re.compile(r"\n  # ─{3,} TIER 3 D2.*?(?=# Defaults для всех patterns)", re.DOTALL)
    if d2_start_pattern.search(main_text):
        main_text = d2_start_pattern.sub("\n", main_text)
        print("🔄 Старый D2 блок удалён, добавляю новый")
    else:
        print("➕ Старого D2 блока нет, добавляю новый")

    fragment = "\n".join(lines) + "\n"
    new_text = main_text.replace(marker_end, fragment + marker_end)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(new_text)
    print(f"✅ Обновлён config/arch104_patterns.yaml")

    # Test loading
    from core.confirmations.arch104_patterns import ARCH104Registry
    reg = ARCH104Registry()
    print(f"\nRegistry: {len(reg.patterns)} patterns total")
    print(f"  LONG: {len(reg.list_by_direction('LONG'))}")
    print(f"  SHORT: {len(reg.list_by_direction('SHORT'))}")
    tf_counts = Counter(p.detection_tf for p in reg.patterns.values())
    print(f"  По TF: {dict(tf_counts)}")
    print(f"\nDistribution selected (anchor × ltf):")
    for k, v in sorted(by_dir_ltf.items()):
        print(f"  {k[0]:<5} {k[1]}: {v}")


if __name__ == "__main__":
    main()
