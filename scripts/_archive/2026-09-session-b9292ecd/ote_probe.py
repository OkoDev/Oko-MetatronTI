# -*- coding: utf-8 -*-
"""Зонд: схема simulated_trades + ключи features_json у ote_nested (июнь и после 28.08)."""
import sqlite3, json, sys, collections
sys.stdout.reconfigure(encoding="utf-8")

DB = r"E:\MTF BOT\CURSOR\crypto_volume_bot\subscriptions.db"
c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row

cols = [r[1] for r in c.execute("PRAGMA table_info(simulated_trades)")]
print("КОЛОНКИ (%d):" % len(cols))
print(", ".join(cols))
print()

# кандидаты на «биржа/VST» и «тип аккаунта»
for cand in ("account_type", "exchange_order_id", "is_vst", "mode", "exchange",
             "order_id", "live", "source_account", "exec_mode", "trade_mode"):
    if cand in cols:
        rows = list(c.execute(
            f"SELECT {cand} AS v, COUNT(*) n FROM simulated_trades "
            f"WHERE signal_type='ote_nested' GROUP BY 1 ORDER BY n DESC LIMIT 8"))
        print(f"{cand}: " + " · ".join(f"{r['v']!r}={r['n']}" for r in rows))
print()

def keyscan(label, where):
    q = (f"SELECT features_json FROM simulated_trades "
         f"WHERE signal_type='ote_nested' AND {where} AND features_json IS NOT NULL LIMIT 400")
    kc, vals = collections.Counter(), collections.defaultdict(collections.Counter)
    n = 0
    for (fj,) in c.execute(q):
        try:
            d = json.loads(fj)
        except Exception:
            continue
        n += 1
        for k, v in d.items():
            kc[k] += 1
            if any(t in k.lower() for t in ("conf", "fvg", "setup", "ote", "htf", "ltf", "trigger", "tier", "type")):
                vals[k][str(v)[:70]] += 1
    print(f"--- {label}: строк {n}, ключей {len(kc)}")
    print("ключи:", ", ".join(sorted(kc)))
    print()
    for k in sorted(vals):
        top = " · ".join(f"{v}={cnt}" for v, cnt in vals[k].most_common(6))
        print(f"  {k}: {top}")
    print()

keyscan("ИЮНЬ 2026", "created_at >= '2026-06-01' AND created_at < '2026-07-01'")
keyscan("ПОСЛЕ 28.08", "created_at >= '2026-08-28'")
