# -*- coding: utf-8 -*-
"""core.context.market_data_sphere — СФЕРА 19 / Market Data (ARCH-129.1, 01.09.2026).

Повод (Егор 27.08): «все в шину! Куб должен работать по полной! сферы их не видят,
а ведь должны». Сверка показала: **213 из 230 признаков боевых решений идут МИМО шины**
([[bus_sees_only_candles]]). Фандинг — первым, потому что это единственный внешний
источник с ПОЛНОЙ историей (1 557 170 строк 2022-2026) и уже готовым живым фетчем
(`DataCollector.get_funding_rate`, DEV-81).

🔴 ЧТО ВСКРЫТО ПРИ РЕАЛИЗАЦИИ (01.09): боевое вето по фандингу НЕ РАБОТАЕТ.
`risk_intelligence.evaluate` проверяет `inputs.funding_pct_8h` против порога
`max_funding_pct`, но единственное место в боевом пути, где это поле заполняется, —
`bot/loops/arch104_observer_loop.py:290`, и там стоит **константа 0.0**
(комментарий «минимальный — TODO: расширить из bot state»). Порог не может быть
превышен никогда. Класс «молчаливый отказ»: конфиг говорит, что вето есть, поведение —
что его нет.

🔴 ЛОВУШКА ИСТОЧНИКОВ (HYPE, 30.08): в один момент BingX отдавал −0.0064%/4ч,
Binance +0.005%/8ч — разный ЗНАК и разный ИНТЕРВАЛ. Проверено по таблице:
интервалы 1ч (61 235), 2ч (493), 4ч (974 575), 8ч (520 867) сосуществуют.
Поэтому ставка хранится КАК ЕСТЬ + интервал + источник, а приведение к %/8ч —
отдельным полем и только явно.

🔑 ПРОИЗВОДНЫЕ, А НЕ УРОВЕНЬ (ARCH-129.5). Разбор HYPE: сквиз предупреждал СЕРИЕЙ
(−0.0060 → −0.0097 → −0.0078 → −0.0064 при медиане +0.005%), а не одиночным
экстремумом. Уровневое вето |f|>0.03% такое не ловит в принципе.

Функции ЧИСТЫЕ (без IO) — историю подаёт вызывающий, как в `phase_sphere`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional, Sequence

logger = logging.getLogger("MarketDataSphere")

# Сколько последних расчётов держим для производных. 90 дней при интервале 8ч ≈ 270,
# при 4ч ≈ 540 — берём с запасом, срез по времени делает вызывающий.
HISTORY_MAX = 600


@dataclass(frozen=True)
class FundingState:
    """Снимок фандинга для одной пары. Ровно то, что уходит в шину."""
    rate: float                       # КАК ОТДАЛ ИСТОЧНИК (ccxt и таблица — доля)
    interval_h: int                   # 1 / 2 / 4 / 8
    source: str                       # "bingx" | "binance" | "cache"
    pct_8h: float                     # ПРОЦЕНТЫ за 8ч — единственное сравнимое поле
    streak: int                       # расчётов подряд с тем же знаком (со знаком!)
    pctile_90d: Optional[float]       # 0..100, где ставка в своей истории
    cum_3d: Optional[float]           # накопленная стоимость удержания за ~3 суток, %
    next_ts: Optional[datetime] = None

    def as_bus_payload(self) -> dict:
        return {
            "rate": self.rate, "interval_h": self.interval_h, "source": self.source,
            "pct_8h": self.pct_8h, "streak": self.streak,
            "pctile_90d": self.pctile_90d, "cum_3d": self.cum_3d,
        }


def to_8h(rate: float, interval_h: int, as_fraction: bool = True) -> float:
    """
    Привести ставку к общей базе **процентов за 8 часов**.

    🔴 ЕДИНИЦЫ — отдельная ловушка, проверена по данным 01.09.2026:
      · `ohlcv_cache.db.funding_rates.rate` хранит ДОЛЮ (BTC ≈ 0.00007 = 0.007%,
        медиана рынка 0.00005 = 0.005%, экстремум −0.03 = −3%);
      · `DataCollector.get_funding_rate` отдаёт ДОЛЮ (ccxt `fundingRate`, «напр. -0.0008»);
      · а `risk_intelligence` сравнивает `funding_pct_8h` с `max_funding_pct: 0.03`
        и комментирует его как «**% за 8h**», то есть ждёт ПРОЦЕНТЫ.
    Подставить долю туда, где ждут процент, — это порог мягче в 100 раз и вето,
    которое молчит всегда. Поэтому конвертация здесь ЯВНАЯ: вход — доля (`as_fraction`),
    выход — всегда проценты.

    🔴 Только отдельным полем: складывать ставки разных интервалов без приведения —
    как раз тот случай, когда расхождение реализаций принимают за свойство рынка
    (BingX −0.0064%/4ч против Binance +0.005%/8ч на HYPE 30.08).
    """
    val = float(rate) * (100.0 if as_fraction else 1.0)
    if not interval_h or interval_h <= 0:
        return val          # интервал неизвестен — не выдумываем масштаб
    return val * (8.0 / float(interval_h))


def sign_streak(rates: Sequence[float]) -> int:
    """
    Сколько последних расчётов подряд имеют ОДИН знак. Возвращается со знаком:
    +3 = три подряд положительных, −4 = четыре подряд отрицательных, 0 = нет данных
    или последняя ставка ровно ноль.

    Это и есть «серия», которой предупреждал HYPE, — уровень её не видит.
    """
    if not rates:
        return 0
    last = rates[-1]
    if last == 0:
        return 0
    want = 1 if last > 0 else -1
    n = 0
    for r in reversed(rates):
        if (r > 0 and want == 1) or (r < 0 and want == -1):
            n += 1
        else:
            break
    return n * want


def percentile_of(value: float, history: Sequence[float]) -> Optional[float]:
    """Где `value` в своей истории, 0..100. Без numpy — вызывается по одной паре."""
    hs = [h for h in history if h is not None]
    if len(hs) < 20:                 # на коротком хвосте перцентиль врёт
        return None
    below = sum(1 for h in hs if h < value)
    equal = sum(1 for h in hs if h == value)
    return 100.0 * (below + 0.5 * equal) / len(hs)


def cumulative(rates: Sequence[float], interval_h: int, hours: float = 72.0) -> Optional[float]:
    """
    Накопленная стоимость удержания за последние `hours` — сумма ставок за период.
    Отвечает на вопрос «сколько стоит держать позицию», которого нет у уровня.
    """
    if not rates or not interval_h or interval_h <= 0:
        return None
    n = max(1, int(hours / interval_h))
    tail = list(rates)[-n:]
    return float(sum(tail))


def build_state(rate: float, interval_h: int, source: str,
                history: Optional[Sequence[float]] = None,
                next_ts: Optional[datetime] = None,
                as_fraction: bool = True) -> FundingState:
    """
    Собрать снимок. `history` — прошлые ставки ТОЙ ЖЕ пары, старые → новые,
    в тех же единицах, что `rate`.

    `as_fraction=True` (по умолчанию) — вход в долях, как отдают и ccxt, и таблица.
    """
    # 🔴 Текущая ставка добавляется к истории ВСЕГДА. Первая версия пропускала её,
    # если она равна предыдущей (`hist[-1] != rate`) — и серия переставала расти там,
    # где фандинг стабилен. А это норма, а не дубль: у HYPE в кэше восемь одинаковых
    # +0.00005 подряд. Тест поймал ошибку на равных значениях.
    # Контракт: `history` НЕ содержит текущую ставку — её добавляем здесь.
    hist = list(history or [])
    full = hist + [rate]
    return FundingState(
        rate=float(rate),
        interval_h=int(interval_h or 0),
        source=source,
        pct_8h=to_8h(rate, interval_h, as_fraction),
        streak=sign_streak(full),
        pctile_90d=percentile_of(rate, hist),
        cum_3d=cumulative(full, interval_h),
        next_ts=next_ts,
    )


class MarketDataSphere:
    """
    Сфера 19: держит историю ставок по парам и публикует состояние в шину.

    Хранение в памяти намеренно: история нужна только для производных, а полная
    лежит в `ohlcv_cache.db.funding_rates`. Прогрев истории — задача вызывающего
    (`warmup`), сама сфера в БД не ходит: чистая логика отделена от IO.
    """

    def __init__(self, bus=None) -> None:
        self._bus = bus
        self._hist: dict[str, list[float]] = {}
        self._interval: dict[str, int] = {}

    def warmup(self, symbol: str, rates: Iterable[float], interval_h: int) -> None:
        """Залить историю из `funding_rates` до первого живого расчёта."""
        self._hist[symbol] = list(rates)[-HISTORY_MAX:]
        self._interval[symbol] = int(interval_h)

    def observe(self, symbol: str, rate: float, interval_h: Optional[int] = None,
                source: str = "exchange",
                next_ts: Optional[datetime] = None) -> FundingState:
        """Принять живую ставку, обновить историю, вернуть состояние."""
        iv = int(interval_h or self._interval.get(symbol) or 8)
        self._interval[symbol] = iv
        hist = self._hist.setdefault(symbol, [])
        st = build_state(rate, iv, source, history=hist, next_ts=next_ts)
        hist.append(float(rate))
        if len(hist) > HISTORY_MAX:
            del hist[:-HISTORY_MAX]
        return st

    def publish(self, symbol: str, st: FundingState) -> None:
        """
        Положить снимок в шину. Поля заведены в `PairState` секцией «Сфера 19»
        ДО этого вызова — `PairContextBus.update()` молча роняет неизвестные ключи
        в debug-лог, и без полей публикация ушла бы в никуда (тот же дефект, что
        поймали у WaveService 29.08).
        """
        if self._bus is None:
            return
        from core.context.pair_context import SphereEvent

        # 🔑 `update` принимает **kwargs, `publish` — (symbol, event_type, data).
        # Порядок аргументов проверен по коду шины, не по памяти.
        self._bus.update(
            symbol,
            funding_rate=st.rate,
            funding_interval_h=st.interval_h,
            funding_source=st.source,
            funding_pct_8h=st.pct_8h,
            funding_streak=st.streak,
            funding_pctile_90d=st.pctile_90d,
            funding_cum_3d=st.cum_3d,
            funding_next_ts=st.next_ts,
            funding_updated_at=datetime.now(timezone.utc),
        )
        try:
            self._bus.publish(symbol, SphereEvent.FUNDING_UPDATED, st.as_bus_payload())
        except Exception as e:                       # шина не должна ронять сбор данных
            logger.debug("[S19] publish не прошёл для %s: %s", symbol, e)

    def observe_and_publish(self, symbol: str, rate: float,
                            interval_h: Optional[int] = None,
                            source: str = "exchange") -> FundingState:
        st = self.observe(symbol, rate, interval_h, source)
        self.publish(symbol, st)
        return st

    # ── ОТКРЫТЫЙ ИНТЕРЕС (ARCH-129.2) ──────────────────────────────────────
    def publish_oi(self, symbol: str, d5: Optional[float] = None,
                   d15: Optional[float] = None, d1d: Optional[float] = None,
                   quadrant: Optional[str] = None) -> Optional[str]:
        """
        Довести OI до шины. Данные УЖЕ собираются (`oi_snapshots`, `radar_state`),
        но идут в `features_json` мимо Куба — это и есть дыра ARCH-129.2.
        Возвращает метку сквиза, если он распознан.
        """
        sq = squeeze_flag(quadrant)
        if self._bus is not None:
            from core.context.pair_context import SphereEvent
            self._bus.update(symbol, oi_d5=d5, oi_d15=d15, oi_d1d=d1d,
                             oi_px_quadrant=quadrant,
                             oi_updated_at=datetime.now(timezone.utc))
            try:
                self._bus.publish(symbol, SphereEvent.OI_UPDATED, {
                    "d5": d5, "d15": d15, "d1d": d1d,
                    "quadrant": quadrant, "squeeze": sq,
                })
            except Exception as e:
                logger.debug("[S19] publish OI не прошёл для %s: %s", symbol, e)
        return sq


# ── ЧТЕНИЕ OI: сквиз против подтверждённого движения ────────────────────────
# 🔑 Квадрант OI×цена уже считается радаром (`radar_state.quadrant`, 12.07) —
# здесь его только ТОЛКУЕМ, а не пересчитываем ([[principle_reuse_not_duplication]]).
#
# Канон, подтверждённый разбором HYPE 30.08: рост цены при ПАДАЮЩЕМ OI — это не сила,
# а закрытие шортов, то есть сквиз. Движение умерло за два бара, а шесть боевых
# источников (цена↑, объём 2.11×, WT↑) видели «силу» и не могли увидеть иного.
# 🔴 Формат метки взят ИЗ ДАННЫХ, а не придуман: `radar_state.quadrant` хранит
# «PUP+OIDN» через плюс, и состояний ТРИ, а не два — есть флэт (FL):
# PUP/PDN/PFL × OIUP/OIDN/OIFL, девять комбинаций (проверено 01.09, 389 строк).
_SQUEEZE = {
    "PUP+OIDN": "short_squeeze",   # цена вверх, OI вниз → закрывают шорты, топлива нет
    "PDN+OIDN": "long_flush",      # цена вниз, OI вниз → выходят лонги, капитуляция
}


def squeeze_flag(quadrant: Optional[str]) -> Optional[str]:
    """
    `short_squeeze` / `long_flush` / None.

    None означает «не сквиз»: движение либо подтверждено ростом OI (OIUP),
    либо OI плоский (OIFL) — в обоих случаях повода звать это сквизом нет.
    """
    if not quadrant:
        return None
    return _SQUEEZE.get(str(quadrant).upper().replace("_", "+"))
