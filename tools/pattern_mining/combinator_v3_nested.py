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

# HTF ядро (золотой паттерн, walk-forward validated)
HTF_CORE = ["bull_div_1d", "bull_fvg_4h", "wt_os_4h"]

# Greedy pruning
TOP_1F = 30
TOP_3F = 25
TOP_4F = 15
TOP_5F = 10


def compute_htf_mask(path_1h: Path) -> pd.Series:
    """
    Загружает 1h данные, считает HTF флаги (с lookahead fix),
    возвращает Series HTF mask (True когда HTF core активен).
    """
    res = cb.process_symbol(path_1h)
    if res is None:
        return None
    flags, _, _ = res
    # HTF core mask: все три флага должны быть True
    mask = pd.Series(True, index=flags.index)
    for f in HTF_CORE:
        if f not in flags.columns:
            return None
        mask &= flags[f]
    return mask


def compute_ltf_flags(df_ltf: pd.DataFrame, label: str) -> pd.DataFrame:
    """SMC + индикаторы на LTF + пивоты 1D/1W (статические уровни)."""
    return cb.compute_flags(df_ltf, label, include_pivots=True)


def simulate_ltf(df: pd.DataFrame, tp_r: float, future: int):
    """LONG-симуляция на LTF (SHORT не нужен — золотой паттерн только LONG)."""
    n = len(df)
    high  = df["high"].values
    low   = df["low"].values
    close = df["close"].values
    r_long = np.full(n, np.nan)
    for i in range(20, n - future - 1):
        price = close[i]
        sl = low[i-10:i+1].min() * 0.999
        sld = price - sl
        if sld <= 0 or sld/price > 0.06:
            continue
        tp = price + sld*tp_r
        fh = high[i+1:i+1+future]; fl = low[i+1:i+1+future]
        ht = (fh >= tp); hs = (fl <= sl)
        if ht.any() and hs.any():
            r_long[i] = tp_r if np.argmax(ht) <= np.argmax(hs) else -1.0
        elif ht.any(): r_long[i] = tp_r
        elif hs.any(): r_long[i] = -1.0
        else:          r_long[i] = (close[i+future]-price)/sld
    return r_long


def process_pair(symbol: str):
    """Возвращает (ltf_flags_df, r_long, htf_mask_on_ltf)."""
    path_1h = HISTORY_1H / f"{symbol}.parquet"
    path_ltf = HISTORY_LTF_BASE / LTF / f"{symbol}.parquet"
    if not path_1h.exists() or not path_ltf.exists():
        return None

    try:
        # HTF mask на 1h сетке
        htf_mask_1h = compute_htf_mask(path_1h)
        if htf_mask_1h is None or not htf_mask_1h.any():
            return None

        # LTF данные
        df_ltf = pd.read_parquet(path_ltf)
        df_ltf.columns = [c.lower() for c in df_ltf.columns]
        if "ts" in df_ltf.columns:
            df_ltf["ts"] = pd.to_datetime(df_ltf["ts"], unit="ms", utc=True, errors="coerce")
            df_ltf = df_ltf.set_index("ts")
        df_ltf = df_ltf[["open","high","low","close","volume"]].dropna().sort_index()
        if len(df_ltf) < 500:
            return None

        # LTF SMC + индикаторы
        ltf_flags = compute_ltf_flags(df_ltf, LTF)

        # HTF mask reindex на LTF (lookahead-safe: 1h close активен +1h)
        htf_mask_1h_shifted = htf_mask_1h.copy()
        htf_mask_1h_shifted.index = htf_mask_1h_shifted.index + pd.Timedelta(hours=1)
        htf_on_ltf = htf_mask_1h_shifted.reindex(df_ltf.index, method="ffill").fillna(False).astype(bool)

        if not htf_on_ltf.any():
            return None

        # LTF simulation (только LONG)
        r_long = simulate_ltf(df_ltf, TP_R, FUTURE_BARS_LTF)
        return ltf_flags, r_long, htf_on_ltf.values

    except Exception as e:
        print(f"  ERR {symbol}: {e}")
        return None


