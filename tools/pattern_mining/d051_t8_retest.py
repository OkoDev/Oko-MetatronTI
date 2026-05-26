"""D-051 T8 Retest: anchors БЕЗ wt_cross_*_1h + wt_cross_*_{ltf} как pinned gate.

Сравнение с D-047:
  D-047:  HTF = [..., wt_cross_up_1h]      + свободные LTF комбинации
  D-051:  HTF = [... БЕЗ wt_cross_up_1h]  + wt_cross_up_{ltf} PINNED + доп. LTF

Гипотеза пользователя (26.05.2026): D-051 gate на det_tf покрывает нужное подтверждение,
1h cross в anchor избыточен и режет трафик. Если убрать 1h cross из паттерна,
но добавить det_tf cross как обязательный — получим больше сделок с сопоставимым WR.

Output: data/research/2026-05-26--d051-retest/nested_D051_*_{ltf}.csv
"""
from __future__ import annotations

import sys, time, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from itertools import combinations
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import combinator_v2 as cb
# combinator_v3_nested читает sys.argv[1] при импорте — подставляем нейтральное значение
_argv_saved = sys.argv[:]
sys.argv = sys.argv[:1]
import combinator_v3_nested as nested
sys.argv = _argv_saved

PROJECT_ROOT = Path("E:/MTF BOT/CURSOR/crypto_volume_bot")
OUTPUT_DIR = PROJECT_ROOT / "data" / "research" / "2026-05-26--d051-retest"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Те же семейства что в D-047, но БЕЗ wt_cross_*_1h
ANCHORS = {
    "D051_L1_hidden": {
        "factors": ["wt_div_bull_hidden_4h", "bull_fvg_4h", "above_ema200_4h"],
        "direction": "LONG",
    },
    "D051_L2_reg": {
        "factors": ["wt_div_bull_reg_4h", "wt_os_4h", "bull_fvg_4h"],
        "direction": "LONG",
    },
    "D051_L3_golden": {
        "factors": ["bull_div_1d", "bull_fvg_4h", "wt_os_4h"],
        "direction": "LONG",
    },
    "D051_S1_hidden": {
        "factors": ["wt_div_bear_hidden_4h", "bear_ob_4h", "below_ema200_4h"],
        "direction": "SHORT",
    },
    "D051_S2_reg": {
        "factors": ["wt_div_bear_reg_4h", "wt_ob_4h", "bear_ob_4h"],
        "direction": "SHORT",
    },
}

MIN_N = 30
MIN_AVG_R = 0.7
MIN_WR = 65.0
TOP_PER_PAIR = 5


