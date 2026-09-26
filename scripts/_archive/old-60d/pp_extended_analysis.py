"""
Расширенный анализ PP zone: Weekly + Daily PP, все пары, всё время.
"""
import sqlite3, sys
sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect('subscriptions.db')
cur = conn.cursor()

# Общая статистика
cur.execute("SELECT COUNT(*), AVG(R_multiple) FROM simulated_trades WHERE status!='OPEN' AND R_multiple IS NOT NULL")
total_n, total_avg = cur.fetchone()
print(f"Всего закрытых сделок с R: {total_n}, avgR={total_avg:.3f}")

# ===============================
# БЛОК 0: Распределение по символам
# ===============================
print("\n=== БЛОК 0: Топ-20 символов по кол-ву сделок ===")
cur.execute("""
SELECT symbol, COUNT(*) as cnt, AVG(R_multiple) as avgR,
       SUM(CASE WHEN R_multiple > 0 THEN 1 ELSE 0 END)*100.0/COUNT(*) as wr
FROM simulated_trades
WHERE status!='OPEN' AND R_multiple IS NOT NULL
GROUP BY symbol ORDER BY cnt DESC LIMIT 20
""")
for sym, cnt, avgR, wr in cur.fetchall():
    print(f"  {sym:<30} n={cnt:4d}  avgR={avgR:+.3f}  WR={wr:.0f}%")

# ===============================
# БЛОК 1: Weekly PP — зоны по дистанции (всё время, все пары)
# ===============================
print("\n=== БЛОК 1: Weekly PP — режим × дистанция (ALL TIME, n={}) ===".format(total_n))
cur.execute("""
WITH latest_wpp AS (
    SELECT symbol, pp, s1, s2, r1, r2,
           ROW_NUMBER() OVER(PARTITION BY symbol ORDER BY updated_at DESC) as rn
    FROM pivot_cache WHERE timeframe='1W' AND pp > 0
)
SELECT
    COALESCE(t.regime, 'None') as regime,
    CASE
        WHEN ABS(t.entry_price - w.pp) / w.pp < 0.01 THEN '0-1% PP'
        WHEN ABS(t.entry_price - w.pp) / w.pp < 0.03 THEN '1-3% PP'
        WHEN ABS(t.entry_price - w.pp) / w.pp < 0.05 THEN '3-5% PP'
        WHEN ABS(t.entry_price - w.pp) / w.pp < 0.10 THEN '5-10% PP'
        ELSE '>10% PP'
    END as dist_zone,
    t.direction,
    COUNT(*) as n,
    ROUND(AVG(t.R_multiple), 3) as avgR,
    ROUND(SUM(t.R_multiple), 1) as totalR,
    ROUND(SUM(CASE WHEN t.R_multiple > 0 THEN 1.0 ELSE 0 END)*100/COUNT(*), 1) as wr_pct
FROM simulated_trades t
JOIN latest_wpp w ON t.symbol = w.symbol AND w.rn = 1
WHERE t.status != 'OPEN' AND t.R_multiple IS NOT NULL AND t.entry_price > 0
GROUP BY regime, dist_zone, t.direction
HAVING n >= 10
ORDER BY regime, dist_zone, t.direction
""")
rows = cur.fetchall()
print(f"{'Режим':<20} {'Zone':<10} {'Dir':<6} {'n':>5} {'avgR':>7} {'totalR':>8} {'WR%':>6}")
print("-"*65)
for regime, zone, direction, n, avgR, totalR, wr in rows:
    flag = " ⚠️" if avgR < -0.5 and n >= 20 else (" ✅" if avgR > 0.3 and n >= 20 else "")
    print(f"  {regime:<18} {zone:<10} {direction:<6} {n:>5}  {avgR:>+7.3f}  {totalR:>8.1f}  {wr:>5.1f}%{flag}")

