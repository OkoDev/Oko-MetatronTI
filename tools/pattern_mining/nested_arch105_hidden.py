"""ARCH-105 nested walkforward: hidden divergence как HTF anchors.

Anchors предложены роем (mistral+cerebras lead, 2026-05-22):

LONG continuation:
  A1_bull_hidden_4h:  wt_div_bull_hidden_4h + bull_fvg_4h + above_ema200_4h
  A2_bull_reg_4h:     wt_div_bull_reg_4h + wt_os_4h + bull_fvg_4h          (reversal sanity)

SHORT continuation:
  A3_bear_hidden_4h:  wt_div_bear_hidden_4h + bear_ob_4h + below_ema200_4h
  A4_bear_reg_4h:     wt_div_bear_reg_4h + wt_ob_4h + bear_ob_4h           (reversal sanity)

LTF: 5m, 15m
Output: data/research/2026-05-22--arch105/nested_<anchor>_<ltf>.csv
"""
from __future__ import annotations

import sys
import time
import warnings
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
from _run_registry import register_run
import combinator_v2 as cb
import combinator_v3_nested as nested

PROJECT_ROOT = Path("E:/MTF BOT/CURSOR/crypto_volume_bot")
OUTPUT_DIR = PROJECT_ROOT / "data" / "research" / "2026-05-22--arch105"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


ANCHORS = {
    "A1_bull_hidden_4h": {
        "factors": ["wt_div_bull_hidden_4h", "bull_fvg_4h", "above_ema200_4h"],
        "direction": "LONG",
    },
    "A2_bull_reg_4h": {
        "factors": ["wt_div_bull_reg_4h", "wt_os_4h", "bull_fvg_4h"],
        "direction": "LONG",
    },
    "A3_bear_hidden_4h": {
        "factors": ["wt_div_bear_hidden_4h", "bear_ob_4h", "below_ema200_4h"],
        "direction": "SHORT",
    },
    "A4_bear_reg_4h": {
        "factors": ["wt_div_bear_reg_4h", "wt_ob_4h", "bear_ob_4h"],
        "direction": "SHORT",
    },
}


