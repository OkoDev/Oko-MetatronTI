# -*- coding: utf-8 -*-
"""Поллер btc_flows: раз в 10 мин собирает BTC exchange-флоу → oko_feed external_data.db.

pm2 start python --name btc-flows -- scripts/btc_flows_poller.py
"""
import sys, time
sys.path.insert(0, ".")
from oko_feed.collectors.btc_flows import collect

INTERVAL = 600

if __name__ == "__main__":
    print("[BTC-FLOWS] poller start (кошельки бирж, >=5 BTC, каждые 10 мин)")
    while True:
        try:
            r = collect(window_sec=INTERVAL + 120)
            net = r["outflow_btc"] - r["inflow_btc"]
            print(f"[BTC-FLOWS] {time.strftime('%H:%M:%S')} in={r['inflow_btc']} out={r['outflow_btc']} "
                  f"net={net:+.1f} BTC {'(в холд)' if net > 0 else '(на биржи!)' if net < 0 else ''}")
        except KeyboardInterrupt:
            break
        except Exception as e:  # noqa: BLE001
            print(f"[BTC-FLOWS] err: {e}")
        time.sleep(INTERVAL)