# ===============================
# БЛОК 2: Daily PP — зоны по дистанции
# ===============================
print("\n=== БЛОК 2: Daily PP — режим × дистанция ===")
cur.execute("""
WITH latest_dpp AS (
    SELECT symbol, pp, s1, s2, r1, r2,
           ROW_NUMBER() OVER(PARTITION BY symbol ORDER BY updated_at DESC) as rn
    FROM pivot_cache WHERE timeframe='1D' AND pp > 0
)
SELECT
    COALESCE(t.regime, 'None') as regime,
    CASE
        WHEN ABS(t.entry_price - w.pp) / w.pp < 0.01 THEN '0-1% DPP'
        WHEN ABS(t.entry_price - w.pp) / w.pp < 0.03 THEN '1-3% DPP'
        WHEN ABS(t.entry_price - w.pp) / w.pp < 0.05 THEN '3-5% DPP'
        WHEN ABS(t.entry_price - w.pp) / w.pp < 0.10 THEN '5-10% DPP'
        ELSE '>10% DPP'
    END as dist_zone,
    t.direction,
    COUNT(*) as n,
    ROUND(AVG(t.R_multiple), 3) as avgR,
    ROUND(SUM(t.R_multiple), 1) as totalR,
    ROUND(SUM(CASE WHEN t.R_multiple > 0 THEN 1.0 ELSE 0 END)*100/COUNT(*), 1) as wr_pct
FROM simulated_trades t
JOIN latest_dpp w ON t.symbol = w.symbol AND w.rn = 1
WHERE t.status != 'OPEN' AND t.R_multiple IS NOT NULL AND t.entry_price > 0
GROUP BY regime, dist_zone, t.direction
HAVING n >= 10
ORDER BY regime, dist_zone, t.direction
""")
rows = cur.fetchall()
print(f"{'Режим':<20} {'Zone':<10} {'Dir':<6} {'n':>5} {'avgR':>7} {'totalR':>8} {'WR%':>6}")
print("-"*65)
for regime, zone, direction, n, avgR, totalR, wr in rows:
    flag = " ⚠️" if avgR < -0.5 and n >= 20 else (" ✅" if avgR > 0.3 and n >= 20 else "")
    print(f"  {regime:<18} {zone:<10} {direction:<6} {n:>5}  {avgR:>+7.3f}  {totalR:>8.1f}  {wr:>5.1f}%{flag}")

# ===============================
# БЛОК 3: PP Zone (0-3%) — signal_type breakdown
# ===============================
print("\n=== БЛОК 3: Weekly PP zone 0-3% — по signal_type ===")
cur.execute("""
WITH latest_wpp AS (
    SELECT symbol, pp,
           ROW_NUMBER() OVER(PARTITION BY symbol ORDER BY updated_at DESC) as rn
    FROM pivot_cache WHERE timeframe='1W' AND pp > 0
)
SELECT
    COALESCE(t.signal_type, 'unknown') as sig,
    t.direction,
    COALESCE(t.regime, 'None') as regime,
    COUNT(*) as n,
    ROUND(AVG(t.R_multiple), 3) as avgR,
    ROUND(SUM(t.R_multiple), 1) as totalR,
    ROUND(SUM(CASE WHEN t.R_multiple > 0 THEN 1.0 ELSE 0 END)*100/COUNT(*), 1) as wr_pct
FROM simulated_trades t
JOIN latest_wpp w ON t.symbol = w.symbol AND w.rn = 1
WHERE t.status != 'OPEN' AND t.R_multiple IS NOT NULL AND t.entry_price > 0
  AND ABS(t.entry_price - w.pp) / w.pp < 0.03
GROUP BY sig, t.direction, regime
HAVING n >= 5
ORDER BY avgR ASC
""")
rows = cur.fetchall()
print(f"{'Signal':<25} {'Dir':<6} {'Режим':<15} {'n':>5} {'avgR':>7} {'totalR':>8} {'WR%':>6}")
print("-"*70)
for sig, direction, regime, n, avgR, totalR, wr in rows:
    flag = " ⚠️" if avgR < -0.5 else (" ✅" if avgR > 0.3 else "")
    print(f"  {sig:<23} {direction:<6} {regime:<15} {n:>5}  {avgR:>+7.3f}  {totalR:>8.1f}  {wr:>5.1f}%{flag}")

