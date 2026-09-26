"""
Анализ: насколько mtf_wt_spread из features_json коррелирует с реальным R?
Проверяем гипотезу сжатия WT как улучшенного детектора RANGE.
"""
import sqlite3, json, sys, statistics
sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect('subscriptions.db')
cur = conn.cursor()

cur.execute("""
SELECT regime, signal_type, direction, R_multiple, features_json
FROM simulated_trades
WHERE status != 'OPEN' AND R_multiple IS NOT NULL
  AND features_json IS NOT NULL AND regime IS NOT NULL
  AND created_at > '2026-04-15'
""")
rows = cur.fetchall()
print(f"Сделок для анализа (post-15.04): {len(rows)}")

# Разбираем features_json
data = []
for regime, sig, direction, r_mult, fj in rows:
    try:
        d = json.loads(fj)
        wt1_15m = d.get('wt1_value') or d.get('wt1')
        wt1_1h  = d.get('htf_wt1_1h')
        wt2_1h  = d.get('htf_wt2_1h')
        spread_1h = d.get('mtf_wt_spread_1h')  # |wt1-wt2| на 1h
        spread_4h = d.get('mtf_wt_spread_4h')
        wt_zone   = d.get('wt_zone')

        # Вычисляем spread_1h если нет готового
        if spread_1h is None and wt1_1h is not None and wt2_1h is not None:
            try:
                spread_1h = abs(float(wt1_1h) - float(wt2_1h))
            except:
                pass

        data.append({
            'regime': regime,
            'sig': sig,
            'dir': direction,
            'R': float(r_mult),
            'wt1_15m': float(wt1_15m) if wt1_15m is not None else None,
            'wt1_1h': float(wt1_1h) if wt1_1h is not None else None,
            'wt2_1h': float(wt2_1h) if wt2_1h is not None else None,
            'spread_1h': float(spread_1h) if spread_1h is not None else None,
            'spread_4h': float(spread_4h) if spread_4h is not None else None,
            'wt_zone': wt_zone,
        })
    except Exception as e:
        pass

print(f"Разобрано: {len(data)}")
spread_ok = [d for d in data if d['spread_1h'] is not None]
print(f"Имеют spread_1h: {len(spread_ok)}")

# ===============================
# БЛОК 1: spread_1h vs regime — правильно ли текущий классификатор?
# ===============================
print("\n=== БЛОК 1: spread_1h (|wt1-wt2| на 1h) по режимам ===")
from collections import defaultdict
regime_spread = defaultdict(list)
regime_r = defaultdict(list)
for d in spread_ok:
    regime_spread[d['regime']].append(d['spread_1h'])
    regime_r[d['regime']].append(d['R'])

print(f"{'Режим':<15} {'n':>5} {'avg_spread':>11} {'med_spread':>11} {'avgR':>7}")
print("-"*55)
for regime in ['TREND_UP', 'TREND_DOWN', 'RANGE', 'HIGH_VOL']:
    vals = regime_spread[regime]
    rs   = regime_r[regime]
    if not vals:
        continue
    print(f"  {regime:<13} {len(vals):>5}  {sum(vals)/len(vals):>10.1f}  {sorted(vals)[len(vals)//2]:>10.1f}  {sum(rs)/len(rs):>+6.3f}")

# ===============================
# БЛОК 2: Корреляция spread_1h с R_multiple
# ===============================
print("\n=== БЛОК 2: R по бакетам spread_1h (все режимы) ===")
buckets = {
    '0-10 (flat)':    [d for d in spread_ok if d['spread_1h'] < 10],
    '10-25 (low)':    [d for d in spread_ok if 10 <= d['spread_1h'] < 25],
    '25-50 (medium)': [d for d in spread_ok if 25 <= d['spread_1h'] < 50],
    '50-80 (high)':   [d for d in spread_ok if 50 <= d['spread_1h'] < 80],
    '>80 (extreme)':  [d for d in spread_ok if d['spread_1h'] >= 80],
}
print(f"{'Spread 1h':<20} {'n':>5} {'avgR':>7} {'WR%':>7} {'режимы'}")
print("-"*70)
for label, items in buckets.items():
    if not items:
        continue
    avgR = sum(d['R'] for d in items) / len(items)
    wr   = sum(1 for d in items if d['R'] > 0) * 100 / len(items)
    regime_counts = defaultdict(int)
    for d in items:
        regime_counts[d['regime']] += 1
    regime_str = ', '.join(f"{k}:{v}" for k, v in sorted(regime_counts.items(), key=lambda x: -x[1]))
    print(f"  {label:<18} {len(items):>5}  {avgR:>+6.3f}  {wr:>6.1f}%  {regime_str}")

