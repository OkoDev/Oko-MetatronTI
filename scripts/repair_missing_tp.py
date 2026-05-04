#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Восстанавливает TAKE_PROFIT ордера на BingX для открытых позиций.

Логика:
  1. Получаем все open-позиции с биржи.
  2. По каждой ищем в simulated_trades последнюю OPEN-сделку (symbol+direction).
  3. Если tsl_activated=1 → пропускаем (TSL-защита включена, TP не нужен).
  4. Если tsl_activated=0:
       - смотрим open_orders: TAKE_PROFIT_MARKET / TAKE_PROFIT того же pos_side
       - если найдено >1 дубликатов → оставляем самый свежий, остальные cancel
       - если нет TP → ставим новый по take_profit из БД

Dry-run по умолчанию. Для применения: --apply.

Usage:
    python scripts/repair_missing_tp.py              # dry-run
    python scripts/repair_missing_tp.py --apply      # реально
    python scripts/repair_missing_tp.py --apply --symbols CAKE-USDT
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import sys
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.infra.config_loader import config
from core.exchange.order_manager import OrderManager


_DB_SNAPSHOT: Optional[str] = None


def _get_db_snapshot(db_path: str) -> str:
    """WSL+Windows блокирует субд при активном боте → копируем db+wal+shm в /tmp."""
    global _DB_SNAPSHOT
    if _DB_SNAPSHOT and os.path.exists(_DB_SNAPSHOT):
        return _DB_SNAPSHOT
    import shutil
    import tempfile
    src = os.path.abspath(db_path)
    tmp_dir = tempfile.gettempdir()
    snap = os.path.join(tmp_dir, f"repair_tp_{os.getpid()}.db")
    shutil.copy2(src, snap)
    for suffix in ("-wal", "-shm"):
        s = src + suffix
        if os.path.exists(s):
            shutil.copy2(s, snap + suffix)
    _DB_SNAPSHOT = snap
    print(f"[repair-tp] БД snapshot: {snap}")
    return snap


