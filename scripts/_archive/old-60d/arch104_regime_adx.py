"""arch104 ADX/regime check."""
import sqlite3; db = sqlite3.connect("subscriptions.db"); db.row_factory = sqlite3.Row

print("=== arch104 SHORT-only by regime ===")
for regime in ['TREND_DOWN', 'TREND_UP', 'RANGE', 'HIGH_VOL']:
    r = db.execute(f"""SELECT COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s,
        100.0*SUM(CASE WHEN R_multiple>0 THEN 1 END)/COUNT(*) w
        FROM simulated_trades WHERE signal_type='arch104' AND direction='SHORT'
        AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL
        AND regime_v2='{regime}'""").fetchone()
    a = r['a'] or 0; s = r['s'] or 0; w = r['w'] or 0
    ok = "OK" if a > 0.1 else ("~0" if a > 0 else "LOSS")
    print(f"  {regime:12s}: n={r['n']:>4d} avgR={a:>+7.3f} WR={w:>5.1f}% sumR={s:>+8.1f} [{ok}]")

print()
print("=== arch104 SHORT by strength (top performing) ===")
for s in [82, 84, 86, 88]:
    r = db.execute(f"""SELECT COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s
        FROM simulated_trades WHERE signal_type='arch104' AND direction='SHORT'
        AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL
        AND strength={s}""").fetchone()
    a = r['a'] or 0
    print(f"  strength={s}: n={r['n']:>4d} avgR={a:>+7.3f} sumR={r['s'] or 0:>+8.1f}")

print()
print("=== arch104 SHORT by strength x regime ===")
for s in [84, 86]:
    for regime in ['TREND_DOWN', 'TREND_UP', 'RANGE']:
        r = db.execute(f"""SELECT COUNT(*) n, AVG(R_multiple) a FROM simulated_trades
            WHERE signal_type='arch104' AND direction='SHORT'
            AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL
            AND regime_v2='{regime}' AND strength={s}""").fetchone()
        if r['n'] >= 5:
            a = r['a'] or 0
            print(f"  s={s} {regime:12s}: n={r['n']:>3d} avgR={a:>+7.3f}")

# Best combo: SHORT + TREND_DOWN + strength=84
print()
print("=== BEST COMBO candidates ===")
combos = [
    ("SHORT + s=84", "direction='SHORT' AND strength=84"),
    ("SHORT + s=84 + TREND_DOWN", "direction='SHORT' AND strength=84 AND regime_v2='TREND_DOWN'"),
    ("SHORT + s=84 + RANGE", "direction='SHORT' AND strength=84 AND regime_v2='RANGE'"),
    ("SHORT + s=84 + TREND_UP", "direction='SHORT' AND strength=84 AND regime_v2='TREND_UP'"),
    ("SHORT + s=84 +NOT TREND_UP", "direction='SHORT' AND strength=84 AND regime_v2!='TREND_UP'"),
]
for label, cond in combos:
    r = db.execute(f"""SELECT COUNT(*) n, AVG(R_multiple) a, SUM(R_multiple) s,
        100.0*SUM(CASE WHEN R_multiple>0 THEN 1 END)/COUNT(*) w
        FROM simulated_trades WHERE signal_type='arch104' AND {cond}
        AND status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL""").fetchone()
    a = r['a'] or 0; s = r['s'] or 0
    print(f"  {label:30s}: n={r['n']:>4d} avgR={a:>+7.3f} WR={r['w']:>5.1f}% sumR={s:>+8.1f}")

db.close()
