# -*- coding: utf-8 -*-
"""Поллер btc_flows: раз в 10 мин собирает BTC exchange-флоу → oko_feed external_data.db.

pm2 start python --name btc-flows -- scripts/btc_flows_poller.py
"""
import sys, time
sys.path.insert(0, ".")
from oko_feed.collectors.btc_flows import collect
from oko_feed.collectors.oi import collect as collect_oi

INTERVAL = 600
_tick = 0

if __name__ == "__main__":
    print("[BTC-FLOWS] poller start (кошельки бирж >=5 BTC / 10 мин + OI 18 монет / час)")
    while True:
        try:
            _tick += 1
            if _tick % 6 == 1:                      # раз в час — OI-снимок ядра (24ч-дельты)
                oi = collect_oi()
                hot = {k: v for k, v in oi.items() if isinstance(v, float) and abs(v) >= 3}
                print(f"[OI] {time.strftime('%H:%M')} Δ24ч≥3%: {hot}")
            # ОПЕРАТИВНЫЙ OI-радар (каждые 10 мин): |Δ10м|≥0.5% → oi_spike в Feed
            from oko_feed.collectors.oi import live_radar
            ev = live_radar()
            if ev:
                print(f"[OI-RADAR] {time.strftime('%H:%M')} {ev}")
            # FEED-ALERTS → TG (сквизы/киты/флоу/режим, cooldown внутри)
            from oko_feed.alerts import check_and_alert
            al = check_and_alert()
            if al:
                print(f"[ALERTS] {time.strftime('%H:%M')} отправлено: {al}")
            r = collect(window_sec=INTERVAL + 120)
            net = r["outflow_btc"] - r["inflow_btc"]
            print(f"[BTC-FLOWS] {time.strftime('%H:%M:%S')} in={r['inflow_btc']} out={r['outflow_btc']} "
                  f"net={net:+.1f} BTC {'(в холд)' if net > 0 else '(на биржи!)' if net < 0 else ''}")
        except KeyboardInterrupt:
            break
        except Exception as e:  # noqa: BLE001
            print(f"[BTC-FLOWS] err: {e}")
        time.sleep(INTERVAL)
