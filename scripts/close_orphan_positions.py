#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Emergency close for orphan exchange positions that are already closed in DB.

Default mode is dry-run. Real close happens only with --apply.

Examples:
    python scripts/close_orphan_positions.py
    python scripts/close_orphan_positions.py --apply
    python scripts/close_orphan_positions.py --symbols PTB-USDT,MEW-USDT
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


APPROVED_SYMBOLS = {
    "PTB-USDT",
    "MEW-USDT",
    "HOME-USDT",
    "ALLO-USDT",
    "AAPLX-USDT",
}
DB_CLOSED_STATUSES = {"SL", "TP", "TSL", "EXPIRED"}


def parse_symbols(raw: str | None) -> list[str]:
    if not raw:
        return sorted(APPROVED_SYMBOLS)
    symbols = []
    for chunk in raw.split(","):
        chunk = chunk.strip().upper()
        if not chunk:
            continue
        symbols.append(chunk)
    unknown = [symbol for symbol in symbols if symbol not in APPROVED_SYMBOLS]
    if unknown:
        raise ValueError(
            f"Only approved symbols are allowed: {sorted(APPROVED_SYMBOLS)} | got {unknown}"
        )
    return symbols


def load_latest_db_trade(db_path: str, bx_symbol: str) -> dict[str, Any] | None:
    our_symbol = bx_symbol.replace("-", "/") + ":USDT"
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT id, symbol, direction, entry_price, stop_loss, take_profit,
                   status, exchange_order_id, exchange_sl_order_id,
                   created_at, closed_at, exit_price
            FROM simulated_trades
            WHERE symbol=? AND exchange_order_id IS NOT NULL AND exchange_order_id != ''
            ORDER BY id DESC
            LIMIT 1
            """,
            (our_symbol,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


async def close_symbols(db_path: str, symbols: list[str], apply_changes: bool) -> int:
    om = OrderManager(config)
    if not om.is_live():
        raise RuntimeError("trading.execution_mode must be vst or live")

    client = await om._get_client_synced()
    positions = await client.get_positions()
    positions_by_symbol_side: dict[tuple[str, str], dict[str, Any]] = {}
    positions_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for pos in positions:
        qty = float(pos.get("positionAmt") or pos.get("availableAmt") or 0)
        if qty == 0:
            continue
        symbol = str(pos.get("symbol", ""))
        pos_side = str(pos.get("positionSide", "")).upper()
        positions_by_symbol_side[(symbol, pos_side)] = pos
        positions_by_symbol.setdefault(symbol, []).append(pos)

    closed = 0
    print("Emergency orphan close")
    print("=" * 80)
    print(f"Mode: {'APPLY' if apply_changes else 'DRY-RUN'}")
    print(f"Approved symbols: {sorted(APPROVED_SYMBOLS)}")

    for bx_symbol in symbols:
        db_trade = load_latest_db_trade(db_path, bx_symbol)
        print(f"\nsymbol={bx_symbol}")

        if not db_trade:
            print("  SKIP: no exchange-backed DB trade found")
            continue
        if db_trade["status"] not in DB_CLOSED_STATUSES:
            print(f"  SKIP: latest DB status is {db_trade['status']} (not closed)")
            continue

        direction = str(db_trade["direction"]).upper()
        pos_side = "LONG" if direction == "LONG" else "SHORT"
        position = positions_by_symbol_side.get((bx_symbol, pos_side))
        if not position:
            print("  SKIP: matching open exchange position not found")
            continue

        our_symbol = bx_symbol.replace("-", "/") + ":USDT"
        exchange_qty = abs(float(position.get("positionAmt") or position.get("availableAmt") or 0))
        side = "BUY" if direction == "LONG" else "SELL"
        open_orders = await client.get_open_orders(our_symbol)

        print(
            f"  DB trade_id={db_trade['id']} status={db_trade['status']} "
            f"closed_at={db_trade['closed_at']} exit_price={db_trade['exit_price']}"
        )
        print(
            f"  PLAN: cancel {len(open_orders)} open order(s), then close {our_symbol} "
            f"{direction} qty={exchange_qty} via MARKET reduce-only"
        )

        if not apply_changes:
            continue

        for order in open_orders:
            order_id = str(order.get("orderId") or "")
            if not order_id:
                continue
            await om.cancel_order(our_symbol, order_id)
            print(f"  CANCELED order_id={order_id}")

        result = await client.close_position_market(our_symbol, side, exchange_qty)
        if result.get("code", -1) != 0:
            print(f"  ERROR: close_position_market failed: {result}")
            continue

        order_id = str(result.get("data", {}).get("order", {}).get("orderId", ""))
        print(f"  OK: close order submitted order_id={order_id}")
        closed += 1

    print("\n" + "=" * 80)
    print(f"Completed. close_submitted={closed} mode={'APPLY' if apply_changes else 'DRY-RUN'}")
    return closed


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Close orphan exchange positions whose latest DB trade is already closed."
    )
    parser.add_argument("--db-path", default="subscriptions.db", help="Path to subscriptions DB")
    parser.add_argument("--symbols", help="Comma-separated subset of approved symbols")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually cancel open orders and submit market close orders",
    )
    args = parser.parse_args()

    symbols = parse_symbols(args.symbols)
    await close_symbols(args.db_path, symbols, args.apply)


if __name__ == "__main__":
    asyncio.run(main())
