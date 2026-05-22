"""
repair_vst_sl.py — принудительное обновление SL-ордеров на бирже для VST позиций.

Запуск (один раз, после fix_sl_audit.py --fix):
  python scripts/repair_vst_sl.py [--dry-run]

Что делает:
  1. Читает все открытые VST позиции из БД
  2. Для каждой: получает live SL ордер с биржи, сравнивает цену с БД stop_loss
  3. Если расхождение > 0.1% — cancel + place_sl_order по цене из БД
"""
import asyncio
import sqlite3
import sys
import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DRY_RUN = "--dry-run" in sys.argv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DB = "subscriptions.db"


async def main():
    from core.exchange.bingx_client import make_client
    from core.exchange.order_manager import OrderManager
    from core.trading.tsl_engine import is_side_valid
    from core.infra.config_loader import config

    client = make_client(mode="vst", config=config)
    if client is None:
        logger.error("Не удалось создать BingXClient (mode=vst) — проверь BINGX_VST_API_KEY в .env")
        return

    om = OrderManager(client)

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT id, symbol, direction, entry_price, stop_loss,
               exchange_sl_order_id, exchange_order_id, qty
        FROM simulated_trades
        WHERE status = 'OPEN'
          AND exchange_order_id IS NOT NULL AND exchange_order_id != ''
        ORDER BY id
    """).fetchall()

    logger.info("Открытых VST позиций: %d", len(rows))

    updated = 0
    skipped = 0
    errors = 0

    for r in rows:
        trade_id = r["id"]
        symbol = r["symbol"]
        direction = r["direction"]
        sl_price = float(r["stop_loss"] or 0)
        db_sl_oid = r["exchange_sl_order_id"] or ""
        qty = float(r["qty"] or 0)
        pos_side = "LONG" if direction == "LONG" else "SHORT"

        if sl_price <= 0:
            skipped += 1
            continue

        try:
            # Текущая цена для is_side_valid проверки
            try:
                cur_price = await client.get_current_price(symbol)
            except Exception:
                cur_price = None

            if cur_price and not is_side_valid(direction, sl_price, float(cur_price)):
                logger.warning("#%d %s %s: skip — SL=%.6f уже пройден ценой=%.6f",
                               trade_id, symbol, direction, sl_price, float(cur_price))
                skipped += 1
                continue

            # Биржевой SL order ID
            live_sl_oid = await om.get_sl_order_id(symbol, pos_side)
            if not live_sl_oid:
                logger.debug("#%d %s: нет биржевого SL ордера — repair_missing_sl восстановит", trade_id, symbol)
                skipped += 1
                continue

            # Получаем детали ордера чтобы узнать его цену
            # BingXClient не имеет get_order_price, используем get_open_orders
            live_price = None
            try:
                orders_resp = await client.get_open_orders(symbol)
                orders = orders_resp if isinstance(orders_resp, list) else orders_resp.get("data", {}).get("orders", [])
                for o in orders:
                    if str(o.get("orderId", "")) == str(live_sl_oid):
                        live_price = float(o.get("stopPrice") or o.get("price") or 0)
                        break
            except Exception as e:
                logger.debug("#%d %s: не удалось получить цену ордера: %s", trade_id, symbol, e)

            if live_price is None:
                logger.debug("#%d %s: live SL oid=%s есть, но цена неизвестна — пропуск", trade_id, symbol, live_sl_oid)
                skipped += 1
                continue

            diff_pct = abs(live_price - sl_price) / sl_price * 100 if sl_price else 0
            if diff_pct < 0.1:
                logger.debug("#%d %s: live_sl=%.6f ~ db_sl=%.6f (%.3f%%) — совпадает",
                             trade_id, symbol, live_price, sl_price, diff_pct)
                skipped += 1
                continue

            logger.info("#%d %s %s: live=%.6f  db=%.6f  diff=%.2f%% — обновляю",
                        trade_id, symbol, direction, live_price, sl_price, diff_pct)

            if DRY_RUN:
                logger.info("  [DRY_RUN] пропущено")
                updated += 1
                continue

            # qty из позиции на бирже
            real_qty = await om.get_position_qty(symbol, pos_side)
            if not real_qty:
                logger.warning("#%d %s: qty=0 на бирже — ORPHAN, пропуск", trade_id, symbol)
                skipped += 1
                continue
            if not qty:
                qty = real_qty

            new_oid = await om.update_sl(
                symbol=symbol, pos_side=pos_side,
                old_sl_order_id=live_sl_oid,
                new_sl_price=sl_price,
                qty=qty,
                old_sl_price=live_price,
                min_move_pct=0.1,
            )
            if new_oid:
                conn.execute(
                    "UPDATE simulated_trades SET exchange_sl_order_id=? WHERE id=?",
                    (new_oid, trade_id),
                )
                conn.commit()
                logger.info("  OK: new SL order_id=%s", new_oid)
                updated += 1
            else:
                logger.warning("  update_sl вернул None — проверь биржу вручную для #%d %s", trade_id, symbol)
                errors += 1

        except Exception as e:
            logger.error("#%d %s: %s", trade_id, symbol, e)
            errors += 1

    conn.close()
    logger.info("\nИтого: updated=%d  skipped=%d  errors=%d", updated, skipped, errors)
    if DRY_RUN:
        logger.info("[DRY_RUN] Реальных изменений нет — запусти без --dry-run")


if __name__ == "__main__":
    asyncio.run(main())
