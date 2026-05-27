#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
adopt_orphans.py — взять под управление orphan-позиции с биржи.

Orphan = позиция открыта на BingX, но в simulated_trades нет соответствующей
записи со статусом OPEN + непустым exchange_order_id. Бот её не видит,
TSL/SL не обновляются.

Скрипт:
  1. Получает все позиции с биржи (через OrderManager).
  2. Сравнивает с DB → находит orphans.
  3. Для каждого orphan'а:
     - читает entry / qty / direction;
     - проверяет open_orders, ищет существующий SL (STOP_MARKET / STOP);
     - если SL нет — ставит fallback (entry × 0.98 для LONG / × 1.02 для SHORT);
     - INSERT в simulated_trades (status=OPEN, strategy_name=adopted_orphan,
       exchange_order_id=adopted_<ts>, exchange_sl_order_id=<live_id>).
  4. trade_tracker_loop подхватит на следующем цикле (60с) и начнёт двигать TSL.

Использование:
  python scripts/adopt_orphans.py                # dry-run, ничего не пишет
  python scripts/adopt_orphans.py --commit       # реально создаёт записи и SL
  python scripts/adopt_orphans.py --commit --no-sl  # adopt без place SL
                                                  # (если хотите поставить вручную)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.infra.config_loader import config
from core.exchange.order_manager import OrderManager


SL_FALLBACK_PCT = 0.02   # -2% от entry для LONG, +2% для SHORT


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def fmt_money(x: float | None) -> str:
    return f"${x:.2f}" if x is not None else "n/a"


async def fetch_orders_for_symbol(om: OrderManager, sym_our: str) -> list[dict]:
    try:
        return await om._get_open_orders_cached(sym_our, force=True)
    except Exception as e:
        print(f"  ! get_open_orders {sym_our} failed: {e}")
        return []


def find_sl_in_orders(orders: list[dict], pos_side: str) -> dict | None:
    """Возвращает свежайший STOP / STOP_MARKET того же pos_side, либо None."""
    sl = [
        o for o in orders
        if o.get("type") in ("STOP_MARKET", "STOP")
        and o.get("positionSide", "").upper() == pos_side.upper()
    ]
    if not sl:
        return None
    sl.sort(key=lambda o: int(o.get("time") or o.get("updateTime") or 0), reverse=True)
    return sl[0]


def get_tracked_pairs(db_path: str) -> set[tuple[str, str]]:
    """Возвращает множество (symbol, direction) для OPEN сделок с exchange_order_id.
    Hedge mode: LONG и SHORT по одной паре — две независимые tracked сделки."""
    with sqlite3.connect(db_path, timeout=10) as conn:
        conn.execute("PRAGMA busy_timeout=10000")
        rows = conn.execute(
            "SELECT DISTINCT symbol, direction FROM simulated_trades "
            "WHERE status='OPEN' AND exchange_order_id IS NOT NULL AND exchange_order_id!=''"
        ).fetchall()
    return {(r[0], (r[1] or "").upper()) for r in rows}


