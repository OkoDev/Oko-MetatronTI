"""
GENERATE TOP-50 FEATURES FOR feature_weights TABLE
Mining ALL 227 features from trade_features for ote_nested
All metrics in % net (NOT R!)
Output: SQL-ready feature_weights + full report
"""
import sqlite3, json, statistics as st
from collections import Counter
import numpy as np

DB = "subscriptions.db"
BIG_THRESHOLD = 2.5
MIN_TRADES = 15

conn = sqlite3.connect(DB); cur = conn.cursor()

# Все ote_nested с features
cur.execute("""SELECT s.profit_pct, tf.features_json
FROM simulated_trades s
JOIN trade_features tf ON s.id = tf.trade_id
WHERE s.status IN ('SL','TP','TSL') AND s.signal_type = 'ote_nested'
AND s.profit_pct IS NOT NULL AND tf.features_json IS NOT NULL""")
rows = cur.fetchall()
print(f"Loaded: {len(rows)} ote_nested trades with features\n")

# Собираем все фичи
all_features = Counter()
trade_data = []
for pct, fj in rows:
    feats = set()
    try:
        j = json.loads(fj)
        ctx = j.get("context", {})
        for cat in ["smc", "trend", "mom", "rsi", "wt", "pivot", "volume"]:
            for k, v in ctx.get(cat, {}).items():
                if v == 1:
                    feats.add(f"{cat}.{k}")
                    all_features[f"{cat}.{k}"] += 1
    except:
        pass
    trade_data.append((pct, feats))

# Только фичи с >= MIN_TRADES вхождений
valid_features = {f for f, c in all_features.items() if c >= MIN_TRADES}
print(f"Total features: {len(all_features)}")
print(f"Features with >= {MIN_TRADES} trades: {len(valid_features)}")

# Расчёт delta% для каждой фичи
feature_stats = []
baseline_nets = [r[0] for r in trade_data]
baseline_avg = st.mean(baseline_nets)
baseline_big = sum(1 for p in baseline_nets if p >= BIG_THRESHOLD) / len(baseline_nets) * 100

for feat_name in sorted(valid_features):
    cat, fname = feat_name.split(".", 1)
    with_f = [r[0] for r in trade_data if feat_name in r[1]]
    without_f = [r[0] for r in trade_data if feat_name not in r[1]]
    if len(with_f) < MIN_TRADES or len(without_f) < MIN_TRADES:
        continue

    avg_with = st.mean(with_f)
    avg_without = st.mean(without_f)
    delta = avg_with - avg_without

    # BIG%
    big_with = sum(1 for p in with_f if p >= BIG_THRESHOLD) / len(with_f) * 100
    big_without = sum(1 for p in without_f if p >= BIG_THRESHOLD) / len(without_f) * 100

    # Win rate
    wr_with = sum(1 for p in with_f if p > 0) / len(with_f) * 100
    wr_without = sum(1 for p in without_f if p > 0) / len(without_f) * 100

    # t-statistic
    n1, n2 = len(with_f), len(without_f)
    s1 = np.std(with_f, ddof=1) if n1 > 1 else 1
    s2 = np.std(without_f, ddof=1) if n2 > 1 else 1
    se = np.sqrt(s1 ** 2 / n1 + s2 ** 2 / n2)
    t_stat = abs(delta / se) if se > 0 else 0

    feature_stats.append({
        "feature": feat_name,
        "delta_pct": delta,
        "n": len(with_f),
        "avg_with": avg_with,
        "avg_without": avg_without,
        "wr_with": wr_with,
        "wr_without": wr_without,
        "big_pct": big_with,
        "big_diff": big_with - big_without,
        "t_stat": t_stat,
        "direction": "EDGE+" if delta > 0 else "EDGE-",
    })

# Сортировка по |delta|
feature_stats.sort(key=lambda x: -abs(x["delta_pct"]))

# === ВЫВОД ===
print("=" * 100)
print(f"TOP-50 FEATURES for feature_weights (baseline: avg={baseline_avg:+.3f}% BIG={baseline_big:.1f}%)")
print("=" * 100)
print(
    f"{'#':<3} {'feature':<45} {'n':>5} {'avg_with':>8} {'avg_wo':>8} {'delta':>8} {'WR_with':>6} {'BIG%':>6} {'|t|':>5}"
)
print("-" * 100)

for i, fs in enumerate(feature_stats[:50]):
    print(
        f"{i + 1:<3} {fs['feature']:<45} {fs['n']:>5} {fs['avg_with']:>+7.3f}% {fs['avg_without']:>+7.3f}% "
        f"{fs['delta_pct']:>+7.3f}% {fs['wr_with']:>5.0f}% {fs['big_pct']:>5.1f}% {fs['t_stat']:>5.1f} {fs['direction']}"
    )

# === SQL для feature_weights ===
print()
print("=" * 60)
print("SQL: INSERT INTO feature_weights (top-50, delta only)")
print("=" * 60)
for fs in feature_stats[:50]:
    weight = round(1.0 + fs["delta_pct"] * 0.2, 3)  # 0.3% delta = +0.06 weight
    weight = max(0.1, min(3.0, weight))
    print(
        f"INSERT INTO feature_weights (feature, regime, delta_pct, n, weight, validated) "
        f"VALUES ('{fs['feature']}', 'any', {fs['delta_pct']:.4f}, {fs['n']}, {weight:.4f}, 1);"
    )

# === СТАТИСТИКА ===
print()
print("=" * 60)
print("SUMMARY")
print("=" * 60)
edge_plus = [fs for fs in feature_stats[:50] if fs["delta_pct"] > 0.05]
edge_minus = [fs for fs in feature_stats[:50] if fs["delta_pct"] < -0.05]
neutral = [fs for fs in feature_stats[:50] if abs(fs["delta_pct"]) <= 0.05]
print(f"EDGE+ (delta>0.05%): {len(edge_plus)} features")
print(f"EDGE- (delta<-0.05%): {len(edge_minus)} features")
print(f"NEUTRAL: {len(neutral)} features")

# По категориям
cats = Counter()
for fs in feature_stats[:50]:
    cat = fs["feature"].split(".")[0]
    cats[cat] += 1
print(f"\nTop-50 by category: {dict(cats.most_common())}")

# Топ BIG% features
print(f"\nTop-10 by BIG% (>={BIG_THRESHOLD}% moves):")
by_big = sorted(feature_stats[:50], key=lambda x: -x["big_pct"])
for fs in by_big[:10]:
    print(f"  {fs['feature']:<45} BIG={fs['big_pct']:.0f}% (n={fs['n']})")

print(f"\nTop-10 by BIG diff (vs without):")
by_big_diff = sorted(feature_stats[:50], key=lambda x: -x["big_diff"])
for fs in by_big_diff[:10]:
    print(f"  {fs['feature']:<45} BIG_diff={fs['big_diff']:+.1f}%")

conn.close()