def evaluate_nested(data: dict, factors: tuple):
    """factors = LTF факторы; HTF mask применяется ВНУТРИ."""
    all_rs = []
    for sym, (flags, r_long, htf_mask) in data.items():
        mask = htf_mask.copy()
        for f in factors:
            if f not in flags.columns:
                return None
            mask &= flags[f].values
        if not mask.any():
            continue
        rs_valid = r_long[mask & ~np.isnan(r_long)]
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
    print(f"HTF контекст (ядро): {' AND '.join(HTF_CORE)}")
    print(f"\nLTF parquet файлов: {len(files)}")
    if not files:
        print(f"Нет LTF данных в {HISTORY_LTF_BASE / LTF}. Сначала запусти fetch_ltf_parallel.py")
        return

    print(f"\n[1] Загрузка пар + HTF mask + LTF флаги...")
    t0 = time.time()
    data = {}
    for path in files:
        sym = path.stem
        res = process_pair(sym)
        if res is None:
            continue
        flags, r_long, htf_mask = res
        n_htf = int(htf_mask.sum())
        n_valid_r = int(np.sum(~np.isnan(r_long) & htf_mask))
        data[sym] = (flags, r_long, htf_mask)
        if len(data) % 5 == 0:
            print(f"  ...{len(data)}/{len(files)} ({time.time()-t0:.0f}с)")
    print(f"  Готово за {time.time()-t0:.0f}с. Пар: {len(data)}")

    if not data:
        print("Нет валидных данных."); return

    # Подсчёт baseline (без LTF фильтра, только HTF context)
    print(f"\n[2] Baseline: только HTF контекст (без LTF фильтра)...")
    baseline = evaluate_nested(data, tuple())
    if baseline:
        print(f"  HTF context alone: n={baseline['n']}  avgR={baseline['avgR']:+.3f}  WR={baseline['WR']:.1f}%  sumR={baseline['sumR']:+.1f}R")
    else:
        print(f"  Недостаточно сделок при baseline")

    # Все LTF факторы
    first = next(iter(data.values()))[0]
    ALL_LTF = list(first.columns)
    LONG_FACTORS = [f for f in ALL_LTF if any(s in f for s in [
        "bull_", "ote_long", "discount", "wt_os", "atr_cross_up", "atr_up",
        "eql_sweep", "wt_cross_up", "above_ema", "vol_spike", "rsi_os",
        "rsi_cross50_up", "ema50_above_ema200",
        "pivot_near_S", "pivot_above_PP", "pivot_bounce_up"
    ])]
    print(f"\n  LTF LONG факторов: {len(LONG_FACTORS)}")

    results = []

    print(f"\n[3] 1-факторные LTF...")
    t1 = time.time()
    for f in LONG_FACTORS:
        s = evaluate_nested(data, (f,))
        if s:
            s.update({"pattern": f, "k": 1, "score": score_fn(s)})
            results.append(s)
    print(f"  → {sum(1 for r in results if r['k']==1)} ({time.time()-t1:.0f}с)")

    print(f"\n[4] 2-факторные LTF...")
    t1 = time.time()
    for f1, f2 in combinations(LONG_FACTORS, 2):
        s = evaluate_nested(data, (f1, f2))
        if s:
            s.update({"pattern": f" + ".join([f1,f2]), "k": 2, "score": score_fn(s), "_factors": (f1, f2)})
            results.append(s)
    print(f"  → {sum(1 for r in results if r['k']==2)} ({time.time()-t1:.0f}с)")

    print(f"\n[5] 3-факторные (топ-{TOP_1F} 1f)...")
    t1 = time.time()
    top1 = sorted([r for r in results if r["k"]==1 and r["avgR"] > 0], key=lambda r: -r["avgR"])[:TOP_1F]
    pool = [r["pattern"] for r in top1]
    for f1, f2, f3 in combinations(pool, 3):
        s = evaluate_nested(data, (f1, f2, f3))
        if s:
            s.update({"pattern": " + ".join([f1,f2,f3]), "k": 3, "score": score_fn(s),
                     "_factors": (f1, f2, f3)})
            results.append(s)
    print(f"  → {sum(1 for r in results if r['k']==3)} ({time.time()-t1:.0f}с)")

    print(f"\n[6] 4-факторные (топ-{TOP_3F} 3f + 1)...")
    t1 = time.time()
    top3 = sorted([r for r in results if r["k"]==3 and r["avgR"] > 0], key=lambda r: -r["score"])[:TOP_3F]
    seen = set()
    for r3 in top3:
        base = r3["_factors"]
        for fnew in LONG_FACTORS:
            if fnew in base: continue
            pat = tuple(sorted(list(base) + [fnew]))
            if pat in seen: continue
            seen.add(pat)
            s = evaluate_nested(data, pat)
            if s:
                s.update({"pattern": " + ".join(pat), "k": 4, "score": score_fn(s), "_factors": pat})
                results.append(s)
    print(f"  → {sum(1 for r in results if r['k']==4)} ({time.time()-t1:.0f}с)")

    print(f"\n[7] 5-факторные (топ-{TOP_4F} 4f + 1)...")
    t1 = time.time()
    top4 = sorted([r for r in results if r["k"]==4 and r["avgR"] > 0], key=lambda r: -r["score"])[:TOP_4F]
    seen5 = set()
    for r4 in top4:
        base = r4["_factors"]
        for fnew in LONG_FACTORS:
            if fnew in base: continue
            pat = tuple(sorted(list(base) + [fnew]))
            if pat in seen5: continue
            seen5.add(pat)
            s = evaluate_nested(data, pat)
            if s:
                s.update({"pattern": " + ".join(pat), "k": 5, "score": score_fn(s), "_factors": pat})
                results.append(s)
    print(f"  → {sum(1 for r in results if r['k']==5)} ({time.time()-t1:.0f}с)")

    # Сортируем и показываем топ
    print(f"\n{'='*120}")
    print(f"NESTED LTF MINING ({LTF})  |  HTF context: {' + '.join(HTF_CORE)}")
    print(f"  Baseline (HTF only): n={baseline['n'] if baseline else 0} avgR={baseline['avgR']:+.3f} WR={baseline['WR']:.1f}%" if baseline else "")
    print(f"  Всего паттернов: {len(results)}  |  TP={TP_R}R")
    print(f"{'='*120}")

    print(f"\n=== ТОП-30 LTF entry triggers (по score) ===")
    print(f"{'#':<3} {'k':<2} {'n':>5} {'avgR':>7} {'WR%':>6} {'sumR':>8} {'score':>7}  pattern")
    print("-"*120)
    for i, r in enumerate(sorted(results, key=lambda r: -r["score"])[:30], 1):
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
    out_dir = Path(f"e:/MTF BOT/CURSOR/crypto_volume_bot/data/research/2026-05-19")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"nested_v3_{LTF}_results.csv"
    df_res = pd.DataFrame([{k:v for k,v in r.items() if not k.startswith("_")} for r in results])
    df_res.to_csv(out, index=False, encoding="utf-8")
    print(f"\nСохранено: {out}  ({len(df_res)} строк)")


if __name__ == "__main__":
    main()
