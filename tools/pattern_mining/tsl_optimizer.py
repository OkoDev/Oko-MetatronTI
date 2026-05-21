"""
TSL Optimizer — найти оптимальные параметры Trailing Stop Loss
для забора максимума из найденных entry points.

Цель: для каждого entry (где сработал HTF+LTF паттерн) симулировать
выход по разным TSL стратегиям и найти параметры с максимальным sumR.

Параметры для оптимизации:
- TSL activation: 0.5R / 1.0R / 1.5R / 2.0R (когда активируется TSL)
- TSL trail method:
    * ATR-based: trail = current - ATR(14) × multi (для LONG)
    * Supertrend (43, 1.25) — как в боте сейчас
    * Fixed % below high
    * High water mark - X% retracement
- TSL distance: 0.5R / 1.0R / 1.5R (на сколько R отступаем от high)
- Time stop: 24h / 48h / no_limit
- Partial TP: nothing / 50% at 1R, 50% trail / 30/70

Сетка: ~100-200 комбинаций, каждая прогоняется на N entry points.

Запуск:
  python tools/pattern_mining/tsl_optimizer.py [15m|5m] [pattern_factors_csv]
"""
import sys, warnings, time
warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from pathlib import Path
from itertools import product
import pandas as pd
import numpy as np

PROJECT_ROOT = Path("E:/MTF BOT/CURSOR/crypto_volume_bot")
HISTORY_1H = PROJECT_ROOT / "data/history/1h"

LTF = sys.argv[1] if len(sys.argv) > 1 else "15m"
HISTORY_LTF = PROJECT_ROOT / f"data/history/{LTF}"

sys.path.insert(0, str(Path(__file__).parent))
import combinator_v2 as cb

# HTF core (золотой паттерн)
HTF_CORE = ["bull_div_1d", "bull_fvg_4h", "wt_os_4h"]
# LTF entry triggers (best discovered)
LTF_TRIGGERS = ["bull_ob_near_15m"]   # будем сравнивать с alternatives

# Параметры TSL для сетки
TSL_ACTIVATION_R = [0.5, 1.0, 1.5, 2.0]
TSL_TRAIL_R      = [0.5, 1.0, 1.5, 2.0]
TIME_LIMIT_BARS  = [24, 48, 96, 200]   # 24×15m=6h, 48=12h, 96=24h, 200=50h


def compute_atr(df, period=14):
    """ATR на n-периодов (вектор)."""
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    tr = np.maximum.reduce([
        h - l,
        np.abs(h - np.roll(c, 1)),
        np.abs(l - np.roll(c, 1)),
    ])
    tr[0] = h[0] - l[0]
    return pd.Series(tr).rolling(period, min_periods=1).mean().values


def simulate_tsl_fixed(df, entry_i, sl, tsl_act_r, tsl_trail_r, time_limit):
    """Простой TSL: одна активация + фиксированный trail distance."""
    high  = df["high"].values; low = df["low"].values; close = df["close"].values
    n = len(df)
    price = close[entry_i]; sl_dist = price - sl
    if sl_dist <= 0: return None, "invalid_sl"
    tsl_active = False; current_sl = sl; peak_high = price
    end_i = min(n - 1, entry_i + 1 + time_limit)
    for i in range(entry_i + 1, end_i + 1):
        if high[i] > peak_high: peak_high = high[i]
        current_R = (peak_high - price) / sl_dist
        if not tsl_active and current_R >= tsl_act_r: tsl_active = True
        if tsl_active:
            new_sl = peak_high - tsl_trail_r * sl_dist
            if new_sl > current_sl: current_sl = new_sl
        if low[i] <= current_sl:
            return (current_sl - price)/sl_dist, "tsl_hit" if tsl_active else "sl_hit"
    return (close[end_i] - price)/sl_dist, "time_exit"