# ===============================
# БЛОК 4: above/below WPP × direction × Daily PP zone
# ===============================
print("\n=== БЛОК 4: above/below WPP × direction × Daily PP дистанция (все режимы) ===")
cur.execute("""
WITH latest_wpp AS (
    SELECT symbol, pp as wpp,
           ROW_NUMBER() OVER(PARTITION BY symbol ORDER BY updated_at DESC) as rn
    FROM pivot_cache WHERE timeframe='1W' AND pp > 0
),
latest_dpp AS (
    SELECT symbol, pp as dpp,
           ROW_NUMBER() OVER(PARTITION BY symbol ORDER BY updated_at DESC) as rn
    FROM pivot_cache WHERE timeframe='1D' AND pp > 0
)
SELECT
    CASE WHEN t.entry_price > wpp.wpp THEN 'above_WPP' ELSE 'below_WPP' END as wpp_side,
    t.direction,
    CASE
        WHEN ABS(t.entry_price - dpp.dpp) / dpp.dpp < 0.01 THEN '0-1% DPP'
        WHEN ABS(t.entry_price - dpp.dpp) / dpp.dpp < 0.03 THEN '1-3% DPP'
        WHEN ABS(t.entry_price - dpp.dpp) / dpp.dpp < 0.05 THEN '3-5% DPP'
        WHEN ABS(t.entry_price - dpp.dpp) / dpp.dpp < 0.10 THEN '5-10% DPP'
        ELSE '>10% DPP'
    END as dpp_zone,
    COUNT(*) as n,
    ROUND(AVG(t.R_multiple), 3) as avgR,
    ROUND(SUM(t.R_multiple), 1) as totalR,
    ROUND(SUM(CASE WHEN t.R_multiple > 0 THEN 1.0 ELSE 0 END)*100/COUNT(*), 1) as wr_pct
FROM simulated_trades t
JOIN latest_wpp wpp ON t.symbol = wpp.symbol AND wpp.rn = 1
JOIN latest_dpp dpp ON t.symbol = dpp.symbol AND dpp.rn = 1
WHERE t.status != 'OPEN' AND t.R_multiple IS NOT NULL AND t.entry_price > 0
GROUP BY wpp_side, t.direction, dpp_zone
HAVING n >= 15
ORDER BY wpp_side, t.direction, avgR ASC
""")
rows = cur.fetchall()
print(f"{'WPP сторона':<12} {'Dir':<6} {'DPP Zone':<12} {'n':>5} {'avgR':>7} {'totalR':>8} {'WR%':>6}")
print("-"*60)
for wpp_side, direction, dpp_zone, n, avgR, totalR, wr in rows:
    flag = " ⚠️" if avgR < -0.5 else (" ✅" if avgR > 0.3 else "")
    print(f"  {wpp_side:<10} {direction:<6} {dpp_zone:<12} {n:>5}  {avgR:>+7.3f}  {totalR:>8.1f}  {wr:>5.1f}%{flag}")

