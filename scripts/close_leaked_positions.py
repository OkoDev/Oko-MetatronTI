# -*- coding: utf-8 -*-
"""CLOSE LEAKED POSITIONS (25.07, Егор «закрыть») — разовое закрытие утёкших VST-позиций.

Контекст: до фикса signal_router.enabled старый путь ставил VST-ордера БЕЗ source-гейта →
неодобренные источники (wt_sideways/confluence/wl_breach/pivot_reversal/liquidity_sweep) висят
на бирже. Закрываем ТОЛЬКО их, оставляем radar/atr_change/atr_s2/ds_advisor.

Надёжность (обход граблей hedge_close_multiacct_root):
- бьём по account_id из БД через router._clients[acc] (НЕ символьный роутинг)
- матч позиции по (symbol, side) на ЕЁ аккаунте → берём positionId (hedge-корень 101205)
- cancel open orders этого символа → close_position_market reduce-only → метка БД EXPIRED
Dry-run по умолчанию; реальное закрытие только с --apply.
"""
import sys, os, asyncio, sqlite3, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from core.infra.config_loader import config
from core.exchange.order_manager import OrderManager

# ⚠️ signal_type хранится как radar_pump/radar_spring/radar_build/atr_change — фильтр по ПРЕФИКСУ,
# НЕ по точному 'radar' (иначе скрипт целит нужные пампы). Урок 25.07.
DB = "subscriptions.db"


def _approved(st: str) -> bool:
    st = st or ""
    return st.startswith("radar") or st.startswith("atr") or st == "ds_advisor"


def _ex_symbol(our: str) -> str:
    # 'BTC/USDT:USDT' → 'BTC-USDT'
    return our.split(":")[0].replace("/", "-")


def _targets():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    q = """SELECT id, symbol, direction, account_id, signal_type FROM simulated_trades
        WHERE status IN ('OPEN','PENDING_ENTRY') AND exchange_order_id IS NOT NULL
        ORDER BY account_id, id"""
    rows = [dict(r) for r in c.execute(q).fetchall() if not _approved(r["signal_type"])]
    c.close()
    return rows


async def main(apply_changes: bool):
    om = OrderManager(config)
    if not om.is_live():
        raise RuntimeError("execution_mode должен быть vst/live")
    router = om._get_router()
    clients = router._clients  # {account_id: BingXClient}
    targets = _targets()
    by_acc = {}
    for t in targets:
        by_acc.setdefault(t["account_id"], []).append(t)
    print("=" * 78)
    print(f"CLOSE LEAKED · режим: {'APPLY' if apply_changes else 'DRY-RUN'} · "
          f"к закрытию {len(targets)} (acc: {{a: len(v) for a,v in by_acc.items()}})".replace(
              "{a: len(v) for a,v in by_acc.items()}", str({a: len(v) for a, v in by_acc.items()})))
    closed = 0; skipped = 0
    for acc, trades in by_acc.items():
        cli = clients.get(acc)
        if cli is None:
            print(f"\n[acc{acc}] НЕТ КЛИЕНТА — пропуск {len(trades)} сделок")
            skipped += len(trades)
            continue
        try:
            positions = await cli.get_positions()
        except Exception as e:
            print(f"\n[acc{acc}] get_positions err: {e}")
            continue
        idx = {}
        for p in positions:
            amt = float(p.get("positionAmt") or p.get("availableAmt") or 0)
            if amt == 0:
                continue
            idx[(str(p.get("symbol", "")), str(p.get("positionSide", "")).upper())] = p
        print(f"\n[acc{acc}] живых позиций: {len(idx)} · целей: {len(trades)}")
        for t in trades:
            exsym = _ex_symbol(t["symbol"])
            side_pos = "LONG" if t["direction"].upper() == "LONG" else "SHORT"
            pos = idx.get((exsym, side_pos))
            if not pos:
                print(f"  SKIP #{t['id']} {exsym} {side_pos}: позиции нет на бирже (уже закрыта?)")
                skipped += 1
                continue
            qty = abs(float(pos.get("positionAmt") or pos.get("availableAmt") or 0))
            pid = str(pos.get("positionId") or "") or None
            side_close = "BUY" if side_pos == "LONG" else "SELL"
            print(f"  #{t['id']} {exsym} {side_pos} qty={qty} pid={pid} → cancel+close reduce-only")
            if not apply_changes:
                continue
            try:
                oo = await cli.get_open_orders(t["symbol"])
                for o in oo:
                    oid = str(o.get("orderId") or "")
                    if oid:
                        await cli.cancel_order(t["symbol"], oid)
                res = await cli.close_position_market(t["symbol"], side_close, qty, position_id=pid)
                if res.get("code", -1) != 0:
                    print(f"    ERROR close: {res}")
                    continue
                cc = sqlite3.connect(DB)
                cc.execute("UPDATE simulated_trades SET status='EXPIRED', closed_at=datetime('now'), "
                           "exit_price=? WHERE id=?", (float(pos.get("markPrice") or 0) or None, t["id"]))
                cc.commit(); cc.close()
                closed += 1
                print(f"    OK закрыта, БД → EXPIRED")
            except Exception as e:
                print(f"    ERR #{t['id']}: {e}")
    print("\n" + "=" * 78)
    print(f"Итог: закрыто={closed} пропущено={skipped} режим={'APPLY' if apply_changes else 'DRY-RUN'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    asyncio.run(main(a.apply))
