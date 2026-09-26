"""DISSECT ote_nested — data-аудит."""
import sqlite3, json; db = sqlite3.connect('subscriptions.db'); db.row_factory = sqlite3.Row

# Overall
ote = db.execute("""SELECT COUNT(*) n, AVG(R_multiple) avgR,
    100.0*SUM(CASE WHEN R_multiple>0 THEN 1 END)/COUNT(*) WR,
    SUM(R_multiple) sumR FROM simulated_trades WHERE signal_type='ote_nested'
    AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL""").fetchone()
print(f"ote_nested: n={ote['n']} avgR={ote['avgR']:+.3f} WR={ote['WR']:.1f}% sumR={ote['sumR']:+.1f}")

# H1: pull vs cont
for typ in ['pull', 'cont']:
    r = db.execute(f"""SELECT COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s,
        100.0*SUM(CASE WHEN R_multiple>0 THEN 1 END)/COUNT(*) w
        FROM simulated_trades WHERE signal_type='ote_nested'
        AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL
        AND tp_source LIKE '%{typ}%'""").fetchone()
    print(f"  {typ:6s}: n={r['n']:>5d} avgR={r['a']:>+7.3f} WR={r['w']:>5.1f}% sumR={r['s']:>+8.1f}")

# By RR zone
print("\nBy RR zone:")
for lo, hi, label in [(0, 1, '0-1R'), (1, 2, '1-2R'), (2, 3, '2-3R'), (3, 5, '3-5R'), (5, 999, '5+R')]:
    r = db.execute(f"""SELECT COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s
        FROM simulated_trades WHERE signal_type='ote_nested'
        AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL
        AND ABS(R_multiple) > {lo} AND ABS(R_multiple) <= {hi}""").fetchone()
    print(f"  {label:6s}: n={r['n']:>5d} avgR={r['a']:>+7.3f} sumR={r['s']:>+8.1f}")

# H2: SL by tsl_tf
print("\nBy tsl_tf (SL impulse TF):")
for tf in ['5m', '15m', '1h', '4h']:
    r = db.execute(f"""SELECT COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s
        FROM simulated_trades WHERE signal_type='ote_nested'
        AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL
        AND tsl_tf='{tf}'""").fetchone()
    if r['n'] > 0:
        print(f"  tsl_tf={tf:4s}: n={r['n']:>5d} avgR={r['a']:>+7.3f} sumR={r['s']:>+8.1f}")

# H3: LTF вложенность
print("\nBy ote_ltf:")
for ltf in ['5m', '15m', '1h']:
    r = db.execute(f"""SELECT COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s
        FROM simulated_trades WHERE signal_type='ote_nested'
        AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL
        AND features_json LIKE '%ote_ltf%{ltf}%'""").fetchone()
    if r['n'] > 0:
        print(f"  LTF={ltf:4s}: n={r['n']:>5d} avgR={r['a']:>+7.3f} sumR={r['s']:>+8.1f}")

print("\nBy ote_htf:")
for htf in ['1h', '4h', '1d']:
    r = db.execute(f"""SELECT COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s
        FROM simulated_trades WHERE signal_type='ote_nested'
        AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL
        AND features_json LIKE '%ote_htf%{htf}%'""").fetchone()
    if r['n'] > 0:
        print(f"  HTF={htf:4s}: n={r['n']:>5d} avgR={r['a']:>+7.3f} sumR={r['s']:>+8.1f}")

# H4: TSL vs no-trail
print("\nBy TSL activated:")
for tsl in [0, 1]:
    r = db.execute(f"""SELECT COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s
        FROM simulated_trades WHERE signal_type='ote_nested'
        AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL
        AND tsl_activated={tsl}""").fetchone()
    if r['n'] > 0:
        print(f"  tsl={tsl}: n={r['n']:>5d} avgR={r['a']:>+7.3f} sumR={r['s']:>+8.1f}")

# VST vs SIM
print("\nVST vs SIM:")
for mode, cond in [('VST', "exchange_order_id IS NOT NULL AND exchange_order_id!='' AND exchange_order_id!='SIM'"),
                    ('SIM', "exchange_order_id IS NULL OR exchange_order_id='' OR exchange_order_id='SIM'")]:
    r = db.execute(f"""SELECT COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s
        FROM simulated_trades WHERE signal_type='ote_nested'
        AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL
        AND ({cond})""").fetchone()
    print(f"  {mode:4s}: n={r['n']:>5d} avgR={r['a']:>+7.3f} sumR={r['s']:>+8.1f}")

# H5: Pull x cont breakdown by status
print("\nPull/cont by status:")
for typ in ['pull', 'cont']:
    for st in ['TP', 'SL', 'TSL', 'EXPIRED']:
        r = db.execute(f"""SELECT COUNT(*) n, AVG(R_multiple) a
            FROM simulated_trades WHERE signal_type='ote_nested' AND status='{st}'
            AND R_multiple IS NOT NULL AND tp_source LIKE '%{typ}%'""").fetchone()
        if r['n'] > 0:
            print(f"  {typ:6s} {st:7s}: n={r['n']:>5d} avgR={r['a']:>+7.3f}")

db.close()
