"""DISSECT atr_change — data-аудит."""
import sqlite3
db = sqlite3.connect('subscriptions.db'); db.row_factory = sqlite3.Row

atr = db.execute("""SELECT COUNT(*) n, AVG(R_multiple) avgR,
    100.0*SUM(CASE WHEN R_multiple>0 THEN 1 END)/COUNT(*) WR,
    SUM(R_multiple) sumR FROM simulated_trades WHERE signal_type='atr_change'
    AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL""").fetchone()
print(f"atr_change: n={atr['n']} avgR={atr['avgR']:+.3f} WR={atr['WR']:.1f}% sumR={atr['sumR']:+.1f}")

# By RR zone
print("\nBy RR zone:")
for lo, hi, label in [(0, 1, '0-1R'), (1, 2, '1-2R'), (2, 3, '2-3R'), (3, 5, '3-5R'), (5, 999, '5+R')]:
    r = db.execute(f"""SELECT COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s
        FROM simulated_trades WHERE signal_type='atr_change'
        AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL
        AND ABS(R_multiple) > {lo} AND ABS(R_multiple) <= {hi}""").fetchone()
    print(f"  {label:6s}: n={r['n']:>5d} avgR={r['a']:>+7.3f} sumR={r['s']:>+8.1f}")

# By tp_source
print("\nBy tp_source:")
for src in db.execute("""SELECT tp_source, COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s
    FROM simulated_trades WHERE signal_type='atr_change'
    AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL
    AND tp_source IS NOT NULL GROUP BY tp_source ORDER BY n DESC LIMIT 10""").fetchall():
    print(f"  {src['tp_source'][:45]:45s} n={src['n']:>5d} avgR={src['a']:>+7.3f} sumR={src['s']:>+8.1f}")

# LONG vs SHORT
print("\nLONG vs SHORT:")
for d in ['LONG', 'SHORT']:
    r = db.execute(f"""SELECT COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s
        FROM simulated_trades WHERE signal_type='atr_change' AND direction='{d}'
        AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL""").fetchone()
    print(f"  {d:5s}: n={r['n']:>5d} avgR={r['a']:>+7.3f} sumR={r['s']:>+8.1f}")

# VST vs SIM
print("\nVST vs SIM:")
for mode, cond in [('VST', "exchange_order_id IS NOT NULL AND exchange_order_id!='' AND exchange_order_id!='SIM'"),
                    ('SIM', "exchange_order_id IS NULL OR exchange_order_id='' OR exchange_order_id='SIM'")]:
    r = db.execute(f"""SELECT COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s
        FROM simulated_trades WHERE signal_type='atr_change'
        AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL
        AND ({cond})""").fetchone()
    print(f"  {mode:4s}: n={r['n']:>5d} avgR={r['a']:>+7.3f} sumR={r['s']:>+8.1f}")

# By status
print("\nBy status:")
for st in ['TP', 'SL', 'TSL', 'EXPIRED']:
    r = db.execute(f"""SELECT COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s
        FROM simulated_trades WHERE signal_type='atr_change' AND status='{st}'
        AND R_multiple IS NOT NULL""").fetchone()
    print(f"  {st:7s}: n={r['n']:>5d} avgR={r['a']:>+7.3f} sumR={r['s']:>+8.1f}")

# OPEN count
op = db.execute("SELECT COUNT(*) FROM simulated_trades WHERE signal_type='atr_change' AND status='OPEN'").fetchone()[0]
print(f"\nOPEN: {op}")

db.close()