def run_anchor(anchor_id: str, anchor_cfg: dict, ltf: str):
    nested.HTF_CORE = anchor_cfg["factors"]
    nested.LTF = ltf
    nested.HISTORY_LTF_BASE = PROJECT_ROOT / "data" / "history"
    nested.FUTURE_BARS_LTF = {"5m": 144, "15m": 48}[ltf]

    direction = anchor_cfg["direction"]
    print(f"\n{'='*80}")
    print(f"Якорь: {anchor_id} ({direction})")
    print(f"Факторы: {' + '.join(anchor_cfg['factors'])}")
    print(f"LTF: {ltf}")
    print(f"{'='*80}")

    files = sorted((PROJECT_ROOT / "data" / "history" / ltf).glob("*.parquet"))
    if not files:
        return None

    data = {}
    t0 = time.time()
    for path in files:
        res = nested.process_pair(path.stem)
        if res is None: continue
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

    first = next(iter(data.values()))[0]
    ALL = list(first.columns)

    if direction == "LONG":
        LTF_F = [f for f in ALL if any(s in f for s in [
            "bull_", "ote_long", "discount", "wt_os", "atr_cross_up", "atr_up",
            "eql_sweep", "wt_cross_up", "above_ema", "vol_spike", "rsi_os",
            "rsi_cross50_up", "ema50_above_ema200",
            "pivot_near_S", "pivot_above_PP", "pivot_bounce_up",
            "wt_div_bull", "rsi_div_bull",
        ])]
    else:
        LTF_F = [f for f in ALL if any(s in f for s in [
            "bear_", "ote_short", "premium", "wt_ob", "atr_cross_down", "atr_down",
            "eqh_sweep", "wt_cross_down", "below_ema", "vol_spike", "rsi_ob",
            "rsi_cross50_down", "ema50_below_ema200",
            "pivot_near_R", "pivot_below_PP", "pivot_bounce_down",
            "wt_div_bear", "rsi_div_bear",
        ])]
    print(f"  LTF факторов ({direction}): {len(LTF_F)}")

    results = []
    t1 = time.time()
    for f in LTF_F:
        s = nested.evaluate_nested(data, (f,))
        if s:
            s.update({"pattern": f, "k": 1, "score": s["avgR"] * (s["WR"]/100) * np.log(s["n"])})
            results.append(s)
    print(f"  1f: {sum(1 for r in results if r['k']==1)} | {time.time()-t1:.0f}s")

    t1 = time.time()
    for f1, f2 in combinations(LTF_F, 2):
        s = nested.evaluate_nested(data, (f1, f2))
        if s:
            s.update({"pattern": " + ".join([f1, f2]), "k": 2,
                      "score": s["avgR"] * (s["WR"]/100) * np.log(s["n"]), "_factors": (f1, f2)})
            results.append(s)
    print(f"  2f: {sum(1 for r in results if r['k']==2)} | {time.time()-t1:.0f}s")

    t1 = time.time()
    top1 = sorted([r for r in results if r["k"]==1 and r["avgR"] > 0], key=lambda r: -r["avgR"])[:25]
    pool = [r["pattern"] for r in top1]
    for f1, f2, f3 in combinations(pool, 3):
        s = nested.evaluate_nested(data, (f1, f2, f3))
        if s:
            s.update({"pattern": " + ".join([f1, f2, f3]), "k": 3,
                      "score": s["avgR"] * (s["WR"]/100) * np.log(s["n"]), "_factors": (f1, f2, f3)})
            results.append(s)
    print(f"  3f: {sum(1 for r in results if r['k']==3)} | {time.time()-t1:.0f}s")

    t1 = time.time()
    top3 = sorted([r for r in results if r["k"]==3 and r["avgR"] > 0], key=lambda r: -r["score"])[:15]
    seen = set()
    for r3 in top3:
        base = r3["_factors"]
        for fnew in LTF_F:
            if fnew in base: continue
            pat = tuple(sorted(list(base) + [fnew]))
            if pat in seen: continue
            seen.add(pat)
            s = nested.evaluate_nested(data, pat)
            if s:
                s.update({"pattern": " + ".join(pat), "k": 4,
                          "score": s["avgR"] * (s["WR"]/100) * np.log(s["n"]), "_factors": pat})
                results.append(s)
    print(f"  4f: {sum(1 for r in results if r['k']==4)} | {time.time()-t1:.0f}s")

    if not results:
        return None

    df_res = pd.DataFrame([{k: v for k, v in r.items() if not k.startswith("_")} for r in results])
    df_res = df_res.sort_values("score", ascending=False)
    df_res["anchor_id"] = anchor_id
    df_res["direction"] = direction
    df_res["ltf"] = ltf

    out = OUTPUT_DIR / f"nested_{anchor_id}_{ltf}.csv"
    df_res.to_csv(out, index=False, encoding="utf-8")
    print(f"  ✅ Сохранено: {out.name} ({len(df_res)} паттернов)")

    print(f"\n  ТОП-5 ({anchor_id} × {ltf}):")
    for _, r in df_res.head(5).iterrows():
        pat = r["pattern"][:75] + ("…" if len(r["pattern"]) > 75 else "")
        print(f"    n={int(r['n']):>5} avgR={r['avgR']:>+.3f} WR={r['WR']:>4.1f}%  {pat}")

    return out


def main():
    with register_run("nested_arch105_hidden", params={"anchors": list(ANCHORS.keys()), "ltfs": ["15m", "5m"]}) as run:
        for anchor_id, anchor_cfg in ANCHORS.items():
            for ltf in ["15m", "5m"]:
                out = run_anchor(anchor_id, anchor_cfg, ltf)
                if out:
                    run.add_output(out)
        print("\n\n✅ ARCH-105 nested COMPLETED")


if __name__ == "__main__":
    main()
