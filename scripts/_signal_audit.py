import sqlite3
conn = sqlite3.connect('subscriptions.db')
c = conn.cursor()

c.execute("""
SELECT signal_type, COUNT(*) as n,
    AVG(R_multiple) as avg_R,
    ROUND(100.0*SUM(CASE WHEN R_multiple > 0 THEN 1 ELSE 0 END)/COUNT(*),1) as wr_pct,
    ROUND(100.0*SUM(CASE WHEN max_price IS NOT NULL AND entry_price IS NOT NULL
         AND stop_loss IS NOT NULL AND ABS(entry_price-stop_loss)>0
         AND (max_price-entry_price)/ABS(entry_price-stop_loss) < 0.3
         THEN 1 ELSE 0 END)/COUNT(*),1) as pct_never_moved
FROM simulated_trades
WHERE status NOT IN ('OPEN','UNKNOWN') AND R_multiple IS NOT NULL
AND created_at >= '2026-04-15'
GROUP BY signal_type HAVING n >= 50
ORDER BY avg_R DESC
""")
rows = c.fetchall()
print(f"{'signal_type':<25s} {'n':>5s}  {'avg_R':>7s}  {'WR%':>5s}  {'died<0.3R%':>10s}")
print('-'*65)
for r in rows:
    marker = ' <<< PROFITABLE' if r[2] > 0 else (' (marginal)' if r[2] > -0.1 else '')
    print(f"{r[0]:<25s} {r[1]:>5d}  {r[2]:>+.3f}R  {r[3]:>5.1f}%  {r[4]:>10.1f}%{marker}")

# Overall
c.execute("""
SELECT COUNT(*), AVG(R_multiple),
    ROUND(100.0*SUM(CASE WHEN R_multiple>0 THEN 1 ELSE 0 END)/COUNT(*),1),
    ROUND(100.0*SUM(CASE WHEN max_price IS NOT NULL AND entry_price IS NOT NULL
         AND stop_loss IS NOT NULL AND ABS(entry_price-stop_loss)>0
         AND (max_price-entry_price)/ABS(entry_price-stop_loss) < 0.3
         THEN 1 ELSE 0 END)/COUNT(*),1)
FROM simulated_trades
WHERE status NOT IN ('OPEN','UNKNOWN') AND R_multiple IS NOT NULL
AND created_at >= '2026-04-15'
""")
r = c.fetchone()
print()
print(f"TOTAL post-era: n={r[0]}, avg_R={r[1]:+.3f}R, WR={r[2]}%, died<0.3R={r[3]}%")
