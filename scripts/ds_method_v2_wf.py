"""
DS-METHOD-V2-DEEP: Walk-Forward OOS + Parameter Sweep (строго по контракту)
Мера: % net, интрабар, лестница 40/30/30+BE
Sweep: len_htf x len_ltf x wave1_window x min_htf_range_pct
Train: 2024 → Test: 2025-2026
"""
import os, sqlite3, sys, statistics as st, time, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.chdir(str(Path(__file__).resolve().parent.parent))

from core.smc.method_v2_mtf import detect_v2_mtf
from scripts.test_method_v2 import load_df

CACHE = "ohlcv_cache.db"; COSTS = 0.2; SHARES = (0.4, 0.3, 0.3)
TIMEOUT_BARS = 800

def liquid_syms(tf, topn):
    with sqlite3.connect(CACHE) as c:
        syms = [r[0] for r in c.execute("SELECT DISTINCT symbol FROM ohlcv_cache WHERE timeframe=?",(tf,))]
    rank = []
    for s in syms:
        try:
            df = load_df(s, tf)
            if len(df) < 500: continue
            rank.append(((df["close"] * df["volume"]).median(), s))
        except: continue
    rank.sort(reverse=True)
    return [s for _, s in rank[:topn]]

def simulate(df, s):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    idx = df.index; pos = idx.get_indexer([s.entry_ts]); ei = pos[0] if pos[0] >= 0 else None
    if ei is None: return None
    n = len(df); lng = s.direction == "LONG"
    t1, t2, t3 = s.targets; entry, sl = s.entry, s.sl
    rem, pnl = 1.0, 0.0; hit = [False] * 3; tg = [t1, t2, t3]
    for j in range(ei + 1, min(ei + 1 + TIMEOUT_BARS, n)):
        if (l[j] <= sl) if lng else (h[j] >= sl):
            move = (sl - entry) / entry * 100 if lng else (entry - sl) / entry * 100
            pnl += rem * move; rem = 0.0; break
        for k in range(3):
            if hit[k] or rem <= 0: continue
            if (h[j] >= tg[k]) if lng else (l[j] <= tg[k]):
                move = (tg[k] - entry) / entry * 100 if lng else (entry - tg[k]) / entry * 100
                pnl += SHARES[k] * move; rem -= SHARES[k]; hit[k] = True
                if k == 0: sl = entry  # BE после TP1
        if rem <= 1e-9: break
    if rem > 1e-9:
        jl = min(ei + 1 + TIMEOUT_BARS, n) - 1
        move = (c[jl] - entry) / entry * 100 if lng else (entry - c[jl]) / entry * 100
        pnl += rem * move
    return {"net": pnl - COSTS, "dir": s.direction, "year": str(s.entry_ts)[:4],
            "t1": hit[0], "t3": hit[2], "conf": bool(getattr(s, "conf", False))}

def stats(lst):
    if not lst: return "n=0"
    nets = [x["net"] for x in lst]
    w = sum(1 for v in nets if v > 0) / len(nets) * 100
    return f"n={len(nets):>5} net={sum(nets)/len(nets):+.3f}% WR={w:.0f}%"

print("DS-METHOD-V2-DEEP: WF-OOS + PARAMETER SWEEP")
print("=" * 70)

syms = liquid_syms("15m", 100)
print(f"Символов: {len(syms)} (top liquid 100)")

# Sweep grid (реальные параметры detect_v2_mtf)
# imp_bars НЕ существует в сигнатуре — пропускаем, докладываем Даату
grid = []
for lh in [20, 30, 50]:
    for ll in [5, 7, 10]:
        for w1 in [4, 6, 8]:
            for mr in [2, 3, 5]:
                grid.append({"len_htf": lh, "len_ltf": ll, "wave1_window_bars_htf": w1,
                            "min_htf_range_pct": mr, "sl_buf_pct": 0.3})

