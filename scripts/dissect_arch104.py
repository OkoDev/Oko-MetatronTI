"""DISSECT arch104 — data-аудит."""
import sqlite3
db = sqlite3.connect('subscriptions.db'); db.row_factory = sqlite3.Row

arch = db.execute("""SELECT COUNT(*) n, AVG(R_multiple) avgR,
    100.0*SUM(CASE WHEN R_multiple>0 THEN 1 END)/COUNT(*) WR,
    SUM(R_multiple) sumR FROM simulated_trades WHERE signal_type='arch104'
    AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL""").fetchone()
print(f"arch104: n={arch['n']} avgR={arch['avgR']:+.3f} WR={arch['WR']:.1f}% sumR={arch['sumR']:+.1f}")

# H1: TP r2.0 vs alternatives (by tp_source)
print("\nBy tp_source:")
for src in db.execute("""SELECT tp_source, COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s
    FROM simulated_trades WHERE signal_type='arch104'
    AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL
    AND tp_source IS NOT NULL GROUP BY tp_source ORDER BY n DESC LIMIT 10""").fetchall():
    print(f"  {src['tp_source'][:40]:40s} n={src['n']:>5d} avgR={src['a']:>+7.3f} sumR={src['s']:>+8.1f}")

# By RR zone
print("\nBy RR zone:")
for lo, hi, label in [(0, 1, '0-1R'), (1, 2, '1-2R'), (2, 3, '2-3R'), (3, 5, '3-5R'), (5, 999, '5+R')]:
    r = db.execute(f"""SELECT COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s
        FROM simulated_trades WHERE signal_type='arch104'
        AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL
        AND ABS(R_multiple) > {lo} AND ABS(R_multiple) <= {hi}""").fetchone()
    print(f"  {label:6s}: n={r['n']:>5d} avgR={r['a']:>+7.3f} sumR={r['s']:>+8.1f}")

# H4: LONG vs SHORT
print("\nLONG vs SHORT:")
for d in ['LONG', 'SHORT']:
    r = db.execute(f"""SELECT COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s,
        100.0*SUM(CASE WHEN R_multiple>0 THEN 1 END)/COUNT(*) w
        FROM simulated_trades WHERE signal_type='arch104' AND direction='{d}'
        AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL""").fetchone()
    print(f"  {d:5s}: n={r['n']:>5d} avgR={r['a']:>+7.3f} WR={r['w']:>5.1f}% sumR={r['s']:>+8.1f}")

# By status
print("\nBy status:")
for st in ['TP', 'SL', 'TSL', 'EXPIRED']:
    r = db.execute(f"""SELECT COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s
        FROM simulated_trades WHERE signal_type='arch104' AND status='{st}'
        AND R_multiple IS NOT NULL""").fetchone()
    print(f"  {st:7s}: n={r['n']:>5d} avgR={r['a']:>+7.3f} sumR={r['s']:>+8.1f}")

# VST vs SIM
print("\nVST vs SIM:")
for mode, cond in [('VST', "exchange_order_id IS NOT NULL AND exchange_order_id!='' AND exchange_order_id!='SIM'"),
                    ('SIM', "exchange_order_id IS NULL OR exchange_order_id='' OR exchange_order_id='SIM'")]:
    r = db.execute(f"""SELECT COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s
        FROM simulated_trades WHERE signal_type='arch104'
        AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL
        AND ({cond})""").fetchone()
    print(f"  {mode:4s}: n={r['n']:>5d} avgR={r['a']:>+7.3f} sumR={r['s']:>+8.1f}")

# H2: pattern profitability
print("\nTop profitable arch104 patterns (live, n>=10):")
for r in db.execute("""SELECT json_extract(features_json,'$.pattern_id') pid,
    COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s
    FROM simulated_trades WHERE signal_type='arch104'
    AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL
    AND features_json IS NOT NULL AND features_json!=''
    GROUP BY pid HAVING n>=10 AND AVG(R_multiple)>0
    ORDER BY SUM(R_multiple) DESC LIMIT 15""").fetchall():
    print(f"  {r['pid'] or '?':30s} n={r['n']:>3d} avgR={r['a']:>+7.3f} sumR={r['s']:>+8.1f}")

print("\nWorst arch104 patterns (live, n>=10):")
for r in db.execute("""SELECT json_extract(features_json,'$.pattern_id') pid,
    COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s
    FROM simulated_trades WHERE signal_type='arch104'
    AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL
    AND features_json IS NOT NULL AND features_json!=''
    GROUP BY pid HAVING n>=10 AND AVG(R_multiple)<0
    ORDER BY SUM(R_multiple) ASC LIMIT 15""").fetchall():
    print(f"  {r['pid'] or '?':30s} n={r['n']:>3d} avgR={r['a']:>+7.3f} sumR={r['s']:>+8.1f}")
db.close()
