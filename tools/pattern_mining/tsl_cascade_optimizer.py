"""
TSL CASCADE OPTIMIZER — выжать максимум из каскадных TSL стратегий.

Расширения относительно tsl_optimizer.py:
1. Многоступенчатые ladder профили (3-7 ступеней)
2. ATR-based trail (адаптируется к волатильности пары)
3. Pivot-based exit (TSL до ближайшего 1D пивота сверху)
4. Partial close (50%/30%/70% позиции на разных уровнях)
5. Volatility-adaptive trail (расширение в HIGH_VOL)
6. De-escalation на pullback от peak
7. Combined: ATR + R-based hybrid

Запуск: python tools/pattern_mining/tsl_cascade_optimizer.py [15m|5m]
"""
import sys, time, warnings
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
import tsl_optimizer as tsl_base

HTF_CORE = ["bull_div_1d", "bull_fvg_4h", "wt_os_4h"]
LTF_TRIGGERS = ["bull_ob_near_15m"] if LTF == "15m" else ["atr_up_5m"]
TIME_LIMITS = {"15m": [48, 96, 200], "5m": [144, 288, 600]}[LTF]


def atr_series(df, period=14):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    tr = np.maximum.reduce([
        h - l,
        np.abs(h - np.roll(c, 1)),
        np.abs(l - np.roll(c, 1)),
    ])
    tr[0] = h[0] - l[0]
    return pd.Series(tr).ewm(span=period, adjust=False).mean().values


def sim_cascade(df, entry_i, sl, steps, deesc_r, time_limit, atr_arr=None, atr_trail_mult=0):
    """
    Каскад TSL:
    - steps: [(trigger_R, trail_R)] с эскалацией
    - deesc_r: откат step при pullback от peak
    - atr_trail_mult > 0: добавить ATR-based hard floor (max(R_trail, ATR×mult))
    """
    high = df["high"].values; low = df["low"].values; close = df["close"].values
    n = len(df)
    price = close[entry_i]
    sl_dist = price - sl
    if sl_dist <= 0: return None, "invalid"

    current_sl = sl
    peak_high = price
    current_step = -1
    sorted_steps = sorted(steps, key=lambda s: s[0])

    end_i = min(n - 1, entry_i + 1 + time_limit)
    for i in range(entry_i + 1, end_i + 1):
        if high[i] > peak_high: peak_high = high[i]
        peak_R = (peak_high - price) / sl_dist
        current_R = (close[i] - price) / sl_dist
        pullback_R = peak_R - current_R

        # Эскалация
        for idx, (trig_R, _) in enumerate(sorted_steps):
            if idx > current_step and peak_R >= trig_R:
                current_step = idx

        # Де-эскалация
        if deesc_r > 0 and pullback_R >= deesc_r and current_step > 0:
            current_step -= 1

        # SL по step
        if current_step >= 0:
            trail_R = sorted_steps[current_step][1]
            if trail_R == 0:
                new_sl_r = price
            else:
                new_sl_r = peak_high - trail_R * sl_dist
            # ATR-based hybrid floor
            if atr_arr is not None and atr_trail_mult > 0:
                new_sl_atr = peak_high - atr_arr[i] * atr_trail_mult
                new_sl = max(new_sl_r, new_sl_atr)
            else:
                new_sl = new_sl_r
            if new_sl > current_sl: current_sl = new_sl

        if low[i] <= current_sl:
            return (current_sl - price) / sl_dist, f"step{current_step}"

    return (close[end_i] - price) / sl_dist, "time_exit"


def sim_partial(df, entry_i, sl, partial_at_r, partial_pct, final_trail_r, time_limit):
    """
    Partial close: при +partial_at_r закрываем partial_pct% позиции,
    оставшийся trail @ final_trail_r от peak.
    Возвращает weighted exit R.
    """
    high = df["high"].values; low = df["low"].values; close = df["close"].values
    n = len(df)
    price = close[entry_i]
    sl_dist = price - sl
    if sl_dist <= 0: return None, "invalid"

    end_i = min(n - 1, entry_i + 1 + time_limit)
    partial_done = False
    partial_r = 0
    current_sl = sl
    peak_high = price

    for i in range(entry_i + 1, end_i + 1):
        if high[i] > peak_high: peak_high = high[i]
        peak_R = (peak_high - price) / sl_dist

        # Partial close
        if not partial_done and peak_R >= partial_at_r:
            partial_r = partial_at_r
            partial_done = True
            # Переставляем SL на BE для оставшейся части
            if price > current_sl: current_sl = price

        # Trail для оставшейся части
        if partial_done and final_trail_r > 0:
            new_sl = peak_high - final_trail_r * sl_dist
            if new_sl > current_sl: current_sl = new_sl

        if low[i] <= current_sl:
            remaining_r = (current_sl - price) / sl_dist
            return partial_pct * partial_r + (1 - partial_pct) * remaining_r, f"partial+stop"

    final_r = (close[end_i] - price) / sl_dist
    if partial_done:
        return partial_pct * partial_r + (1 - partial_pct) * final_r, "partial+time"
    return final_r, "time_exit"