def find_open_trade(db_path: str, symbol: str, direction: str) -> Optional[dict[str, Any]]:
    """Самая свежая OPEN-сделка по symbol+direction. Работает со снапшотом БД."""
    snap = _get_db_snapshot(db_path)
    conn = sqlite3.connect(snap, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT id, symbol, direction, qty, entry_price, stop_loss, take_profit,
                   tsl_activated, status, exchange_order_id, tp1_hit_at
            FROM simulated_trades
            WHERE symbol = ? AND direction = ? AND status = 'OPEN'
            ORDER BY id DESC LIMIT 1
            """,
            (symbol, direction),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


async def place_tp(client, symbol: str, pos_side: str, tp_price: float, qty: float) -> Optional[str]:
    """Ставит TAKE_PROFIT_MARKET на бирже через прямой API-запрос."""
    bx_symbol = symbol.replace("/", "-").replace(":USDT", "")
    side = "SELL" if pos_side == "LONG" else "BUY"
    params = {
        "symbol":       bx_symbol,
        "side":         side,
        "positionSide": pos_side,
        "type":         "TAKE_PROFIT_MARKET",
        "quantity":     str(qty),
        "stopPrice":    str(tp_price),
        "workingType":  "MARK_PRICE",
    }
    resp = await client.post("/openApi/swap/v2/trade/order", params)
    if resp.get("code", -1) != 0:
        print(f"  [TP place] FAIL: {resp.get('msg', resp)}")
        return None
    oid = str(resp.get("data", {}).get("order", {}).get("orderId", ""))
    return oid or None


async def scan_and_repair(apply: bool, symbols_filter: set[str] | None) -> None:
    om = OrderManager(config)
    if not om.is_live():
        print("[repair-tp] OrderManager не в LIVE режиме — выход")
        return

    db_path = config.get("database.path", "subscriptions.db")
    client = await om._get_client_synced()
    positions = await client.get_positions()
    open_positions = [p for p in positions if float(p.get("positionAmt") or 0) != 0]
    print(f"[repair-tp] Открытых позиций: {len(open_positions)}")

    total_placed = 0
    total_cancelled_dups = 0
    total_skipped_tsl = 0
    total_skipped_no_trade = 0

    for pos in open_positions:
        bx_sym = pos.get("symbol", "")
        pos_side = pos.get("positionSide", "").upper()
        real_qty = abs(float(pos.get("positionAmt") or 0))
        if not bx_sym or pos_side not in ("LONG", "SHORT") or real_qty <= 0:
            continue
        symbol = f"{bx_sym[:-5]}/USDT:USDT" if bx_sym.endswith("-USDT") else bx_sym
        if symbols_filter and bx_sym not in symbols_filter and symbol not in symbols_filter:
            continue

        direction = pos_side
        trade = find_open_trade(db_path, symbol, direction)
        if not trade:
            print(f"[repair-tp] {symbol} {pos_side}: нет OPEN-сделки в БД — skip (orphan)")
            total_skipped_no_trade += 1
            continue

        tsl_active = bool(trade.get("tsl_activated"))
        tp_price = float(trade.get("take_profit") or 0)
        trade_id = trade["id"]

        if tsl_active:
            print(f"[repair-tp] {symbol} {pos_side} #{trade_id}: tsl_activated=1 — skip")
            total_skipped_tsl += 1
            continue

        if tp_price <= 0:
            print(f"[repair-tp] {symbol} {pos_side} #{trade_id}: take_profit={tp_price} — skip")
            continue

        # Проверка направления TP (защита от перевёрнутого)
        entry_price = float(trade.get("entry_price") or 0)
        if entry_price > 0:
            tp_ok = (tp_price > entry_price) if pos_side == "LONG" else (tp_price < entry_price)
            if not tp_ok:
                print(f"[repair-tp] {symbol} {pos_side} #{trade_id}: TP={tp_price} на неверной "
                      f"стороне от entry={entry_price} — skip")
                continue

        try:
            orders = await client.get_open_orders(symbol)
        except Exception as e:
            print(f"[repair-tp] {symbol}: get_open_orders error: {e}")
            continue

        tp_orders = [
            o for o in orders
            if o.get("type") in ("TAKE_PROFIT_MARKET", "TAKE_PROFIT")
            and o.get("positionSide", "").upper() == pos_side
        ]

        if len(tp_orders) >= 1:
            # Дедуп
            if len(tp_orders) > 1:
                tp_orders.sort(
                    key=lambda o: int(o.get("time") or o.get("updateTime") or 0),
                    reverse=True,
                )
                keep = tp_orders[0]
                extras = tp_orders[1:]
                print(f"[repair-tp] {symbol} {pos_side} #{trade_id}: {len(tp_orders)} TP, "
                      f"оставляем #{keep.get('orderId')}, отменяем {len(extras)}")
                if apply:
                    for o in extras:
                        await om.cancel_order(symbol, str(o["orderId"]))
                        total_cancelled_dups += 1
                        await asyncio.sleep(0.1)
            else:
                print(f"[repair-tp] {symbol} {pos_side} #{trade_id}: TP уже есть — OK")
            continue

        # TP отсутствует, tsl_activated=0 → ставим
        qty_floor = await client.quantize_qty(symbol, real_qty)
        if qty_floor <= 0:
            print(f"[repair-tp] {symbol} {pos_side} #{trade_id}: qty={real_qty} → 0 после округления — skip")
            continue

        print(f"[repair-tp] {symbol} {pos_side} #{trade_id}: ставим TP @ {tp_price} qty={qty_floor} "
              f"(entry={entry_price}, tsl_activated=0)")
        if apply:
            oid = await place_tp(client, symbol, pos_side, tp_price, qty_floor)
            if oid:
                print(f"  ✅ TP order_id={oid}")
                total_placed += 1
            await asyncio.sleep(0.2)

    mode = "APPLIED" if apply else "DRY-RUN"
    print(f"\n[repair-tp] {mode}: TP поставлено={total_placed} "
          f"дубликатов_отменено={total_cancelled_dups} "
          f"skip_tsl_active={total_skipped_tsl} skip_no_trade={total_skipped_no_trade}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Восстановление TP на BingX для сделок без активного TSL")
    parser.add_argument("--apply", action="store_true", help="Применить изменения")
    parser.add_argument("--symbols", type=str, default="",
                        help="Список символов через запятую. Пусто = все")
    args = parser.parse_args()

    symbols_filter: set[str] | None = None
    if args.symbols.strip():
        symbols_filter = {s.strip() for s in args.symbols.split(",") if s.strip()}
        print(f"[repair-tp] Фильтр: {symbols_filter}")

    asyncio.run(scan_and_repair(apply=args.apply, symbols_filter=symbols_filter))


if __name__ == "__main__":
    main()
