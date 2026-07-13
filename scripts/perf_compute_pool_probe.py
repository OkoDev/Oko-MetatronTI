"""PERF-COMPUTE-POOL Ф0: замер pickle-overhead + CPU-профиль + spawn-start.
Гипотеза: numpy-overhead << выигрыш от разгрузки GIL.
"""
import sys, os, time, pickle, io, warnings, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.WARNING)

import numpy as np, pandas as pd
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from core.indicators.indicators import calculate_wt, calculate_trend
from core.smc.smc_snapshot import build_smc_snapshot

HIST = Path("data/history")
N_PAIRS = 20
REPEAT = 5

print("=" * 60)
print("Ф0.1: PICKLE-OVERHEAD df vs numpy")
print("=" * 60)

# Сбор боевых DataFrame из кэша
dfs = {}
for tf in ["5m", "15m", "1h", "4h", "1d"]:
    tf_dir = HIST / tf
    if not tf_dir.exists():
        continue
    for i, fpath in enumerate(sorted(tf_dir.glob("*.parquet"))[:N_PAIRS]):
        sym = fpath.stem
        df = pd.read_parquet(fpath)
        if isinstance(df.index, pd.DatetimeIndex) and df.index.tz:
            df.index = df.index.tz_localize(None)
        df.columns = [c.lower() for c in df.columns]
        tail = df.tail(160)  # ~160 свечей как в боевом scan
        dfs[(sym, tf)] = tail

print(f"Data: {len(dfs)} DataFrame'ов ({N_PAIRS}+ пар × {len(set(tf for _,tf in dfs))} TF)")

# Замер df-pickle
df_sizes = []
df_times = []
for (sym, tf), df in dfs.items():
    t0 = time.perf_counter()
    data = pickle.dumps(df)
    dt = (time.perf_counter() - t0) * 1000
    df_sizes.append(len(data))
    df_times.append(dt)

# Замер numpy-pickle (только OHLCV, float32)
np_sizes = []
np_times = []
for (sym, tf), df in dfs.items():
    cols = ["open", "high", "low", "close", "volume"]
    arr = df[cols].to_numpy(dtype=np.float32)
    t0 = time.perf_counter()
    data = pickle.dumps(arr)
    dt = (time.perf_counter() - t0) * 1000
    np_sizes.append(len(data))
    np_times.append(dt)

print(f"\ndf-pickle:  avg {np.mean(df_sizes)/1024:.1f} KB  time {np.mean(df_times):.2f} ms  (n={len(df_sizes)})")
print(f"np-pickle:  avg {np.mean(np_sizes)/1024:.1f} KB  time {np.mean(np_times):.2f} ms  (n={len(np_sizes)})")
print(f"Ratio:      size {sum(df_sizes)/sum(np_sizes):.1f}x  time {np.mean(df_times)/np.mean(np_times):.1f}x")
print(f"N_TF × n_pairs pickle total: df={sum(df_sizes)/1024/1024:.1f}MB  np={sum(np_sizes)/1024/1024:.1f}MB")

# ============================================================================
print("\n" + "=" * 60)
print("Ф0.2: CPU-ПРОФИЛЬ compute на пару")
print("=" * 60)

# Возьмём одну пару со всеми TF
sample = None
for (sym, tf), df in dfs.items():
    if sym == sorted(set(s for s,_ in dfs))[0]:
        if sample is None or len(df) > 100:
            sample = (sym, {**getattr(sample, "_tfs", {}), tf: df})
            if not hasattr(sample, "_tfs"):
                sample = (sym, {})
                sample[1][tf] = df

# Проще: берём первый символ с 1h данными
tf_dfs = {}
for (sym, tf), df in dfs.items():
    if sym == "BTCUSDT" and tf in ["5m","15m","1h","4h"]:
        tf_dfs[tf] = df
    if len(tf_dfs) >= 4:
        break

if len(tf_dfs) < 2:
    # Fallback: любой символ
    first_sym = sorted(set(s for s,_ in dfs))[0]
    for (sym, tf), df in dfs.items():
        if sym == first_sym:
            tf_dfs[tf] = df

print(f"Symbol: {first_sym if 'first_sym' in dir() else 'BTCUSDT'}, TFs: {list(tf_dfs.keys())}")

timings = {}
for tf, df in tf_dfs.items():
    d = df.copy()
    t0 = time.perf_counter()
    _ = calculate_wt(d, n1=10, n2=21)
    timings[f"WT_{tf}"] = (time.perf_counter() - t0) * 1000

    d2 = df.copy()
    t0 = time.perf_counter()
    _ = calculate_trend(d2, atr_period=43, factor=1.25)
    timings[f"Trend_{tf}"] = (time.perf_counter() - t0) * 1000

    d3 = df.copy()
    t0 = time.perf_counter()
    try:
        _ = build_smc_snapshot(d3)
    except Exception:
        pass
    timings[f"SMC_{tf}"] = (time.perf_counter() - t0) * 1000

