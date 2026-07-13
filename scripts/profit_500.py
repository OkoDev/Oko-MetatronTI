"""$500 profit calculator."""
import sqlite3; db = sqlite3.connect("subscriptions.db"); db.row_factory = sqlite3.Row

print("=== VST PnL by signal type ===")
for sig in ['ote_nested', 'arch104', 'atr_change']:
    sql = f"SELECT COUNT(*) n, AVG(profit_pct/100.0*qty*entry_price) avg_pnl, SUM(profit_pct/100.0*qty*entry_price) sum_pnl, AVG(qty*entry_price) avg_notional, 100.0*SUM(CASE WHEN profit_pct>0 THEN 1 ELSE 0)/COUNT(*) wr, SUM(qty*entry_price*0.001) est_fee FROM simulated_trades WHERE signal_type='{sig}' AND status IN ('TP','SL','TSL','EXPIRED') AND qty>0 AND entry_price>0 AND profit_pct IS NOT NULL AND exchange_order_id IS NOT NULL AND exchange_order_id!='' AND exchange_order_id!='SIM'"
    r = db.execute(sql).fetchone()
    pnl = r['avg_pnl'] or 0; sp = r['sum_pnl'] or 0; fee = r['est_fee'] or 0
    net = sp - fee
    print(f"  {sig:15s}: n={r['n']:>4d} notional=${r['avg_notional']:>6.0f} avgPnL=${pnl:>+6.3f} sumPnL=${sp:>+7.1f} net=${net:>+7.1f} WR={r['wr']:.1f}%")

# Daily
print()
print("=== Daily VST PnL (last 5 days) ===")
sql = "SELECT date(created_at) d, COUNT(*) n, SUM(profit_pct/100.0*qty*entry_price) pnl, SUM(qty*entry_price*0.001) fee FROM simulated_trades WHERE status IN ('TP','SL','TSL','EXPIRED') AND qty>0 AND entry_price>0 AND profit_pct IS NOT NULL AND exchange_order_id IS NOT NULL AND exchange_order_id!='' AND exchange_order_id!='SIM' AND created_at >= datetime('now','-5 days') GROUP BY d ORDER BY d"
for r in db.execute(sql).fetchall():
    pnl = r['pnl'] or 0; fee = r['fee'] or 0; net = pnl - fee
    print(f"  {r['d']}: n={r['n']:>3d} PnL=${pnl:>+6.2f} fee=${fee:>5.2f} net=${net:>+6.2f}")

# Position sizing
print()
avg_n = db.execute("""SELECT AVG(qty*entry_price) FROM simulated_trades
    WHERE qty>0 AND entry_price>0 AND exchange_order_id IS NOT NULL
    AND exchange_order_id!='' AND exchange_order_id!='SIM'""").fetchone()[0]
avg_lev = 5.0
avg_margin = avg_n / avg_lev
print(f"  Средний номинал: ${avg_n:.0f}")
print(f"  Средняя маржа (5x): ${avg_margin:.0f}")
print(f"  Макс позиций с $500: {int(500/avg_margin)}")

# Realistic: cap at 5 concurrent, $100 notional each
print()
print("=== МОДЕЛИРОВАНИЕ: $500, 5x плечо ===")
daily_n = db.execute("""SELECT COUNT(*)*1.0/5 FROM simulated_trades
    WHERE status IN ('TP','SL','TSL','EXPIRED')
    AND exchange_order_id IS NOT NULL AND exchange_order_id!='' AND exchange_order_id!='SIM'
    AND created_at >= datetime('now','-5 days')""").fetchone()[0]
avg_pnl_pct = db.execute("""SELECT AVG(profit_pct) FROM simulated_trades
    WHERE status IN ('TP','SL','TSL','EXPIRED')
    AND exchange_order_id IS NOT NULL AND exchange_order_id!='' AND exchange_order_id!='SIM'
    AND created_at >= datetime('now','-5 days')""").fetchone()[0] or 0
wr = db.execute("""SELECT 100.0*SUM(CASE WHEN profit_pct>0 THEN 1 ELSE 0)/COUNT(*) FROM simulated_trades
    WHERE status IN ('TP','SL','TSL','EXPIRED')
    AND exchange_order_id IS NOT NULL AND exchange_order_id!='' AND exchange_order_id!='SIM'
    AND created_at >= datetime('now','-5 days')""").fetchone()[0] or 0

print(f"  Сделок/день (все VST): {daily_n:.0f}")
print(f"  Средний profit_pct: {avg_pnl_pct:+.2f}%")
print(f"  WR: {wr:.1f}%")

# With $500, 5x leverage, position_size=$100 (notional=$500 at 5x)
pos_notional = 500  # $500 notional per trade (5x = $100 margin)
pos_margin = pos_notional / 5  # $100 per position
max_pos = int(500 / pos_margin)  # 5 positions

daily_profit = daily_n * pos_notional * avg_pnl_pct / 100
daily_fee = daily_n * pos_notional * 0.001
daily_net = daily_profit - daily_fee

print()
print(f"  Позиций одновременно: {max_pos}")
print(f"  Номинал позиции: ${pos_notional}")
print(f"  Маржа на позицию: ${pos_margin}")
print(f"  Доход/день (до сборов): ${daily_profit:+.2f}")
print(f"  Сборы/день: ${daily_fee:.2f}")
print(f"  ЧИСТЫЙ доход/день: ${daily_net:+.2f}")
print(f"  В месяц (~30 дней): ${daily_net*30:+.0f}")
print(f"  Годовой ROI: {daily_net*365/500*100:.0f}%")

# By signal after gates
print()
print("=== ПОСЛЕ ГЕЙТОВ (arch104 SHORT-only s>=84, ote unchanged, atr unchanged) ===")
for sig, conds in [("ote_nested", ""), ("arch104 SHORT s>=84", "AND signal_type='arch104' AND direction='SHORT' AND strength>=84"), ("atr_change", "AND signal_type='atr_change'")]:
    r = db.execute(f"""SELECT COUNT(*) n, AVG(profit_pct/100.0*qty*entry_price) avg_pnl,
        AVG(profit_pct) avg_pct
        FROM simulated_trades WHERE status IN ('TP','SL','TSL','EXPIRED')
        AND qty>0 AND entry_price>0 AND profit_pct IS NOT NULL
        AND exchange_order_id IS NOT NULL AND exchange_order_id!='' AND exchange_order_id!='SIM'
        AND created_at >= datetime('now','-5 days')
        {conds}""").fetchone()
    n = r['n'] or 0; ap = r['avg_pnl'] or 0; pct = r['avg_pct'] or 0
    daily_n = n / 5
    daily_profit = daily_n * pos_notional * pct / 100
    daily_fee = daily_n * pos_notional * 0.001
    print(f"  {sig:30s}: n/день={daily_n:.0f} avgPnL=${ap:+.3f} PnL/день=${daily_profit-fee:+.2f}")

db.close()
