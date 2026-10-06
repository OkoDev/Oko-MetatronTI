---
name: usdtd_history_source_cmc_llama
description: "Как получить дневную историю USDT.D / BTC.D / total mcap с 2019 без ключей: USDT circulating (DefiLlama) / total mcap (CMC web-API global-metrics historical, кусками ≤2200 дней); в проекте до этого USDT.D был только с 2026-05"
metadata:
  type: reference
---

19.09.2026. `usdtd_1h` в проекте — с 2026-05 (94 дня), `mcap_meta` — 37 дней; CoinGecko public ограничен 365 днями и
`global/market_cap_chart` — Pro. Рабочая связка без ключей:
- USDT в обращении по дням с 2017-11: `https://stablecoins.llama.fi/stablecoincharts/all?stablecoin=1` → `totalCirculatingUSD.peggedUSD`;
- total crypto mcap, BTC.D, ETH.D по дням: `https://api.coinmarketcap.com/data-api/v3/global-metrics/quotes/historical`
  `?format=chart_crypto_details&interval=1d&timeStart=<unix>&timeEnd=<unix>` (User-Agent обязателен; лимит 2200 точек
  на запрос → кусками), ответ `data.quotes[].quote[0].totalMarketCap`, `btcDominance`;
- USDT.D = usdt / total × 100. Файл `G:/oko_lab/out/usdtd_daily.pkl` (2019-06 → 2026-09, колонки total, btc_d, eth_d,
  alt_mcap, usdt, usdt_d). Скрипт — в истории сессии b9292ecd (inline), стоит оформить в `scripts/` при внедрении в Сферу 19.
Ориентиры: 2021 бык 2.2–4.3% · 2022 медведь 7–8% · 2024 4–5% · 2026 6.6–8.9%. Связано: [[side_by_regime_core_waves]],
[[usdtd_is_price_derivative_not_positioning]].
