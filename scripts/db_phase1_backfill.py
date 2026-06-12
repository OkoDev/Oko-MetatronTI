"""
ARCH-DB-V2 Фаза 1 — backfill разметки существующих сделок (12.06.2026).

Заполняет 3 новых поля в simulated_trades (после авто-миграции subscription_manager):
  - execution_mode: exchange_order_id есть → 'VST', иначе → 'SIM' (LIVE не было)
  - account_id:     сделки СВЕЖЕЕ account_routing (created_at >= ROUTING_SINCE) → по symbol;
                    СТАРЫЕ (routing не существовал) → остаются DEFAULT 1 (юзер 12.06: честное «неизвестно»)
  - exchange:       'bingx' (остаётся DEFAULT)

IDEMPOTENT — можно запускать повторно (UPDATE по правилам, не зависит от прошлых прогонов).
Сначала на КОПИИ: python scripts/db_phase1_backfill.py --db subscriptions_test.db
Боевая (через Claude после проверки): python scripts/db_phase1_backfill.py --db subscriptions.db --commit
"""
from __future__ import annotations
import argparse
import sqlite3
import sys

# account_routing заведён 08.06.2026 → сделки старше не покрываются точным account
ROUTING_SINCE = "2026-06-08"


def backfill(db_path: str, commit: bool) -> int:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # колонки должны существовать (авто-миграция subscription_manager). Проверяем.
    cols = {r[1] for r in cur.execute("PRAGMA table_info(simulated_trades)").fetchall()}
    missing = {"account_id", "execution_mode", "exchange"} - cols
    if missing:
        print(f"[!] нет колонок {missing} — сначала применить авто-миграцию (рестарт бота / init_db)")
        return 1

    total = cur.execute("SELECT COUNT(*) FROM simulated_trades").fetchone()[0]

    # 1. execution_mode: исполненные (есть exchange_order_id != 'SIM') → VST, иначе SIM
    cur.execute("""
        UPDATE simulated_trades
        SET execution_mode = CASE
            WHEN exchange_order_id IS NOT NULL AND exchange_order_id != 'SIM' THEN 'VST'
            ELSE 'SIM' END
    """)
    n_mode = cur.rowcount

    # 2. account_id: ТОЛЬКО свежие (routing существовал) по symbol; старые остаются DEFAULT 1
    cur.execute("""
        UPDATE simulated_trades
        SET account_id = (
            SELECT ar.account_id FROM account_routing ar
            WHERE ar.symbol = simulated_trades.symbol LIMIT 1
        )
        WHERE created_at >= ?
          AND symbol IN (SELECT symbol FROM account_routing)
    """, (ROUTING_SINCE,))
    n_acc = cur.rowcount

    # 3. exchange: добить NULL → bingx (на случай если DEFAULT не сработал на старых)
    cur.execute("UPDATE simulated_trades SET exchange = 'bingx' WHERE exchange IS NULL")
    n_exch = cur.rowcount

    # ── статистика ──
    print(f"=== backfill {db_path} (total={total}) ===")
    print(f"execution_mode: {dict(cur.execute('SELECT execution_mode, COUNT(*) FROM simulated_trades GROUP BY 1').fetchall())}")
    print(f"account_id:     {dict(cur.execute('SELECT account_id, COUNT(*) FROM simulated_trades GROUP BY 1').fetchall())}")
    old = cur.execute("SELECT COUNT(*) FROM simulated_trades WHERE created_at < ?", (ROUTING_SINCE,)).fetchone()[0]
    print(f"  account точный (свежие >= {ROUTING_SINCE}): {n_acc} | старые default=1: {old} ({old*100//total}%)")
    print(f"exchange:       {dict(cur.execute('SELECT exchange, COUNT(*) FROM simulated_trades GROUP BY 1').fetchall())}")

    if commit:
        conn.commit()
        print("[✓] COMMIT — изменения записаны")
    else:
        conn.rollback()
        print("[DRY] rollback — для записи добавь --commit")
    conn.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="subscriptions_test.db", help="путь к БД (по умолчанию КОПИЯ)")
    ap.add_argument("--commit", action="store_true", help="реально записать (иначе dry-run)")
    a = ap.parse_args()
    sys.exit(backfill(a.db, a.commit))
