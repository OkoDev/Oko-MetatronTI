# -*- coding: utf-8 -*-
"""OTE-CLONE: бэктест OTE-логики на разных TF-комбинациях.
Использует ТОТ ЖЕ OTESignalGenerator что в проде.
Данные — через data_collector.get_ohlcv() (без parquet).
ШАГ 1: сравнение 5 TF-комбо на 10+ парах.
Exit: tp1 +1R (50%) + runner (SL->BE после TP1) + SL. Без TSL.
"""
import asyncio, os, sys, argparse, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
import pandas as pd, numpy as np
from core.smc.ote_signal_generator import OTESignalGenerator
from core.infra.data_collector import RealTimeData

# TF-комбо: (импульсный ТФ, входной ТФ, нужные данные)
COMBOS = {
    "1h->15m":  ("1h", "15m", ["5m","15m","1h"]),
    "1h->5m":   ("1h", "5m",  ["5m","15m","1h"]),
    "4h->1h":   ("4h", "1h",  ["15m","1h","4h"]),
    "1D->1h":   ("1D", "1h", ["15m","1h","1D"]),
    "1D->4h":   ("1D", "4h", ["15m","1h","1D"]),
}

FEE_TAKER = 0.0005  # BingX taker 0.05%


def simulate(fut, entry, sl, tp_runner, direction):
    one_r = abs(entry - sl)
    if one_r <= 0 or len(fut) == 0:
        return None
    long = direction == "long"
    runner_R = (abs(tp_runner - entry) / one_r)
    tp1 = entry + one_r if long else entry - one_r
    hit_tp1 = False; be = entry
    for hi, lo in zip(fut["high"].values, fut["low"].values):
        if not hit_tp1:
            if (long and lo <= sl) or (not long and hi >= sl):
                return -1.0
            if (long and hi >= tp1) or (not long and lo <= tp1):
                hit_tp1 = True
        else:
            if (long and lo <= be) or (not long and hi >= be):
                return 0.5
            if (long and hi >= tp_runner) or (not long and lo <= tp_runner):
                return 0.5 + 0.5 * runner_R
    last = fut["close"].values[-1]
    rr = (last - entry) / one_r if long else (entry - last) / one_r
    return (0.5 + 0.5 * rr) if hit_tp1 else rr


async def load_ohlcv(rt: RealTimeData, sym: str, tfs: list[str], days: int) -> dict[str, pd.DataFrame]:
    """Загружает OHLCV для списка ТФ через data_collector."""
    dfs = {}
    for tf in tfs:
        try:
            df = await rt.get_ohlcv(sym, timeframe=tf, limit=days * 288 if tf == "5m" else days * 96)
            if df is not None and not df.empty:
                dfs[tf] = df
        except Exception as e:
            print(f"  [{sym}] {tf}: {e}")
    return dfs