# ===============================
# БЛОК 5: atr_change SHORT — WS1/WR1 zones
# ===============================
print("\n=== БЛОК 5: atr_change SHORT — близость к W:S1 и W:R1 ===")
cur.execute("""
WITH latest_wpp AS (
    SELECT symbol, pp, s1, s2, r1, r2,
           ROW_NUMBER() OVER(PARTITION BY symbol ORDER BY updated_at DESC) as rn
    FROM pivot_cache WHERE timeframe='1W' AND pp > 0
)
SELECT
    CASE
        WHEN ABS(t.entry_price - w.s1) / w.s1 < 0.02 THEN 'near_WS1 (<2%)'
        WHEN ABS(t.entry_price - w.s2) / w.s2 < 0.02 THEN 'near_WS2 (<2%)'
        WHEN ABS(t.entry_price - w.r1) / w.r1 < 0.02 THEN 'near_WR1 (<2%)'
        WHEN ABS(t.entry_price - w.pp) / w.pp < 0.03  THEN 'near_WPP (<3%)'
        ELSE 'far_from_pivots'
    END as pivot_zone,
    COUNT(*) as n,
    ROUND(AVG(t.R_multiple), 3) as avgR,
    ROUND(SUM(t.R_multiple), 1) as totalR,
    ROUND(SUM(CASE WHEN t.R_multiple > 0 THEN 1.0 ELSE 0 END)*100/COUNT(*), 1) as wr_pct
FROM simulated_trades t
JOIN latest_wpp w ON t.symbol = w.symbol AND w.rn = 1
WHERE t.status != 'OPEN' AND t.R_multiple IS NOT NULL
  AND t.signal_type = 'atr_change' AND t.direction = 'SHORT'
  AND t.entry_price > 0 AND w.s1 > 0 AND w.r1 > 0
GROUP BY pivot_zone
HAVING n >= 5
ORDER BY avgR DESC
""")
rows = cur.fetchall()
print(f"{'Pivot Zone':<20} {'n':>5} {'avgR':>7} {'totalR':>8} {'WR%':>6}")
print("-"*50)
for pz, n, avgR, totalR, wr in rows:
    flag = " ✅" if avgR > 0.3 else (" ⚠️" if avgR < -0.2 else "")
    print(f"  {pz:<18} {n:>5}  {avgR:>+7.3f}  {totalR:>8.1f}  {wr:>5.1f}%{flag}")

# ===============================
# БЛОК 6: Лучшие и худшие комбо (WPP side + signal_type + direction)
# ===============================
print("\n=== БЛОК 6: ТОП-10 лучших и худших комбо (above/below WPP × signal × dir) ===")
cur.execute("""
WITH latest_wpp AS (
    SELECT symbol, pp,
           ROW_NUMBER() OVER(PARTITION BY symbol ORDER BY updated_at DESC) as rn
    FROM pivot_cache WHERE timeframe='1W' AND pp > 0
)
SELECT
    CASE WHEN t.entry_price > w.pp THEN 'above_WPP' ELSE 'below_WPP' END as wpp_side,
    COALESCE(t.signal_type, 'unknown') as sig,
    t.direction,
    COALESCE(t.regime, 'None') as regime,
    COUNT(*) as n,
    ROUND(AVG(t.R_multiple), 3) as avgR,
    ROUND(SUM(t.R_multiple), 1) as totalR
FROM simulated_trades t
JOIN latest_wpp w ON t.symbol = w.symbol AND w.rn = 1
WHERE t.status != 'OPEN' AND t.R_multiple IS NOT NULL AND t.entry_price > 0
GROUP BY wpp_side, sig, t.direction, regime
HAVING n >= 15
ORDER BY avgR DESC
""")
all_rows = cur.fetchall()
print(f"\nЛУЧШИЕ комбо:")
print(f"{'WPP':<12} {'Signal':<25} {'Dir':<6} {'Режим':<15} {'n':>5} {'avgR':>7} {'totalR':>8}")
print("-"*75)
for wpp_side, sig, direction, regime, n, avgR, totalR in all_rows[:10]:
    print(f"  {wpp_side:<10} {sig:<23} {direction:<6} {regime:<15} {n:>5}  {avgR:>+7.3f}  {totalR:>8.1f}")

print(f"\nХУДШИЕ комбо:")
print(f"{'WPP':<12} {'Signal':<25} {'Dir':<6} {'Режим':<15} {'n':>5} {'avgR':>7} {'totalR':>8}")
print("-"*75)
for wpp_side, sig, direction, regime, n, avgR, totalR in all_rows[-10:]:
    print(f"  {wpp_side:<10} {sig:<23} {direction:<6} {regime:<15} {n:>5}  {avgR:>+7.3f}  {totalR:>8.1f}")

conn.close()
print("\n=== АНАЛИЗ ЗАВЕРШЁН ===")
