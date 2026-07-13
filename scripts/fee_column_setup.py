"""Добавление total_fee в simulated_trades — DDL + backfill (на КОПИИ БД)."""
import sqlite3
db = sqlite3.connect("subscriptions_test.db")

# 1. ALTER TABLE
try:
    db.execute("ALTER TABLE simulated_trades ADD COLUMN total_fee REAL DEFAULT 0")
    print("ALTER TABLE: total_fee added")
except Exception as e:
    print(f"ALTER SKIP: {e}")

# 2. Backfill: estimate fee from qty * entry_price * 0.1%
c = db.execute("""UPDATE simulated_trades SET total_fee = ROUND(qty * entry_price * 0.001, 4)
    WHERE qty IS NOT NULL AND qty > 0 AND entry_price > 0
    AND exchange_order_id IS NOT NULL AND exchange_order_id != ''
    AND exchange_order_id != 'SIM'""")
print(f"Backfill: {c.rowcount} VST trades with estimated fee (0.10% round-trip)")

# 3. SIM trades: fee = 0 (no exchange execution)
c2 = db.execute("""UPDATE simulated_trades SET total_fee = 0
    WHERE total_fee IS NULL OR total_fee = 0""")
print(f"SIM/other: {c2.rowcount} trades with total_fee=0 (no execution cost)")

db.commit()

# 4. Verify
r = db.execute("""SELECT COUNT(*) n, SUM(total_fee) s, AVG(total_fee) a
    FROM simulated_trades WHERE total_fee > 0""").fetchone()
print(f"\nVerify: n={r[0]} sum_fee=${r[1] or 0:.1f} avg_fee=${r[2] or 0:.4f}")

# By status
for st in ['TP','SL','TSL','EXPIRED']:
    r = db.execute(f"""SELECT COUNT(*) n, SUM(total_fee) s
        FROM simulated_trades WHERE status='{st}' AND total_fee > 0""").fetchone()
    print(f"  {st:7s}: n={r[0]} sum_fee=${r[1] or 0:.1f}")

# total_fee column check
cols = [c[1] for c in db.execute("PRAGMA table_info(simulated_trades)").fetchall()]
print(f"\ntotal_fee in schema: {'total_fee' in cols}")

db.close()
print("DONE — test DB ready for Claude")
