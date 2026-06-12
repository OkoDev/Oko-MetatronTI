"""
close_hedge_orphans.py — закрыть HEDGE-orphan позиции ТОЧЕЧНО по стороне (12.06).

Hedge-orphan: биржа держит позицию (symbol, side), которой нет в БД OPEN, НО БД держит
ДРУГУЮ сторону того же символа (hedge-skip в close_orphans). Бот не управляет orphan-стороной.

ВАЖНО: НЕ используем one-click (closeAllPositions закроет и БД-брата!). Только точечный
market close по pos_side (reduceOnly + retry без reduceOnly). Если 109400 не закрылась —
лог, пропуск (безопаснее, чем задеть брата).

Фильтр: --max-pnl X (закрывать только с pnl <= X, по умолчанию все). --commit — реально.
Запуск: python scripts/close_hedge_orphans.py [--max-pnl -5] [--commit]
"""
from __future__ import annotations
import argparse, asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
from dotenv import load_dotenv; load_dotenv()

from core.infra.config_loader import config
from core.exchange.order_manager import OrderManager
from core.exchange.position_parser import parse_positions, by_symbol_side
from scripts.close_orphans import get_open_pairs_all, get_open_symbols, fmt_money


async def main(args):
    om = OrderManager(config)
    if not om.is_live():
        print("[!] нужен vst/live"); return 1
    ex = by_symbol_side(parse_positions(await om._get_positions_cached()))
    tracked = get_open_pairs_all(args.db)
    open_syms = get_open_symbols(args.db)
    # hedge-orphan: биржа без БД OPEN (symbol,dir), НО symbol есть в БД OPEN (др. сторона)
    hedge = {k: p for k, p in ex.items() if k not in tracked and k[0] in open_syms}
    # фильтр по pnl
    targets = {k: p for k, p in hedge.items()
               if args.max_pnl is None or (p.unrealized_pnl or 0) <= args.max_pnl}
    print(f"== hedge-orphan: {len(hedge)} | под закрытие (pnl<={args.max_pnl}): {len(targets)} ==\n")
    if not targets:
        print("нечего закрывать."); return 0

    client = await om._get_client_synced()
    closed = failed = 0; tot = 0.0
    for (sym, direction), p in sorted(targets.items(), key=lambda x: x[1].unrealized_pnl or 0):
        pnl = p.unrealized_pnl or 0; tot += pnl
        # close_position_market(side): side=BUY→закрыть LONG, side=SELL→закрыть SHORT
        side = "BUY" if direction == "LONG" else "SELL"
        print(f"--- {sym.split('/')[0]:12} {direction:5} qty={p.qty:.4g} pnl={fmt_money(pnl)} ---")
        if p.qty <= 0:
            print("  qty<=0 — пропуск"); continue
        # positionId (Separate Isolated mode требует для точечного close)
        pid = p.raw.get("positionId") if isinstance(p.raw, dict) else None
        if not pid:
            pid = await om._get_position_id(sym, direction)
        if not args.commit:
            print(f"  [DRY] закрыл бы точечно market {side} qty={p.qty:.4g} positionId={pid} (БЕЗ one-click)")
            continue
        # есть ли БИРЖЕВОЙ брат (противоположная сторона на бирже)? Если нет — one-click безопасен
        opp = "LONG" if direction == "SHORT" else "SHORT"
        brother_on_exchange = (sym, opp) in ex
        try:
            from core.exchange.bingx_client import to_bingx_symbol
            close_side = "BUY" if direction == "SHORT" else "SELL"
            payload = {"symbol": to_bingx_symbol(sym), "side": close_side,
                       "positionSide": direction, "type": "MARKET", "quantity": str(p.qty)}
            if pid:
                payload["positionId"] = str(pid)
            r = await client.post("/openApi/swap/v2/trade/order", payload)
            code = r.get("code", -1) if isinstance(r, dict) else -1
            if code == 0:
                print(f"  [✓] закрыта точечно (positionId={pid})"); closed += 1
            elif not brother_on_exchange:
                # биржевого брата НЕТ (БД-брат = SIM) → one-click безопасен
                oc = await client.close_position_one_click(sym)
                if oc.get("code") == 0:
                    print(f"  [✓] закрыта one-click (брат SIM, не на бирже)"); closed += 1
                else:
                    print(f"  [✗] one-click code={oc.get('code')} msg={str(oc.get('msg',''))[:45]}"); failed += 1
            else:
                print(f"  [✗] code={code} + биржевой брат ЕСТЬ → точечный не вышел, one-click опасен — пропуск"); failed += 1
        except Exception as e:
            print(f"  [✗] err {e}"); failed += 1
        print()
    print(f"\n==== ИТОГ ==== закрыто={closed} не_закрылось={failed} суммарный_pnl={fmt_money(tot)}")
    if not args.commit:
        print("\n[DRY] для реального закрытия → --commit")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="subscriptions.db")
    ap.add_argument("--max-pnl", type=float, default=None, help="закрывать только pnl<=X (напр -5)")
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a)))
