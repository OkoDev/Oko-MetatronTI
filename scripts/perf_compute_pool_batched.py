"""
PERF-COMPUTE-POOL Ф1 v2: батчинг-стратегия.
N пар → 1 воркер → 1 spawn. Амортизация оверхеда.
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
N_PAIRS = 47  # all available
TF_LIST = ["5m", "15m", "1h"]
ATR_PERIOD, FACTOR = 43, 1.25


# ═══════════════════════════════════════════════════════════════════════════════
# BATCH worker: N пар × 1 TF за 1 spawn
# ═══════════════════════════════════════════════════════════════════════════════

def _worker_trend_batch(args: tuple) -> tuple:
    """Принимает [(sym, ohlcv_np), ...] для одного TF."""
    tf, batch = args
    try:
        from core.indicators.indicators import calculate_trend
        results = []
        for sym, arr in batch:
            df = pd.DataFrame(arr, columns=["open", "high", "low", "close", "volume"])
            r = calculate_trend(df, atr_period=ATR_PERIOD, factor=FACTOR)
            trend = int(r["trend"].values[-1]) if r is not None and "trend" in r.columns else 0
            results.append((sym, tf, trend))
        return ("ok", len(results), results)
    except Exception as e:
        return ("err", 0, str(e))


def _worker_wt_batch(args: tuple) -> tuple:
    """Принимает [(sym, ohlcv_np), ...] для одного TF."""
    tf, batch = args
    try:
        from core.indicators.indicators import calculate_wt
        results = []
        for sym, arr in batch:
            df = pd.DataFrame(arr, columns=["open", "high", "low", "close", "volume"])
            r = calculate_wt(df, n1=10, n2=21)
            wt1 = float(r["wt1"].values[-1]) if r is not None and "wt1" in r.columns else 0.0
            results.append((sym, tf, wt1))
        return ("ok", len(results), results)
    except Exception as e:
        return ("err", 0, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("Ф1 v2: БАТЧИНГ ProcessPoolExecutor")
    print("=" * 60)

    # ── Сбор данных ──────────────────────────────────────────────────────────
    batches = {}
    for tf in TF_LIST:
        tf_dir = HIST / tf
        if not tf_dir.exists():
            continue
        batch = []
        for fpath in sorted(tf_dir.glob("*.parquet"))[:N_PAIRS]:
            df = pd.read_parquet(fpath)
            if isinstance(df.index, pd.DatetimeIndex) and df.index.tz:
                df.index = df.index.tz_localize(None)
            df.columns = [c.lower() for c in df.columns]
            tail = df.tail(160)
            cols = ["open", "high", "low", "close", "volume"]
            arr = tail[cols].to_numpy(dtype=np.float32)
            batch.append((fpath.stem, arr))
        batches[tf] = batch

    total_pairs = sum(len(b) for b in batches.values())
    print(f"Data: {total_pairs} пар ({len(TF_LIST)} TF): "
          f"{', '.join(f'{tf}={len(b)}' for tf,b in batches.items())}")

    # ── Sync benchmark ───────────────────────────────────────────────────────
    from core.indicators.indicators import calculate_trend, calculate_wt

    sync_trend = []
    sync_wt = []
    for tf, batch in batches.items():
        for sym, arr in batch[:5]:  # 5 на замер
            df = pd.DataFrame(arr, columns=["open", "high", "low", "close", "volume"])
            t0 = time.perf_counter()
            _ = calculate_trend(df, atr_period=ATR_PERIOD, factor=FACTOR)
            sync_trend.append((time.perf_counter() - t0) * 1000)
            t0 = time.perf_counter()
            _ = calculate_wt(df, n1=10, n2=21)
            sync_wt.append((time.perf_counter() - t0) * 1000)

    print(f"\nSync trend: {np.mean(sync_trend):.1f} ms/paru  WT: {np.mean(sync_wt):.1f} ms/paru")

    # ── Pool BATCHED: 1 воркер = 1 TF × все пары─────────────────────────────
    for n_workers in [2, 3]:
        tf_tasks = [(tf, batch) for tf, batch in batches.items()]

        # Trend
        t0 = time.perf_counter()
        with ProcessPoolExecutor(max_workers=n_workers) as ex:
            futs = [ex.submit(_worker_trend_batch, t) for t in tf_tasks]
            results = [f.result() for f in futs]
        trend_ms = (time.perf_counter() - t0) * 1000
        trend_total = sum(r[1] for r in results if r[0] == "ok")
        errors_t = sum(1 for r in results if r[0] == "err")

        # WT
        t0 = time.perf_counter()
        with ProcessPoolExecutor(max_workers=n_workers) as ex:
            futs = [ex.submit(_worker_wt_batch, t) for t in tf_tasks]
            _ = [f.result() for f in futs]
        wt_ms = (time.perf_counter() - t0) * 1000

        print(f"\nPool ({n_workers}w) batched:")
        print(f"  Trend: {trend_ms:.0f} ms ({trend_total} пар) — "
              f"{trend_ms/trend_total:.1f} ms/paru, errors={errors_t}")
        print(f"  WT:    {wt_ms:.0f} ms ({trend_total} пар) — "
              f"{wt_ms/trend_total:.1f} ms/paru")

    # ── Pickle overhead ──────────────────────────────────────────────────────
    raw_size = 0
    for tf, batch in batches.items():
        raw_size += sum(a.nbytes for _, a in batch)
    t0 = time.perf_counter()
    data = pickle.dumps(tf_tasks)
    pickle_ms = (time.perf_counter() - t0) * 1000
    pickle_mb = len(data) / 1024 / 1024

    sync_total_ms = total_pairs * (np.mean(sync_trend) + np.mean(sync_wt))
    print(f"\nPickle: {pickle_mb:.1f} MB, {pickle_ms:.1f} ms")
    print(f"Raw numpy: {raw_size/1024/1024:.1f} MB")
    print(f"Sync total: {sync_total_ms:.0f} ms ({total_pairs} пар x (trend+WT))")
    print(f"Overhead ratio: {pickle_ms/sync_total_ms*100:.1f}%")


if __name__ == "__main__":
    main()
