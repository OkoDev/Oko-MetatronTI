---
name: vst_has_fewer_contracts_than_live
description: "VST-демо и LIVE различаются СОСТАВОМ инструментов: 1171 контракт против 1225. Из наших 966 активных USDT-свопов на VST недоступны 5 (ICP, ILV, DOOD, 1000000MOG, NCFXEUR2JPY). Биржа отвечает 'is offline currently' — формулировка врёт, монета торгуется, её просто нет на демо-аккаунте"
metadata:
  node_type: memory
  type: reference
  originSessionId: ea98197f-5cfa-4b48-ab76-1b2fcebf5d0d
  modified: 2026-10-06T20:02:12.292Z
---

# ⚖️ VST ≠ LIVE ПО СОСТАВУ ИНСТРУМЕНТОВ (06.10.2026)

Егор, увидев в логе «ордер не ушёл, монеты нет в торгах»: «на монету, которой нет
в торгах?! это как?» — вопрос правильный, ICP это Internet Computer, крупная монета,
и `ccxt.load_markets()` показывает по ней `active=True`.

**Проверка `/openApi/swap/v2/quote/contracts` на обоих доменах одним ключом:**

| домен | контрактов | `ICP-USDT` |
|---|---|---|
| VST (демо) | **1171** | ❌ нет |
| LIVE (боевой) | **1225** | ✅ есть |

Разница 54 инструмента, «только на VST» — ноль. Из 54 почти все USDC-пары
(BTC-USDC, ETH-USDC, ADA-USDC…), которые мы не торгуем.

🔴 **USDT-пар, которых нет на VST, всего 5:**
`1000000MOG-USDT` · `DOOD-USDT` · `ICP-USDT` · `ILV-USDT` · `NCFXEUR2JPY-USDT`

Из нашей вселенной (966 активных USDT-свопов) это **0.5%** — то есть ICP был невезением,
а не системным перекосом. Первый шорт `waves_long` 06.10 попал ровно в эти полпроцента.

## Что важно помнить

1. **Сообщение биржи вводит в заблуждение.** `"ICP-USDT is offline currently, all
   validted symbols in api:/openApi/swap/v2/quote/contracts"` читается как «монета не
   торгуется», а значит «её нет на ЭТОМ аккаунте». Проверять надо список контрактов
   того домена, куда шлём ордер, а не `ccxt.load_markets()` (он ходит на боевой).
2. **Поведение роутера корректное:** сделка остаётся в симуляции
   (`execution_mode=SIM`, `exchange_order_id=None`), ставится пауза 60 мин по монете.
   Торговля не ломается, но в дашборде с фильтром «Exchange» такая сделка не видна —
   искать в «SIM».
3. **Для замеров исполнения** эти 5 монет — слепое пятно VST: сигналы по ним
   регистрируются, но данных о филлах не дают.

Связано: [[vst_spread_measured_market_only]] · [[safety_vst_live_isolation_proven]] ·
[[symbol_format_invariant_cube]]
