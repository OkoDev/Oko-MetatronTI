"""
SMC + ALL INDICATORS Pattern Mining v2.

Добавлены:
- MTF Pivots (1D/1W) — 7 уровней (R3..S3), флаги: near/above/below + bounce
- RSI (на каждом TF) — OS/OB зоны + cross
- Bullish/Bearish divergence (RSI и WT)
- Trend regime (TREND_UP / TREND_DOWN / RANGE по ATR + EMA slope)
- BTC correlation context (опционально)

Pattern Mining через greedy hill-climbing:
- 1f: все
- 2f: все
- 3f: top-40 1f
- 4f: top-30 3f + 1 фактор
- 5f: top-20 4f + 1 фактор

Запуск: python e:/tmp/smc_combinator_v2.py
"""
import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from pathlib import Path
# ARCH-128 (DS-313): bridge импортирует core.smc.smc_engine + tools.pattern_mining (абсолютные) →
# нужен КОРЕНЬ проекта в sys.path, иначе CLI-скрипты pattern_mining падают «No module named tools/core».
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from itertools import combinations
import pandas as pd
import numpy as np

HISTORY_DIR = Path("E:/MTF BOT/CURSOR/crypto_volume_bot/data/history/1h")
TP_R        = 2.0
FUTURE_BARS = 12
MIN_N       = 50
TOP_1F = 40
TOP_3F = 30
TOP_4F = 20

# ARCH-118.3 (05.06): ЕДИНЫЙ калькулятор вынесен в core/calculators/combinator_core.py
# (bit-identity live≡backtest, без stdout-hijack/HISTORY_DIR side-effects). CLI-mining ниже
# импортирует ОТСЮДА. Запрет дублировать формулы — только потребление core.
from core.calculators.combinator_core import (
    wavetrend, rsi, atr_supertrend, calc_pivots, add_pivot_flags,
    _wtx_divergences, _pivot_indices, _calc_divergence, compute_flags, aggregate_tf,
    ATR_PERIOD, ATR_FACTOR, WT_OS, WT_OB, RSI_OS, RSI_OB,
    DIV_PIVOT_PRD, DIV_MAX_PP, DIV_MAX_BARS,
)


def simulate(df: pd.DataFrame, tp_r: float = TP_R, future: int = FUTURE_BARS):
    n = len(df)
    high = df["high"].values; low = df["low"].values; close = df["close"].values
    r_long  = np.full(n, np.nan)
    r_short = np.full(n, np.nan)
    for i in range(20, n - future - 1):
        price = close[i]
        sl_l = low[i-10:i+1].min() * 0.999
        sld = price - sl_l
        if sld > 0 and sld/price < 0.06:
            tp = price + sld*tp_r
            fh = high[i+1:i+1+future]; fl = low[i+1:i+1+future]
            ht = (fh >= tp); hs = (fl <= sl_l)
            if ht.any() and hs.any():
                r_long[i] = tp_r if np.argmax(ht) <= np.argmax(hs) else -1.0
            elif ht.any(): r_long[i] = tp_r
            elif hs.any(): r_long[i] = -1.0
            else:          r_long[i] = (close[i+future]-price)/sld
        sl_s = high[i-10:i+1].max() * 1.001
        sld_s = sl_s - price
        if sld_s > 0 and sld_s/price < 0.06:
            tp = price - sld_s*tp_r
            fh = high[i+1:i+1+future]; fl = low[i+1:i+1+future]
            ht = (fl <= tp); hs = (fh >= sl_s)
            if ht.any() and hs.any():
                r_short[i] = tp_r if np.argmax(ht) <= np.argmax(hs) else -1.0
            elif ht.any(): r_short[i] = tp_r
            elif hs.any(): r_short[i] = -1.0
            else:          r_short[i] = (price-close[i+future])/sld_s
    return r_long, r_short


def process_symbol(path: Path):
    try:
        df_1h = pd.read_parquet(path)
        df_1h.columns = [c.lower() for c in df_1h.columns]
        if "ts" in df_1h.columns:
            try:
                df_1h["ts"] = pd.to_datetime(df_1h["ts"], unit="ms", utc=True)
            except Exception:
                df_1h["ts"] = pd.to_datetime(df_1h["ts"], utc=True, errors="coerce")
            df_1h = df_1h.set_index("ts")
        df_1h = df_1h[["open","high","low","close","volume"]].dropna().sort_index()
        if len(df_1h) < 200: return None
        df_4h = aggregate_tf(df_1h, "4h")
        df_1d = aggregate_tf(df_1h, "1d")
        if len(df_4h) < 50 or len(df_1d) < 30: return None
        f_1h = compute_flags(df_1h, "1h", include_pivots=True)
        # Lookahead fix: HTF индекс на конец периода (только после close)
        f_4h_raw = compute_flags(df_4h, "4h")
        f_4h_raw.index = f_4h_raw.index + pd.Timedelta(hours=4)
        f_4h = f_4h_raw.reindex(df_1h.index, method="ffill").fillna(False)
        f_1d_raw = compute_flags(df_1d, "1d")
        f_1d_raw.index = f_1d_raw.index + pd.Timedelta(days=1)
        f_1d = f_1d_raw.reindex(df_1h.index, method="ffill").fillna(False)
        all_flags = pd.concat([f_1h, f_4h, f_1d], axis=1).astype(bool)
        r_long, r_short = simulate(df_1h)
        return all_flags, r_long, r_short
    except Exception as e:
        print(f"  ERR {path.stem}: {e}")
        return None


