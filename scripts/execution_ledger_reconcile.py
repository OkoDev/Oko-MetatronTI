# -*- coding: utf-8 -*-
"""ExecutionLedger: сверка $-потоков (Ф3.3, DS)."""
import sqlite3, sys
sys.stdout.reconfigure(encoding="utf-8")

db = sqlite3.connect("subscriptions.db")
cur = db.cursor()

# 1. balance_snapshots
cur.execute("""SELECT account_id, timestamp, equity, created_at FROM balance_snapshots ORDER BY account_id, created_at ASC""")
snaps = cur.fetchall()
accounts = {}
for acc_id, ts, equity, created in snaps:
    if acc_id not in accounts: accounts[acc_id] = {"first": None, "last": None, "snaps": 0}
    a = accounts[acc_id]; a["snaps"] += 1
    if a["first"] is None: a["first"] = (created, equity)
    a["last"] = (created, equity)

print("=== Balance Snapshots ===")
for acc_id, a in sorted(accounts.items()):
    if a["first"] and a["last"]:
        de = a["last"][1] - a["first"][1]
        print(f"  Account {acc_id}: {a['snaps']} snaps, ${a['first'][1]:.2f} -> ${a['last'][1]:.2f}, D=${de:+.2f}")

# 2. simulated_trades
cur.execute("""SELECT account_id,
    SUM(profit_pct * qty * actual_entry_price / 100.0) as est_pnl,
    SUM(ABS(total_fee)) as total_fee, COUNT(*) as n
    FROM simulated_trades
    WHERE execution_mode='VST' AND status IN ('CLOSED','TSL','TP','SL','EXPIRED')
    AND total_fee IS NOT NULL AND qty IS NOT NULL AND actual_entry_price IS NOT NULL AND profit_pct IS NOT NULL
    GROUP BY account_id""")
trade_stats = {r[0]: {"pnl": r[1] or 0, "fee": r[2] or 0, "n": r[3]} for r in cur.fetchall()}

print(f"\n=== Simulated Trades (VST) ===")
for acc_id, ts in sorted(trade_stats.items()):
    t = ts["pnl"] + ts["fee"]
    print(f"  Account {acc_id}: {ts['n']} trades, PnL=${ts['pnl']:+.2f}, Fee=${ts['fee']:+.2f}, Tracked=${t:+.2f}")

# 3. Gap
print(f"\n=== Gap Analysis ===")
print(f"  {'Acc':>4s} {'Dequity':>10s} {'PnL':>10s} {'Fee':>10s} {'Tracked':>10s} {'Untracked':>10s}")
all_acc = sorted(set(accounts.keys()) | set(trade_stats.keys()))
total_de = 0; total_pnl = 0; total_fee = 0
for acc_id in all_acc:
    a = accounts.get(acc_id, {})
    ts = trade_stats.get(acc_id, {"pnl": 0, "fee": 0, "n": 0})
    de = a["last"][1] - a["first"][1] if a.get("first") and a.get("last") else 0
    tracked = ts["pnl"] + ts["fee"]
    untracked = de - tracked
    total_de += de; total_pnl += ts["pnl"]; total_fee += ts["fee"]
    print(f"  {acc_id:4d} ${de:+9.2f} ${ts['pnl']:+9.2f} ${ts['fee']:+9.2f} ${tracked:+9.2f} ${untracked:+9.2f}")

total_tracked = total_pnl + total_fee
total_untracked = total_de - total_tracked
print(f"  {'ALL':>4s} ${total_de:+9.2f} ${total_pnl:+9.2f} ${total_fee:+9.2f} ${total_tracked:+9.2f} ${total_untracked:+9.2f}")

print(f"\n=== Untracked breakdown ===")
print(f"  Total untracked: ${total_untracked:+.2f}")
if abs(total_de) > 0:
    print(f"  Untracked %% of |Dequity|: {abs(total_untracked/max(abs(total_de),1))*100:.0f}%%")
print(f"  Likely: funding fees + slippage + exchange fees not in total_fee")
print(f"  Gap to close: ${total_untracked:+.2f}")

# 4. Account 1 daily
print(f"\n=== Account 1 daily (last 7 days) ===")
cur.execute("""SELECT date(created_at) as day,
    SUM(profit_pct * qty * actual_entry_price / 100.0) as pnl,
    SUM(ABS(total_fee)) as fee, COUNT(*) as n
    FROM simulated_trades WHERE execution_mode='VST' AND account_id=1
    AND status IN ('CLOSED','TSL','TP','SL','EXPIRED')
    AND created_at >= datetime('now','-7 days')
    AND total_fee IS NOT NULL AND qty IS NOT NULL
    GROUP BY day ORDER BY day""")
print(f"  {'day':>12s} {'n':>5s} {'PnL':>10s} {'Fee':>10s}")
for day, pnl, fee, n in cur.fetchall():
    print(f"  {day:>12s} {n:5d} ${(pnl or 0):+9.2f} ${(fee or 0):+9.2f}")

db.close()
