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

**Роадмап коллекторов (полная карта, 03.07):**
| Будущий коллектор | Источник | Наработки уже есть |
|---|---|---|
| `orderbook` | сводный стакан BingX/Binance (walls, imbalance, depth) | memory/order_book_backlog.md + OB-DATA (TASKS 🔵) |
| `social` | CryptoPanic + Telegram + новостные ленты | SOCIAL-SIGNALS (TASKS 🔵), docs/SOCIAL_SIGNALS_INTEGRATION.py |
| `news_digest` | market_news_digest.py (уже живёт в tools) | мигрировать |
| `oi_liquidations` | Coinglass/Hyblock (Open Interest, ликвидации) | LIQUIDATION-CASC (TASKS 🧊) |
| `btcd_history` | TW-MCP CRYPTOCAP:BTC.D скролл | по образцу usdtd |
| `fundamentals` | CoinGecko (mcap/FDV) + DefiLlama (TVL/fees) | **метод Егора (как нашёл GRT) автоматом**: MCap/Fees, MCap/TVL, динамика 3м → ранжирование недооценёнок по 500 монетам. Эндпоинты проверены 03.07 |

**Инфраструктура:** BTC.D-режим · funding-миграция · HTTP-порт (ADR-001) · отдельный репо.