async def run_one_combo(combo_name: str, impulse_tf: str, entry_tf: str,
                        need_tfs: list[str], pairs: list[str], days: int, step: int):
    """Прогон одной TF-комбинации."""
    print(f"\n{'='*60}")
    print(f"  {combo_name}: impulse={impulse_tf} entry={entry_tf}")
    print(f"{'='*60}")

    rt = RealTimeData()
    gen = OTESignalGenerator()
    results = []
    total_fire = 0

    for sym in pairs[:20]:  # макс 20 пар
        dfs = await load_ohlcv(rt, sym, need_tfs, days)
        if entry_tf not in dfs or impulse_tf not in dfs:
            continue
        if "5m" not in dfs and entry_tf in ("5m", "15m"):
            continue

        df_entry = dfs[entry_tf]
        n = len(df_entry)
        bars_total = days * (288 if entry_tf in ("5m","15m") else 96 if entry_tf == "1h" else 24 if entry_tf == "4h" else 7)
        start = max(100, n - bars_total)

        fire_count = 0
        for i in range(start, n - 1, step):
            t = df_entry.index[i]
            sl_ = {}
            for tf_name, df in dfs.items():
                sl_[tf_name] = df[df.index <= t].tail(1500)
            if entry_tf not in sl_ or len(sl_[entry_tf]) < 30:
                continue
            try:
                sigs = gen.generate(sym, sl_)
            except Exception:
                continue
            for sg in sigs:
                if sg.status != "FIRE":
                    continue
                fut = df_entry.iloc[i+1 : i+1 + (288 if entry_tf in ("5m","15m") else 96)]
                R = simulate(fut, sg.entry, sg.sl, sg.tp_runner, sg.direction)
                if R is None:
                    continue
                one_r = abs(sg.entry - sg.sl)
                sl_frac = (one_r / sg.entry) if sg.entry else 0.0
                fee_R = (FEE_TAKER * 2 / sl_frac) if sl_frac > 0 else 0.0  # round-trip
                results.append({
                    "sym": sym, "combo": combo_name, "R": R, "net": R - fee_R,
                    "sl_frac": sl_frac, "fee_R": fee_R,
                })
                fire_count += 1

        print(f"  {sym:12s} FIRE={fire_count}")
        total_fire += fire_count

    await rt.close()

    if not results:
        print("  НЕТ результатов\n")
        return None

    rs = [r["R"] for r in results]
    nets = [r["net"] for r in results]
    n = len(rs)
    avg = np.mean(rs); wr = np.mean(np.array(rs) > 0) * 100
    net_avg = np.mean(nets)
    fee_avg = np.mean([r["fee_R"] for r in results])
    sl_med = np.median([r["sl_frac"] for r in results]) * 100

    print(f"\n  сделок={n}  GROSS avgR={avg:+.3f}  WR={wr:.1f}%")
    print(f"  NET avgR={net_avg:+.3f}  fee_avg={fee_avg:.3f}R  SL_median={sl_med:.2f}%")
    
    return {"combo": combo_name, "n": n, "gross": avg, "wr": wr, "net": net_avg,
            "fee": fee_avg, "sl_pct": sl_med}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=int, default=5)
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--step", type=int, default=3)
    ap.add_argument("--mode", type=str, default="all",
                    help="all | 1D-4h | 1D-1h | 4h-1h | 1h-15m | 1h-5m")
    args = ap.parse_args()

    # Пары из БД (топ ote_nested)
    import sqlite3
    db = sqlite3.connect("file:subscriptions.db?mode=ro", uri=True)
    cur = db.cursor()
    cur.execute("SELECT DISTINCT symbol FROM simulated_trades WHERE signal_type='ote_nested' ORDER BY created_at DESC LIMIT 50")
    all_pairs = [r[0].split("/")[0].replace(":USDT", "") + "USDT" for r in cur.fetchall()]
    db.close()
    seen = set()
    pairs = [p for p in all_pairs if not (p in seen or seen.add(p))][:args.pairs]

    print(f"OTE-CLONE: {len(pairs)} пар, {args.days} дней, step={args.step}")
    print(f"TF-комбо: {args.mode}")

    combos_to_run = {}
    if args.mode == "all":
        combos_to_run = dict(COMBOS)
    else:
        mode_key = args.mode.replace("-", "->")
        if mode_key in COMBOS:
            combos_to_run[mode_key] = COMBOS[mode_key]
        else:
            print(f"Unknown: {args.mode}. Use: all | {' | '.join(k.replace('->','-') for k in COMBOS)}")
            return

    all_results = []
    for name, (imp_tf, ent_tf, tfs) in combos_to_run.items():
        res = await run_one_combo(name, imp_tf, ent_tf, tfs, pairs, args.days, args.step)
        if res:
            all_results.append(res)

    # Сводная таблица
    print(f"\n{'='*80}")
    print(f"СВОДКА: {'combo':<10s} {'n':>5s} {'GROSS':>8s} {'NET':>8s} {'WR':>6s} {'fee_R':>6s} {'SL%':>6s}")
    print("-" * 55)
    for r in all_results:
        print(f"{r['combo']:<10s} {r['n']:5d} {r['gross']:+8.3f} {r['net']:+8.3f} {r['wr']:5.1f}% {r['fee']:6.3f} {r['sl_pct']:5.2f}%")


if __name__ == "__main__":
    asyncio.run(main())