# ===============================
# БЛОК 3: "Ложный RANGE" — сделки где режим=RANGE но spread_1h > 25 (фактически тренд)
# ===============================
print("\n=== БЛОК 3: 'Ложный RANGE' (режим=RANGE, spread_1h > 25) ===")
false_range = [d for d in spread_ok if d['regime'] == 'RANGE' and d['spread_1h'] > 25]
true_range  = [d for d in spread_ok if d['regime'] == 'RANGE' and d['spread_1h'] <= 25]
print(f"  RANGE + spread>25 (ложный): n={len(false_range)}, avgR={sum(d['R'] for d in false_range)/len(false_range):+.3f}" if false_range else "  (нет данных)")
print(f"  RANGE + spread≤25 (истинный): n={len(true_range)}, avgR={sum(d['R'] for d in true_range)/len(true_range):+.3f}" if true_range else "  (нет данных)")

if false_range:
    print(f"\n  Топ сигналов в 'ложном RANGE':")
    sig_count = defaultdict(list)
    for d in false_range:
        sig_count[d['sig']].append(d['R'])
    for sig, rs in sorted(sig_count.items(), key=lambda x: -len(x[1])):
        print(f"    {sig:<25} n={len(rs):>4}  avgR={sum(rs)/len(rs):>+.3f}")

# ===============================
# БЛОК 4: wt1_1h абсолютное значение — смещение в OB/OS
# ===============================
print("\n=== БЛОК 4: |wt1_1h| (смещение) по режимам ===")
wt1_ok = [d for d in data if d['wt1_1h'] is not None]
print(f"Сделок с wt1_1h: {len(wt1_ok)}")
regime_wt1 = defaultdict(list)
for d in wt1_ok:
    regime_wt1[d['regime']].append(abs(d['wt1_1h']))

print(f"{'Режим':<15} {'n':>5} {'avg|wt1_1h|':>12} {'med|wt1_1h|':>12}")
print("-"*47)
for regime in ['TREND_UP', 'TREND_DOWN', 'RANGE', 'HIGH_VOL']:
    vals = regime_wt1[regime]
    if not vals:
        continue
    print(f"  {regime:<13} {len(vals):>5}  {sum(vals)/len(vals):>11.1f}  {sorted(vals)[len(vals)//2]:>11.1f}")

# ===============================
# БЛОК 5: Предложение нового RANGE критерия — spread<15 OR |wt1_1h|<20
# Насколько это меняет R?
# ===============================
print("\n=== БЛОК 5: Новый критерий RANGE (WT compression) vs текущий ===")
# Текущий RANGE
cur_range = [d for d in spread_ok if d['regime'] == 'RANGE']
# Новый RANGE: spread_1h < 15 (сжат)
new_range_tight = [d for d in spread_ok if d['spread_1h'] < 15]
# Новый НЕ-RANGE: spread > 25 (реально есть направление)
new_trend = [d for d in spread_ok if d['spread_1h'] >= 25]

def stats(items, label):
    if not items: return
    avgR = sum(d['R'] for d in items) / len(items)
    wr = sum(1 for d in items if d['R'] > 0) * 100 / len(items)
    print(f"  {label:<40} n={len(items):>4}  avgR={avgR:>+.3f}  WR={wr:.0f}%")

stats(cur_range, "Текущий RANGE (classifier)")
stats(new_range_tight, "WT compression RANGE (spread_1h < 15)")
stats(new_trend, "WT trend signal (spread_1h >= 25)")
stats([d for d in spread_ok if d['regime'] == 'RANGE' and d['spread_1h'] < 15],
      "Истинный RANGE (оба согласны)")
stats([d for d in spread_ok if d['regime'] == 'RANGE' and d['spread_1h'] >= 25],
      "Конфликт: RANGE-класс + WT-тренд")

conn.close()
print("\n=== ГОТОВО ===")
