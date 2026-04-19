#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Safe emergency repair for a fixed list of trades missing exchange STOP_MARKET orders.

Default mode is dry-run. Real changes happen only with --apply.

Examples:
    python scripts/repair_missing_stops.py
    python scripts/repair_missing_stops.py --apply
    python scripts/repair_missing_stops.py --ids 5306,5329
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import sys
import time
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config_loader import config
from core.exchange.order_manager import OrderManager


APPROVED_TRADE_IDS = {6498}


def parse_ids(raw: str | None) -> list[int]:
    if not raw:
        return sorted(APPROVED_TRADE_IDS)
    ids = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        ids.append(int(chunk))
    unknown = [trade_id for trade_id in ids if trade_id not in APPROVED_TRADE_IDS]
    if unknown:
        raise ValueError(
            f"Only approved trade ids are allowed: {sorted(APPROVED_TRADE_IDS)} | got {unknown}"
        )
    return ids


def load_trades(db_path: str, trade_ids: list[int]) -> list[dict[str, Any]]:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _ in trade_ids)
        rows = conn.execute(
            f"""
            SELECT id, symbol, direction, qty, entry_price, stop_loss,
                   exchange_order_id, exchange_sl_order_id, tsl_activated, status
            FROM simulated_trades
            WHERE id IN ({placeholders})
            ORDER BY id ASC
            """,
            tuple(trade_ids),
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def update_db_sl_order_id(db_path: str, trade_id: int, sl_order_id: str) -> None:
    last_error: Exception | None = None
    for attempt in range(5):
        conn = sqlite3.connect(db_path, timeout=10)
        try:
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute(
                "UPDATE simulated_trades SET exchange_sl_order_id=? WHERE id=?",
                (sl_order_id, trade_id),
            )
            conn.commit()
            return
        except sqlite3.OperationalError as exc:
            last_error = exc
            if "locked" not in str(exc).lower() or attempt == 4:
                raise
            time.sleep(1.0 + attempt * 0.5)
        finally:
            conn.close()
    if last_error is not None:
        raise last_error


def try_update_db_sl_order_id(db_path: str, trade_id: int, sl_order_id: str) -> bool:
    try:
        update_db_sl_order_id(db_path, trade_id, sl_order_id)
        return True
    except Exception as exc:
        print(f"  WARN: failed to update DB exchange_sl_order_id for trade_id={trade_id}: {exc}")
        return False


def build_position_maps(positions: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    by_symbol: dict[str, dict[str, Any]] = {}
    by_symbol_side: dict[tuple[str, str], dict[str, Any]] = {}
    for pos in positions:
        qty = float(pos.get("positionAmt") or pos.get("availableAmt") or 0)
        if qty == 0:
            continue
        symbol = pos.get("symbol", "")
        pos_side = (pos.get("positionSide") or "").upper()
        by_symbol[symbol] = pos
        by_symbol_side[(symbol, pos_side)] = pos
    return by_symbol, by_symbol_side


async def repair_trades(db_path: str, trade_ids: list[int], apply_changes: bool) -> int:
    trades = load_trades(db_path, trade_ids)
    found_ids = {trade["id"] for trade in trades}
    missing_ids = [trade_id for trade_id in trade_ids if trade_id not in found_ids]
    if missing_ids:
        raise RuntimeError(f"Trades not found in DB: {missing_ids}")

    om = OrderManager(config)
    if not om.is_live():
        raise RuntimeError("trading.execution_mode must be vst or live")

    client = await om._get_client_synced()
    positions = await client.get_positions()
    _, positions_by_symbol_side = build_position_maps(positions)
    repaired = 0

    print("Emergency SL repair")
    print("=" * 80)
    print(f"Mode: {'APPLY' if apply_changes else 'DRY-RUN'}")
    print(f"Approved trade ids: {sorted(APPROVED_TRADE_IDS)}")

    for trade in trades:
        trade_id = int(trade["id"])
        symbol = str(trade["symbol"])
        direction = str(trade["direction"]).upper()
        pos_side = "LONG" if direction == "LONG" else "SHORT"
        bx_symbol = symbol.replace("/USDT:USDT", "-USDT")
        stop_loss = float(trade["stop_loss"] or 0)
        db_qty = float(trade["qty"] or 0)
        exchange_order_id = trade["exchange_order_id"]
        exchange_sl_order_id = trade["exchange_sl_order_id"]

        print(f"\ntrade_id={trade_id} symbol={symbol} direction={direction}")

        if trade["status"] != "OPEN":
            print(f"  SKIP: status={trade['status']} (not OPEN)")
            continue
        if not exchange_order_id:
            print("  SKIP: no exchange_order_id")
            continue
        if stop_loss <= 0:
            print(f"  SKIP: invalid stop_loss={stop_loss}")
            continue
        position = positions_by_symbol_side.get((bx_symbol, pos_side))
        if not position:
            print("  SKIP: position not open on exchange")
            continue

        exchange_qty = float(position.get("positionAmt") or position.get("availableAmt") or 0)
        exchange_qty = abs(exchange_qty)
        if exchange_qty <= 0:
            print(f"  SKIP: invalid exchange qty={exchange_qty}")
            continue
        if db_qty <= 0:
            print(f"  NOTE: DB qty is empty or invalid: db_qty={db_qty}")

        open_orders = await client.get_open_orders(symbol)
        sl_orders = [
            o for o in open_orders
            if o.get("type") == "STOP_MARKET"
            and (o.get("positionSide") or "").upper() == pos_side
        ]
        if sl_orders:
            first_order_id = str(sl_orders[0].get("orderId") or "")
            if apply_changes and first_order_id and first_order_id != str(exchange_sl_order_id or ""):
                if try_update_db_sl_order_id(db_path, trade_id, first_order_id):
                    print(f"  SYNC: updated DB exchange_sl_order_id={first_order_id}")
            print(
                "  SKIP: exchange already has STOP_MARKET order(s): "
                + ", ".join(str(o.get("orderId")) for o in sl_orders)
            )
            continue

        print(
            f"  PLAN: place STOP_MARKET {symbol} {pos_side} qty={exchange_qty} stop_loss={stop_loss} "
            f"(db_qty={db_qty}, db exchange_sl_order_id={exchange_sl_order_id})"
        )
        if not apply_changes:
            continue

        new_sl_order_id = await om.place_sl_order(symbol, pos_side, stop_loss, exchange_qty)
        if not new_sl_order_id:
            print("  ERROR: place_sl_order returned no order id")
            continue

        try_update_db_sl_order_id(db_path, trade_id, new_sl_order_id)
        repaired += 1
        print(f"  OK: created STOP_MARKET order_id={new_sl_order_id}")

    print("\n" + "=" * 80)
    print(f"Completed. repaired={repaired} mode={'APPLY' if apply_changes else 'DRY-RUN'}")
    return repaired


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Safely restore STOP_MARKET orders for a fixed approved set of trades."
    )
    parser.add_argument("--db-path", default="subscriptions.db", help="Path to subscriptions DB")
    parser.add_argument(
        "--ids",
        help="Comma-separated subset of approved trade ids",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually place STOP_MARKET orders on exchange and update DB",
    )
    args = parser.parse_args()

    trade_ids = parse_ids(args.ids)
    await repair_trades(args.db_path, trade_ids, apply_changes=args.apply)


if __name__ == "__main__":
    asyncio.run(main())