print(f"Параметров: {len(grid)} (len_htf x len_ltf x wave1 x min_rng)")
print(f"Ожидание: ~{len(grid)*5//60} мин на {len(syms)} символах")
print()

all_trade_data = []
results_table = []

for pi, p in enumerate(grid):
    t0 = time.time()
    trades = []
    for sym in syms:
        try:
            d4 = load_df(sym, "4h"); d15 = load_df(sym, "15m")
            if d4 is None or len(d4) < 100 or d15 is None or len(d15) < 500: continue
            for s in detect_v2_mtf(d4, d15, **p):
                r = simulate(d15, s)
                if r: trades.append(r)
        except: continue

    train = [t for t in trades if t["year"] in ("2022", "2023", "2024")]
    test  = [t for t in trades if t["year"] in ("2025", "2026")]

    if len(train) < 10:
        continue

    t_mean = st.mean([t["net"] for t in train])
    o_mean = st.mean([t["net"] for t in test]) if test else 0
    results_table.append({
        "len_htf": p["len_htf"], "len_ltf": p["len_ltf"],
        "w1": p["wave1_window_bars_htf"], "mr": p["min_htf_range_pct"],
        "train_n": len(train), "train_net": t_mean,
        "test_n": len(test), "test_net": o_mean,
        "total_n": len(trades)
    })
    all_trade_data.append((p, trades))

    dt = time.time() - t0
    print(f"  [{pi+1}/{len(grid)}] lh={p['len_htf']} ll={p['len_ltf']} w1={p['wave1_window_bars_htf']} mr={p['min_htf_range_pct']} | "
          f"train={t_mean:+.3f}% (n={len(train)}) test={o_mean:+.3f}% (n={len(test)}) | {dt:.0f}s", flush=True)

# --- Результаты ---
print(f"\n{'='*70}")
print("РЕЗУЛЬТАТЫ WF-OOS (train 2022-24 → test 2025-26)")
print(f"{'='*70}")

# Сортируем по test_net (OOS)
results_table.sort(key=lambda x: x["test_net"], reverse=True)

print(f"\n{'len_htf':>7} {'len_ltf':>7} {'w1':>4} {'min_rng':>7} {'train_n':>7} {'train%':>8} {'test_n':>6} {'test%':>8}")
print("-" * 65)
for r in results_table[:15]:
    print(f"{r['len_htf']:>7} {r['len_ltf']:>7} {r['w1']:>4} {r['mr']:>7} {r['train_n']:>7} {r['train_net']:>+7.3f} {r['test_n']:>6} {r['test_net']:>+7.3f}")

# Лучший OOS
best = results_table[0] if results_table else None
if best:
    print(f"\nЛУЧШИЙ OOS: lh={best['len_htf']} ll={best['len_ltf']} w1={best['w1']} mr={best['mr']}")
    print(f"  TRAIN: net={best['train_net']:+.3f}% (n={best['train_n']})")
    print(f"  TEST:  net={best['test_net']:+.3f}% (n={best['test_n']})")
    print(f"  VERDICT: {'EDGE OOS+' if best['test_net'] > 0 else 'NO EDGE OOS'}")

# Плато-анализ (широкий диапазон работает?)
print(f"\nПЛАТО-АНАЛИЗ (параметры где test_net > 0):")
positive = [r for r in results_table if r["test_net"] > 0]
if positive:
    for r in positive:
        print(f"  lh={r['len_htf']} ll={r['len_ltf']} w1={r['w1']} mr={r['mr']} test={r['test_net']:+.3f}% (n={r['test_n']})")
    print(f"  Всего положительных OOS: {len(positive)}/{len(results_table)}")
else:
    print("  НИ ОДНОЙ положительной OOS комбинации. Edge НЕ выживает.")

# Примечание о imp_bars
print(f"\n⚠️ Параметр 'imp_bars' не найден в сигнатуре detect_v2_mtf. Использованы len_ltf, wave1_window_bars_htf.")
print(f"Если imp_bars нужен — Даат должен добавить его в детектор.")
