# -*- coding: utf-8 -*-
"""SHADOW-поллер The Graph (P2): раз в 5 мин тянет крупные Uniswap-события → onchain_events.

Отдельный процесс (НЕ в боте — изоляция). Копим историю с первого дня для честной валидации.
Запуск:  set THEGRAPH_API_KEY=... && python scripts/thegraph_shadow_poller.py
Или ключ в config.yaml: the_graph: { api_key: "..." }
"""
import sys, time, logging
sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
from core.signals.thegraph_client import poll_uniswap_events

INTERVAL = 300

if __name__ == "__main__":
    print("[GRAPH-SHADOW] poller start (Uniswap V3: swaps>$250k, liq>$500k, каждые 5 мин)")
    while True:
        try:
            r = poll_uniswap_events(since_ts=int(time.time()) - INTERVAL - 60)
            print(f"[GRAPH-SHADOW] {time.strftime('%H:%M:%S')} → {r}")
            if "error" in r:
                print("[GRAPH-SHADOW] нет ключа? THEGRAPH_API_KEY / config the_graph.api_key. Сплю 30 мин.")
                time.sleep(1800)
                continue
        except KeyboardInterrupt:
            break
        except Exception as e:  # noqa: BLE001
            print(f"[GRAPH-SHADOW] err: {e}")
        time.sleep(INTERVAL)
