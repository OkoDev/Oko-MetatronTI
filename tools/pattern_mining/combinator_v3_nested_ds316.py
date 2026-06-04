"""
Nested LTF Combinator v3.

Идея: используем ЗОЛОТОЙ HTF паттерн как РЕЖИМ (когда смотреть), а LTF
факторы (5m/15m) — как ТРИГГЕРЫ ВХОДА (когда нажимать кнопку).

HTF контекст (фиксированное ядро):
  bull_div_1d AND bull_fvg_4h AND wt_os_4h

LTF триггеры (перебираем все 1f → 5f):
  WT OS/cross_up на 5m/15m
  Bull FVG/OB/CHoCH/BOS на 5m/15m
  ATR cross UP на 5m/15m
  OTE/discount на 5m/15m
  RSI OS/cross50 на 5m/15m
  Volume spike, momentum на 5m/15m
  Pivot bounce на 1D pivots (применимы к LTF тоже)

Цель: получить МНОГО точек входа (сотни-тысячи) внутри HTF режима,
которые сохраняют WR>70% при TP=2R.

Запуск:
  python tools/pattern_mining/combinator_v3_nested.py [5m|15m]  (default: 15m)
"""
import sys, time, warnings
warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from pathlib import Path
from itertools import combinations
import pandas as pd
import numpy as np

# Импорты из combinator_v2 для compute_flags + indicators
sys.path.insert(0, str(Path(__file__).parent))
import combinator_v2 as cb

PROJECT_ROOT = Path("E:/MTF BOT/CURSOR/crypto_volume_bot")
HISTORY_1H = PROJECT_ROOT / "data/history/1h"
HISTORY_LTF_BASE = PROJECT_ROOT / "data/history"

LTF      = sys.argv[1] if len(sys.argv) > 1 else "15m"
TP_R     = 2.0
MIN_N    = 30
WT_OS    = -60

# Будущие бары LTF для симуляции (целимся в 6-12 часов)
FUTURE_BARS_LTF = {"5m": 144, "15m": 48, "30m": 24}[LTF]

# ── DS-316: МЯГКИЙ HTF контекст (зоны/тренды, не редкие события) ──
# Контекст применяется как активное окно: флаг расширяется на +-ACTIVE_WINDOW баров
ACTIVE_WINDOW = 2  # HTF флаг "живёт" +-2 бара

# Набор МЯГКИХ HTF-контекстов (LONG + SHORT) — зоны и тренды
HTF_CONTEXTS = {
    "LONG": [
        ["bull_fvg_1h", "bull_fvg_4h"],           # FVG зона (persistent)
        ["bull_fvg_1h", "discount_1h"],            # FVG + discount зона
        ["bull_fvg_4h", "atr_up_4h"],              # FVG + тренд
        ["bull_fvg_1h", "atr_up_1h", "discount_1h"],  # FVG + тренд + зона
        ["bull_fvg_4h", "discount_4h"],
        ["atr_up_1h", "discount_1h"],              # Только тренд + зона
    ],
    "SHORT": [
        ["bear_fvg_1h", "bear_fvg_4h"],
        ["bear_fvg_1h", "premium_1h"],
        ["bear_fvg_4h", "atr_down_4h"],
        ["bear_fvg_1h", "atr_down_1h", "premium_1h"],
        ["bear_fvg_4h", "premium_4h"],
        ["atr_down_1h", "premium_1h"],
    ],
}

# Greedy pruning
TOP_1F = 30
TOP_3F = 25
TOP_4F = 15
TOP_5F = 10

# ── DS-318: Комбо hidden_HTF + regular_LTF ───────────────────────────
DIV_COMBO_PAIRS = [("4h","15m"),("4h","5m"),("1h","15m"),("1h","5m")]
DIV_TYPES = ["wt_div", "rsi_div"]
DIV_DIRS = ["bull", "bear"]


def add_divergence_combos(ltf_flags, htf_flags, ltf_idx, ltf_label: str, htf_label: str):
    """DS-318: hidden_HTF & regular_LTF комбо-флаги в ltf_flags."""
    for dt in DIV_TYPES:
        for d in DIV_DIRS:
            htf_col = f"{dt}_{d}_hidden_{htf_label}"
            ltf_col = f"{dt}_{d}_regular_{ltf_label}"
            if htf_col not in htf_flags.columns or ltf_col not in ltf_flags.columns:
                continue
            htf_s = htf_flags[htf_col].reindex(ltf_idx, method="ffill").fillna(False).astype(bool)
            combo = f"{dt}_{d}_hidden{htf_label}_regular{ltf_label}"
            ltf_flags[combo] = htf_s.values & ltf_flags[ltf_col].values
    return ltf_flags