# ===== Каскад профилей =====
CASCADE_PROFILES = {
    # Простые ladder'ы (как в tsl_optimizer)
    "ladder_3":            [(0.5, 0.0), (1.0, 1.0), (2.0, 0.5)],
    "ladder_4":            [(0.5, 0.0), (1.0, 1.0), (2.0, 0.5), (3.0, 0.3)],
    "ladder_5":            [(0.5, 0.0), (1.0, 1.0), (2.0, 0.7), (3.0, 0.4), (5.0, 0.2)],
    "ladder_7":            [(0.5, 0.0), (1.0, 1.5), (2.0, 1.0), (3.0, 0.7), (5.0, 0.4), (7.0, 0.2), (10.0, 0.1)],

    # Late activation (как Best Fixed: act=2R trail=2R)
    "late_2R_wide":        [(2.0, 2.0)],
    "late_2R_medium":      [(2.0, 1.5)],
    "late_2R_tight":       [(2.0, 1.0)],

    # 2-step с поздней активацией
    "late_2R_then_tight":  [(2.0, 2.0), (4.0, 1.0)],
    "late_2R_then_runner": [(2.0, 2.0), (5.0, 0.5)],

    # Поздний BE
    "be_at_2R":            [(2.0, 0.0), (4.0, 2.0)],
    "be_at_2R_trail":      [(2.0, 0.0), (3.0, 1.5)],
    "be_at_3R":            [(3.0, 0.0), (5.0, 2.0)],

    # Aggressive
    "agg_5step":           [(1.0, 1.5), (2.0, 1.0), (3.0, 0.5), (5.0, 0.3), (8.0, 0.15)],
    "moonshot":            [(3.0, 3.0), (5.0, 2.0), (10.0, 1.0)],

    # No-trail (просто time limit)
    "no_trail":            [],
}

# Партиальные стратегии
PARTIAL_CONFIGS = [
    # (partial_at_R, partial_pct, final_trail_R)
    (1.0, 0.3, 2.0),   # 30% @ 1R, остальное trail 2R
    (1.0, 0.5, 2.0),   # 50% @ 1R, остальное trail 2R
    (2.0, 0.3, 2.0),   # 30% @ 2R, остальное trail 2R
    (2.0, 0.5, 2.0),   # 50% @ 2R, остальное trail 2R
    (2.0, 0.5, 1.0),   # 50% @ 2R, остальное trail tight 1R
    (3.0, 0.5, 2.0),   # 50% @ 3R, остальное trail 2R
    (2.0, 0.7, 2.0),   # 70% @ 2R (агрессивный close), остальное runner
]


def collect_entries():
    """Сбор entry points + ATR на LTF."""
    print(f"Сбор entry points: HTF={'+'.join(HTF_CORE)}, LTF={'+'.join(LTF_TRIGGERS)}, TF={LTF}")
    symbols = [p.stem for p in HISTORY_LTF.glob("*.parquet")]
    data = {}
    t0 = time.time()
    for sym in symbols:
        # Используем уже написанный сбор из tsl_optimizer
        path_1h = HISTORY_1H / f"{sym}.parquet"
        path_ltf = HISTORY_LTF / f"{sym}.parquet"
        if not path_1h.exists() or not path_ltf.exists(): continue

        res = cb.process_symbol(path_1h)
        if res is None: continue
        htf_flags, _, _ = res
        htf_mask_1h = pd.Series(True, index=htf_flags.index)
        for f in HTF_CORE:
            if f not in htf_flags.columns:
                htf_mask_1h = pd.Series(False, index=htf_flags.index); break
            htf_mask_1h &= htf_flags[f]
        if not htf_mask_1h.any(): continue

        df_ltf = pd.read_parquet(path_ltf)
        df_ltf.columns = [c.lower() for c in df_ltf.columns]
        if "ts" in df_ltf.columns:
            df_ltf["ts"] = pd.to_datetime(df_ltf["ts"], unit="ms", utc=True, errors="coerce")
            df_ltf = df_ltf.set_index("ts")
        df_ltf = df_ltf[["open","high","low","close","volume"]].dropna().sort_index()
        if len(df_ltf) < 500: continue

        ltf_flags = cb.compute_flags(df_ltf, LTF, include_pivots=False)
        htf_shifted = htf_mask_1h.copy()
        htf_shifted.index = htf_shifted.index + pd.Timedelta(hours=1)
        htf_on_ltf = htf_shifted.reindex(df_ltf.index, method="ffill").fillna(False).astype(bool)

        trigger_mask = pd.Series(True, index=df_ltf.index)
        for f in LTF_TRIGGERS:
            if f not in ltf_flags.columns:
                trigger_mask = pd.Series(False, index=df_ltf.index); break
            trigger_mask &= ltf_flags[f]

        entry_mask = (htf_on_ltf & trigger_mask).values
        entry_indices = np.where(entry_mask)[0]
        future_max = max(TIME_LIMITS) + 1
        entry_indices = entry_indices[(entry_indices >= 20) & (entry_indices < len(df_ltf) - future_max)]

        low = df_ltf["low"].values; close = df_ltf["close"].values
        atr_arr = atr_series(df_ltf, 14)
        entries = []
        for i in entry_indices:
            price = close[i]
            sl = low[i-10:i+1].min() * 0.999
            if (price - sl) / price < 0.06:
                entries.append((i, price, sl))
        if entries:
            data[sym] = (df_ltf, entries, atr_arr)

    print(f"  Собрано: {sum(len(d[1]) for d in data.values())} entries из {len(data)} пар за {time.time()-t0:.0f}с")
    return data


