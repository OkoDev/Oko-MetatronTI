# -*- coding: utf-8 -*-
"""РЕКОНСИЛЯЦИЯ ФАНТОМОВ (07.08, Егор «вариант А») — восстановить ФАКТИЧЕСКИЕ выходы.

Проблема: 9 из 17 VST-сделок числятся OPEN в БД, но на бирже их нет (позиция закрылась,
а БД не обновилась). Дашборд считает по ним P&L → форвард-статистика загрязнена.

Решение (вариант А — честный): поднять реальный выход с биржи.
  1) get_filled_orders(symbol) → ищем ЗАКРЫВАЮЩИЙ филл после входа (противоположная сторона)
  2) get_income(REALIZED_PNL) в окне → денежная истина по сделке (сверка)
  3) статус выводим из цены выхода против SL/TP записи (SL / TP / EXPIRED)
Dry-run по умолчанию; запись только с --apply. Ничего не выдумываем: если выход
не найден — НЕ трогаем запись и говорим об этом прямо.
"""
import sys, os, asyncio, sqlite3, argparse, datetime as dt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from core.infra.config_loader import config
from core.exchange.order_manager import OrderManager

DB = "subscriptions.db"


def _open_vst():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    q = """SELECT id, symbol, direction, account_id, signal_type, created_at,
                  entry_price, actual_entry_price, stop_loss, take_profit, position_id
           FROM simulated_trades
           WHERE status IN ('OPEN','PENDING_ENTRY') AND execution_mode='VST'
           ORDER BY created_at"""
    rows = [dict(r) for r in c.execute(q).fetchall()]
    c.close()
    return rows


def _ts(s):
    try:
        d = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None


async def main(apply_changes: bool):
    om = OrderManager(config)
    if not om.is_live():
        raise RuntimeError("execution_mode должен быть vst/live")
    router = om._get_router()
    clients = router._clients
    print(f"клиентов: {list(clients)}")

    # что реально висит на бирже
    def _norm(s):
        """'APEX-USDT' и 'APEX/USDT:USDT' → 'APEX'. Баг 07.08: сравнивал разные форматы,
        и ВСЕ 17 записей попали в «фантомы» (спасла только защита «выход не найден»)."""
        s = str(s or "").split(":")[0].replace("/", "-")
        return s.split("-")[0].upper()

    live = {}
    for acc, cli in clients.items():
        try:
            for p in (await cli.get_positions() or []):
                if float(p.get("positionAmt") or p.get("qty") or 0) != 0:
                    live[_norm(p.get("symbol"))] = p
        except Exception as e:
            print(f"  acc{acc} get_positions err: {type(e).__name__}")
    print(f"на бирже позиций: {len(live)} → {sorted(live)}\n")

    rows = _open_vst()
    phantoms = [r for r in rows if _norm(r["symbol"]) not in live]
    print(f"OPEN в БД: {len(rows)} · ФАНТОМОВ (нет на бирже): {len(phantoms)}\n")

    updates = []
    for r in phantoms:
        cli = clients.get(r["account_id"]) or next(iter(clients.values()))
        opened = _ts(r["created_at"])
        entry = float(r["actual_entry_price"] or r["entry_price"] or 0)
        d = str(r["direction"] or "").upper()
        close_side = "SELL" if d.startswith("L") else "BUY"
        exit_px = exit_ts = None; src = ""
        try:
            orders = await cli.get_filled_orders(r["symbol"], limit=100)
        except Exception as e:
            orders = []
            print(f"  #{r['id']} {r['symbol']}: get_filled_orders err {type(e).__name__}")
        cands = []
        for o in orders:
            try:
                t = int(o.get("updateTime") or o.get("time") or 0)
                if opened and t < int(opened.timestamp() * 1000):
                    continue
                if str(o.get("side", "")).upper() != close_side:
                    continue
                px = float(o.get("avgPrice") or o.get("price") or 0)
                if px > 0:
                    cands.append((t, px, o.get("type"), o.get("orderId")))
            except Exception:
                continue
        if cands:
            cands.sort()
            exit_ts, exit_px, otype, oid = cands[0]
            src = f"filled_order {otype} #{oid}"
        # денежная сверка
        rp = None
        if opened:
            try:
                inc = await cli.get_income(int(opened.timestamp() * 1000),
                                           int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000),
                                           income_type="REALIZED_PNL")
                bx = r["symbol"].split(":")[0].replace("/", "-")
                vals = [float(x.get("income") or 0) for x in inc if str(x.get("symbol")) == bx]
                if vals:
                    rp = sum(vals)
            except Exception:
                pass
        if not exit_px or not entry:
            print(f"  ⚠️  #{r['id']:6} {r['symbol'][:18]:18} {r['signal_type'][:12]:12} — ВЫХОД НЕ НАЙДЕН, не трогаю"
                  f" (realized={rp})")
            continue
        pnl = ((exit_px - entry) / entry * 100) if d.startswith("L") else ((entry - exit_px) / entry * 100)
        # Статус по ТИПУ ордера — авторитетнее арифметики. Баг 07.08: сравнение цены со стопом
        # врало, когда TSL подтянул стоп ВЫШЕ входа (AEONBSC вышел по TAKE_PROFIT, метился SL).
        ot = str(otype or "").upper()
        if "TAKE_PROFIT" in ot:
            status = "TP"
        elif "STOP" in ot or "TRAILING" in ot:
            status = "TSL" if pnl > 0 else "SL"   # стоп в профите = сработал трейлинг
        else:
            status = "EXPIRED"
        ct = dt.datetime.fromtimestamp(exit_ts / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        age = (dt.datetime.now(dt.timezone.utc) - opened).total_seconds() / 86400 if opened else -1
        print(f"  ✅ #{r['id']:6} {r['symbol'][:18]:18} {r['signal_type'][:12]:12} возраст={age:4.1f}д "
              f"вход={entry:.6g} выход={exit_px:.6g} → {status:8} P&L={pnl:+7.2f}% realized=${rp if rp is not None else '?'} "
              f"[{src}]")
        updates.append((status, exit_px, round(pnl, 4), ct, r["id"]))

    print(f"\nк записи: {len(updates)} из {len(phantoms)} фантомов")
    if not apply_changes:
        print("DRY-RUN. Для записи: --apply")
        return
    c = sqlite3.connect(DB)
    for status, px, pnl, ct, tid in updates:
        c.execute("""UPDATE simulated_trades SET status=?, exit_price=?, profit_pct=?, closed_at=?
                     WHERE id=? AND status IN ('OPEN','PENDING_ENTRY')""", (status, px, pnl, ct, tid))
    c.commit(); c.close()
    print(f"✅ записано {len(updates)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    asyncio.run(main(a.apply))
