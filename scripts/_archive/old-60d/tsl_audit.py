import sqlite3, sys
sys.stdout.reconfigure(encoding='utf-8')
conn = sqlite3.connect('subscriptions.db')
cur = conn.cursor()

cur.execute("""
SELECT status, COUNT(*) as n, ROUND(AVG(R_multiple),3) as avgR
FROM simulated_trades WHERE created_at > '2026-04-15'
GROUP BY status ORDER BY n DESC
""")
print("=== Статусы (post-15.04) ===")
for row in cur.fetchall():
    print(f"  {row[0]:<10} n={row[1]:>5}  avgR={row[2] or 'N/A'}")

cur.execute("""
SELECT tsl_activated, status, COUNT(*) as n
FROM simulated_trades WHERE created_at > '2026-04-15'
GROUP BY tsl_activated, status ORDER BY tsl_activated DESC, n DESC
""")
print("\n=== TSL activated vs status ===")
for act, status, n in cur.fetchall():
    print(f"  tsl_activated={act}  status={status:<10}  n={n}")

cur.execute("SELECT COUNT(*) FROM simulated_trades WHERE created_at>'2026-04-15' AND tsl_activated=1 AND status='TSL'")
tsl_closed = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM simulated_trades WHERE created_at>'2026-04-15' AND tsl_activated=1")
tsl_total = cur.fetchone()[0]
print(f"\nИз tsl_activated=1: {tsl_closed}/{tsl_total} закрылись по TSL ({tsl_closed/max(tsl_total,1)*100:.0f}%)")

cur.execute("""
SELECT status,
       ROUND(AVG(R_multiple),3) as avgR,
       ROUND(AVG(max_R_possible),3) as avg_mfe,
       ROUND(AVG(captured_R_pct),1) as capt
FROM simulated_trades
WHERE created_at>'2026-04-15' AND status IN ('TSL','TP','SL') AND R_multiple IS NOT NULL
GROUP BY status
""")
print("\n=== R по типу выхода ===")
print(f"{'Status':<8} {'avgR':>8} {'avg_mfe':>10} {'captured%':>10}")
for status, avgR, mfe, capt in cur.fetchall():
    print(f"  {status:<8} {avgR:>8}  {str(mfe):>10}  {str(capt):>10}")

# Сколько сделок вообще дошли до 1R (tsl_activation_r порог)
cur.execute("""
SELECT
  COUNT(*) as total,
  SUM(CASE WHEN max_R_possible >= 1.0 THEN 1 ELSE 0 END) as reached_1R,
  SUM(CASE WHEN tsl_activated = 1 THEN 1 ELSE 0 END) as tsl_activated,
  SUM(CASE WHEN max_R_possible >= 1.0 AND tsl_activated = 0 THEN 1 ELSE 0 END) as missed_tsl
FROM simulated_trades
WHERE created_at>'2026-04-15' AND status != 'OPEN' AND max_R_possible IS NOT NULL
""")
total, r1, act, missed = cur.fetchone()
print(f"\n=== TSL gap анализ ===")
print(f"  Всего закрытых с MFE данными: {total}")
print(f"  Достигли 1R по MFE:           {r1} ({r1/total*100:.0f}%)")
print(f"  TSL активирован:               {act} ({act/total*100:.0f}%)")
print(f"  Достигли 1R но TSL НЕ активирован (GAP): {missed} ({missed/total*100:.0f}%)")

# Из пропущенных — по каким сигналам чаще всего?
cur.execute("""
SELECT signal_type, direction, COUNT(*) as n, ROUND(AVG(R_multiple),3) as avgR
FROM simulated_trades
WHERE created_at>'2026-04-15' AND status != 'OPEN'
  AND max_R_possible >= 1.0 AND tsl_activated = 0
  AND max_R_possible IS NOT NULL
GROUP BY signal_type, direction
ORDER BY n DESC LIMIT 12
""")
print("\n=== Топ сигналов в TSL gap (mfe>=1R, tsl=0) ===")
for sig, direction, n, avgR in cur.fetchall():
    print(f"  {sig:<25} {direction:<6} n={n:>4}  avgR={avgR:>+.3f}")

conn.close()
