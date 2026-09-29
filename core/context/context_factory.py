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

Теперь оборот живёт в шине, а лупы зовут `build_market_context`. СЕТЬ НЕ ДЁРГАЕТСЯ НИКОГДА:
  1. `PairState` (шина). Наполняется ДВУМЯ путями: `OHLCV_UPDATED` (scan_loop считает оборот
     из уже загруженных свечей) и `TICK_PRICE` (WsFeed, когда включён);
  2. кэш тикеров DataCollector — ЕСЛИ такой метод появится. Сейчас его в проекте НЕТ
     (`get_cached_ticker` вызывают через `hasattr` и получают None), поэтому ветка ничего не
     делает и оставлена как точка расширения, а не как рабочий источник;
  3. нули — но уже как ЧЕСТНОЕ «нет данных», а не как заглушка, навязанная сигнатурой.

🔴 Почему нельзя было опереться на `TICK_PRICE` одним: `performance.ws_enabled=false` (DEV-230),
WsFeed не стартует, событие не приходит вовсе. Правка, опирающаяся только на него, дала бы нуль.
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


def _base(symbol: str) -> str:
    """BASE из символа. Инвариант пары у нас BASE/USDT:USDT, карта оборотов ключуется базой."""
    return str(symbol).split("/")[0]


def turnover_snapshot(bot: Any) -> dict:
    """ОБОРОТЫ ВСЕХ ПАР — одна точка чтения для гейтов и сортировок.

    🔴 29.09 (Егор: «почему не один источник?»). До этого обороты добывались тремя путями:
    `ws_feed` (выключен), `turnover_map()` bulk-REST в каждом лупе, расчёт из свечей в шине.
    Теперь потребители зовут ЭТО, а оно: берёт кэшированную карту (`turnover_map` ходит в биржу
    не чаще раза в 10 мин) и **оседает в шине**, чтобы состояние пары знало свой оборот и его
    видели все читатели, а не только вызвавший гейт ([[turnover_gate_fails_open]]).

    Пустой dict = данных НЕТ. Потребитель обязан трактовать это запретительно (fail-closed),
    а не как «ограничение снято».
    """
    try:
        from core.context.market_regime import turnover_map
        turn = turnover_map() or {}
    except Exception:                                        # noqa: BLE001
        turn = {}
    bus = getattr(bot, "pair_context", None)
    if turn and bus is not None:
        now = datetime.now(timezone.utc)
        try:
            for sym in bus.all_symbols():
                v = turn.get(_base(sym))
                if v:
                    st = bus.get(sym)
                    # свечной путь (OHLCV_UPDATED) считает оборот по НАШЕМУ окну; биржевой
                    # quoteVolume точнее, поэтому он побеждает и обновляет отметку времени
                    st.volume_24h = float(v)
                    st.volume_24h_time = now
        except Exception:                                    # noqa: BLE001
            pass
    return turn


def turnover_of(bot: Any, symbol: str) -> Optional[float]:
    """Оборот ОДНОЙ пары: шина → карта. None = данных нет (а не «ноль»)."""
    bus = getattr(bot, "pair_context", None)
    if bus is not None:
        try:
            v = getattr(bus.get(symbol), "volume_24h", None)
            if v:
                return float(v)
        except Exception:                                    # noqa: BLE001
            pass
    return turnover_snapshot(bot).get(_base(symbol))


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
