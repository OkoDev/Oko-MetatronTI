"""Стратегические гипотезы — сбор данных из features_json."""
import sqlite3, json
db = sqlite3.connect('subscriptions.db'); db.row_factory = sqlite3.Row

# 1. Volume/volatility edge zones
print("=== ote_nested by 24h price change (from features_json) ===")
for label, cond in [
    ("flat_2pct", "ABS(CAST(json_extract(features_json,'$.price_change_24h') AS REAL)) < 2"),
    ("dump_5pct", "CAST(json_extract(features_json,'$.price_change_24h') AS REAL) < -5"),
    ("pump_5pct", "CAST(json_extract(features_json,'$.price_change_24h') AS REAL) > 5"),
]:
    r = db.execute(f"""SELECT COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s
        FROM simulated_trades WHERE signal_type='ote_nested'
        AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL
        AND features_json IS NOT NULL AND features_json!='' AND ({cond})""").fetchone()
    a = r['a'] or 0; s = r['s'] or 0
    print(f"  {label:12s}: n={r['n']:>4d} avgR={a:>+7.3f} sumR={s:>+8.1f}")

# 2. ote_tier
print("\n=== ote_nested by tier ===")
for tier_label, tier_val in [("TIER1", "1"), ("TIER2", "2")]:
    r = db.execute(f"""SELECT COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s
        FROM simulated_trades WHERE signal_type='ote_nested'
        AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL
        AND features_json LIKE '%ote_tier%{tier_val}%'""").fetchone()
    a = r['a'] or 0; s = r['s'] or 0
    print(f"  {tier_label}: n={r['n']:>4d} avgR={a:>+7.3f} sumR={s:>+8.1f}")

# 3. arch104 by volatility
print("\n=== arch104 by volume_24h ===")
for label, cond in [
    ("low_vol", "CAST(json_extract(features_json,'$.volume_24h') AS REAL) < 1e6"),
    ("mid_vol", "CAST(json_extract(features_json,'$.volume_24h') AS REAL) BETWEEN 1e6 AND 10e6"),
    ("high_vol", "CAST(json_extract(features_json,'$.volume_24h') AS REAL) > 10e6"),
]:
    r = db.execute(f"""SELECT COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s
        FROM simulated_trades WHERE signal_type='arch104'
        AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL
        AND features_json IS NOT NULL AND features_json!='' AND ({cond})""").fetchone()
    a = r['a'] or 0; s = r['s'] or 0
    print(f"  {label:12s}: n={r['n']:>4d} avgR={a:>+7.3f} sumR={s:>+8.1f}")

# 4. magnet TP impact on arch104
print("\n=== arch104: magnet TP vs no magnet ===")
for label, cond in [
    ("with_magnet", "magnet_tp_price IS NOT NULL AND magnet_tp_price > 0"),
    ("no_magnet", "magnet_tp_price IS NULL OR magnet_tp_price = 0"),
]:
    r = db.execute(f"""SELECT COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s
        FROM simulated_trades WHERE signal_type='arch104'
        AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL
        AND ({cond})""").fetchone()
    a = r['a'] or 0; s = r['s'] or 0
    print(f"  {label:12s}: n={r['n']:>4d} avgR={a:>+7.3f} sumR={s:>+8.1f}")

# 5. regime_v2
print("\n=== arch104 by regime_v2 ===")
for r in db.execute("""SELECT regime_v2, COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s
    FROM simulated_trades WHERE signal_type='arch104'
    AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL
    AND regime_v2 IS NOT NULL GROUP BY regime_v2 ORDER BY n DESC""").fetchall():
    a = r['a'] or 0; s = r['s'] or 0
    print(f"  {r['regime_v2'] or 'NULL':20s} n={r['n']:>5d} avgR={a:>+7.3f} sumR={s:>+8.1f}")

# 6. SL type effectiveness for arch104
print("\n=== arch104 by sl_source ===")
for r in db.execute("""SELECT sl_source, COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s
    FROM simulated_trades WHERE signal_type='arch104'
    AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL
    AND sl_source IS NOT NULL GROUP BY sl_source ORDER BY n DESC LIMIT 10""").fetchall():
    a = r['a'] or 0; s = r['s'] or 0
    print(f"  {r['sl_source'][:45]:45s} n={r['n']:>5d} avgR={a:>+7.3f} sumR={s:>+8.1f}")

# 7. strength vs R (arch104)
print("\n=== arch104 by strength ===")
for r in db.execute("""SELECT strength, COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s
    FROM simulated_trades WHERE signal_type='arch104'
    AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL
    AND strength IS NOT NULL GROUP BY strength ORDER BY strength""").fetchall():
    a = r['a'] or 0; s = r['s'] or 0
    print(f"  strength={r['strength']:>3d}: n={r['n']:>5d} avgR={a:>+7.3f} sumR={s:>+8.1f}")

# 8. data_era (post-15.04 vs older)
print("\n=== ote_nested by data_era ===")
for r in db.execute("""SELECT json_extract(features_json,'$.data_era') era,
    COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s
    FROM simulated_trades WHERE signal_type='ote_nested'
    AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL
    AND features_json IS NOT NULL AND features_json!=''
    GROUP BY era""").fetchall():
    a = r['a'] or 0; s = r['s'] or 0
    print(f"  {r['era'] or 'NULL':15s} n={r['n']:>5d} avgR={a:>+7.3f} sumR={s:>+8.1f}")

db.close()
