---
name: env-binance-fstream-ws-blocked
description: "fstream.binance.com WS молчит с машины Егора (коннект ок, данных 0) — фьючерсные WS-стримы Binance недоступны; spot-WS и REST fapi работают"
metadata: 
  node_type: memory
  type: project
  originSessionId: 70bdb517-4925-4055-bc3f-52cc60dde717
---

# Binance FUTURES WS заблокирован с машины (03.07.2026)

**Факт (проверено пробами 03.07):** `wss://fstream.binance.com` — TLS-коннект устанавливается,
но данных НЕ приходит вообще (aggTrade BTC = 0 msg/35с, !forceOrder@arr = 0). При этом:
- SPOT WS `wss://stream.binance.com:9443` — работает (494 msg/20с)
- SPOT WS `wss://data-stream.binance.vision` — работает
- REST `fapi.binance.com` — работает (радар на нём живёт)

**Why:** похоже на региональную фильтрацию именно фьючерсного WS data-plane. Публичного REST
для чужих ликвидаций у Binance нет (allForceOrders deprecated).

**Дополнение (03.07, проверено):** SG-прокси проекта (PROXY_LIST) НЕ спасает — туннель WSS
работает (SPOT через прокси 41 msg/15с), но fstream молчит и через SG = гео-фильтр Binance
для NL И SG (уход из NL + запрет MAS в SG). VPN Егора = NL.

**How to apply:**
- НЕ строить фичи на fstream WS без проверки живости потока (коннект без данных = тихий провал).
- **РЕШЕНИЕ: ликвидации с Bybit** — `wss://stream.bybit.com/v5/public/linear`,
  topic `allLiquidation.{SYM}USDT` живой (проверено 157 тиков/20с на publicTrade).
  `scripts/liq_ws.py` переписан (9f9ee6b): source='bybit_ws', op:ping/20с, chunks по 10.
- Второй слой: синтетика из OI-унвинда `oi_fast_poller._log_liq_synth` (source='oi_synth').
- Если понадобится realtime фьючерсов Binance: только VPN другого региона.

Связано: [[liq-magnets-pump-radar-tools]]