def compute_context_masks(path_1h: Path) -> dict:
    """
    Загружает 1h данные, считает МЯГКИЕ HTF контексты с активным окном.
    Возвращает dict: {(direction, context_idx): mask Series}
    """
    res = cb.process_symbol(path_1h)
    if res is None:
        return {}
    flags, _, _ = res
    masks = {}
    for direction in ["LONG", "SHORT"]:
        for ci, factors in enumerate(HTF_CONTEXTS[direction]):
            # Проверить что все факторы есть
            if not all(f in flags.columns for f in factors):
                continue
            # Base mask: все факторы True
            mask = pd.Series(True, index=flags.index)
            for f in factors:
                mask &= flags[f]
            # Активное окно: расширить на +-ACTIVE_WINDOW баров
            if mask.any() and ACTIVE_WINDOW > 0:
                mask = mask.rolling(window=2*ACTIVE_WINDOW+1, center=True, min_periods=1).max().astype(bool)
            masks[(direction, ci)] = mask
    return masks


def compute_ltf_flags(df_ltf: pd.DataFrame, label: str) -> pd.DataFrame:
    """SMC + индикаторы на LTF + пивоты 1D/1W (статические уровни)."""
    return cb.compute_flags(df_ltf, label, include_pivots=True)


def simulate_ltf(df: pd.DataFrame, tp_r: float, future: int, direction: str = "LONG"):
    """LONG и SHORT симуляция на LTF."""
    n = len(df)
    high = df["high"].values; low = df["low"].values; close = df["close"].values
    r = np.full(n, np.nan)
    for i in range(20, n - future - 1):
        price = close[i]
        if direction == "LONG":
            sl = low[i-10:i+1].min() * 0.999
            sld = price - sl
            if sld <= 0 or sld/price > 0.06: continue
            tp = price + sld*tp_r
            fh = high[i+1:i+1+future]; fl = low[i+1:i+1+future]
        else:  # SHORT
            sl = high[i-10:i+1].max() * 1.001
            sld = sl - price
            if sld <= 0 or sld/price > 0.06: continue
            tp = price - sld*tp_r
            fh = high[i+1:i+1+future]; fl = low[i+1:i+1+future]
        ht = (fh >= tp) if direction == "LONG" else (fl <= tp)
        hs = (fl <= sl) if direction == "LONG" else (fh >= sl)
        if ht.any() and hs.any():
            r[i] = tp_r if np.argmax(ht) <= np.argmax(hs) else -1.0
        elif ht.any(): r[i] = tp_r
        elif hs.any(): r[i] = -1.0
        else: r[i] = (close[i+future]-price)/sld
    return r


