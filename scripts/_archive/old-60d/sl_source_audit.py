"""SL source аудит — почему 1R = 3-6% движения."""
import sqlite3, sys
sys.stdout.reconfigure(encoding='utf-8')
conn = sqlite3.connect('subscriptions.db')
cur = conn.cursor()

# Реальный SL distance (% от entry) по sl_source
print("=== SL DISTANCE ОТ ENTRY (%) по sl_source ===")
cur.execute("""
SELECT sl_source,
       COUNT(*) as n,
       ROUND(AVG(ABS(entry_price - stop_loss)/entry_price*100), 2) as avg_sl_pct,
       ROUND(MIN(ABS(entry_price - stop_loss)/entry_price*100), 2) as min_sl_pct,
       ROUND(MAX(ABS(entry_price - stop_loss)/entry_price*100), 2) as max_sl_pct,
       ROUND(AVG(R_multiple), 3) as avgR
FROM simulated_trades
WHERE created_at > '2026-04-15' AND status != 'OPEN'
  AND entry_price > 0 AND stop_loss > 0 AND R_multiple IS NOT NULL
  AND sl_source IS NOT NULL
GROUP BY sl_source
HAVING n >= 5
ORDER BY avg_sl_pct DESC
""")
print(f"{'sl_source':<30} {'n':>5} {'avg_sl%':>9} {'min_sl%':>8} {'max_sl%':>8} {'avgR':>7}")
print("-"*72)
for row in cur.fetchall():
    flag = " ⚠️ WIDE" if row[2] > 3.0 else (" ✅" if row[2] < 1.5 else "")
    print(f"  {str(row[0]):<28} {row[1]:>5}  {row[2]:>8.2f}%  {row[3]:>7.2f}%  {row[4]:>7.2f}%  {row[5]:>+6.3f}{flag}")

# SL distance по signal_type
print("\n=== SL DISTANCE ПО signal_type ===")
cur.execute("""
SELECT signal_type, direction,
       COUNT(*) as n,
       ROUND(AVG(ABS(entry_price - stop_loss)/entry_price*100), 2) as avg_sl_pct,
       ROUND(AVG(R_multiple), 3) as avgR,
       ROUND(AVG(max_R_possible), 3) as avg_mfe
FROM simulated_trades
WHERE created_at > '2026-04-15' AND status != 'OPEN'
  AND entry_price > 0 AND stop_loss > 0 AND R_multiple IS NOT NULL
GROUP BY signal_type, direction
HAVING n >= 15
ORDER BY avg_sl_pct DESC
""")
print(f"{'Signal':<25} {'Dir':<6} {'n':>5} {'avg_sl%':>9} {'avgR':>7} {'avg_mfe':>8}")
print("-"*65)
for sig, direction, n, sl_pct, avgR, mfe in cur.fetchall():
    flag = " ⚠️" if sl_pct > 3.0 else (" ✅" if sl_pct < 1.5 else "")
    print(f"  {sig:<23} {direction:<6} {n:>5}  {sl_pct:>8.2f}%  {avgR:>+6.3f}  {str(mfe):>8}{flag}")

# Распределение SL distance
print("\n=== РАСПРЕДЕЛЕНИЕ SL DISTANCE (все сделки post-15.04) ===")
cur.execute("""
SELECT
  CASE
    WHEN ABS(entry_price-stop_loss)/entry_price*100 < 1.0 THEN '<1%'
    WHEN ABS(entry_price-stop_loss)/entry_price*100 < 2.0 THEN '1-2%'
    WHEN ABS(entry_price-stop_loss)/entry_price*100 < 3.0 THEN '2-3%'
    WHEN ABS(entry_price-stop_loss)/entry_price*100 < 5.0 THEN '3-5%'
    WHEN ABS(entry_price-stop_loss)/entry_price*100 < 8.0 THEN '5-8%'
    ELSE '>8%'
  END as bucket,
  COUNT(*) as n,
  ROUND(AVG(R_multiple), 3) as avgR,
  ROUND(AVG(tsl_activated)*100, 1) as tsl_pct
FROM simulated_trades
WHERE created_at > '2026-04-15' AND status != 'OPEN'
  AND entry_price > 0 AND stop_loss > 0 AND R_multiple IS NOT NULL
GROUP BY bucket
ORDER BY MIN(ABS(entry_price-stop_loss)/entry_price*100)
""")
print(f"{'SL dist':<10} {'n':>5} {'avgR':>7} {'TSL%':>7}")
print("-"*35)
for bucket, n, avgR, tsl_pct in cur.fetchall():
    flag = " ⚠️" if (bucket in ('3-5%', '5-8%', '>8%')) else (" ✅" if bucket == '<1%' else "")
    print(f"  {bucket:<8} {n:>5}  {avgR:>+6.3f}  {tsl_pct:>6.1f}%{flag}")

# PAXG конкретно
print("\n=== PAXG — последние сделки ===")
cur.execute("""
SELECT id, direction, signal_type, entry_price, stop_loss, take_profit,
       ROUND(ABS(entry_price-stop_loss)/entry_price*100, 2) as sl_pct,
       status, R_multiple, tsl_activated, sl_source, created_at
FROM simulated_trades
WHERE symbol LIKE '%PAXG%'
ORDER BY id DESC LIMIT 10
""")
for row in cur.fetchall():
    print(f"  #{row[0]} {row[1]:<6} {row[2]:<20} entry={row[3]:.4f} SL={row[4]:.4f} ({row[6]}%) "
          f"status={row[7]} R={row[8]} tsl={row[9]} src={row[10]}")
    print(f"         created={row[11]}")

conn.close()
