#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сопоставление биржевых позиций (без связи с DB) с DB OPEN-записями без exchange_order_id.

Для каждой биржевой позиции (symbol, positionSide) ищет DB OPEN-запись с тем же
symbol+direction и пустым exchange_order_id. Если найдено ровно одна — присваивает
exchange_order_id (placeholder "RESYNC_<position_symbol>"), а также подхватывает
SL/TP orderId с биржи.

Default dry-run. --apply для реальных изменений в DB.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.infra.config_loader import config
from core.exchange.order_manager import OrderManager


def load_candidates(db_path: str) -> list[dict[str, Any]]:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, symbol, direction, entry_price, stop_loss, take_profit, created_at
            FROM simulated_trades
            WHERE status='OPEN'
              AND (exchange_order_id IS NULL OR exchange_order_id='')
            ORDER BY created_at DESC
            """
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def update_db_trade(db_path: str, trade_id: int, ex_id: str, sl_id: str, tp_id: str) -> None:
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute(
            """UPDATE simulated_trades
               SET exchange_order_id=?, exchange_sl_order_id=?, exchange_tp_order_id=?
               WHERE id=?""",
            (ex_id, sl_id, tp_id, trade_id),
        )
        conn.commit()
    finally:
        conn.close()


def expire_trade(db_path: str, trade_id: int) -> None:
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute(
            """UPDATE simulated_trades
               SET status='EXPIRED', closed_at=CURRENT_TIMESTAMP,
                   exit_price=0, profit_pct=0, R_multiple=0,
                   duration_minutes = CAST((julianday('now') - julianday(created_at)) * 1440 AS INTEGER)
               WHERE id=?""",
            (trade_id,),
        )
        conn.commit()
    finally:
        conn.close()


async def resync(db_path: str, apply_changes: bool) -> None:
    om = OrderManager(config)
    if not om.is_live():
        raise RuntimeError("trading.execution_mode must be vst or live")

    client = await om._get_client_synced()
    positions = await client.get_positions()

    # Только открытые позиции
    active = []
    for p in positions:
        qty = float(p.get("positionAmt") or p.get("availableAmt") or 0)
        if qty == 0:
            continue
        active.append(p)

    db_rows = load_candidates(db_path)
    print("=" * 80)
    print(f"Mode: {'APPLY' if apply_changes else 'DRY-RUN'}")
    print(f"Exchange positions: {len(active)} | DB OPEN без ex_id: {len(db_rows)}")
    print("=" * 80)

    # Индекс DB по (symbol, direction)
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in db_rows:
        key = (r["symbol"], r["direction"].upper())
        by_key.setdefault(key, []).append(r)

    matched_ids: set[int] = set()
    matched = 0
    ambiguous = 0
    orphan_positions = 0

    for p in active:
        bx_symbol = p.get("symbol", "")
        our_symbol = bx_symbol.replace("-", "/") + ":USDT"
        pos_side = (p.get("positionSide") or "").upper()
        direction = pos_side  # LONG/SHORT

        key = (our_symbol, direction)
        candidates = by_key.get(key, [])
        # Skip already-matched rows (e.g. post-patch MANTA/AUCTION уже заполнены)
        fresh_candidates = [c for c in candidates if c["id"] not in matched_ids]

        if len(fresh_candidates) == 0:
            print(f"  ORPHAN-POS: {our_symbol} {direction} — нет подходящих DB OPEN")
            orphan_positions += 1
            continue
        if len(fresh_candidates) > 1:
            print(f"  AMBIG: {our_symbol} {direction} — {len(fresh_candidates)} кандидатов: ids={[c['id'] for c in fresh_candidates]}")
            ambiguous += 1
            # Берём самую свежую (первую — они отсортированы DESC)
            chosen = fresh_candidates[0]
            print(f"      -> выбран самый свежий id={chosen['id']}")
        else:
            chosen = fresh_candidates[0]

        # Подхватываем SL/TP с биржи
        sl_id = await om.get_sl_order_id(our_symbol, pos_side) or ""
        tp_id = await om.get_tp_order_id(our_symbol, pos_side) or ""
        ex_id_placeholder = f"RESYNC_{bx_symbol}_{pos_side}"

        print(f"  MATCH: id={chosen['id']} {our_symbol} {direction} created={chosen['created_at']} -> ex={ex_id_placeholder} sl={sl_id or 'None'} tp={tp_id or 'None'}")
        matched_ids.add(chosen["id"])
        matched += 1

        if apply_changes:
            update_db_trade(db_path, chosen["id"], ex_id_placeholder, sl_id, tp_id)

    # Остальные DB OPEN без совпадения биржи — zombies
    zombies = [r for r in db_rows if r["id"] not in matched_ids]
    print()
    print(f"Zombies (DB OPEN без позиции на бирже): {len(zombies)}")
    for z in zombies[:10]:
        print(f"  id={z['id']} {z['symbol']} {z['direction']} created={z['created_at']}")
    if len(zombies) > 10:
        print(f"  ... ещё {len(zombies)-10}")

    if apply_changes and zombies:
        print(f"\nПомечаю {len(zombies)} zombies как EXPIRED...")
        for z in zombies:
            expire_trade(db_path, z["id"])

    print()
    print("=" * 80)
    print(f"Matched: {matched} | Ambiguous: {ambiguous} | Orphan positions: {orphan_positions} | Zombies: {len(zombies)}")
    print(f"Mode: {'APPLY' if apply_changes else 'DRY-RUN'}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default="subscriptions.db")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    await resync(args.db_path, apply_changes=args.apply)


if __name__ == "__main__":
    asyncio.run(main())
