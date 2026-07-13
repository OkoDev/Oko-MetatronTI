"""Оценка комиссий BingX vs PnL."""
import sqlite3; db = sqlite3.connect("subscriptions.db"); db.row_factory = sqlite3.Row

TAKER = 0.0005          # 0.05% taker
ROUND_TRIP = 2 * TAKER   # 0.10% per round trip (open + close)

# VST: fee = qty * entry_price * 0.10%
vst = db.execute("""SELECT COUNT(*) n,
    SUM(qty * entry_price) total_notional,
    SUM(qty * entry_price * 0.001) total_fee_est,
    SUM(profit_pct / 100.0 * qty * entry_price) total_pnl_usd,
    AVG(qty * entry_price) avg_notional
    FROM simulated_trades WHERE status IN ('TP','SL','TSL','EXPIRED')
    AND qty IS NOT NULL AND qty > 0 AND entry_price > 0 AND profit_pct IS NOT NULL
    AND exchange_order_id IS NOT NULL AND exchange_order_id != ''
    AND exchange_order_id != 'SIM'""").fetchone()

print(f"VST (n={vst['n']})")
print(f"  Avg notional = ${vst['avg_notional'] or 0:.0f} per trade")
print(f"  Total notional = ${vst['total_notional'] or 0:.0f}")
print(f"  Estimated fees (0.10% round-trip) = ${vst['total_fee_est'] or 0:.1f}")
pnl = vst['total_pnl_usd'] or 0
print(f"  Total PnL = ${pnl:+.1f}")
if pnl and pnl != 0:
    ratio = vst['total_fee_est'] / abs(pnl) * 100
    print(f"  Fee / PnL = {ratio:.1f}%")
    print(f"  Net PnL (after fees) = ${pnl - vst['total_fee_est']:+.1f}")

# Per signal_type (VST only)
print(f"\n=== VST by signal_type ===")
for sig in ['ote_nested', 'arch104', 'atr_change', 'pivot_reversal', 'confluence', 'watch_list_breach']:
    r = db.execute(f"""SELECT COUNT(*) n,
        SUM(qty * entry_price * 0.001) fee,
        SUM(profit_pct / 100.0 * qty * entry_price) pnl
        FROM simulated_trades WHERE status IN ('TP','SL','TSL','EXPIRED')
        AND qty > 0 AND entry_price > 0 AND profit_pct IS NOT NULL
        AND exchange_order_id IS NOT NULL AND exchange_order_id != ''
        AND exchange_order_id != 'SIM'
        AND signal_type = '{sig}'""").fetchone()
    if r['n'] < 3:
        continue
    fee = r['fee'] or 0
    pnl_s = r['pnl'] or 0
    net = pnl_s - fee
    ratio = f"{fee / abs(pnl_s) * 100:.0f}%" if pnl_s else "N/A"
    print(f"  {sig:20s}: n={r['n']:>4d} fee=${fee:>+8.1f} PnL=${pnl_s:>+8.1f} net=${net:>+8.1f} fee/PnL={ratio}")

# SIM: assume $10 notional per trade
SIM_NOTIONAL = 10.0
sim_n = db.execute("""SELECT COUNT(*) FROM simulated_trades
    WHERE status IN ('TP','SL','TSL','EXPIRED')
    AND (exchange_order_id IS NULL OR exchange_order_id = '' OR exchange_order_id = 'SIM')""").fetchone()[0]
sim_fee = sim_n * SIM_NOTIONAL * 0.001
sim_sumR = db.execute("""SELECT SUM(R_multiple) FROM simulated_trades
    WHERE status IN ('TP','SL','TSL','EXPIRED')
    AND (exchange_order_id IS NULL OR exchange_order_id = '' OR exchange_order_id = 'SIM')""").fetchone()[0]
print(f"\nSIM: n={sim_n}, assumed notional=${SIM_NOTIONAL}/trade")
print(f"  Estimated fees = ${sim_fee:.0f}")
print(f"  Total sumR = {sim_sumR:+.0f}R")

# Grand total
grand_fee = (vst['total_fee_est'] or 0) + sim_fee
print(f"\n=== GRAND TOTAL ===")
print(f"  Total estimated fees (all time) = ${grand_fee:.0f}")
total_vst_pnl = db.execute("""SELECT SUM(profit_pct / 100.0 * qty * entry_price)
    FROM simulated_trades WHERE qty > 0 AND entry_price > 0 AND profit_pct IS NOT NULL
    AND exchange_order_id IS NOT NULL AND exchange_order_id != ''
    AND exchange_order_id != 'SIM'""").fetchone()[0] or 0
print(f"  VST PnL before fees = ${total_vst_pnl:+.1f}")
print(f"  VST PnL after fees  = ${total_vst_pnl - (vst['total_fee_est'] or 0):+.1f}")
db.close()
