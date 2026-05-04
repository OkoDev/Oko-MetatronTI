#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Чистка накопленных дубликатов SL-ордеров на BingX.

Проблема 20.04: get_sl_order_id искал только STOP_MARKET, а при sl_limit_buffer_pct>0
SL создаётся как STOP. → repair_missing_sl каждые 60с ставил новый SL → накопление
(30 ордеров на CAKE, 24 на PUMPBTC и т.д.).

Скрипт: для каждой открытой позиции находит все SL (STOP+STOP_MARKET) того же pos_side.
Если >1 — оставляет самый свежий, остальные cancel.

По умолчанию dry-run. Для применения: --apply.

Usage:
    python scripts/cleanup_duplicate_sl.py              # dry-run
    python scripts/cleanup_duplicate_sl.py --apply      # реальная чистка
    python scripts/cleanup_duplicate_sl.py --apply --symbols CAKE-USDT,PUMPBTC-USDT
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.infra.config_loader import config
from core.exchange.order_manager import OrderManager


async def scan_and_cleanup(apply: bool, symbols_filter: set[str] | None) -> None:
    om = OrderManager(config)
    if not om.is_live():
        print("[cleanup] OrderManager не в LIVE режиме — выход")
        return

    client = await om._get_client_synced()
    positions = await client.get_positions()
    open_positions = [p for p in positions if float(p.get("positionAmt") or 0) != 0]
    print(f"[cleanup] Открытых позиций: {len(open_positions)}")

    total_extras = 0
    total_cancelled = 0

    for pos in open_positions:
        bx_sym = pos.get("symbol", "")
        pos_side = pos.get("positionSide", "").upper()
        if not bx_sym or pos_side not in ("LONG", "SHORT"):
            continue
        symbol = f"{bx_sym[:-5]}/USDT:USDT" if bx_sym.endswith("-USDT") else bx_sym
        if symbols_filter and bx_sym not in symbols_filter and symbol not in symbols_filter:
            continue

        try:
            orders = await client.get_open_orders(symbol)
        except Exception as e:
            print(f"[cleanup] {symbol}: get_open_orders error: {e}")
            continue

        sl_orders = [
            o for o in orders
            if o.get("type") in ("STOP_MARKET", "STOP")
            and o.get("positionSide", "").upper() == pos_side
        ]
        if len(sl_orders) <= 1:
            print(f"[cleanup] {symbol} {pos_side}: SL={len(sl_orders)} — OK")
            continue

        sl_orders.sort(
            key=lambda o: int(o.get("time") or o.get("updateTime") or 0),
            reverse=True,
        )
        keep = sl_orders[0]
        extras = sl_orders[1:]
        total_extras += len(extras)

        print(
            f"[cleanup] {symbol} {pos_side}: найдено {len(sl_orders)} SL, "
            f"оставляем #{keep.get('orderId')} (price={keep.get('stopPrice')}), "
            f"отменяем {len(extras)}",
        )

        if not apply:
            continue

        for o in extras:
            oid = str(o["orderId"])
            ok = await om.cancel_order(symbol, oid)
            if ok:
                total_cancelled += 1
            await asyncio.sleep(0.1)  # анти rate-limit

    mode = "APPLIED" if apply else "DRY-RUN"
    print(f"\n[cleanup] {mode}: дубликатов={total_extras} отменено={total_cancelled}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Чистка дубликатов SL-ордеров на BingX")
    parser.add_argument("--apply", action="store_true", help="Применить (иначе dry-run)")
    parser.add_argument(
        "--symbols",
        type=str,
        default="",
        help="Список символов через запятую (например CAKE-USDT,PUMPBTC-USDT). Пусто = все",
    )
    args = parser.parse_args()

    symbols_filter: set[str] | None = None
    if args.symbols.strip():
        symbols_filter = {s.strip() for s in args.symbols.split(",") if s.strip()}
        print(f"[cleanup] Фильтр по символам: {symbols_filter}")

    asyncio.run(scan_and_cleanup(apply=args.apply, symbols_filter=symbols_filter))


if __name__ == "__main__":
    main()