def run_anchor(anchor_id: str, anchor_cfg: dict, ltf: str):
    direction = anchor_cfg["direction"]
    cross_dir = "up" if direction == "LONG" else "down"
    pinned = f"wt_cross_{cross_dir}_{ltf}"   # D-051 gate — обязательный LTF фактор

    nested.HTF_CORE = anchor_cfg["factors"]
    nested.LTF = ltf
    nested.HISTORY_LTF_BASE = PROJECT_ROOT / "data" / "history"
    nested.FUTURE_BARS_LTF = {"5m": 144, "15m": 48}[ltf]

    print(f"\n{'='*80}")
    print(f"Якорь: {anchor_id} ({direction})")
    print(f"HTF: {' + '.join(anchor_cfg['factors'])}")
    print(f"Pinned LTF gate: {pinned}")
    print(f"LTF: {ltf}")
    print(f"{'='*80}")

    files = sorted((PROJECT_ROOT / "data" / "history" / ltf).glob("*.parquet"))
    if not files:
        print(f"  Нет LTF данных!")
        return None

    data = {}
    t0 = time.time()
    for path in files:
        res = nested.process_pair(path.stem)
        if res is None:
            continue
        flags, r_long, htf_mask = res
        if direction == "SHORT":
            df_ltf = pd.read_parquet(path)
            df_ltf.columns = [c.lower() for c in df_ltf.columns]
            if "ts" in df_ltf.columns:
                df_ltf["ts"] = pd.to_datetime(df_ltf["ts"], unit="ms", utc=True, errors="coerce")
                df_ltf = df_ltf.set_index("ts")
            df_ltf = df_ltf[["open","high","low","close","volume"]].dropna().sort_index()
            _, r_short = cb.simulate(df_ltf, tp_r=2.0, future=nested.FUTURE_BARS_LTF)
            data[path.stem] = (flags, r_short, htf_mask)
        else:
            data[path.stem] = (flags, r_long, htf_mask)
    print(f"  Пар валидных: {len(data)} | {time.time()-t0:.0f}s")
    if not data:
        return None

    # Проверяем что pinned factor существует в данных
    first_flags = next(iter(data.values()))[0]
    if pinned not in first_flags.columns:
        print(f"  ⚠️  {pinned} не найден в флагах! Доступные wt_cross: "
              f"{[c for c in first_flags.columns if 'wt_cross' in c]}")
        return None

    # Baseline: HTF anchor + только pinned (без доп. LTF)
    baseline = nested.evaluate_nested(data, (pinned,))
    if baseline:
        print(f"  Baseline (HTF+{pinned}): n={baseline['n']} avgR={baseline['avgR']:+.3f} WR={baseline['WR']:.1f}%")
    else:
        print(f"  Baseline (HTF+{pinned}): нет данных (n<{nested.MIN_N})")

    # LTF кандидаты — всё кроме самого pinned
    ALL = list(first_flags.columns)
    if direction == "LONG":
        LTF_POOL = [f for f in ALL if f != pinned and any(s in f for s in [
            "bull_", "ote_long", "discount", "wt_os", "atr_cross_up", "atr_up",
            "eql_sweep", "wt_cross_up", "above_ema", "vol_spike", "rsi_os",
            "rsi_cross50_up", "ema50_above_ema200",
            "pivot_near_S", "pivot_above_PP", "pivot_bounce_up",
            "wt_div_bull", "rsi_div_bull",
        ])]
    else:
        LTF_POOL = [f for f in ALL if f != pinned and any(s in f for s in [
            "bear_", "ote_short", "premium", "wt_ob", "atr_cross_down", "atr_down",
            "eqh_sweep", "wt_cross_down", "below_ema", "vol_spike", "rsi_ob",
            "rsi_cross50_down", "ema50_below_ema200",
            "pivot_near_R", "pivot_below_PP", "pivot_bounce_down",
            "wt_div_bear", "rsi_div_bear",
        ])]
    print(f"  LTF pool (без pinned): {len(LTF_POOL)}")

    results = []
    if baseline:
        baseline.update({"pattern": pinned, "k": 1,
                         "score": baseline["avgR"] * (baseline["WR"]/100) * np.log(max(baseline["n"], 1))})
        results.append(baseline)

    # 1-extra: pinned + 1 доп. фактор
    t1 = time.time()
    for f in LTF_POOL:
        s = nested.evaluate_nested(data, (pinned, f))
        if s:
            s.update({"pattern": f"{pinned} + {f}", "k": 2,
                      "score": s["avgR"] * (s["WR"]/100) * np.log(max(s["n"], 1))})
            results.append(s)
    print(f"  +1f: {sum(1 for r in results if r['k']==2)} | {time.time()-t1:.0f}s")

    # 2-extra: pinned + 2 доп. фактора (из топ-20 по avgR)
    t1 = time.time()
    top1 = sorted([r for r in results if r["k"]==2 and r["avgR"] > 0], key=lambda r: -r["avgR"])[:20]
    pool2 = [r["pattern"].split(" + ")[1] for r in top1]
    for f1, f2 in combinations(pool2, 2):
        s = nested.evaluate_nested(data, (pinned, f1, f2))
        if s:
            s.update({"pattern": " + ".join([pinned, f1, f2]), "k": 3,
                      "score": s["avgR"] * (s["WR"]/100) * np.log(max(s["n"], 1))})
            results.append(s)
    print(f"  +2f: {sum(1 for r in results if r['k']==3)} | {time.time()-t1:.0f}s")

    # 3-extra: pinned + 3 доп. фактора (из топ-10 по score)
    t1 = time.time()
    top3 = sorted([r for r in results if r["k"]==3 and r["avgR"] > 0], key=lambda r: -r["score"])[:10]
    seen = set()
    for r3 in top3:
        parts = [p.strip() for p in r3["pattern"].split("+")]
        extras = [p for p in parts if p != pinned]
        for fnew in pool2:
            if fnew in extras:
                continue
            pat = tuple(sorted([pinned] + extras + [fnew]))
            if pat in seen:
                continue
            seen.add(pat)
            s = nested.evaluate_nested(data, pat)
            if s:
                s.update({"pattern": " + ".join(pat), "k": 4,
                          "score": s["avgR"] * (s["WR"]/100) * np.log(max(s["n"], 1))})
                results.append(s)
    print(f"  +3f: {sum(1 for r in results if r['k']==4)} | {time.time()-t1:.0f}s")

    if not results:
        return None

    df_res = pd.DataFrame([r for r in results])
    df_res = df_res.sort_values("score", ascending=False)
    df_res["anchor_id"] = anchor_id
    df_res["direction"] = direction
    df_res["ltf"] = ltf
    df_res["pinned"] = pinned

    out = OUTPUT_DIR / f"nested_{anchor_id}_{ltf}.csv"
    df_res.to_csv(out, index=False)
    print(f"  → {out.name}  ({len(df_res)} строк)")

    # Топ-5 для вывода
    good = df_res[(df_res["n"] >= MIN_N) & (df_res["avgR"] >= MIN_AVG_R) & (df_res["WR"] >= MIN_WR)]
    print(f"\n  Топ-5 (n≥{MIN_N}, avgR≥{MIN_AVG_R}, WR≥{MIN_WR}%):")
    for _, row in good.head(5).iterrows():
        print(f"    n={int(row['n']):4d} avgR={row['avgR']:+.3f} WR={row['WR']:.1f}%  {row['pattern']}")

    return df_res


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--anchors", nargs="*", help="Только эти якоря (по умолчанию все)")
    parser.add_argument("--ltf", choices=["5m", "15m", "both"], default="both")
    args = parser.parse_args()

    anchors_to_run = {k: v for k, v in ANCHORS.items()
                      if not args.anchors or k in args.anchors}
    ltfs = ["5m", "15m"] if args.ltf == "both" else [args.ltf]

    print(f"D-051 T8 Retest — {len(anchors_to_run)} якорей × {len(ltfs)} LTF")
    print(f"Гипотеза: убрать wt_cross_*_1h из HTF, добавить wt_cross_*_{{ltf}} как gate")
    print(f"Output: {OUTPUT_DIR}\n")

    all_results = []
    t_total = time.time()
    for anchor_id, anchor_cfg in anchors_to_run.items():
        for ltf in ltfs:
            df = run_anchor(anchor_id, anchor_cfg, ltf)
            if df is not None:
                all_results.append(df)

    if all_results:
        combined = pd.concat(all_results, ignore_index=True)
        good = combined[
            (combined["n"] >= MIN_N) &
            (combined["avgR"] >= MIN_AVG_R) &
            (combined["WR"] >= MIN_WR)
        ].sort_values("score", ascending=False)

        print(f"\n{'='*80}")
        print(f"ИТОГ D-051 RETEST | {len(anchors_to_run)} якорей | {len(ltfs)} TF")
        print(f"Кандидатов (n≥{MIN_N}, avgR≥{MIN_AVG_R}R, WR≥{MIN_WR}%): {len(good)}")
        print(f"{'='*80}")
        print(f"\n=== Топ-10 LONG ===")
        for _, row in good[good["direction"]=="LONG"].head(10).iterrows():
            print(f"  n={int(row['n']):4d} avgR={row['avgR']:+.3f} WR={row['WR']:.1f}%  "
                  f"[{row['anchor_id']} {row['ltf']}]  {row['pattern']}")
        print(f"\n=== Топ-5 SHORT ===")
        for _, row in good[good["direction"]=="SHORT"].head(5).iterrows():
            print(f"  n={int(row['n']):4d} avgR={row['avgR']:+.3f} WR={row['WR']:.1f}%  "
                  f"[{row['anchor_id']} {row['ltf']}]  {row['pattern']}")

        # Сравнение с D-047
        print(f"\n=== Сравнение с D-047 ===")
        print(f"  D-047 (с wt_cross_up_1h в anchor):   топ LONG n=48 avgR=+1.94 WR=97.9%")
        if len(good[good["direction"]=="LONG"]) > 0:
            best = good[good["direction"]=="LONG"].iloc[0]
            print(f"  D-051 (wt_cross_up_{{ltf}} как gate): топ LONG n={int(best['n'])} avgR={best['avgR']:+.3f} WR={best['WR']:.1f}%")

    print(f"\nВсего: {time.time()-t_total:.0f}s")


if __name__ == "__main__":
    main()
