# oko_feed — подключаемая сфера внешних данных (Cross-Market + On-Chain)

> Идея Егора 03.07.2026: «сбор данных — в подключаемую сферу: USDT.D / BTC.D / CoinGecko и пр.,
> чтобы использовать и в других проектах, и отдельно от всего».

**Принципы:**
- **Zero-deps от бота**: пакет не импортирует ничего из `core/`/`bot/` — только stdlib + pandas/yaml.
- **Своя БД**: `oko_feed/external_data.db` (SQLite) — переносится копированием.
- **Каждый коллектор = standalone**: запускается отдельно (`python -m oko_feed.collectors.thegraph`),
  и/или дергается из любого проекта через python-API.
- Бот подключается через тонкие адаптеры (`core/signals/usdtd_regime.py` и др. постепенно мигрируют).

**Коллекторы (статус):**
| Коллектор | Источник | Данные | Статус |
|---|---|---|---|
| `thegraph` | gateway.thegraph.com (ключ) | Uniswap V3 whale-свопы >$250k, ликвидность >$500k | ✅ готов, ждёт ключ |
| `dominance` | CoinGecko /global | USDT.D, BTC.D (live, копится ряд) | ✅ готов |
| `funding` | data.binance.vision | funding rates история | ✅ (пока scripts/fetch_binance_funding.py → мигрирует) |
| `usdtd_tw` | TW-MCP CRYPTOCAP | глубокая история доминаций | ручной снят 300д (таблица usdtd в ohlcv_cache) |

**API:**
```python
from oko_feed import store
store.dominance_series("usdt")      # [(date, value)]
store.onchain_events(hours=24)      # крупные on-chain события
```

**Роадмап:** BTC.D история · funding-мигрция · HTTP-порт (ADR-001) · выделение в отдельный репо.