def process_pair(symbol: str) -> list:
    """Возвращает список (direction, ltf_flags_df, r_sim, htf_mask_on_ltf) для каждого живого контекста."""
    path_1h = HISTORY_1H / f"{symbol}.parquet"
    path_ltf = HISTORY_LTF_BASE / LTF / f"{symbol}.parquet"
    if not path_1h.exists() or not path_ltf.exists():
        return []

    try:
        # HTF контексты
        context_masks = compute_context_masks(path_1h)
        if not context_masks:
            return []

        # LTF данные
        df_ltf = pd.read_parquet(path_ltf)
        df_ltf.columns = [c.lower() for c in df_ltf.columns]
        if "ts" in df_ltf.columns:
            df_ltf["ts"] = pd.to_datetime(df_ltf["ts"], unit="ms", utc=True, errors="coerce")
            df_ltf = df_ltf.set_index("ts")
        df_ltf = df_ltf[["open","high","low","close","volume"]].dropna().sort_index()
        if len(df_ltf) < 500:
            return []

        # LTF SMC + индикаторы
        ltf_flags = compute_ltf_flags(df_ltf, LTF)

        # ── DS-318: hidden_HTF + regular_LTF комбо ──
        for htf_label in ["4h", "1h"]:
            path_htf = HISTORY_LTF_BASE / htf_label / f"{symbol}.parquet"
            if path_htf.exists():
                df_htf = pd.read_parquet(path_htf)
                df_htf.columns = [c.lower() for c in df_htf.columns]
                if "ts" in df_htf.columns:
                    df_htf["ts"] = pd.to_datetime(df_htf["ts"], unit="ms", utc=True, errors="coerce")
                    df_htf = df_htf.set_index("ts")
                df_htf = df_htf[["open","high","low","close","volume"]].dropna().sort_index()
                if len(df_htf) >= 200:
                    htf_flags = compute_ltf_flags(df_htf, htf_label)
                    ltf_flags = add_divergence_combos(ltf_flags, htf_flags, df_ltf.index, LTF, htf_label)

        results = []
        for (direction, ci), htf_mask_1h in context_masks.items():
            if not htf_mask_1h.any():
                continue
            # HTF mask reindex на LTF (lookahead-safe: +1h)
            htf_mask_shifted = htf_mask_1h.copy()
            htf_mask_shifted.index = htf_mask_shifted.index + pd.Timedelta(hours=1)
            htf_on_ltf = htf_mask_shifted.reindex(df_ltf.index, method="ffill").fillna(False).astype(bool)
            if not htf_on_ltf.any():
                continue
            r_sim = simulate_ltf(df_ltf, TP_R, FUTURE_BARS_LTF, direction)
            results.append((direction, ltf_flags, r_sim, htf_on_ltf.values))
        return results

    except Exception as e:
        return []


def evaluate_nested(data: dict, factors: tuple, direction: str):
    """factors = LTF факторы для указанного direction."""
    all_rs = []
    for key, entries in data.items():
        for dir_, flags, r_sim, htf_mask in entries:
            if dir_ != direction:
                continue
            mask = htf_mask.copy()
            for f in factors:
                if f not in flags.columns:
                    return None
                mask &= flags[f].values
            if not mask.any():
                continue
            rs_valid = r_sim[mask & ~np.isnan(r_sim)]
            if len(rs_valid):
                all_rs.extend(rs_valid)
    if len(all_rs) < MIN_N:
        return None
    arr = np.array(all_rs)
    return {"n": len(arr), "avgR": float(arr.mean()), "sumR": float(arr.sum()),
            "WR": float((arr > 0).mean()*100), "stdR": float(arr.std())}


def score_fn(stats):
    return stats["avgR"] * (stats["WR"]/100) * np.log(stats["n"]) if stats else -999