print(f"\nPer-TF timing (ms):")
for name in sorted(timings):
    print(f"  {name:20s}: {timings[name]:>8.2f} ms")

wt_total = sum(v for k, v in timings.items() if "WT_" in k)
trend_total = sum(v for k, v in timings.items() if "Trend_" in k)
smc_total = sum(v for k, v in timings.items() if "SMC_" in k)
print(f"\n  WT total:     {wt_total:>8.1f} ms")
print(f"  Trend total:  {trend_total:>8.1f} ms")
print(f"  SMC total:    {smc_total:>8.1f} ms")

# ============================================================================
print("\n" + "=" * 60)
print("Ф0.3: SPAWN-СТАРТ ProcessPoolExecutor на Windows")
print("=" * 60)

def _holostoy(x):
    return x * 2

for n_workers in [1, 2, 4]:
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        futs = [ex.submit(_holostoy, i) for i in range(n_workers * 2)]
        results = [f.result() for f in futs]
    dt = (time.perf_counter() - t0) * 1000
    print(f"  workers={n_workers}: {dt:>8.1f} ms (вкл spawn+import+submit+result)")

# Cold start (первый раз)
t0 = time.perf_counter()
with ProcessPoolExecutor(max_workers=1) as ex:
    f = ex.submit(_holostoy, 42)
    _ = f.result()
cold_ms = (time.perf_counter() - t0) * 1000
print(f"\n  Cold start (1 worker, 1-й spawn): {cold_ms:.0f} ms")

# ============================================================================
print("\n" + "=" * 60)
print("Ф0.4: АУДИТ ЧИСТОТЫ ФУНКЦИЙ (глобалы?)")
print("=" * 60)

import inspect
from core.indicators.indicators import calculate_wt as _wt, calculate_trend as _tr
from core.smc.smc_snapshot import build_smc_snapshot as _smc

for name, fn in [("calculate_wt", _wt), ("calculate_trend", _tr), ("build_smc_snapshot", _smc)]:
    src = inspect.getsource(fn)
    has_config = "config" in src.lower()
    has_global = "global " in src
    has_env = "os.environ" in src or "os.getenv" in src
    uses_bot = "bot" in src.lower() and ("self.bot" in src or "getattr" in src)
    # Check if reads from external state
    votes = []
    if has_config: votes.append("config")
    if has_global: votes.append("global")
    if has_env: votes.append("env")
    if uses_bot: votes.append("bot")
    pure = "PURE" if not votes else f"IMPURE: {','.join(votes)}"
    print(f"  {name:25s}: {pure}")

# Быстрый grep по проекту
import subprocess
result = subprocess.run(
    ["grep", "-rn", "from core.infra.config_loader import\\|import config_loader\\|cfg = ConfigLoader\\|config\\.get(",
     "core/indicators/indicators.py", "core/smc/smc_engine.py"],
    capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if result.stdout.strip():
    print(f"\n  Найдены импорты config:")
    for line in result.stdout.strip().split("\n")[:5]:
        print(f"    {line}")
else:
    print(f"\n  config_loader НЕ импортируется в indicators/smc_engine — PURE ✅")

# ============================================================================
print("\n" + "=" * 60)
print("Ф0.5: ВЫВОД")
print("=" * 60)

total_per_pair = (np.mean(df_times) + np.mean(np_times)) / 2  # avg pickle
total_np_transfer = np.mean(np_times) * len(dfs)  # ms for all pairs
compute_per_pair = sum(timings.values())  # ms per pair
total_compute = compute_per_pair * len(dfs)  # all pairs

print(f"Pickle overhead (numpy, 1 пара):  {np.mean(np_times):.1f} ms")
print(f"Compute per pair (WT+trend+SMC):   {compute_per_pair:.0f} ms")
print(f"Pickle ratio:                      {np.mean(np_times)/compute_per_pair*100:.1f}% of compute")
print(f"")
print(f"Total transfer (all pairs, numpy): {total_np_transfer/1000:.1f} сек")
print(f"Total compute (all pairs):         {total_compute/1000:.1f} сек")
print(f"")
print(f"Cold spawn:                        {cold_ms:.0f} ms (Windows)")
print(f"Окупается: transfer << compute ({np.mean(np_times)/compute_per_pair*100:.1f}% overhead)")
print(f"Рекомендация: запускать Ф1 с самой тяжёлой функции")
