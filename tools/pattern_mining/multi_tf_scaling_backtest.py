"""
Multi-TF Scaling-In Backtest.

Концепция: внутри HTF режима (золотой паттерн активен) одна пара может дать
несколько НЕЗАВИСИМЫХ entry'ев на разных LTF:
- 5m entry  → Position #1 (узкий SL = 5m swing_low)
- 15m entry → Position #2 (средний SL = 15m swing_low)
- 1h entry  → Position #3 (широкий SL = 1h swing_low)
- 4h entry  → Position #4 (самый широкий SL = 4h swing_low)

Каждая позиция:
- Свой entry timing
- Свой SL (на основе своего TF)
- Свой R-distance (TF-зависимый)
- Свой exit (time limit зависит от TF)

Цель: измерить эффект масштабирования.

Запуск: python tools/pattern_mining/multi_tf_scaling_backtest.py
"""
import sys, time, warnings
warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from pathlib import Path
import pandas as pd
import numpy as np
from collections import defaultdict

PROJECT_ROOT = Path("E:/MTF BOT/CURSOR/crypto_volume_bot")
HISTORY_1H  = PROJECT_ROOT / "data/history/1h"
HISTORY_15M = PROJECT_ROOT / "data/history/15m"
HISTORY_5M  = PROJECT_ROOT / "data/history/5m"

sys.path.insert(0, str(Path(__file__).parent))
import combinator_v2 as cb

# HTF режим (золотой)
HTF_CORE = ["bull_div_1d", "bull_fvg_4h", "wt_os_4h"]

# LTF entry triggers по TF (валидированные)
LTF_TRIGGERS = {
    "5m":  ["atr_up_5m"],
    "15m": ["bull_ob_near_15m"],
    "1h":  ["bull_ob_near_1h"],  # будем проверять
    "4h":  None,  # 4h уже часть HTF — каждый момент активного HTF = entry
}

# Time limits для каждого TF (no_trail strategy)
TIME_LIMITS_HOURS = {"5m": 24, "15m": 24, "1h": 48, "4h": 96}
SL_LOOKBACK_BARS = 10


def load_tf(symbol: str, tf: str) -> pd.DataFrame:
    base_dir = {"5m": HISTORY_5M, "15m": HISTORY_15M, "1h": HISTORY_1H}[tf]
    path = base_dir / f"{symbol}.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    df.columns = [c.lower() for c in df.columns]
    if "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True, errors="coerce")
        df = df.set_index("ts")
    df = df[["open","high","low","close","volume"]].dropna().sort_index()
    return df


def compute_htf_mask_1h(symbol: str) -> pd.Series:
    """HTF mask на 1h сетке (с lookahead fix)."""
    path = HISTORY_1H / f"{symbol}.parquet"
    if not path.exists():
        return None
    res = cb.process_symbol(path)
    if res is None:
        return None
    flags, _, _ = res
    mask = pd.Series(True, index=flags.index)
    for f in HTF_CORE:
        if f not in flags.columns:
            return None
        mask &= flags[f]
    return mask if mask.any() else None


def reindex_htf_to_ltf(htf_mask_1h: pd.Series, ltf_index: pd.DatetimeIndex) -> np.ndarray:
    """1h HTF mask → LTF grid с +1h shift (lookahead-safe)."""
    shifted = htf_mask_1h.copy()
    shifted.index = shifted.index + pd.Timedelta(hours=1)
    return shifted.reindex(ltf_index, method="ffill").fillna(False).astype(bool).values


def find_entries(df: pd.DataFrame, tf_label: str, htf_mask_ltf: np.ndarray, triggers: list):
    """Возвращает индексы баров где HTF активен И все LTF triggers сработали."""
    if triggers is None:
        return np.where(htf_mask_ltf)[0]
    ltf_flags = cb.compute_flags(df, tf_label, include_pivots=False)
    mask = htf_mask_ltf.copy()
    for f in triggers:
        if f not in ltf_flags.columns:
            return np.array([])
        mask &= ltf_flags[f].values
    return np.where(mask)[0]


