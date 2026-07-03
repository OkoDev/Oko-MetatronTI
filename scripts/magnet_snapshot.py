# -*- coding: utf-8 -*-
"""Копилка карт магнитов — дневной снапшот по всем монетам радара (Егор 03.07: добро).

Зачем: OI-история Binance живёт 20 дней — карты магнитов НЕ восстановимы задним числом
(в отличие от пивотов/FVG, которые считаются из вечных klines). Форвард-копилка =
единственный способ доказать формулу «ниже WPP → за топливом вниз» и точность
магнит-целей. Сверка с фактами: liq_events (scripts/liq_ws.py) — предсказание vs факт.

Запуск разовый:  python scripts/magnet_snapshot.py
pm2 (раз в день): pm2 start scripts/magnet_snapshot.py --name magnet-snap
                  --interpreter <python> --no-autorestart --cron-restart "15 8 * * *"
"""
import sys
import time
import json

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
sys.path.insert(0, ".")

from oko_feed.store import conn
from scripts.liq_magnets import build_magnets
from scripts.oi_fast_poller import CORE


def snapshot_all() -> int:
    c = conn()
    c.execute("""CREATE TABLE IF NOT EXISTS magnet_snapshots (
        date TEXT, ts INTEGER, symbol TEXT, px REAL,
        tot_above REAL, tot_below REAL, above_json TEXT, below_json TEXT,
        PRIMARY KEY (symbol, date))""")
    c.commit()
    today = time.strftime("%Y-%m-%d", time.gmtime())
    n_ok = 0
    for sym in CORE:
        try:
            m = build_magnets(sym)
        except Exception as e:  # noqa: BLE001
            print(f"[MAGNET-SNAP] {sym}: err {e}")
            m = None
        if m:
            c.execute("INSERT OR REPLACE INTO magnet_snapshots VALUES (?,?,?,?,?,?,?,?)",
                      (today, int(time.time()), sym, m["px"], m["tot_above"], m["tot_below"],
                       json.dumps(m["above"]), json.dumps(m["below"])))
            c.commit()
            n_ok += 1
        time.sleep(0.4)                                  # бережно к weight-лимиту
    c.close()
    print(f"[MAGNET-SNAP] {today}: {n_ok}/{len(CORE)} снапшотов сохранено")
    return n_ok


if __name__ == "__main__":
    snapshot_all()
