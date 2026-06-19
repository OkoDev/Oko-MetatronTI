# -*- coding: utf-8 -*-
"""Ledger-forward reconcile: сверка ExecutionLedger с balance_snapshots на живом потоке.
Запуск: python scripts/ledger_forward_check.py
"""
import sqlite3, time, sys
sys.path.insert(0, ".")
from core.execution.execution_ledger import ExecutionLedger

DB = "subscriptions.db"


def get_latest_equity() -> dict:
    """Последний equity из balance_snapshots по аккаунтам."""
    db = sqlite3.connect(DB)
    cur = db.cursor()
    cur.execute("""SELECT account_id, equity, created_at FROM balance_snapshots
        WHERE (account_id, created_at) IN (
            SELECT account_id, MAX(created_at) FROM balance_snapshots GROUP BY account_id
        )""")
    eq = {r[0]: {"equity": r[1], "ts": r[2]} for r in cur.fetchall()}
    db.close()
    return eq


def get_initial_equity(since_hours: float = 3) -> dict:
    """Самый ранний equity за последние N часов."""
    db = sqlite3.connect(DB)
    cur = db.cursor()
    cur.execute(f"""SELECT account_id, MIN(equity), MAX(equity), MIN(created_at), MAX(created_at)
        FROM balance_snapshots
        WHERE created_at >= datetime('now','-{since_hours} hours')
        GROUP BY account_id""")
    eq = {}
    for acc, min_eq, max_eq, first_ts, last_ts in cur.fetchall():
        eq[acc] = {"first_eq": min_eq, "last_eq": max_eq,
                   "first_ts": first_ts, "last_ts": last_ts,
                   "delta": max_eq - min_eq}
    db.close()
    return eq


def reconcile_from_snapshots(since_hours: float = 3):
    """Сверка: Dequity из снапшотов = ledger_sum (предположительно)."""
    init_eq = get_initial_equity(since_hours)

    print(f"=== Ledger Forward Reconcile (last {since_hours}h) ===")
    print(f"Note: ExecutionLedger накапливается в памяти бота (shadow).")
    print(f"Этот скрипт показывает Dequity из balance_snapshots.")
    print(f"Полная сверка будет когда ExecutionLedger отдаст running_sum через API.")
    print()

    print(f"  {'Acc':>4s} {'First $':>10s} {'Last $':>10s} {'Dequity':>10s} {'Period':>30s}")
    for acc in sorted(init_eq):
        d = init_eq[acc]
        print(f"  {acc:4d} ${d['first_eq']:>9.2f} ${d['last_eq']:>9.2f} ${d['delta']:+9.2f}  {d['first_ts']} -> {d['last_ts']}")

    # Also show simulated_trades PnL for the same period
    db = sqlite3.connect(DB)
    cur = db.cursor()
    cur.execute(f"""SELECT account_id,
        SUM(profit_pct * qty * actual_entry_price / 100.0) as pnl,
        SUM(ABS(total_fee)) as fee, COUNT(*) as n
        FROM simulated_trades WHERE execution_mode='VST'
        AND status IN ('CLOSED','TSL','TP','SL','EXPIRED')
        AND created_at >= datetime('now','-{since_hours} hours')
        AND qty IS NOT NULL AND actual_entry_price IS NOT NULL AND total_fee IS NOT NULL
        GROUP BY account_id""")
    trades = {r[0]: {"pnl": r[1] or 0, "fee": r[2] or 0, "n": r[3]} for r in cur.fetchall()}
    db.close()

    print(f"\n  Simulated trades PnL (same period, VST):")
    for acc, t in sorted(trades.items()):
        print(f"  Acc {acc}: {t['n']} trades, estPnL=${t['pnl']:+.2f}, Fee=${t['fee']:+.2f}")

    # Gap
    print(f"\n  Estimated gap (Dequity - trades):")
    for acc in sorted(set(init_eq.keys()) | set(trades.keys())):
        eq = init_eq.get(acc, {})
        t = trades.get(acc, {"pnl": 0, "fee": 0})
        de = eq.get("delta", 0)
        tracked = t["pnl"] + t["fee"]
        gap = de - tracked
        print(f"  Acc {acc}: Dequity=${de:+.2f} - Tracked=${tracked:+.2f} = Gap=${gap:+.2f}")


if __name__ == "__main__":
    reconcile_from_snapshots()