def simulate_no_trail(df: pd.DataFrame, entry_i: int, time_limit_bars: int):
    """No-trail simulation: initial SL = swing_low ×0.999, exit by SL или time."""
    n = len(df)
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    price = close[entry_i]
    sl = low[max(0, entry_i-SL_LOOKBACK_BARS):entry_i+1].min() * 0.999
    sl_dist = price - sl
    if sl_dist <= 0 or sl_dist/price > 0.06:
        return None

    end_i = min(n - 1, entry_i + time_limit_bars)
    fl = low[entry_i+1:end_i+1]
    hit_sl = (fl <= sl).any()
    if hit_sl:
        return {"exit_r": -1.0, "exit_type": "sl", "sl_dist_pct": sl_dist/price*100}
    exit_price = close[end_i]
    exit_r = (exit_price - price) / sl_dist
    return {"exit_r": exit_r, "exit_type": "time", "sl_dist_pct": sl_dist/price*100}


def main():
    print("MULTI-TF SCALING-IN BACKTEST")
    print(f"HTF: {' + '.join(HTF_CORE)}")
    print(f"LTF Triggers:")
    for tf, trig in LTF_TRIGGERS.items():
        print(f"  {tf}: {trig if trig else '(только HTF activeness)'}")

    # Берём пары которые есть на всех TF
    syms_1h  = {p.stem for p in HISTORY_1H.glob("*.parquet")}
    syms_15m = {p.stem for p in HISTORY_15M.glob("*.parquet")}
    syms_5m  = {p.stem for p in HISTORY_5M.glob("*.parquet")}
    common = sorted(syms_1h & syms_15m & syms_5m)
    print(f"\nПар на всех TF: {len(common)}")

    # ──── Для каждой пары: находим entries на каждом TF + симулируем ────
    per_tf_entries = defaultdict(list)
    per_tf_combined = defaultdict(int)   # (5m_active, 15m_active, 1h_active) → count
    t0 = time.time()

    # Глобальный сбор (ts, sym, tf, exit_r, sl_dist_pct)
    all_trades = []

    for sym in common:
        # HTF mask на 1h
        htf_mask_1h = compute_htf_mask_1h(sym)
        if htf_mask_1h is None:
            continue

        # Загружаем LTF данные
        df_5m  = load_tf(sym, "5m")
        df_15m = load_tf(sym, "15m")
        df_1h  = load_tf(sym, "1h")
        if df_5m is None or df_15m is None or df_1h is None:
            continue

        # HTF reindex на каждый LTF
        htf_5m  = reindex_htf_to_ltf(htf_mask_1h, df_5m.index)
        htf_15m = reindex_htf_to_ltf(htf_mask_1h, df_15m.index)
        htf_1h  = reindex_htf_to_ltf(htf_mask_1h, df_1h.index)

        # Find entries
        try:
            entries_5m  = find_entries(df_5m,  "5m",  htf_5m,  LTF_TRIGGERS["5m"])
            entries_15m = find_entries(df_15m, "15m", htf_15m, LTF_TRIGGERS["15m"])
            entries_1h  = find_entries(df_1h,  "1h",  htf_1h,  LTF_TRIGGERS["1h"])
        except Exception as e:
            print(f"  ERR {sym}: {e}")
            continue

        # Симулируем каждый entry
        for tf_name, df, entries, time_lim_h in [
            ("5m",  df_5m,  entries_5m,  TIME_LIMITS_HOURS["5m"]),
            ("15m", df_15m, entries_15m, TIME_LIMITS_HOURS["15m"]),
            ("1h",  df_1h,  entries_1h,  TIME_LIMITS_HOURS["1h"]),
        ]:
            bars_per_hour = {"5m": 12, "15m": 4, "1h": 1}[tf_name]
            time_lim_bars = time_lim_h * bars_per_hour
            for i in entries:
                if i < SL_LOOKBACK_BARS + 5 or i >= len(df) - time_lim_bars:
                    continue
                res = simulate_no_trail(df, i, time_lim_bars)
                if res is None: continue
                ts = df.index[i]
                all_trades.append({
                    "sym":         sym,
                    "tf":          tf_name,
                    "ts":          ts,
                    "exit_r":      res["exit_r"],
                    "exit_type":   res["exit_type"],
                    "sl_dist_pct": res["sl_dist_pct"],
                })
                per_tf_entries[tf_name].append(res["exit_r"])

        if len(per_tf_entries["5m"]) % 50 == 0:
            print(f"  {sym}: total 5m={len(entries_5m)} 15m={len(entries_15m)} 1h={len(entries_1h)}")

    print(f"\nГотово за {time.time()-t0:.0f}с")

    # ───────────── Раздельная статистика по TF ─────────────
    print(f"\n{'='*100}")
    print(f"СТАТИСТИКА ПО TF (no_trail, time exit)")
    print(f"{'='*100}")
    print(f"{'TF':<5} {'n':>5} {'avgR':>8} {'WR%':>6} {'sumR':>9} {'medR':>7} {'maxR':>7} {'avg_SL%':>8}")
    print("-"*100)
    for tf in ["5m", "15m", "1h"]:
        rs = per_tf_entries[tf]
        if not rs: continue
        arr = np.array(rs)
        sl_dists = [t["sl_dist_pct"] for t in all_trades if t["tf"] == tf]
        avg_sl = sum(sl_dists) / len(sl_dists) if sl_dists else 0
        print(f"{tf:<5} {len(arr):>5} {arr.mean():>+8.3f} {(arr>0).mean()*100:>5.1f}% {arr.sum():>+9.1f} {np.median(arr):>+7.2f} {arr.max():>+7.2f} {avg_sl:>7.2f}%")

    # ───────────── Анализ overlap: сколько раз 5m → 15m на одной паре в течение HTF ─────────────
    print(f"\n{'='*100}")
    print(f"OVERLAP ANALYSIS (HTF режим активен → сколько entries каждого TF в одном окне)")
    print(f"{'='*100}")

    # Группируем сделки по парам и сортируем по времени
    by_sym = defaultdict(list)
    for t in all_trades:
        by_sym[t["sym"]].append(t)
    for sym in by_sym:
        by_sym[sym].sort(key=lambda x: x["ts"])

    # Считаем pyramid sequences: сколько раз 5m → 15m → 1h в окне 24h
    pyramid_counts = defaultdict(int)
    for sym, trades in by_sym.items():
        # Сгруппируем по 24h окнам
        i = 0
        while i < len(trades):
            window_start = trades[i]["ts"]
            window_end = window_start + pd.Timedelta(hours=24)
            window_trades = []
            j = i
            while j < len(trades) and trades[j]["ts"] <= window_end:
                window_trades.append(trades[j])
                j += 1
            tfs_in_window = set(t["tf"] for t in window_trades)
            key = tuple(sorted(tfs_in_window))
            pyramid_counts[key] += 1
            i = j

    print(f"\n{'Комбинация TF в 24h окне':<35} {'Кол-во окон':>12}")
    for combo, cnt in sorted(pyramid_counts.items(), key=lambda x: -x[1]):
        print(f"  {str(combo):<35} {cnt:>12}")

    # ───────────── Портфельная сумма всех сделок ─────────────
    print(f"\n{'='*100}")
    print(f"ПОРТФЕЛЬ всех TF (независимые позиции)")
    print(f"{'='*100}")
    all_rs = np.array([t["exit_r"] for t in all_trades])
    if len(all_rs):
        sl_dists_all = [t["sl_dist_pct"] for t in all_trades]
        print(f"  Всего сделок:  {len(all_rs)}")
        print(f"  avgR:          {all_rs.mean():+.3f}")
        print(f"  WR:            {(all_rs>0).mean()*100:.1f}%")
        print(f"  sumR:          {all_rs.sum():+.1f}")
        print(f"  medR:          {np.median(all_rs):+.2f}")
        print(f"  maxR:          {all_rs.max():+.2f}")
        print(f"  avg SL%:       {sum(sl_dists_all)/len(sl_dists_all):.2f}%")
        # При 1% риска per trade — компаудинг
        wealth = 1.0
        for r in all_rs:
            wealth *= (1 + 0.01 * r)
        print(f"  Compound R: при 1% risk → wealth multiple = ×{wealth:.2f}")

    # Сохранить
    df_all = pd.DataFrame(all_trades)
    out = PROJECT_ROOT / "data/research/2026-05-19/multi_tf_scaling_results.csv"
    df_all.to_csv(out, index=False, encoding="utf-8")
    print(f"\nСохранено: {out}")


if __name__ == "__main__":
    main()
