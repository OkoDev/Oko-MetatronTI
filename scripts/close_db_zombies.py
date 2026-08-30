#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Разовая уборка зомби-OPEN: строка в БД открыта, позиции на бирже НЕТ.

Инцидент 30.08.2026: 23 таких строки (возраст 6-42ч, нотионал ~$3595). Копились потому,
что при `sphere_cutover` закрытие БД делает ТОЛЬКО WS-путь (pa=0), а бот рестартили 256 раз —
события в окне downtime терялись, и store Сферы после cold_start про них уже не знал.
Постоянное лечение — `_db_reconcile` в position_sync (тот же резолв, каждый цикл);
этот скрипт разбирает УЖЕ накопленное.

Цену НЕ угадываем: exit тянем тем же каскадом, что и штатный close (REST filled по
positionId → income-ledger). Не резолвится → строку не трогаем (её добьёт vst_time_exit по TTL).

    python scripts/close_db_zombies.py            # dry-run: что нашли и какой exit дотянули
    python scripts/close_db_zombies.py --apply    # закрыть в БД
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.infra.config_loader import config
from core.exchange.order_manager import OrderManager
from core.exchange.position_parser import parse_positions


def _load_open_vst(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT id, symbol, direction, signal_type, account_id, qty, entry_price,
                      actual_entry_price, stop_loss, position_id, exchange_order_id, created_at
               FROM simulated_trades
               WHERE status='OPEN' AND execution_mode!='SIM'
                 AND exchange_order_id IS NOT NULL AND exchange_order_id NOT IN ('', 'SIM')
               ORDER BY created_at"""
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="реально закрыть (по умолчанию dry-run)")
    ap.add_argument("--db", default="subscriptions.db")
    args = ap.parse_args()

    om = OrderManager(config)
    if not om.is_live():
        print("режим SIM — на бирже сверять нечего")
        return

    live = {(pp.symbol_our, pp.side) for pp in parse_positions(await om._get_positions_cached(force=True))
            if getattr(pp, "qty", 0)}
    rows = _load_open_vst(args.db)
    zombies = [r for r in rows if (r["symbol"], (r["direction"] or "").upper()) not in live]
    print(f"позиций на бирже: {len(live)} · OPEN VST в БД: {len(rows)} · ЗОМБИ: {len(zombies)}")
    if not zombies:
        return

    # тот же резолв, что у штатного close-пути — через Сферу (adapter + pid из БД)
    from core.execution.bingx_adapter import BingXAdapter
    from core.execution.position_store import PositionStore
    from core.execution.sphere import ExecutionSphere
    from core.execution.domain import Position
    from core.execution.db_writer import apply_exit_to_trade
    from core.trading.trade_simulator import TradeSimulator

    sphere = ExecutionSphere(BingXAdapter(om), PositionStore(), on_close=None)
    sim = TradeSimulator(args.db)

    closed = unresolved = 0
    for r in zombies:
        acc = int(r["account_id"] or 1)
        side = (r["direction"] or "LONG").upper()
        pos = Position(symbol=r["symbol"], side=side, qty=float(r["qty"] or 0), account=acc,
                       entry=float(r["actual_entry_price"] or r["entry_price"] or 0) or None,
                       position_id=str(r["position_id"]) if r["position_id"] else None)
        ex = await sphere._resolve_exit_via_rest(acc, pos)
        if ex is None:
            ex = await sphere._resolve_exit_via_income(acc, pos)
        if ex is None:
            unresolved += 1
            print(f"  #{r['id']:<6} {r['symbol']:<18} {side:<5} acc{acc} — exit НЕ резолвится, пропуск")
            continue
        print(f"  #{r['id']:<6} {r['symbol']:<18} {side:<5} acc{acc} → {ex.status} @ {ex.exit_price:.8g} "
              f"rp={ex.realized_pnl:.4g} ({ex.order_type})")
        if args.apply:
            if await apply_exit_to_trade(sim, int(r["id"]), ex, symbol=r["symbol"], side=side,
                                         reason="zombie_cleanup"):
                closed += 1

    print(f"\nитог: резолвлено {len(zombies) - unresolved}/{len(zombies)}"
          + (f", закрыто {closed}" if args.apply else " (dry-run — БД не тронута)"))


if __name__ == "__main__":
    asyncio.run(main())