def simulate_tsl_escalating(df, entry_i, sl, steps, deescalation_r, time_limit):
    """
    Эскалирующий TSL: список steps = [(trigger_R, trail_R), ...]
    отсортирован по trigger_R. При достижении trigger_R активируется новый trail.

    Де-эскалация: если peak_R - current_R >= deescalation_r → откатить на предыдущую ступень.
    """
    high  = df["high"].values; low = df["low"].values; close = df["close"].values
    n = len(df)
    price = close[entry_i]; sl_dist = price - sl
    if sl_dist <= 0: return None, "invalid_sl"

    current_sl = sl
    peak_high  = price
    current_step = -1   # индекс активного step (-1 = неактивен)
    sorted_steps = sorted(steps, key=lambda s: s[0])

    end_i = min(n - 1, entry_i + 1 + time_limit)
    for i in range(entry_i + 1, end_i + 1):
        if high[i] > peak_high: peak_high = high[i]
        peak_R = (peak_high - price) / sl_dist
        current_R = (close[i] - price) / sl_dist
        pullback_R = peak_R - current_R

        # Эскалация — повышаем step при достижении trigger
        for idx, (trig_R, trail_R) in enumerate(sorted_steps):
            if idx > current_step and peak_R >= trig_R:
                current_step = idx

        # Де-эскалация — если откат от пика > deescalation_r, откатываем step
        if deescalation_r > 0 and pullback_R >= deescalation_r and current_step > 0:
            current_step -= 1

        # Trailing SL по текущему step
        if current_step >= 0:
            trail_R = sorted_steps[current_step][1]
            if trail_R == 0:  # breakeven
                new_sl = price
            elif trail_R > 0:
                new_sl = peak_high - trail_R * sl_dist
            else:
                new_sl = current_sl
            if new_sl > current_sl: current_sl = new_sl

        if low[i] <= current_sl:
            reason = f"tsl_step{current_step}_hit" if current_step >= 0 else "sl_hit"
            return (current_sl - price)/sl_dist, reason

    return (close[end_i] - price)/sl_dist, "time_exit"


# Алиас для совместимости
simulate_tsl = simulate_tsl_fixed


def collect_entry_points(symbols: list, ltf: str):
    """
    Возвращает список (symbol, entry_index, entry_price, sl) для каждой точки
    где HTF активен И LTF entry trigger сработал.
    """
    entries_per_sym = {}
    for sym in symbols:
        path_1h = HISTORY_1H / f"{sym}.parquet"
        path_ltf = HISTORY_LTF / f"{sym}.parquet"
        if not path_1h.exists() or not path_ltf.exists():
            continue

        # HTF mask
        res = cb.process_symbol(path_1h)
        if res is None:
            continue
        htf_flags, _, _ = res
        htf_mask_1h = pd.Series(True, index=htf_flags.index)
        for f in HTF_CORE:
            if f not in htf_flags.columns:
                htf_mask_1h = pd.Series(False, index=htf_flags.index)
                break
            htf_mask_1h &= htf_flags[f]
        if not htf_mask_1h.any():
            continue

        # LTF data
        df_ltf = pd.read_parquet(path_ltf)
        df_ltf.columns = [c.lower() for c in df_ltf.columns]
        if "ts" in df_ltf.columns:
            df_ltf["ts"] = pd.to_datetime(df_ltf["ts"], unit="ms", utc=True, errors="coerce")
            df_ltf = df_ltf.set_index("ts")
        df_ltf = df_ltf[["open","high","low","close","volume"]].dropna().sort_index()
        if len(df_ltf) < 500:
            continue

        # LTF flags
        ltf_flags = cb.compute_flags(df_ltf, ltf, include_pivots=False)

        # HTF reindex на LTF с +1h shift
        htf_shifted = htf_mask_1h.copy()
        htf_shifted.index = htf_shifted.index + pd.Timedelta(hours=1)
        htf_on_ltf = htf_shifted.reindex(df_ltf.index, method="ffill").fillna(False).astype(bool)

        # LTF trigger mask
        trigger_mask = pd.Series(True, index=df_ltf.index)
        for f in LTF_TRIGGERS:
            if f not in ltf_flags.columns:
                trigger_mask = pd.Series(False, index=df_ltf.index)
                break
            trigger_mask &= ltf_flags[f]

        # Final entry mask
        entry_mask = (htf_on_ltf & trigger_mask).values
        entry_indices = np.where(entry_mask)[0]
        # Filter: достаточно баров для симуляции
        entry_indices = entry_indices[(entry_indices >= 20) & (entry_indices < len(df_ltf) - 250)]

        entries = []
        low = df_ltf["low"].values
        close = df_ltf["close"].values
        for i in entry_indices:
            price = close[i]
            sl = low[i-10:i+1].min() * 0.999
            if (price - sl) / price < 0.06:
                entries.append((i, price, sl))

        if entries:
            entries_per_sym[sym] = (df_ltf, entries)

    return entries_per_sym