def main():
    print(f"TSL CASCADE OPTIMIZER  |  LTF: {LTF}")
    data = collect_entries()
    total = sum(len(d[1]) for d in data.values())
    if total < 30:
        print("Мало entries"); return

    # ============================================
    # Block 1: Cascade profiles × de-escalation × time × atr_mult
    # ============================================
    print(f"\n{'='*80}")
    print(f"[1] Cascade profiles × de-escalation × ATR-hybrid")
    print(f"{'='*80}")
    DEESC = [0.0, 0.5, 1.0, 1.5, 2.0]
    ATR_MULTS = [0, 1.5, 2.5, 4.0]   # 0 = чистый R-based

    cascade_results = []
    for prof_name, steps in CASCADE_PROFILES.items():
        for deesc_r, time_lim, atr_mult in product(DEESC, TIME_LIMITS, ATR_MULTS):
            rs = []
            for sym, (df, entries, atr_arr) in data.items():
                for i, price, sl in entries:
                    if not steps:   # no_trail: только time exit + initial SL
                        end_i = min(len(df) - 1, i + 1 + time_lim)
                        low = df["low"].values
                        # Простой initial SL check
                        sl_dist = price - sl
                        fl = low[i+1:end_i+1]
                        if (fl <= sl).any():
                            r = -1.0
                        else:
                            r = (df["close"].iloc[end_i] - price) / sl_dist
                    else:
                        r, _ = sim_cascade(df, i, sl, steps, deesc_r, time_lim,
                                          atr_arr if atr_mult > 0 else None, atr_mult)
                    if r is not None: rs.append(r)
            if len(rs) < 20: continue
            arr = np.array(rs)
            cascade_results.append({
                "profile": prof_name, "steps": str(steps),
                "deesc_r": deesc_r, "time": time_lim, "atr_mult": atr_mult,
                "n": len(arr), "avgR": float(arr.mean()), "sumR": float(arr.sum()),
                "WR": float((arr > 0).mean()*100), "medR": float(np.median(arr)),
                "maxR": float(arr.max()), "p95": float(np.percentile(arr, 95)),
            })

    df_c = pd.DataFrame(cascade_results).sort_values("avgR", ascending=False)
    print(f"\nТОП-25 каскадных (по avgR):")
    print(f"{'profile':<22} {'desc':>4} {'time':>4} {'atr':>4} {'n':>5} {'avgR':>7} {'WR%':>6} {'sumR':>7} {'medR':>6} {'maxR':>6}")
    for _, r in df_c.head(25).iterrows():
        print(f"{r['profile']:<22} {r['deesc_r']:>4.1f} {int(r['time']):>4} {r['atr_mult']:>4.1f} {int(r['n']):>5} {r['avgR']:>+7.3f} {r['WR']:>5.1f}% {r['sumR']:>+7.1f} {r['medR']:>+6.2f} {r['maxR']:>+6.2f}")

    print(f"\nТОП-10 по sumR:")
    for _, r in df_c.sort_values("sumR", ascending=False).head(10).iterrows():
        print(f"  {r['profile']:<22} desc={r['deesc_r']:.1f} time={int(r['time'])} atr={r['atr_mult']:.1f}  n={int(r['n'])}  sumR={r['sumR']:+.1f}  avgR={r['avgR']:+.3f}")

    # ============================================
    # Block 2: Partial close strategies
    # ============================================
    print(f"\n{'='*80}")
    print(f"[2] Partial Close strategies")
    print(f"{'='*80}")
    partial_results = []
    for partial_r, pct, trail_r in PARTIAL_CONFIGS:
        for time_lim in TIME_LIMITS:
            rs = []
            for sym, (df, entries, _) in data.items():
                for i, price, sl in entries:
                    r, _ = sim_partial(df, i, sl, partial_r, pct, trail_r, time_lim)
                    if r is not None: rs.append(r)
            if len(rs) < 20: continue
            arr = np.array(rs)
            partial_results.append({
                "partial_at_R": partial_r, "partial_pct": pct, "final_trail_R": trail_r,
                "time": time_lim, "n": len(arr),
                "avgR": float(arr.mean()), "sumR": float(arr.sum()),
                "WR": float((arr > 0).mean()*100), "medR": float(np.median(arr)),
                "maxR": float(arr.max()),
            })
    df_p = pd.DataFrame(partial_results).sort_values("avgR", ascending=False)
    print(f"\nТОП-15 partial:")
    print(f"{'p@R':>5} {'pct':>5} {'trail':>6} {'time':>4} {'n':>5} {'avgR':>7} {'WR%':>6} {'sumR':>7}")
    for _, r in df_p.head(15).iterrows():
        print(f"{r['partial_at_R']:>5.1f} {r['partial_pct']:>5.0%} {r['final_trail_R']:>6.1f} {int(r['time']):>4} {int(r['n']):>5} {r['avgR']:>+7.3f} {r['WR']:>5.1f}% {r['sumR']:>+7.1f}")

    # ============================================
    # ИТОГ: best cascade vs best partial vs baseline TP=2R
    # ============================================
    print(f"\n{'='*80}")
    print(f"ИТОГ {LTF}")
    print(f"{'='*80}")
    # Baseline TP=2R fixed
    rs_base = []
    for sym, (df, entries, _) in data.items():
        for i, price, sl in entries:
            sl_dist = price - sl
            tp = price + sl_dist * 2.0
            end_i = min(len(df) - 1, i + 1 + TIME_LIMITS[1])
            fh = df["high"].values[i+1:end_i+1]
            fl = df["low"].values[i+1:end_i+1]
            ht = (fh >= tp).any(); hs = (fl <= sl).any()
            if ht and hs:
                r = 2.0 if np.argmax(fh >= tp) <= np.argmax(fl <= sl) else -1.0
            elif ht: r = 2.0
            elif hs: r = -1.0
            else: r = (df["close"].iloc[end_i] - price) / sl_dist
            rs_base.append(r)
    arr_b = np.array(rs_base)
    bc = df_c.iloc[0]; bp = df_p.iloc[0] if len(df_p) else None
    print(f"{'Strategy':<40} {'n':>5} {'avgR':>7} {'sumR':>8} {'WR%':>6} {'medR':>6} {'maxR':>6}")
    print(f"{'-'*80}")
    print(f"{'Baseline TP=2R fixed':<40} {len(arr_b):>5} {arr_b.mean():>+7.3f} {arr_b.sum():>+8.1f} {(arr_b>0).mean()*100:>5.1f}% {np.median(arr_b):>+6.2f} {arr_b.max():>+6.2f}")
    print(f"{'Best CASCADE':<40} {int(bc['n']):>5} {bc['avgR']:>+7.3f} {bc['sumR']:>+8.1f} {bc['WR']:>5.1f}% {bc['medR']:>+6.2f} {bc['maxR']:>+6.2f}")
    print(f"  └ profile={bc['profile']} desc={bc['deesc_r']} time={int(bc['time'])} atr={bc['atr_mult']}")
    print(f"  └ steps={bc['steps']}")
    if bp is not None:
        print(f"{'Best PARTIAL':<40} {int(bp['n']):>5} {bp['avgR']:>+7.3f} {bp['sumR']:>+8.1f} {bp['WR']:>5.1f}% {bp['medR']:>+6.2f} {bp['maxR']:>+6.2f}")
        print(f"  └ {bp['partial_pct']:.0%} @ {bp['partial_at_R']}R, trail {bp['final_trail_R']}R, time={int(bp['time'])}")

    out_c = PROJECT_ROOT / "data/research/2026-05-19" / f"tsl_cascade_{LTF}_results.csv"
    df_c.to_csv(out_c, index=False, encoding="utf-8")
    out_p = PROJECT_ROOT / "data/research/2026-05-19" / f"tsl_partial_{LTF}_results.csv"
    df_p.to_csv(out_p, index=False, encoding="utf-8")
    print(f"\nСохранено: {out_c}, {out_p}")


if __name__ == "__main__":
    main()
