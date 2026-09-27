"""ЧТЕНИЕ (ничего не меняет): реальные позиции на VST против записей live_orders.
Вопрос: записи live_orders висят OPEN, хотя сделки закрыты — это зомби-записи или живые позиции?"""
import asyncio, sqlite3, sys
from pathlib import Path

ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT))
import logging; logging.disable(logging.CRITICAL)
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from core.infra.config_loader import config          # noqa: E402
from core.exchange.bingx_client import make_client  # noqa: E402
from core.exchange.position_parser import parse_positions  # noqa: E402


async def main():
    live: dict = {}
    for acc in (1, 2, 3):
        cli = make_client("vst", config, account=acc)
        if cli is None:
            continue
        try:
            raw = await cli.get_positions()
            items = parse_positions(raw)
            print(f"аккаунт {acc}: позиций {len(items)}")
            for p in items:
                live[(p.symbol_our, p.side)] = (acc, p.qty)
        except Exception as e:                      # noqa: BLE001
            print(f"аккаунт {acc}: ошибка чтения позиций — {e}")
        finally:
            try:
                await cli.close()
            except Exception:                        # noqa: BLE001
                pass

    print(f"\nВСЕГО ПОЗИЦИЙ НА VST: {len(live)}")
    for (s, sd), (acc, q) in sorted(live.items()):
        print(f"   {s:<20}{sd:<6} acc={acc} qty={q}")

    c = sqlite3.connect(ROOT / "subscriptions.db")
    rows = c.execute(
        "select lo.id, lo.symbol, lo.side, lo.sim_trade_id, st.signal_type, st.status, st.closed_at "
        "from live_orders lo left join simulated_trades st on st.id = lo.sim_trade_id "
        "where lo.status in ('OPEN','PENDING') order by lo.id").fetchall()
    print(f"\nЗАПИСЕЙ live_orders OPEN: {len(rows)}")
    zombie, real = [], []
    for lid, sym, side, sid, st_type, st_status, closed in rows:
        on_ex = (sym, side) in live
        (real if on_ex else zombie).append(lid)
        print(f"   {lid} {sym:<20}{side:<6}{str(st_type):<18}sim={str(st_status):<9}"
              f"{'НА БИРЖЕ' if on_ex else 'зомби-запись'}")
    print(f"\nИТОГ: реально в рынке {len(real)} · зомби-записей {len(zombie)} → {zombie}")

    known = {(r[1], r[2]) for r in rows}
    orphan = [k for k in live if k not in known]
    if orphan:
        print(f"\n!! ПОЗИЦИИ НА БИРЖЕ БЕЗ ЗАПИСИ live_orders ({len(orphan)}):")
        for k in orphan:
            print("   ", k, live[k])


asyncio.run(main())
