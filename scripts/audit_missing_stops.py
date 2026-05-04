#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Emergency audit for exchange positions missing STOP_MARKET orders.

Examples:
    python scripts/audit_missing_stops.py
    python scripts/audit_missing_stops.py --only-missing
    python scripts/audit_missing_stops.py --json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.infra.config_loader import config
from core.exchange.order_manager import OrderManager


def load_open_db_trades(db_path: str) -> dict[str, dict[str, Any]]:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, symbol, direction, qty, entry_price, stop_loss,
                   exchange_order_id, exchange_sl_order_id, tsl_activated, tsl_tf
            FROM simulated_trades
            WHERE status='OPEN' AND exchange_order_id IS NOT NULL AND exchange_order_id != ''
            ORDER BY id ASC
            """
        ).fetchall()
    finally:
        conn.close()

    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        trade = dict(row)
        bx_symbol = trade["symbol"].replace("/USDT:USDT", "-USDT")
        result[bx_symbol] = trade
    return result


async def build_report(db_path: str) -> dict[str, Any]:
    db_trades = load_open_db_trades(db_path)

    om = OrderManager(config)
    if not om.is_live():
        raise RuntimeError("trading.execution_mode must be vst or live")

    client = await om._get_client_synced()
    positions = await client.get_positions()

    tracked_missing_sl: list[dict[str, Any]] = []
    tracked_with_sl: list[dict[str, Any]] = []
    untracked_missing_sl: list[dict[str, Any]] = []
    untracked_with_sl: list[dict[str, Any]] = []

    for pos in positions:
        qty = float(pos.get("positionAmt") or pos.get("availableAmt") or 0)
        if qty == 0:
            continue

        bx_symbol = pos.get("symbol", "")
        pos_side = (pos.get("positionSide") or "").upper()
        our_symbol = bx_symbol.replace("-", "/") + ":USDT"
        open_orders = await client.get_open_orders(our_symbol)
        sl_orders = [
            {
                "order_id": str(o.get("orderId", "")),
                "stop_price": o.get("stopPrice"),
                "qty": o.get("origQty") or o.get("quantity"),
                "status": o.get("status"),
            }
            for o in open_orders
            if o.get("type") in ("STOP_MARKET", "STOP")
            and (o.get("positionSide") or "").upper() == pos_side
        ]

        item = {
            "symbol": bx_symbol,
            "position_side": pos_side,
            "qty": qty,
            "avg_price": pos.get("avgPrice") or pos.get("avgPositionPrice") or pos.get("price"),
            "open_orders": len(open_orders),
            "sl_orders": sl_orders,
        }

        db_trade = db_trades.get(bx_symbol)
        if db_trade:
            item["db_trade_id"] = db_trade["id"]
            item["db_stop_loss"] = db_trade["stop_loss"]
            item["db_exchange_sl_order_id"] = db_trade["exchange_sl_order_id"]
            item["db_tsl_activated"] = db_trade["tsl_activated"]
            item["db_tsl_tf"] = db_trade["tsl_tf"]
            if sl_orders:
                tracked_with_sl.append(item)
            else:
                tracked_missing_sl.append(item)
        else:
            if sl_orders:
                untracked_with_sl.append(item)
            else:
                untracked_missing_sl.append(item)

    return {
        "summary": {
            "tracked_missing_sl": len(tracked_missing_sl),
            "tracked_with_sl": len(tracked_with_sl),
            "untracked_missing_sl": len(untracked_missing_sl),
            "untracked_with_sl": len(untracked_with_sl),
            "open_positions_total": (
                len(tracked_missing_sl)
                + len(tracked_with_sl)
                + len(untracked_missing_sl)
                + len(untracked_with_sl)
            ),
        },
        "tracked_missing_sl": tracked_missing_sl,
        "tracked_with_sl": tracked_with_sl,
        "untracked_missing_sl": untracked_missing_sl,
        "untracked_with_sl": untracked_with_sl,
    }


def print_items(title: str, items: list[dict[str, Any]]) -> None:
    print(f"\n{title}: {len(items)}")
    for item in items:
        base = (
            f"  {item['symbol']} {item['position_side']} qty={item['qty']} "
            f"open_orders={item['open_orders']} sl_orders={len(item['sl_orders'])}"
        )
        extras = []
        if "db_trade_id" in item:
            extras.append(f"trade_id={item['db_trade_id']}")
            extras.append(f"db_sl={item['db_stop_loss']}")
            extras.append(f"db_sl_order_id={item['db_exchange_sl_order_id']}")
            extras.append(f"tsl_activated={item['db_tsl_activated']}")
        if item["sl_orders"]:
            extras.append(
                "sl_prices=" + ",".join(str(sl["stop_price"]) for sl in item["sl_orders"])
            )
        if extras:
            base += " | " + " | ".join(extras)
        print(base)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit BingX open positions and detect missing STOP_MARKET orders."
    )
    parser.add_argument("--db-path", default="subscriptions.db", help="Path to subscriptions DB")
    parser.add_argument(
        "--only-missing",
        action="store_true",
        help="Print only positions missing STOP_MARKET",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full report as JSON",
    )
    args = parser.parse_args()

    report = await build_report(args.db_path)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    summary = report["summary"]
    print("Emergency SL audit")
    print("=" * 80)
    print(
        "Open positions: {open_positions_total} | tracked missing SL: {tracked_missing_sl} | "
        "tracked with SL: {tracked_with_sl} | untracked missing SL: {untracked_missing_sl} | "
        "untracked with SL: {untracked_with_sl}".format(**summary)
    )

    if args.only_missing:
        print_items("Tracked by bot but missing SL", report["tracked_missing_sl"])
        print_items("Untracked by bot and missing SL", report["untracked_missing_sl"])
        return

    print_items("Tracked by bot but missing SL", report["tracked_missing_sl"])
    print_items("Tracked by bot and protected", report["tracked_with_sl"])
    print_items("Untracked by bot and missing SL", report["untracked_missing_sl"])
    print_items("Untracked by bot but protected", report["untracked_with_sl"])


if __name__ == "__main__":
    asyncio.run(main())