def main():
    files = sorted((HISTORY_LTF_BASE / LTF).glob("*.parquet"))
    print(f"LTF: {LTF}  |  TP: {TP_R}R  |  Future: {FUTURE_BARS_LTF} баров  |  MIN_N: {MIN_N}")
    print(f"DS-316 SOFT HTF (6 контекстов LONG + 6 SHORT)  |  Active window +-{ACTIVE_WINDOW} bars")
    print(f"\nLTF parquet файлов: {len(files)}")
    if not files:
        print(f"Нет LTF данных в {HISTORY_LTF_BASE / LTF}. Сначала запусти fetch_ltf_parallel.py")
        return

    print(f"\n[1] Загрузка пар + HTF контексты + LTF флаги...")
    t0 = time.time()
    data = {}
    for path in files:
        sym = path.stem
        entries = process_pair(sym)
        if entries:
            data[sym] = entries
        if len(data) % 5 == 0:
            print(f"  ...{len(data)}/{len(files)} ({time.time()-t0:.0f}с)")
    total_contexts = sum(len(v) for v in data.values())
    print(f"  Готово за {time.time()-t0:.0f}с. Пар: {len(data)}, контекстов: {total_contexts}")

    if not data:
        print("Нет валидных данных."); return

    # Все LTF факторы (общие для LONG/SHORT)
    first_entry = next(iter(data.values()))[0]
    first_flags = first_entry[1]
    ALL_LTF = list(first_flags.columns)
    LONG_FACTORS = [f for f in ALL_LTF if any(s in f for s in [
        "bull_", "ote_long", "discount", "wt_os", "atr_cross_up", "atr_up",
        "eql_sweep", "wt_cross_up", "above_ema", "vol_spike", "rsi_os",
        "rsi_cross50_up", "ema50_above_ema200",
        "pivot_near_S", "pivot_above_PP", "pivot_bounce_up"
    ])]
    SHORT_FACTORS = [f for f in ALL_LTF if any(s in f for s in [
        "bear_", "ote_short", "premium", "wt_ob", "atr_cross_down", "atr_down",
        "eqh_sweep", "wt_cross_down", "below_ema", "vol_spike", "rsi_ob",
        "rsi_cross50_down", "ema50_below_ema200",
        "pivot_near_R", "pivot_below_PP", "pivot_bounce_down"
    ])]

    results = []

    for DIRECTION, FACTORS in [("LONG", LONG_FACTORS), ("SHORT", SHORT_FACTORS)]:
        # Baseline (только HTF контекст, без LTF фильтра)
        baseline = evaluate_nested(data, tuple(), DIRECTION)
        if baseline:
            print(f"\n  [{DIRECTION}] Baseline (HTF contexts only): n={baseline['n']} avgR={baseline['avgR']:+.3f} WR={baseline['WR']:.1f}% sumR={baseline['sumR']:+.1f}R")
        else:
            print(f"\n  [{DIRECTION}] Baseline: недостаточно сделок")

        print(f"  LTF {DIRECTION} факторов: {len(FACTORS)}")

        # 1-факторные
        print(f"\n[{DIRECTION}] 1-факторные LTF...")
        t1 = time.time()
        for f in FACTORS:
            s = evaluate_nested(data, (f,), DIRECTION)
            if s:
                s.update({"pattern": f, "k": 1, "direction": DIRECTION, "score": score_fn(s)})
                results.append(s)
        print(f"  -> 1f: {sum(1 for r in results if r['direction']==DIRECTION and r['k']==1)} ({time.time()-t1:.0f}с)")

        # 2-факторные
        print(f"[{DIRECTION}] 2-факторные...")
        t1 = time.time()
        for f1, f2 in combinations(FACTORS, 2):
            s = evaluate_nested(data, (f1, f2), DIRECTION)
            if s:
                s.update({"pattern": " + ".join([f1,f2]), "k": 2, "direction": DIRECTION,
                         "score": score_fn(s), "_factors": (f1, f2)})
                results.append(s)
        n2 = sum(1 for r in results if r['direction']==DIRECTION and r['k']==2)
        print(f"  -> 2f: {n2} ({time.time()-t1:.0f}с)")

        # 3-факторные
        top1 = sorted([r for r in results if r["k"]==1 and r["direction"]==DIRECTION and r["avgR"] > 0],
                      key=lambda r: -r["avgR"])[:TOP_1F]
        pool = [r["pattern"] for r in top1]
        if len(pool) >= 3:
            print(f"[{DIRECTION}] 3-факторные (топ-{len(pool)} 1f)...")
            t1 = time.time()
            for f1, f2, f3 in combinations(pool, 3):
                s = evaluate_nested(data, (f1, f2, f3), DIRECTION)
                if s:
                    s.update({"pattern": " + ".join([f1,f2,f3]), "k": 3, "direction": DIRECTION,
                             "score": score_fn(s), "_factors": (f1, f2, f3)})
                    results.append(s)
            n3 = sum(1 for r in results if r['direction']==DIRECTION and r['k']==3)
            print(f"  -> 3f: {n3} ({time.time()-t1:.0f}с)")

        for DIR in ["LONG", "SHORT"]:
            dir_factors = LONG_FACTORS if DIR == "LONG" else SHORT_FACTORS
            dir_results = [r for r in results if r.get("direction") == DIR]
            if len(dir_results) < 3: continue

            # 4f
            top3 = sorted([r for r in dir_results if r["k"]==3 and r["avgR"] > 0], key=lambda r: -r["score"])[:TOP_3F]
            if top3:
                print(f"[{DIR}] 4-факторные (топ-{len(top3)} 3f + 1)...")
                t1 = time.time()
                seen = set()
                for r3 in top3:
                    base = r3["_factors"]
                    for fnew in dir_factors:
                        if fnew in base: continue
                        pat = tuple(sorted(list(base) + [fnew]))
                        if pat in seen: continue
                        seen.add(pat)
                        s = evaluate_nested(data, pat, DIR)
                        if s:
                            s.update({"pattern": " + ".join(pat), "k": 4, "direction": DIR,
                                     "score": score_fn(s), "_factors": pat})
                            results.append(s)
                n4 = sum(1 for r in results if r.get("direction")==DIR and r['k']==4)
                print(f"  -> 4f: {n4} ({time.time()-t1:.0f}с)")

            # 5f
            top4 = sorted([r for r in dir_results if r["k"]==4 and r["avgR"] > 0], key=lambda r: -r["score"])[:TOP_4F]
            if top4:
                print(f"[{DIR}] 5-факторные (топ-{len(top4)} 4f + 1)...")
                t1 = time.time()
                seen5 = set()
                for r4 in top4:
                    base = r4["_factors"]
                    for fnew in dir_factors:
                        if fnew in base: continue
                        pat = tuple(sorted(list(base) + [fnew]))
                        if pat in seen5: continue
                        seen5.add(pat)
                        s = evaluate_nested(data, pat, DIR)
                        if s:
                            s.update({"pattern": " + ".join(pat), "k": 5, "direction": DIR,
                                     "score": score_fn(s), "_factors": pat})
                            results.append(s)
                n5 = sum(1 for r in results if r.get("direction")==DIR and r['k']==5)
                print(f"  -> 5f: {n5} ({time.time()-t1:.0f}с)")

    # Сортируем и показываем топ
    print(f"\n{'='*120}")
    print(f"DS-316 NESTED LTF ({LTF})  |  HTF: SOFT zones+trends (6 contexts x LONG/SHORT)")
    print(f"  TP={TP_R}R  |  Active window +-{ACTIVE_WINDOW} bars  |  Паттернов: {len(results)}")
    print(f"{'='*120}")

    for DIR in ["LONG", "SHORT"]:
        dir_results = [r for r in results if r.get("direction") == DIR]
        if not dir_results: continue
        print(f"\n=== [{DIR}] ТОП-15 LTF (по score) ===")
        print(f"{'#':<3} {'k':<2} {'n':>5} {'avgR':>7} {'WR%':>6} {'sumR':>8} {'score':>7}  pattern")
        print("-"*110)
        for i, r in enumerate(sorted(dir_results, key=lambda r: -r["score"])[:15], 1):
            pat = r["pattern"][:80] + ("…" if len(r["pattern"])>80 else "")
            print(f"{i:<3} {r['k']:<2} {r['n']:>5} {r['avgR']:>+7.3f} {r['WR']:>5.1f}% {r['sumR']:>+8.1f} {r['score']:>+7.3f}  {pat}")

    print(f"\n=== ТОП-15 LTF 1-факторных (с большим n) ===")
    top1 = sorted([r for r in results if r["k"]==1], key=lambda r: -r["score"])[:15]
    for r in top1:
        print(f"  n={r['n']:>5} avgR={r['avgR']:>+.3f} WR={r['WR']:>4.1f}%  {r['pattern']}")

    print(f"\n=== ТОП-15 LTF 2-факторных ===")
    top2 = sorted([r for r in results if r["k"]==2], key=lambda r: -r["score"])[:15]
    for r in top2:
        pat = r["pattern"][:75] + ("…" if len(r["pattern"])>75 else "")
        print(f"  n={r['n']:>5} avgR={r['avgR']:>+.3f} WR={r['WR']:>4.1f}%  {pat}")

    for k in [3, 4, 5]:
        print(f"\n=== ТОП-15 LTF {k}-факторных ===")
        topk = sorted([r for r in results if r["k"]==k], key=lambda r: -r["score"])[:15]
        for r in topk:
            pat = r["pattern"][:90] + ("…" if len(r["pattern"])>90 else "")
            print(f"  n={r['n']:>5} avgR={r['avgR']:>+.3f} WR={r['WR']:>4.1f}%  {pat}")

    # Сохраняем
    out_dir = Path("e:/MTF BOT/CURSOR/crypto_volume_bot/data/research/2026-06-03--ds316")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"nested_ltf_{LTF}_results.csv"
    df_res = pd.DataFrame([{k:v for k,v in r.items() if not k.startswith("_")} for r in results])
    df_res.to_csv(out, index=False, encoding="utf-8")
    print(f"\nСохранено: {out}  ({len(df_res)} строк)")


if __name__ == "__main__":
    main()
