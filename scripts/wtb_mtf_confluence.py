"""WT-B MTF confluence check."""
import sqlite3; db = sqlite3.connect("subscriptions.db"); db.row_factory = sqlite3.Row

print("=== wt_b co-occurrence with other signals (within 1h) ===")
r = db.execute("""SELECT 
    SUM(CASE WHEN b.direction='LONG' THEN 1 ELSE 0 END) long_n,
    AVG(CASE WHEN b.direction='LONG' THEN b.R_multiple END) long_r,
    SUM(CASE WHEN b.direction='SHORT' THEN 1 ELSE 0 END) short_n,
    AVG(CASE WHEN b.direction='SHORT' THEN b.R_multiple END) short_r,
    COUNT(*) total,
    AVG(b.R_multiple) all_r
    FROM simulated_trades b
    WHERE b.signal_type='wt_b_signal'
    AND b.status IN ('TP','SL','TSL','EXPIRED') AND b.R_multiple IS NOT NULL
    AND EXISTS (
        SELECT 1 FROM simulated_trades o
        WHERE o.symbol=b.symbol AND o.signal_type!=b.signal_type
        AND o.created_at BETWEEN datetime(b.created_at,'-1 hour') AND datetime(b.created_at,'+1 hour')
        AND o.status IN ('TP','SL','TSL','EXPIRED')
    )""").fetchone()
a = r["all_r"] or 0; lr = r["long_r"] or 0; sr = r["short_r"] or 0
print(f"  With confluence: n={r['total']} LONG_n={r['long_n']} LONG_R={lr:+.3f} SHORT_n={r['short_n']} SHORT_R={sr:+.3f} ALL_R={a:+.3f}")

r2 = db.execute("""SELECT 
    SUM(CASE WHEN b.direction='LONG' THEN 1 ELSE 0 END) long_n,
    AVG(CASE WHEN b.direction='LONG' THEN b.R_multiple END) long_r,
    SUM(CASE WHEN b.direction='SHORT' THEN 1 ELSE 0 END) short_n,
    AVG(CASE WHEN b.direction='SHORT' THEN b.R_multiple END) short_r,
    COUNT(*) total,
    AVG(b.R_multiple) all_r
    FROM simulated_trades b
    WHERE b.signal_type='wt_b_signal'
    AND b.status IN ('TP','SL','TSL','EXPIRED') AND b.R_multiple IS NOT NULL
    AND NOT EXISTS (
        SELECT 1 FROM simulated_trades o
        WHERE o.symbol=b.symbol AND o.signal_type!=b.signal_type
        AND o.created_at BETWEEN datetime(b.created_at,'-1 hour') AND datetime(b.created_at,'+1 hour')
        AND o.status IN ('TP','SL','TSL','EXPIRED')
    )""").fetchone()
a2 = r2["all_r"] or 0; lr2 = r2["long_r"] or 0; sr2 = r2["short_r"] or 0
print(f"  Without confluence: n={r2['total']} LONG_n={r2['long_n']} LONG_R={lr2:+.3f} SHORT_n={r2['short_n']} SHORT_R={sr2:+.3f} ALL_R={a2:+.3f}")

print()
print("=== Co-occurring signal types ===")
for r3 in db.execute("""SELECT o.signal_type, COUNT(*) n, AVG(b.R_multiple) a
    FROM simulated_trades b
    JOIN simulated_trades o ON o.symbol=b.symbol AND o.signal_type!=b.signal_type
    AND o.created_at BETWEEN datetime(b.created_at,'-1 hour') AND datetime(b.created_at,'+1 hour')
    AND o.status IN ('TP','SL','TSL','EXPIRED')
    WHERE b.signal_type='wt_b_signal'
    AND b.status IN ('TP','SL','TSL','EXPIRED') AND b.R_multiple IS NOT NULL
    GROUP BY o.signal_type ORDER BY n DESC""").fetchall():
    a = r3["a"] or 0
    print(f"  + {r3['signal_type']:20s}: n={r3['n']:>3d} wt_b_avgR={a:+.3f}")

# Same-direction co-occurrence (more relevant)
print()
print("=== Same-direction co-occurring ===")
for r4 in db.execute("""SELECT o.signal_type, COUNT(*) n, AVG(b.R_multiple) a
    FROM simulated_trades b
    JOIN simulated_trades o ON o.symbol=b.symbol AND o.signal_type!=b.signal_type
    AND o.direction=b.direction
    AND o.created_at BETWEEN datetime(b.created_at,'-1 hour') AND datetime(b.created_at,'+1 hour')
    AND o.status IN ('TP','SL','TSL','EXPIRED')
    WHERE b.signal_type='wt_b_signal'
    AND b.status IN ('TP','SL','TSL','EXPIRED') AND b.R_multiple IS NOT NULL
    GROUP BY o.signal_type ORDER BY n DESC""").fetchall():
    a = r4["a"] or 0
    print(f"  + {r4['signal_type']:20s}: n={r4['n']:>3d} wt_b_avgR={a:+.3f}")

db.close()
