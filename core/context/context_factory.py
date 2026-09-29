"""ЕДИНАЯ ТОЧКА СБОРКИ `MarketContext` (29.09.2026).

🔴 Повод — вопрос Егора: «почему 6 лупов обороты заполняют? почему не один источник? у нас ведь
сфера для этого была?». Была и есть. Разбор показал:

  · `MarketContext.volume_24h` был ОБЯЗАТЕЛЬНЫМ полем → каждый луп обязан был что-то передать;
  · в шине для оборота НЕ БЫЛО МЕСТА: каталог обещал `TICK_PRICE: {price, volume_24h}`, а
    `PairState` хранил только цену, и обработчик оборот выбрасывал;
  · поэтому шесть лупов писали `volume_24h=0.0`, а четыре лезли за тикером ПО СЕТИ на каждый
    сигнал (дублирующая качка, [[market_data_duplicated_fetches]]);
  · итог: оборот 0.0 во ВСЕХ 922 боевых сделках, срез по ликвидности невозможен, а гейт
    `min_volume_usd` сравнивал порог с нулём ([[signal_volume24h_is_always_zero]]).

Теперь оборот живёт в шине (Сфера 2 → центральный хаб), а лупы зовут `build_market_context`.
Порядок источников — от самого дешёвого к дорогому, СЕТЬ НЕ ДЁРГАЕТСЯ НИКОГДА:
  1. `PairState` (шина) — наполняется из `TICK_PRICE`;
  2. кэш тикеров DataCollector (`get_cached_ticker`) — если он есть; прочитанное кладём обратно
     в шину, чтобы следующий вызов обошёлся первым шагом;
  3. нули — но уже как ЧЕСТНОЕ «нет данных», а не как заглушка, навязанная сигнатурой.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from core.signals.signal_models import MarketContext

logger = logging.getLogger(__name__)

# Ключи оборота в тикере ccxt: quoteVolume — оборот в USDT (то, что нам нужно для порогов),
# baseVolume — в монетах. Порядок важен: сравнивать с порогом в долларах можно только первый.
_VOL_KEYS = ("quoteVolume", "quote_volume", "volume_24h")


def _from_bus(bus: Any, symbol: str) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """(цена, оборот, изменение за сутки) из шины. Ошибки шины не должны ронять торговлю."""
    try:
        st = bus.get(symbol)
    except Exception:                                        # noqa: BLE001
        return None, None, None
    return (getattr(st, "tick_price", None),
            getattr(st, "volume_24h", None),
            getattr(st, "price_change_24h", None))


def _from_ticker_cache(dc: Any, symbol: str) -> tuple[Optional[float], Optional[float]]:
    """(оборот, изменение) из КЭША тикеров. Сеть не трогаем: только `get_cached_ticker`."""
    getter = getattr(dc, "get_cached_ticker", None)
    if not callable(getter):
        return None, None
    try:
        tk = getter(symbol) or {}
    except Exception:                                        # noqa: BLE001
        return None, None
    vol = next((float(tk[k]) for k in _VOL_KEYS if tk.get(k)), None)
    chg = tk.get("percentage")
    return vol, (float(chg) if chg is not None else None)


def build_market_context(bot: Any, symbol: str, *, current_price: Optional[float] = None,
                         **extra: Any) -> MarketContext:
    """Собрать `MarketContext` из шины. Единственный способ, которым лупы должны его получать.

    `current_price` перекрывает цену из шины (у лупа часто есть более точная цена входа).
    `extra` передаётся в `MarketContext` как есть — regime, atr, swing_low и прочее, что луп
    посчитал сам и что шина не хранит.
    """
    bus = getattr(bot, "pair_context", None)
    px, vol, chg = _from_bus(bus, symbol) if bus is not None else (None, None, None)

    if vol is None:
        vol, chg2 = _from_ticker_cache(getattr(bot, "data_collector", None), symbol)
        if chg is None:
            chg = chg2
        # положить найденное обратно в шину: следующий вызов обойдётся первым шагом,
        # и оборот увидят все читатели состояния, а не только этот сигнал
        if vol is not None and bus is not None:
            try:
                st = bus.get(symbol)
                st.volume_24h = float(vol)
                st.volume_24h_time = datetime.now(timezone.utc)
                if chg is not None:
                    st.price_change_24h = float(chg)
            except Exception:                                # noqa: BLE001
                pass

    price = current_price if current_price else (px or 0.0)
    if not price:
        logger.debug("[CTX] %s: цены нет ни в аргументе, ни в шине", symbol)

    return MarketContext(
        symbol=symbol,
        current_price=float(price or 0.0),
        volume_24h=float(vol or 0.0),
        price_change_24h=float(chg or 0.0),
        **extra,
    )
