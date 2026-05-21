"""
Multi-Pattern Portfolio Engine.

Берёт несколько (10-20) топ паттернов из combinator_v2 (LONG + SHORT),
для каждого делает walk-forward, симулирует одновременную торговлю
(портфель из независимых стратегий), считает агрегированную статистику.

Цель:
1. Не упустить хорошие SHORT паттерны (которые не были в walk-forward LTF)
2. Портфельный эффект (~доходность × N стратегий минус корреляция)
3. Снизить variance — разные паттерны срабатывают в разное время

Запуск: python tools/pattern_mining/multi_pattern_portfolio.py
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

PROJECT_ROOT = Path("E:/MTF BOT/CURSOR/crypto_volume_bot")
HISTORY_1H = PROJECT_ROOT / "data/history/1h"

sys.path.insert(0, str(Path(__file__).parent))
import combinator_v2 as cb

TP_R        = 2.0
FUTURE_BARS = 12
MIN_N_WF    = 15
TIME_LIMIT  = 24   # часов (для no_trail strategy)

TRAIN_END = pd.Timestamp("2025-07-01", tz="UTC")

# ===== ТОП ПАТТЕРНЫ ИЗ COMBINATOR_V2 =====
# (берём из dedup, минимум 50 сделок на all период)
TOP_PATTERNS = [
    # ──── LONG ────
    {"id":"L1_golden",        "direction":"LONG",  "factors":["bull_div_1d","bull_fvg_4h","wt_os_4h"]},
    {"id":"L2_wt_double_fvg", "direction":"LONG",  "factors":["wt_os_1d","bull_fvg_4h","wt_os_1h"]},
    {"id":"L3_premium",       "direction":"LONG",  "factors":["wt_os_1d","bull_fvg_4h","wt_os_1h","discount_1d","ote_long_4h"]},
    {"id":"L4_wt_atr",        "direction":"LONG",  "factors":["wt_os_1d","atr_up_4h","wt_os_1h"]},
    {"id":"L5_choch_1d",      "direction":"LONG",  "factors":["bull_choch_1d"]},
    {"id":"L6_choch_4h",      "direction":"LONG",  "factors":["bull_choch_4h"]},
    {"id":"L7_bos_1d",        "direction":"LONG",  "factors":["bull_bos_1d"]},
    {"id":"L8_div_fvg_ob",    "direction":"LONG",  "factors":["bull_div_1d","bull_fvg_4h","bull_ob_1h","wt_os_4h"]},

    # ──── SHORT ────
    {"id":"S1_bos_atr_premium",   "direction":"SHORT", "factors":["atr_cross_down_1d","bear_bos_1d","premium_4h"]},
    {"id":"S2_fvg_bos_premium",   "direction":"SHORT", "factors":["bear_fvg_in_1h","bear_bos_1d","premium_4h"]},
    {"id":"S3_full",              "direction":"SHORT", "factors":["bear_bos_1d","bear_fvg_in_1h","below_ema50_1h","premium_4h"]},
    {"id":"S4_strong",            "direction":"SHORT", "factors":["atr_cross_down_1d","bear_bos_1d","bear_fvg_1d","bear_fvg_in_4h","premium_4h"]},
    {"id":"S5_rsi_cross",         "direction":"SHORT", "factors":["bear_bos_1d","bear_fvg_in_1h","premium_4h","rsi_cross50_down_1d"]},
    {"id":"S6_bos_1d",            "direction":"SHORT", "factors":["bear_bos_1d"]},
    {"id":"S7_choch_1d",          "direction":"SHORT", "factors":["bear_choch_1d"]},
    {"id":"S8_ote_strong",        "direction":"SHORT", "factors":["bear_bos_1d","bear_fvg_in_1h","ote_short_1h","premium_4h"]},
]


def evaluate_pattern_on_data(data: dict, factors: tuple, direction: str, mask_extra=None):
    """Симуляция одного паттерна на all data (либо train/test split)."""
    all_rs = []
    all_ts = []
    all_syms = []
    for sym, (flags, r_long, r_short) in data.items():
        mask = np.ones(len(flags), dtype=bool)
        for f in factors:
            if f not in flags.columns:
                return None
            mask &= flags[f].values
        if mask_extra is not None:
            mask &= mask_extra[sym]
        if not mask.any():
            continue
        rs = r_long if direction == "LONG" else r_short
        valid_mask = mask & ~np.isnan(rs)
        valid_idx = np.where(valid_mask)[0]
        for idx in valid_idx:
            all_rs.append(rs[idx])
            all_ts.append(flags.index[idx])
            all_syms.append(sym)
    if not all_rs:
        return None
    return {"rs": np.array(all_rs), "ts": all_ts, "syms": all_syms}


def stats(rs: np.ndarray):
    if len(rs) == 0:
        return None
    return {"n": len(rs), "avgR": float(rs.mean()), "sumR": float(rs.sum()),
            "WR": float((rs > 0).mean()*100), "medR": float(np.median(rs)),
            "maxR": float(rs.max()), "minR": float(rs.min())}


def split_train_test(data: dict, cutoff: pd.Timestamp):
    """Возвращает (train_masks, test_masks) — словарь boolean masks для каждого sym."""
    train_m, test_m = {}, {}
    for sym, (flags, _, _) in data.items():
        idx = flags.index
        train_m[sym] = np.asarray(idx < cutoff)
        test_m[sym]  = np.asarray(idx >= cutoff)
    return train_m, test_m


def main():
    print("MULTI-PATTERN PORTFOLIO ENGINE")
    print(f"Паттернов в наборе: {len(TOP_PATTERNS)} (LONG: {sum(1 for p in TOP_PATTERNS if p['direction']=='LONG')}, SHORT: {sum(1 for p in TOP_PATTERNS if p['direction']=='SHORT')})")

    # Загрузка
    files = sorted(HISTORY_1H.glob("*.parquet"))
    print(f"\nЗагрузка {len(files)} пар + флаги...")
    t0 = time.time()
    data = {}
    for path in files:
        res = cb.process_symbol(path)
        if res is None: continue
        data[path.stem] = res
    print(f"  Готово за {time.time()-t0:.0f}с. Пар: {len(data)}")

    train_masks, test_masks = split_train_test(data, TRAIN_END)

    # ============================================
    # Оцениваем каждый паттерн отдельно
    # ============================================
    print(f"\n{'='*120}")
    print(f"ОЦЕНКА КАЖДОГО ПАТТЕРНА (TP={TP_R}R, train→test split={TRAIN_END.date()})")
    print(f"{'='*120}")
    print(f"{'id':<22} {'dir':<5} {'all_n':>5} {'all_avgR':>9} {'all_WR':>7} {'tr_n':>4} {'tr_avgR':>8} {'te_n':>4} {'te_avgR':>9} {'te_WR':>7} {'deg':>6}")
    print("-"*120)

    results = []
    aggregate_ts_long  = []   # timestamps всех LONG сигналов (для overlap check)
    aggregate_ts_short = []   # timestamps SHORT
    for pat in TOP_PATTERNS:
        all_res = evaluate_pattern_on_data(data, tuple(pat["factors"]), pat["direction"])
        if not all_res or len(all_res["rs"]) < MIN_N_WF:
            print(f"{pat['id']:<22} {pat['direction']:<5}  --- мало n ---")
            continue
        all_s = stats(all_res["rs"])

        # Train/test split
        tr_res = evaluate_pattern_on_data(data, tuple(pat["factors"]), pat["direction"], train_masks)
        te_res = evaluate_pattern_on_data(data, tuple(pat["factors"]), pat["direction"], test_masks)
        tr_s = stats(tr_res["rs"]) if tr_res else None
        te_s = stats(te_res["rs"]) if te_res else None
        deg = (tr_s["avgR"] - te_s["avgR"]) if (tr_s and te_s) else float("nan")

        results.append({
            "id":        pat["id"],
            "direction": pat["direction"],
            "factors":   " + ".join(pat["factors"]),
            "all_n":     all_s["n"],
            "all_avgR":  all_s["avgR"],
            "all_WR":    all_s["WR"],
            "all_sumR":  all_s["sumR"],
            "train_n":   tr_s["n"] if tr_s else 0,
            "train_avgR":tr_s["avgR"] if tr_s else None,
            "test_n":    te_s["n"] if te_s else 0,
            "test_avgR": te_s["avgR"] if te_s else None,
            "test_WR":   te_s["WR"] if te_s else None,
            "test_maxR": te_s["maxR"] if te_s else None,
            "degradation": deg,
            "stable":    (te_s is not None and te_s["avgR"] > 0 and te_s["WR"] > 50 and abs(deg) < 1.5),
        })

        tr_n = tr_s["n"] if tr_s else 0
        tr_a = tr_s["avgR"] if tr_s else 0
        te_n = te_s["n"] if te_s else 0
        te_a = te_s["avgR"] if te_s else 0
        te_wr= te_s["WR"] if te_s else 0
        print(f"{pat['id']:<22} {pat['direction']:<5} {all_s['n']:>5} {all_s['avgR']:>+9.3f} {all_s['WR']:>6.1f}% {tr_n:>4} {tr_a:>+8.3f} {te_n:>4} {te_a:>+9.3f} {te_wr:>6.1f}% {deg:>+6.2f}")

        # Аккумулируем (sym, ts) для overlap
        if te_res:
            for ts, sym in zip(te_res["ts"], te_res["syms"]):
                lst = aggregate_ts_long if pat["direction"]=="LONG" else aggregate_ts_short
                lst.append((sym, ts, pat["id"], te_res["rs"][len(lst)-1] if len(lst) <= len(te_res["rs"]) else None))

    res_df = pd.DataFrame(results)
    if len(res_df) == 0:
        print("\nНет валидных паттернов."); return

    # ============================================
    # Портфельная статистика (test period)
    # ============================================
    print(f"\n{'='*120}")
    print(f"ПОРТФЕЛЬНАЯ СТАТИСТИКА (test 2025-07..2026-05)")
    print(f"{'='*120}")

    stable = res_df[res_df["stable"]]
    print(f"\nУстойчивых паттернов: {len(stable)}/{len(res_df)}")
    if len(stable):
        # Все сделки портфеля (всех устойчивых) — но без аггрегации overlap
        total_test_n = stable["test_n"].sum()
        weighted_test_avgR = (stable["test_n"] * stable["test_avgR"]).sum() / total_test_n
        total_test_sumR = (stable["test_n"] * stable["test_avgR"]).sum()
        print(f"\n--- Портфель из {len(stable)} устойчивых паттернов ---")
        print(f"  Суммарное кол-во сделок на test: {int(total_test_n)}")
        print(f"  Средний avgR взвешенный:         {weighted_test_avgR:+.3f}")
        print(f"  Суммарный test R:                {total_test_sumR:+.1f}R")
        print(f"  Длительность теста: 11 мес → ~{int(total_test_n/11)} сделок/мес")

    # Только LONG
    long_stable = stable[stable["direction"]=="LONG"]
    short_stable = stable[stable["direction"]=="SHORT"]
    print(f"\nLONG-портфель: {len(long_stable)} паттернов, суммарно {int(long_stable['test_n'].sum())} сделок")
    print(f"SHORT-портфель: {len(short_stable)} паттернов, суммарно {int(short_stable['test_n'].sum())} сделок")

    # ============================================
    # Сохранить
    # ============================================
    out = PROJECT_ROOT / "data/research/2026-05-19" / "multi_pattern_portfolio_results.csv"
    res_df.to_csv(out, index=False, encoding="utf-8")
    print(f"\nСохранено: {out}")

    # Топ устойчивых для дальнейшей реализации
    print(f"\n{'='*120}")
    print(f"РЕКОМЕНДАЦИЯ К РЕАЛИЗАЦИИ — топ-устойчивых")
    print(f"{'='*120}")
    print(f"{'id':<22} {'dir':<5} {'te_n':>4} {'te_avgR':>9} {'te_WR':>7} {'te_max':>7}  factors")
    for _, r in stable.sort_values("test_avgR", ascending=False).iterrows():
        f_str = r["factors"][:60] + ("…" if len(r["factors"])>60 else "")
        print(f"{r['id']:<22} {r['direction']:<5} {int(r['test_n']):>4} {r['test_avgR']:>+9.3f} {r['test_WR']:>6.1f}% {r['test_maxR']:>+7.2f}  {f_str}")


if __name__ == "__main__":
    main()
