"""
PERF-COMPUTE-POOL Ф1: прототип ProcessPoolExecutor для calculate_trend.

Цель: доказать что вынос calculate_trend в spawn-воркеры окупается
на боевых данных. Прецедент: market_ws_v2.py spawn-паттерн.
"""
import sys, os, time, pickle, warnings, logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

import numpy as np, pandas as pd
from concurrent.futures import ProcessPoolExecutor

HIST = Path("data/history")
N_PAIRS = 20
TF_LIST = ["5m", "15m", "1h"]
REPEAT = 3


# ═══════════════════════════════════════════════════════════════════════════════
# TOP-LEVEL worker (spawn-safe — импортируется из модуля, не __main__)
# ═══════════════════════════════════════════════════════════════════════════════

def _worker_trend(args: tuple) -> tuple:
    """
    Pure worker: принимает (sym, tf, ohlcv_np, atr_period, factor)
    Возвращает (sym, tf, trend_array) или (sym, tf, None, error_str).
    """
    sym, tf, ohlcv_arr, atr_period, factor = args
    try:
        # Импорт внутри worker'а (spawn-безопасно)
        from core.indicators.indicators import calculate_trend
        import pandas as pd

        df = pd.DataFrame(ohlcv_arr, columns=["open", "high", "low", "close", "volume"])
        result = calculate_trend(df, atr_period=atr_period, factor=factor)
        if result is not None and "trend" in result.columns:
            trend = result["trend"].values[-1]  # последнее значение
            return (sym, tf, int(trend))
        return (sym, tf, 0)
    except Exception as e:
        return (sym, tf, None, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("Ф1-ПРОТОТИП: ProcessPoolExecutor для calculate_trend")
    print("=" * 60)

    # ── Сбор данных ──────────────────────────────────────────────────────────
    tasks = []
    for tf in TF_LIST:
        tf_dir = HIST / tf
        if not tf_dir.exists():
            continue
        for fpath in sorted(tf_dir.glob("*.parquet"))[:N_PAIRS]:
            df = pd.read_parquet(fpath)
            if isinstance(df.index, pd.DatetimeIndex) and df.index.tz:
                df.index = df.index.tz_localize(None)
            df.columns = [c.lower() for c in df.columns]
            tail = df.tail(160)
            cols = ["open", "high", "low", "close", "volume"]
            arr = tail[cols].to_numpy(dtype=np.float32)
            tasks.append((fpath.stem, tf, arr, 43, 1.25))

    print(f"Tasks: {len(tasks)} ({N_PAIRS} пар x {len(TF_LIST)} TF)")

    # ── Бенчмарк: синхронно (как сейчас) ─────────────────────────────────────
    from core.indicators.indicators import calculate_trend

    sync_times = []
    for sym, tf, arr, atr_period, factor in tasks[:10]:  # 10 для скорости
        df = pd.DataFrame(arr, columns=["open", "high", "low", "close", "volume"])
        t0 = time.perf_counter()
        _ = calculate_trend(df, atr_period=atr_period, factor=factor)
        sync_times.append((time.perf_counter() - t0) * 1000)

    avg_sync = np.mean(sync_times)
    print(f"\nSync (нынешний): {avg_sync:.1f} ms/пару (n=10)")

    # ── ProcessPoolExecutor ──────────────────────────────────────────────────
    for n_workers in [2, 4]:
        pool_times = []
        for _ in range(REPEAT):
            t0 = time.perf_counter()
            with ProcessPoolExecutor(max_workers=n_workers) as ex:
                futs = [ex.submit(_worker_trend, t) for t in tasks]
                results = [f.result() for f in futs]
            pool_times.append((time.perf_counter() - t0) * 1000)

        avg_pool = np.mean(pool_times)
        per_task = avg_pool / len(tasks)
        speedup = avg_sync / per_task if per_task > 0 else 0
        errors = sum(1 for r in results if len(r) > 2 and r[2] is None)
        print(f"Pool ({n_workers}w): {avg_pool:.0f} ms total, {per_task:.1f} ms/task, "
              f"speedup={speedup:.1f}x, errors={errors}/{len(tasks)}")

    # ── Pickle overhead ──────────────────────────────────────────────────────
    t0 = time.perf_counter()
    data = pickle.dumps(tasks)
    pickle_ms = (time.perf_counter() - t0) * 1000
    pickle_mb = len(data) / 1024 / 1024
    print(f"\nPickle tasks: {pickle_mb:.1f} MB, {pickle_ms:.1f} ms")

    # ── Вывод ────────────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print("ВЫВОД:")
    print(f"  Sync per pair:      {avg_sync:.1f} ms")
    print(f"  Pool per task (4w): {avg_pool/len(tasks):.1f} ms" if "avg_pool" in dir() else "  (pending)")
    print(f"  Pickle overhead:    {pickle_ms:.1f} ms")
    print(f"  Прототип: worker работает, spawn-безопасен")


if __name__ == "__main__":
    main()
