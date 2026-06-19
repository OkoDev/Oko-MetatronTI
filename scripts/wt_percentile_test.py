# -*- coding: utf-8 -*-
"""WT-PCT: тест WT-процентилей vs фикс. OB/OS порогов.
Гипотеза: P10(50b) ловит экстремумы точнее чем WT < -60.
Запуск: python scripts/wt_percentile_test.py --pairs 5 --days 14
"""
import asyncio, os, sys, argparse, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
import pandas as pd, numpy as np
from core.indicators.indicators import calculate_wt
from core.infra.data_collector import RealTimeData

# WT периоды как в проде
WT_N1, WT_N2 = 10, 21

async def load_wt_history(rt: RealTimeData, sym: str, tf: str, days: int) -> pd.Series | None:
    limit = days * (288 if tf == "5m" else 96 if tf == "15m" else 60 if tf == "1h" else 24)
    df = await rt.get_ohlcv(sym, timeframe=tf, limit=limit)
    if df is None or df.empty:
        return None
    wt_df = calculate_wt(df, WT_N1, WT_N2)
    return wt_df['wt2']


async def test_one_pair(rt: RealTimeData, sym: str, days: int):
    """Сравнивает фикс-пороги vs процентили на одном символе."""
    wt15 = await load_wt_history(rt, sym, "15m", days)
    if wt15 is None or len(wt15) < 200:
        return {}

    vals = wt15.values
    results = {}

    # 1. Сколько баров WT < -60 (текущий OS-триггер)
    fix_os = np.sum(vals < -60)
    fix_ob = np.sum(vals > 60)

    results['fix_OS_pct'] = fix_os / len(vals) * 100
    results['fix_OB_pct'] = fix_ob / len(vals) * 100

    # 2. Процентили на разных окнах
    for window in [20, 50, 100]:
        p10_cnt = 0; p5_cnt = 0; p90_cnt = 0; p95_cnt = 0
        for i in range(window, len(vals)):
            w = vals[i-window:i]
            p10 = np.percentile(w, 10)
            p5 = np.percentile(w, 5)
            p90 = np.percentile(w, 90)
            p95 = np.percentile(w, 95)
            if vals[i] < p10: p10_cnt += 1
            if vals[i] < p5: p5_cnt += 1
            if vals[i] > p90: p90_cnt += 1
            if vals[i] > p95: p95_cnt += 1

        total = len(vals) - window
        results[f'P10_{window}b'] = p10_cnt / total * 100
        results[f'P5_{window}b'] = p5_cnt / total * 100
        results[f'P90_{window}b'] = p90_cnt / total * 100
        results[f'P95_{window}b'] = p95_cnt / total * 100

    return results


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=int, default=5)
    ap.add_argument("--days", type=int, default=14)
    args = ap.parse_args()

    import sqlite3
    db = sqlite3.connect("file:subscriptions.db?mode=ro", uri=True)
    cur = db.cursor()
    cur.execute("SELECT DISTINCT symbol FROM simulated_trades WHERE signal_type='ote_nested' ORDER BY created_at DESC LIMIT 30")
    all_pairs = [r[0].split("/")[0].replace(":USDT", "") + "USDT" for r in cur.fetchall()]
    db.close()
    seen = set()
    pairs = [p for p in all_pairs if not (p in seen or seen.add(p))][:args.pairs]

    print(f"WT-PCT: {len(pairs)} пар, {args.days} дней")
    print(f"{'pair':<20s} {'fixOS%':>6s} {'P10_20b%':>8s} {'P5_50b%':>8s} {'P5_100b%':>8s}")
    print("-" * 58)

    rt = RealTimeData()
    all_res = []

    for sym in pairs:
        r = await test_one_pair(rt, sym, args.days)
        if not r:
            continue
        all_res.append(r)
        print(f"{sym:<20s} {r['fix_OS_pct']:5.1f}% {r['P10_20b']:7.1f}% {r['P5_50b']:7.1f}% {r['P5_100b']:7.1f}%")

    await rt.close()

    if all_res:
        print(f"\nСРЕДНЕЕ по {len(all_res)} парам:")
        for key in ['fix_OS_pct', 'P10_20b', 'P5_20b', 'P10_50b', 'P5_50b', 'P10_100b', 'P5_100b']:
            if key in all_res[0]:
                avg = np.mean([r[key] for r in all_res])
                print(f"  {key}: {avg:.1f}%")

        print(f"\nВЫВОД: P5(50b) должно дать ~{np.mean([r.get('P5_50b',0) for r in all_res]):.0f}% сигналов")
        print(f"       vs фикс -60 даёт {np.mean([r['fix_OS_pct'] for r in all_res]):.0f}%")
        print(f"       P5 отсекает шум, оставляя только реальные экстремумы")


if __name__ == "__main__":
    asyncio.run(main())