def main():
    print(f"TSL Optimizer  |  LTF: {LTF}")
    print(f"HTF core: {' AND '.join(HTF_CORE)}")
    print(f"LTF trigger: {' AND '.join(LTF_TRIGGERS)}")

    symbols = [p.stem for p in HISTORY_LTF.glob("*.parquet")]
    print(f"\nСбор entry points с {len(symbols)} пар...")
    t0 = time.time()
    entries_data = collect_entry_points(symbols, LTF)
    total_entries = sum(len(e[1]) for e in entries_data.values())
    print(f"  Собрано: {total_entries} entry points с {len(entries_data)} пар за {time.time()-t0:.0f}с")

    if total_entries < 20:
        print("Слишком мало entry points")
        return

    print(f"\n=== Тестируем TSL grid ===")
    print(f"  activation_R: {TSL_ACTIVATION_R}")
    print(f"  trail_R:      {TSL_TRAIL_R}")
    print(f"  time_limit:   {TIME_LIMIT_BARS} баров {LTF}")

    # Baseline: фиксированный TP=2R / SL = swing
    print(f"\n[Baseline: fixed TP=2R / SL=swing]")
    rs_base = []
    for sym, (df, entries) in entries_data.items():
        high = df["high"].values
        low  = df["low"].values
        close = df["close"].values
        for i, price, sl in entries:
            sl_dist = price - sl
            tp = price + sl_dist * 2.0
            end_i = min(len(df) - 1, i + 1 + 48)
            fh = high[i+1:end_i+1]
            fl = low[i+1:end_i+1]
            hit_tp = (fh >= tp).any()
            hit_sl = (fl <= sl).any()
            if hit_tp and hit_sl:
                r = 2.0 if np.argmax(fh >= tp) <= np.argmax(fl <= sl) else -1.0
            elif hit_tp: r = 2.0
            elif hit_sl: r = -1.0
            else: r = (close[end_i] - price) / sl_dist
            rs_base.append(r)
    if rs_base:
        arr = np.array(rs_base)
        print(f"  n={len(arr)}  avgR={arr.mean():+.3f}  sumR={arr.sum():+.1f}  WR={(arr>0).mean()*100:.1f}%")

    # TSL grid
    print(f"\n[TSL Grid Search]")
    results = []
    for act_r, trail_r, time_lim in product(TSL_ACTIVATION_R, TSL_TRAIL_R, TIME_LIMIT_BARS):
        rs = []
        reasons = {"tsl_hit":0, "sl_hit":0, "time_exit":0}
        for sym, (df, entries) in entries_data.items():
            for i, price, sl in entries:
                r, reason = simulate_tsl(df, i, sl, act_r, trail_r, time_lim)
                if r is None:
                    continue
                rs.append(r)
                reasons[reason] = reasons.get(reason, 0) + 1
        if len(rs) < 20:
            continue
        arr = np.array(rs)
        results.append({
            "tsl_act_r":    act_r,
            "tsl_trail_r":  trail_r,
            "time_limit":   time_lim,
            "n":            len(arr),
            "avgR":         float(arr.mean()),
            "sumR":         float(arr.sum()),
            "WR":           float((arr > 0).mean() * 100),
            "stdR":         float(arr.std()),
            "tsl_hit":      reasons.get("tsl_hit", 0),
            "sl_hit":       reasons.get("sl_hit", 0),
            "time_exit":    reasons.get("time_exit", 0),
            "med_R":        float(np.median(arr)),
            "max_R":        float(arr.max()),
            "p95_R":        float(np.percentile(arr, 95)),
        })

    df_res = pd.DataFrame(results).sort_values("avgR", ascending=False)

    print(f"\n{'='*120}")
    print(f"ТОП-15 TSL КОНФИГУРАЦИЙ (по avgR)")
    print(f"{'='*120}")
    print(f"{'act_R':>6} {'trail_R':>8} {'time':>5} {'n':>5} {'avgR':>7} {'WR%':>6} {'sumR':>8} {'medR':>7} {'maxR':>7} {'tsl':>4} {'sl':>4} {'time':>5}")
    for _, r in df_res.head(15).iterrows():
        print(f"{r['tsl_act_r']:>6.1f} {r['tsl_trail_r']:>8.1f} {int(r['time_limit']):>5} {int(r['n']):>5} {r['avgR']:>+7.3f} {r['WR']:>5.1f}% {r['sumR']:>+8.1f} {r['med_R']:>+7.2f} {r['max_R']:>+7.2f} {int(r['tsl_hit']):>4} {int(r['sl_hit']):>4} {int(r['time_exit']):>5}")

    print(f"\n{'='*120}")
    print(f"ТОП-10 по sumR (всего собранных R)")
    print(f"{'='*120}")
    for _, r in df_res.sort_values("sumR", ascending=False).head(10).iterrows():
        print(f"  act_R={r['tsl_act_r']} trail_R={r['tsl_trail_r']} time={int(r['time_limit'])}  n={int(r['n'])}  avgR={r['avgR']:+.3f}  sumR={r['sumR']:+.1f}  WR={r['WR']:.1f}%  med={r['med_R']:+.2f}")

    out = PROJECT_ROOT / "data/research/2026-05-19" / f"tsl_optimizer_{LTF}_results.csv"
    df_res.to_csv(out, index=False, encoding="utf-8")
    print(f"\nСохранено: {out}")

    # ─── Escalating TSL Grid ─────────────────────────────────────────────
    print(f"\n{'='*120}")
    print(f"ЭСКАЛИРУЮЩИЙ TSL (multi-step + de-escalation)")
    print(f"{'='*120}")

    # Профили эскалации: список (trigger_R, trail_R)
    # trail_R = 0 значит breakeven (SL = entry)
    PROFILES = {
        "ladder_3step":     [(0.5, 0.0), (1.0, 1.0), (2.0, 0.5)],
        "ladder_4step":     [(0.5, 0.0), (1.0, 1.0), (2.0, 0.5), (3.0, 0.3)],
        "agg_breakeven":    [(0.3, 0.0), (1.0, 0.5), (2.0, 0.3)],
        "patient_step":    [(1.0, 0.0), (2.0, 1.0), (3.0, 0.5)],
        "smart_trail":     [(0.5, 0.0), (1.5, 0.8), (3.0, 0.4), (5.0, 0.2)],
        "be_then_runner":  [(1.0, 0.0), (3.0, 1.5)],  # breakeven при +1R, потом wide trail
    }
    DEESCALATION_R = [0.0, 0.5, 1.0, 1.5]   # 0 = без де-эскалации

    esc_results = []
    for profile_name, steps in PROFILES.items():
        for desc_r in DEESCALATION_R:
            for time_lim in TIME_LIMIT_BARS:
                rs = []
                reasons = {}
                for sym, (df, entries) in entries_data.items():
                    for i, price, sl in entries:
                        r, reason = simulate_tsl_escalating(df, i, sl, steps, desc_r, time_lim)
                        if r is None: continue
                        rs.append(r)
                        reasons[reason] = reasons.get(reason, 0) + 1
                if len(rs) < 20: continue
                arr = np.array(rs)
                esc_results.append({
                    "profile":      profile_name,
                    "steps":        str(steps),
                    "deesc_r":      desc_r,
                    "time_limit":   time_lim,
                    "n":            len(arr),
                    "avgR":         float(arr.mean()),
                    "sumR":         float(arr.sum()),
                    "WR":           float((arr > 0).mean()*100),
                    "med_R":        float(np.median(arr)),
                    "max_R":        float(arr.max()),
                    "p95_R":        float(np.percentile(arr, 95)),
                })

    df_esc = pd.DataFrame(esc_results).sort_values("avgR", ascending=False)
    print(f"\nТОП-20 эскалирующих профилей (по avgR):")
    print(f"{'profile':<18} {'desc_R':>6} {'time':>5} {'n':>5} {'avgR':>7} {'WR%':>6} {'sumR':>8} {'medR':>6} {'maxR':>6} {'p95':>6}")
    for _, r in df_esc.head(20).iterrows():
        print(f"{r['profile']:<18} {r['deesc_r']:>6.1f} {int(r['time_limit']):>5} {int(r['n']):>5} {r['avgR']:>+7.3f} {r['WR']:>5.1f}% {r['sumR']:>+8.1f} {r['med_R']:>+6.2f} {r['max_R']:>+6.2f} {r['p95_R']:>+6.2f}")

    print(f"\nТОП-10 эскалирующих по sumR (для максимизации):")
    for _, r in df_esc.sort_values("sumR", ascending=False).head(10).iterrows():
        print(f"  {r['profile']:<18} desc_R={r['deesc_r']} time={int(r['time_limit'])}  n={int(r['n'])}  sumR={r['sumR']:+.1f}  avgR={r['avgR']:+.3f}  med={r['med_R']:+.2f}  p95={r['p95_R']:+.2f}")
        print(f"    steps={r['steps']}")

    out_esc = PROJECT_ROOT / "data/research/2026-05-19" / f"tsl_optimizer_esc_{LTF}_results.csv"
    df_esc.to_csv(out_esc, index=False, encoding="utf-8")
    print(f"\nСохранено: {out_esc}")

    # ─── Сравнение Baseline vs Best Fixed vs Best Escalating ───────────
    if rs_base and len(df_res) and len(df_esc):
        best_fixed = df_res.iloc[0]
        best_esc   = df_esc.iloc[0]
        arr_b = np.array(rs_base)
        print(f"\n{'='*120}")
        print(f"ИТОГ: сравнение лучших стратегий")
        print(f"{'='*120}")
        print(f"{'Strategy':<35} {'n':>5} {'avgR':>7} {'sumR':>8} {'WR%':>6} {'medR':>6}")
        print(f"{'-'*70}")
        print(f"{'Baseline (TP=2R fixed)':<35} {len(arr_b):>5} {arr_b.mean():>+7.3f} {arr_b.sum():>+8.1f} {(arr_b>0).mean()*100:>5.1f}% {np.median(arr_b):>+6.2f}")
        print(f"{'Best Fixed TSL':<35} {int(best_fixed['n']):>5} {best_fixed['avgR']:>+7.3f} {best_fixed['sumR']:>+8.1f} {best_fixed['WR']:>5.1f}% {best_fixed['med_R']:>+6.2f}")
        print(f"  └ act_R={best_fixed['tsl_act_r']} trail_R={best_fixed['tsl_trail_r']} time={int(best_fixed['time_limit'])}")
        print(f"{'Best Escalating TSL':<35} {int(best_esc['n']):>5} {best_esc['avgR']:>+7.3f} {best_esc['sumR']:>+8.1f} {best_esc['WR']:>5.1f}% {best_esc['med_R']:>+6.2f}")
        print(f"  └ profile={best_esc['profile']} desc_R={best_esc['deesc_r']} time={int(best_esc['time_limit'])}")
        print(f"  └ steps={best_esc['steps']}")


if __name__ == "__main__":
    main()