def insert_orphan(
    db_path: str, *,
    symbol: str, direction: str, entry: float, qty: float,
    stop_loss: float, exchange_order_id: str, exchange_sl_order_id: str,
    timeframe: str = "15m",
) -> int:
    """INSERT нового OPEN trade. Возвращает trade_id."""
    last_err: Exception | None = None
    for _ in range(5):
        try:
            with sqlite3.connect(db_path, timeout=10) as conn:
                conn.execute("PRAGMA busy_timeout=10000")
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO simulated_trades
                      (symbol, timeframe, direction, entry_price, stop_loss,
                       take_profit, qty, status, strategy_name, strategy_type,
                       sl_source, tp_source, tsl_tf, tsl_activated,
                       exchange_order_id, exchange_sl_order_id, actual_entry_price,
                       original_sl, created_at)
                    VALUES
                      (?, ?, ?, ?, ?,
                       NULL, ?, 'OPEN', 'adopted_orphan', 'SINGLE',
                       'adopted_orphan_fallback', NULL, ?, 0,
                       ?, ?, ?,
                       ?, ?)
                    """,
                    (
                        symbol, timeframe, direction, float(entry), float(stop_loss),
                        float(qty),
                        timeframe,
                        str(exchange_order_id), str(exchange_sl_order_id), float(entry),
                        float(stop_loss), now_iso(),
                    ),
                )
                conn.commit()
                return int(cur.lastrowid)
        except Exception as e:
            last_err = e
    raise RuntimeError(f"insert_orphan {symbol} failed: {last_err}")


async def adopt(args: argparse.Namespace) -> int:
    om = OrderManager(config)
    if not om.is_live():
        print(f"[!] OrderManager mode={om.mode.value} — нужен vst или live. Выход.")
        return 1

    # 1. positions с биржи
    try:
        positions = await om._get_positions_cached()
    except Exception as e:
        print(f"[!] get_positions failed: {e}")
        return 1

    # Парсинг через единый core.exchange.position_parser (hedge-aware).
    from core.exchange.position_parser import parse_positions, by_symbol_side
    open_on_exchange: dict[tuple[str, str], object] = by_symbol_side(parse_positions(positions))

    # 2. tracked в БД (symbol, direction) — иначе LONG в БД не считается за SHORT на бирже
    tracked = get_tracked_pairs(args.db)
    orphans = {k: p for k, p in open_on_exchange.items() if k not in tracked}

    print(f"== Биржа: {len(open_on_exchange)} позиций | DB OPEN+exch: {len(tracked)} | orphans: {len(orphans)} ==\n")
    if not orphans:
        print("Orphan'ов нет — нечего adopt'ить.")
        return 0

    summary: list[dict[str, Any]] = []

    for (sym_our, direction), pp in sorted(orphans.items()):
        pos_side  = direction
        qty       = pp.qty
        entry     = pp.entry
        mark      = pp.mark
        leverage  = pp.leverage
        notional  = pp.notional
        pos       = pp.raw   # legacy compat для fetch_orders_for_symbol

        print(f"--- {sym_our} {direction} qty={qty:.6f} entry={entry:.6f} mark={mark:.6f} notional={fmt_money(notional)} lev={leverage}x ---")

        if entry <= 0 or qty <= 0:
            print("  ! пропуск: entry или qty невалидны")
            continue

        # 3. SL на бирже?
        orders = await fetch_orders_for_symbol(om, sym_our)
        live_sl = find_sl_in_orders(orders, pos_side)
        live_sl_id = ""
        sl_price = 0.0

        if live_sl:
            live_sl_id = str(live_sl.get("orderId", ""))
            sl_price = float(live_sl.get("stopPrice") or 0)
            print(f"  [OK] SL уже на бирже: order_id={live_sl_id} stopPrice={sl_price:.6f}")
        else:
            # fallback расчёт
            if direction == "LONG":
                sl_price = entry * (1.0 - SL_FALLBACK_PCT)
            else:
                sl_price = entry * (1.0 + SL_FALLBACK_PCT)
            print(f"  [-] SL отсутствует. Fallback: {sl_price:.6f} ({'-' if direction=='LONG' else '+'}{SL_FALLBACK_PCT*100:.1f}% от entry)")

            if args.no_sl:
                print("  [-] --no-sl: SL не ставим (placeholder в БД будет = fallback, но на бирже его НЕТ)")
            elif args.commit:
                try:
                    new_id = await om.place_sl_order(sym_our, pos_side, sl_price, qty)
                    if new_id:
                        live_sl_id = new_id
                        print(f"  [+] SL placed: order_id={live_sl_id} @ {sl_price:.6f}")
                    else:
                        print("  [!] place_sl_order вернул None — adopt всё равно (repair_missing_sl попробует ещё)")
                except Exception as e:
                    print(f"  [!] place_sl_order error: {e}")
            else:
                print("  [-] DRY-RUN: SL не ставится")

        # 4. INSERT в БД
        adopted_exch_id = f"adopted_{int(datetime.now().timestamp())}_{sym_our.split('/')[0]}"
        if args.commit:
            try:
                tid = insert_orphan(
                    args.db,
                    symbol=sym_our, direction=direction, entry=entry, qty=qty,
                    stop_loss=sl_price,
                    exchange_order_id=adopted_exch_id,
                    exchange_sl_order_id=live_sl_id,
                )
                print(f"  [+] DB inserted: trade_id={tid}")
                summary.append({"trade_id": tid, "symbol": sym_our, "direction": direction,
                                "entry": entry, "sl": sl_price, "sl_id": live_sl_id})
            except Exception as e:
                print(f"  [!] INSERT failed: {e}")
        else:
            print(f"  [-] DRY-RUN: INSERT skipped (exch_id would be: {adopted_exch_id}, sl_id={live_sl_id or 'NEW'})")
            summary.append({"trade_id": "DRY", "symbol": sym_our, "direction": direction,
                            "entry": entry, "sl": sl_price, "sl_id": live_sl_id or "NEW"})

        print()

    print("==== ИТОГ ====")
    print(f"{'TID':>7} {'SYMBOL':<22} {'DIR':<5} {'ENTRY':>12} {'SL':>12} {'SL_ID':>15}")
    for s in summary:
        print(f"{str(s['trade_id']):>7} {s['symbol']:<22} {s['direction']:<5} {s['entry']:>12.6f} {s['sl']:>12.6f} {s['sl_id']:>15}")
    if not args.commit:
        print("\n[DRY-RUN] Чтобы реально создать записи и поставить SL -> запусти с --commit")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="subscriptions.db", help="Путь к БД (default: subscriptions.db)")
    ap.add_argument("--commit", action="store_true", help="Реально писать в БД и ставить SL")
    ap.add_argument("--no-sl", action="store_true", help="С --commit: не ставить SL, только INSERT")
    args = ap.parse_args()

    return asyncio.run(adopt(args))


if __name__ == "__main__":
    sys.exit(main())
