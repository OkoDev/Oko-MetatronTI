#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
close_orphans.py — ЗАКРЫТЬ orphan-позиции на бирже (OPS-06, 12.06).

Orphan = позиция на BingX без OPEN-записи в БД (БД закрыла сделку, биржевой close упал
→ позиция висит без управления). В отличие от adopt_orphans.py (подхватить в БД), этот
скрипт ЗАКРЫВАЕТ позицию на бирже (market close + one-click fallback). БД не трогаем —
она уже закрыта (orphan = нет OPEN записи).

Использование:
  python scripts/close_orphans.py            # dry-run, ничего не закрывает
  python scripts/close_orphans.py --commit   # реально закрывает позиции на бирже
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import sqlite3

from core.infra.config_loader import config
from core.exchange.order_manager import OrderManager
from scripts.adopt_orphans import fmt_money


def get_open_pairs_all(db_path: str) -> set[tuple[str, str]]:
    """ВСЕ OPEN (symbol, direction) НЕЗАВИСИМО от exchange_order_id.

    Критично: orphan = биржа держит позицию, а в БД НЕТ OPEN-записи. Если фильтровать
    по exch_id (как adopt), то живая бот-сделка с потерянным exchange_order_id
    (XLM atr_change OPEN exch=None — баг-семья qty/exch_id) ложно считается orphan'ом
    и была бы закрыта. Берём ВСЕ OPEN → не трогаем живые сделки.
    """
    with sqlite3.connect(db_path, timeout=10) as conn:
        conn.execute("PRAGMA busy_timeout=10000")
        rows = conn.execute(
            "SELECT DISTINCT symbol, direction FROM simulated_trades WHERE status='OPEN'"
        ).fetchall()
    return {(r[0], (r[1] or "").upper()) for r in rows}


def get_open_symbols(db_path: str) -> set[str]:
    """Символы с ЛЮБОЙ OPEN-сделкой (любое направление). Если символ тут — НЕ закрываем
    биржевую позицию (БД держит по нему сделку → hedge-риск/живая логика)."""
    with sqlite3.connect(db_path, timeout=10) as conn:
        conn.execute("PRAGMA busy_timeout=10000")
        rows = conn.execute(
            "SELECT DISTINCT symbol FROM simulated_trades WHERE status='OPEN'"
        ).fetchall()
    return {r[0] for r in rows}


async def close_orphans(args: argparse.Namespace) -> int:
    om = OrderManager(config)
    if not om.is_live():
        print(f"[!] OrderManager mode={om.mode.value} — нужен vst или live. Выход.")
        return 1

    try:
        positions = await om._get_positions_cached()
    except Exception as e:
        print(f"[!] get_positions failed: {e}")
        return 1

    from core.exchange.position_parser import parse_positions, by_symbol_side
    open_on_exchange = by_symbol_side(parse_positions(positions))
    tracked = get_open_pairs_all(args.db)
    open_syms = get_open_symbols(args.db)
    all_orphans = {k: p for k, p in open_on_exchange.items() if k not in tracked}
    # SAFETY: пропускаем символы где БД держит OPEN (hedge-риск/живая сделка).
    orphans = {k: p for k, p in all_orphans.items() if k[0] not in open_syms}
    hedge_skip = {k: p for k, p in all_orphans.items() if k[0] in open_syms}
    if hedge_skip:
        print(f"⚠️ ПРОПУЩЕНО {len(hedge_skip)} (БД держит OPEN по символу — hedge-риск, НЕ закрываем):")
        for (s, d), p in sorted(hedge_skip.items()):
            print(f"   {s} {d} qty={p.qty:.4f} pnl={fmt_money(p.unrealized_pnl or 0)}")
        print()

    print(f"== Биржа: {len(open_on_exchange)} позиций | DB OPEN+exch: {len(tracked)} | orphans: {len(orphans)} ==\n")
    if not orphans:
        print("Orphan'ов нет — нечего закрывать.")
        return 0

    client = await om._get_client_synced()
    closed = 0
    failed = 0
    total_pnl = 0.0

    for (sym_our, direction), pp in sorted(orphans.items()):
        qty = pp.qty
        pnl = pp.unrealized_pnl or 0.0
        total_pnl += pnl
        side_close = "SELL" if direction == "LONG" else "BUY"
        print(f"--- {sym_our} {direction} qty={qty:.4f} mark={pp.mark:.6f} pnl={fmt_money(pnl)} ---")
        if qty <= 0:
            print("  ! qty<=0 — пропуск")
            continue
        if not args.commit:
            print(f"  [DRY-RUN] закрыл бы market {side_close} qty={qty:.4f}")
            continue
        try:
            resp = await client.close_position_market(sym_our, side_close, qty)
            code = resp.get("code", 0) if isinstance(resp, dict) else 0
            if code != 0:
                print(f"  [!] market close failed code={code} — one-click fallback")
                resp2 = await client.close_position_one_click(sym_our)
                code2 = resp2.get("code", 0) if isinstance(resp2, dict) else 0
                if code2 != 0:
                    print(f"  [✗] one-click тоже failed code={code2}")
                    failed += 1
                    continue
                print(f"  [✓] закрыт one-click")
            else:
                print(f"  [✓] закрыт market")
            closed += 1
        except Exception as e:
            print(f"  [✗] ошибка close: {e}")
            failed += 1
        print()

    print("\n==== ИТОГ ====")
    print(f"orphans={len(orphans)} закрыто={closed} ошибок={failed} суммарный_pnl={fmt_money(total_pnl)}")
    if not args.commit:
        print("\n[DRY-RUN] Чтобы реально закрыть → python scripts/close_orphans.py --commit")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="subscriptions.db")
    ap.add_argument("--commit", action="store_true", help="Реально закрыть позиции на бирже")
    args = ap.parse_args()
    return asyncio.run(close_orphans(args))


if __name__ == "__main__":
    sys.exit(main())
