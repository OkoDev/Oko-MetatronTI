---
name: bingx_api_key_single_per_account
description: "BingX: API-ключ ОДИН на аккаунт, демо/реал решает ДОМЕН (не ключ). BINGX_API_KEY в .env невалиден (100413), рабочий — BINGX_VST_API_KEY, он отвечает на обоих доменах. На боевом счету $0.6"
metadata: 
  node_type: memory
  type: project
  originSessionId: 8a85002d-70e3-47a1-91f1-8bb41a7089c3
  modified: 2026-08-14T01:18:23.384Z
---

# BingX: ключ один на аккаунт, режим решает домен (14.08.2026)

Проверено прямым чтением баланса всеми четырьмя комбинациями ключ×домен:

| ключ | VST-домен | LIVE-домен |
|---|---|---|
| `BINGX_API_KEY` (.env) | **100413** Incorrect apiKey | **100413** Incorrect apiKey |
| `BINGX_VST_API_KEY` (.env) | code=0, asset=VST | code=0, asset=USDT |

**Вывод:** у BingX ключ выдаётся на АККАУНТ; демо-торговля (VST) и реальная отличаются только
базовым URL (`open-api-vst.bingx.com` ⇄ `open-api.bingx.com`). Отдельной «пары ключей для LIVE»
не существует — переменная `BINGX_API_KEY` в `.env` содержит отозванный/протухший ключ и
отвергается на ОБОИХ доменах.

**Состояние счетов (14.08.2026):** VST balance 573.81 / available 486.07 · **LIVE balance $0.605,
available $0.0003** + висит реальная позиция ATOM SHORT 16.24 @ 1.518. То есть боевой счёт
фактически пуст — переключение в LIVE не даст торговать, пока не пополнен.

**How to apply:** `make_client(mode="live")` в [core/exchange/bingx_client.py] берёт `BINGX_API_KEY`
и молча получит 100413 — если боевой режим когда-нибудь включат, сначала завести валидный ключ
ЛИБО использовать ключ аккаунта с боевым доменом. В мониторе (`web/structure_terminal.py`,
`_trade_client`) уже сделан фолбэк: BINGX_API_KEY → при отказе ключ аккаунта + LIVE-домен.

Связано: [[exec_sim_split_epic]], [[forward_machine_sphere11]] (REAL-MONEY гейт 20-30 чистых net+).