# ───────── Combinator engine ─────────
def evaluate(flags_dict, factors: tuple, direction: str):
    all_rs = []
    for _, (flags, r_long, r_short) in flags_dict.items():
        mask = np.ones(len(flags), dtype=bool)
        for f in factors:
            if f not in flags.columns: return None
            mask &= flags[f].values
        if not mask.any(): continue
        rs = r_long if direction == "LONG" else r_short
        rs_valid = rs[mask & ~np.isnan(rs)]
        if len(rs_valid):
            all_rs.extend(rs_valid)
    if len(all_rs) < MIN_N: return None
    arr = np.array(all_rs)
    return {"n": len(arr), "avgR": float(arr.mean()), "sumR": float(arr.sum()),
            "WR": float((arr > 0).mean()*100), "stdR": float(arr.std())}


def score_fn(stats):
    return stats["avgR"] * (stats["WR"]/100) * np.log(stats["n"]) if stats else -999


# ───────── Main ─────────
def main():
    files = sorted(HISTORY_DIR.glob("*.parquet"))
    print(f"Найдено parquet: {len(files)}")
    if not files: return

    print(f"\n[1] Загрузка {len(files)} пар + SMC + Pivots + RSI...")
    t0 = time.time()
    flags_dict = {}
    for path in files:
        res = process_symbol(path)
        if res is None: continue
        flags_dict[path.stem] = res
        if len(flags_dict) % 5 == 0:
            print(f"  ...{len(flags_dict)}/{len(files)} ({time.time()-t0:.0f}с)")
    print(f"  Готово за {time.time()-t0:.0f}с. Пар: {len(flags_dict)}")
    if not flags_dict: return

    first = next(iter(flags_dict.values()))[0]
    ALL = list(first.columns)
    print(f"  Всего флагов: {len(ALL)}")

    LONG_F = [f for f in ALL if any(s in f for s in [
        "bull_","ote_long","discount","wt_os","atr_cross_up","atr_up",
        "eql_sweep","wt_cross_up","above_ema","vol_spike","rsi_os","rsi_cross50_up",
        "ema50_above_ema200","pivot_bounce_up","pivot_near_S","pivot_above_PP"
    ])]
    SHORT_F = [f for f in ALL if any(s in f for s in [
        "bear_","ote_short","premium","wt_ob","atr_cross_down","atr_down",
        "eqh_sweep","wt_cross_down","below_ema","vol_spike","rsi_ob","rsi_cross50_down",
        "ema50_below_ema200","pivot_bounce_down","pivot_near_R","pivot_below_PP"
    ])]
    print(f"  LONG: {len(LONG_F)}, SHORT: {len(SHORT_F)}")

    results = []

    print(f"\n[2] 1-факторные...")
    t1 = time.time()
    for direction, factors in [("LONG", LONG_F), ("SHORT", SHORT_F)]:
        for f in factors:
            s = evaluate(flags_dict, (f,), direction)
            if s:
                s.update({"pattern": f, "direction": direction, "k": 1, "score": score_fn(s)})
                results.append(s)
    print(f"  → {sum(1 for r in results if r['k']==1)} ({time.time()-t1:.0f}с)")

    print(f"\n[3] 2-факторные...")
    t1 = time.time()
    for direction, factors in [("LONG", LONG_F), ("SHORT", SHORT_F)]:
        for f1, f2 in combinations(factors, 2):
            s = evaluate(flags_dict, (f1, f2), direction)
            if s:
                s.update({"pattern": " + ".join([f1,f2]), "direction": direction, "k": 2,
                         "score": score_fn(s), "_factors": (f1, f2)})
                results.append(s)
    print(f"  → {sum(1 for r in results if r['k']==2)} ({time.time()-t1:.0f}с)")

    print(f"\n[4] 3-факторные (топ-{TOP_1F} 1f)...")
    t1 = time.time()
    for direction in ["LONG", "SHORT"]:
        top1 = sorted([r for r in results if r["k"]==1 and r["direction"]==direction and r["avgR"] > 0], key=lambda r: -r["avgR"])[:TOP_1F]
        pool = [r["pattern"] for r in top1]
        for f1, f2, f3 in combinations(pool, 3):
            s = evaluate(flags_dict, (f1, f2, f3), direction)
            if s:
                s.update({"pattern": " + ".join([f1,f2,f3]), "direction": direction, "k": 3,
                         "score": score_fn(s), "_factors": (f1, f2, f3)})
                results.append(s)
    print(f"  → {sum(1 for r in results if r['k']==3)} ({time.time()-t1:.0f}с)")

    print(f"\n[5] 4-факторные (топ-{TOP_3F} 3f + 1 фактор)...")
    t1 = time.time()
    for direction, factors in [("LONG", LONG_F), ("SHORT", SHORT_F)]:
        top3 = sorted([r for r in results if r["k"]==3 and r["direction"]==direction and r["avgR"] > 0], key=lambda r: -r["score"])[:TOP_3F]
        seen = set()
        for r3 in top3:
            base = r3["_factors"]
            for fnew in factors:
                if fnew in base: continue
                pat = tuple(sorted(list(base) + [fnew]))
                if pat in seen: continue
                seen.add(pat)
                s = evaluate(flags_dict, pat, direction)
                if s:
                    s.update({"pattern": " + ".join(pat), "direction": direction, "k": 4,
                             "score": score_fn(s), "_factors": pat})
                    results.append(s)
    print(f"  → {sum(1 for r in results if r['k']==4)} ({time.time()-t1:.0f}с)")

    print(f"\n[6] 5-факторные (топ-{TOP_4F} 4f + 1 фактор)...")
    t1 = time.time()
    for direction, factors in [("LONG", LONG_F), ("SHORT", SHORT_F)]:
        top4 = sorted([r for r in results if r["k"]==4 and r["direction"]==direction and r["avgR"] > 0], key=lambda r: -r["score"])[:TOP_4F]
        seen = set()
        for r4 in top4:
            base = r4["_factors"]
            for fnew in factors:
                if fnew in base: continue
                pat = tuple(sorted(list(base) + [fnew]))
                if pat in seen: continue
                seen.add(pat)
                s = evaluate(flags_dict, pat, direction)
                if s:
                    s.update({"pattern": " + ".join(pat), "direction": direction, "k": 5,
                             "score": score_fn(s), "_factors": pat})
                    results.append(s)
    print(f"  → {sum(1 for r in results if r['k']==5)} ({time.time()-t1:.0f}с)")

    print(f"\n{'='*110}")
    print(f"ВСЕГО ПАТТЕРНОВ: {len(results)}  |  пар: {len(flags_dict)}  |  TP={TP_R}R  |  fut: {FUTURE_BARS}h  |  min n={MIN_N}")
    print(f"{'='*110}")

    print(f"\n=== ТОП-30 ВСЕХ паттернов ===")
    print(f"{'#':<3} {'k':<2} {'dir':<5} {'n':>6} {'avgR':>7} {'WR%':>6} {'sumR':>9} {'score':>7}  pattern")
    print("-"*110)
    for i, r in enumerate(sorted(results, key=lambda r: -r["score"])[:30], 1):
        pat = r["pattern"][:60] + ("…" if len(r["pattern"])>60 else "")
        print(f"{i:<3} {r['k']:<2} {r['direction']:<5} {r['n']:>6} {r['avgR']:>+7.3f} {r['WR']:>5.1f}% {r['sumR']:>+9.1f} {r['score']:>+7.3f}  {pat}")

    for k in [1,2,3,4,5]:
        for d in ["LONG","SHORT"]:
            top = sorted([r for r in results if r["k"]==k and r["direction"]==d], key=lambda r: -r["score"])[:8]
            if not top: continue
            print(f"\n=== ТОП-8 {k}-факторных {d} ===")
            for r in top:
                pat = r["pattern"][:80] + ("…" if len(r["pattern"])>80 else "")
                print(f"  n={r['n']:>5} avgR={r['avgR']:>+.3f} WR={r['WR']:>4.1f}% sumR={r['sumR']:>+7.1f}  {pat}")

    out = Path("e:/tmp/smc_combinator_v2_results.csv")
    df_res = pd.DataFrame([{k:v for k,v in r.items() if not k.startswith("_")} for r in results])
    df_res = df_res.sort_values("score", ascending=False)
    df_res.to_csv(out, index=False, encoding="utf-8")
    print(f"\nПолный CSV: {out}  ({len(df_res)} строк)")


if __name__ == "__main__":
    main()
