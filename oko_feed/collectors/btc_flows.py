"""BTC exchange flows — нативный Bitcoin через mempool.space (бесплатно, без ключей).

Механика: следим за известными горячими кошельками бирж. INFLOW (депозиты) = готовятся
продавать (медвежье), OUTFLOW (выводы в холд) = не собираются продавать (бычье).
Видим даже мемпул (до подтверждения) — быстрее платных Glassnode/CryptoQuant.

Standalone: python -m oko_feed.collectors.btc_flows
Пишет в external_data.db: onchain_events (kind=btc_inflow/btc_outflow, source=mempool.space).
"""
from __future__ import annotations

import json
import time
import urllib.request

from ..store import add_onchain_event, conn

# Известные горячие кошельки (публичные метки). Дополняется по мере находок.
EXCHANGE_WALLETS = {
    "bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h": "binance_hot",
    "34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo": "binance_cold_legacy",
    "bc1qgdjqv0av3q56jvd82tkdjpy7gdp9ut8tlqmgrpmv24sq90ecnvqqjwvw97": "bitfinex_hot",
    "3Cbq7aT1tY8kMxWLbitaG7yT6bPbKChq64": "huobi_cold",
}
MIN_BTC = 5.0                  # события от 5 BTC (~$300k)


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 oko-feed"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def collect(window_sec: int = 3600) -> dict:
    """Свежие крупные in/out по биржевым кошелькам за окно (+мемпул). → счётчики."""
    now = int(time.time())
    n_in = n_out = 0
    btc_in = btc_out = 0.0
    for addr, label in EXCHANGE_WALLETS.items():
        try:
            txs = _get(f"https://mempool.space/api/address/{addr}/txs")
        except Exception as e:  # noqa: BLE001
            print(f"[btc_flows] {label}: {e}")
            continue
        for t in txs:
            st = t.get("status", {})
            ts = st.get("block_time") or now          # mempool = сейчас
            if ts < now - window_sec:
                continue
            vin_addrs = {v.get("prevout", {}).get("scriptpubkey_address") for v in t.get("vin", [])}
            to_addr = sum(o.get("value", 0) for o in t.get("vout", [])
                          if o.get("scriptpubkey_address") == addr) / 1e8
            from_addr = addr in vin_addrs
            if from_addr:
                amt = sum(o.get("value", 0) for o in t.get("vout", [])
                          if o.get("scriptpubkey_address") != addr) / 1e8
                if amt >= MIN_BTC:
                    add_onchain_event(ts, "btc_outflow", "mempool.space", label, amt, "risk_on",
                                      t.get("txid", "")[:64])
                    n_out += 1; btc_out += amt
            elif to_addr >= MIN_BTC:
                add_onchain_event(ts, "btc_inflow", "mempool.space", label, to_addr, "risk_off",
                                  t.get("txid", "")[:64])
                n_in += 1; btc_in += to_addr
        time.sleep(1)                                  # вежливость к API
    return {"inflow_n": n_in, "inflow_btc": round(btc_in, 2),
            "outflow_n": n_out, "outflow_btc": round(btc_out, 2)}


if __name__ == "__main__":
    r = collect()
    print(f"[btc_flows] {r}")
    net = r["outflow_btc"] - r["inflow_btc"]
    print(f"[btc_flows] НЕТТО за час: {net:+.1f} BTC "
          f"({'ВЫВОДЯТ (бычье)' if net > 0 else 'ЗАВОДЯТ на биржи (медвежье)' if net < 0 else 'нейтрально'})")
