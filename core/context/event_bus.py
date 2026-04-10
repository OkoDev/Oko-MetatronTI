"""
EventBus — ARCH-70 / Куб Метатрона Фаза 3.

Централизованная шина событий: детекторы публикуют → Full CALL (analyze_symbol) выполняется.

Принципы:
  - Детектор публикует событие, не зная о потребителях
  - Единственный потребитель: _fire_analysis() → analyze_symbol() → register_trade_async()
  - Дедупликация: cooldown 30 мин/пара (не вызывать analyze чаще)
  - Приоритеты: меньший номер = важнее (используется heapq)
  - Защита: max_concurrent семафор (не перегружать скан)
  - Shadow mode: WOULD_FIRE лог без реального вызова

Config (config.yaml):
  event_bus:
    enabled: true             # false = полный off
    shadow: true              # true = только WOULD_FIRE, без analyze
    cooldown_minutes: 30      # мин. интервал Full CALL / пара
    max_concurrent: 3         # макс. параллельных analyze_symbol
"""
from __future__ import annotations

import asyncio
import heapq
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, List, Optional

logger = logging.getLogger("event_bus")

# Приоритеты событий (меньше = важнее)
EVENT_PRIORITY = {
    "liquidity_sweep":   1,
    "pivot_touch":       2,
    "funding_extreme":   2,
    "wt_confluence":     3,
    "ote_reentry":       3,
    "cascade":           3,
    "ml_verdict":        3,
    "anomaly_volume":    4,
    "btc_macro":         4,
    "trade_closed":      5,  # ARCH-72: Feedback Loop
}


@dataclass(order=True)
class _QueueItem:
    priority:   int
    seq:        int               # tiebreaker (FIFO внутри приоритета)
    symbol:     str = field(compare=False)
    event_type: str = field(compare=False)
    data:       Any = field(compare=False, default=None)


class EventBus:
    """
    Асинхронная шина событий с приоритетной очередью и дедупликацией.

    Использование:
        event_bus = EventBus(config)
        await event_bus.publish("BTC/USDT:USDT", "wt_confluence")
        asyncio.create_task(event_bus.consume_loop(bot))
    """

    def __init__(self, config=None):
        """
        config — объект ConfigLoader (с методом .get("dot.key", default))
        или None (все параметры по умолчанию).
        """
        def _cfg(key: str, default):
            if config is None:
                return default
            return config.get(f"event_bus.{key}", default)

        self.enabled: bool       = bool(_cfg("enabled", True))
        self.shadow:  bool       = bool(_cfg("shadow",  True))
        self.cooldown_min: float = float(_cfg("cooldown_minutes", 30))
        self.max_concurrent: int = int(_cfg("max_concurrent", 3))

        self._heap: list[_QueueItem] = []   # heapq (min-heap)
        self._in_queue: set[str]     = set()  # symbol деdup
        self._cooldowns: dict[str, datetime] = {}
        self._semaphore  = asyncio.Semaphore(self.max_concurrent)
        self._wake       = asyncio.Event()
        self._seq        = 0

    async def publish(
        self,
        symbol:     str,
        event_type: str,
        data:       Any  = None,
        priority:   Optional[int] = None,
    ) -> bool:
        """
        Публикует событие в очередь.

        Возвращает True если событие принято, False если:
          - EventBus выключен
          - пара на cooldown
          - пара уже в очереди (будет обновлён приоритет если новый выше)
        """
        if not self.enabled:
            return False

        # Cooldown check
        last = self._cooldowns.get(symbol)
        if last:
            elapsed = (datetime.now(timezone.utc) - last).total_seconds() / 60
            if elapsed < self.cooldown_min:
                logger.debug(
                    "[EventBus] %s %s: cooldown %.1f мин (осталось %.1f)",
                    symbol, event_type, self.cooldown_min, self.cooldown_min - elapsed,
                )
                return False

        prio = priority if priority is not None else EVENT_PRIORITY.get(event_type, 5)

        if symbol in self._in_queue:
            # Пара уже в очереди — пропускаем (можно улучшить до update priority, но YAGNI)
            logger.debug("[EventBus] %s already in queue, skip %s", symbol, event_type)
            return False

        self._seq += 1
        item = _QueueItem(priority=prio, seq=self._seq, symbol=symbol,
                          event_type=event_type, data=data)
        heapq.heappush(self._heap, item)
        self._in_queue.add(symbol)
        self._wake.set()

        logger.info(
            "[EventBus] publish %s %s prio=%d queue_size=%d",
            symbol, event_type, prio, len(self._heap),
        )
        return True

    async def consume_loop(self, bot) -> None:
        """
        Основной цикл потребителя. Запускать как asyncio.create_task().
        Читает из heap → _fire_analysis() с семафором.
        """
        logger.info(
            "[EventBus] consume_loop старт shadow=%s cooldown=%.0fmin max_concurrent=%d",
            self.shadow, self.cooldown_min, self.max_concurrent,
        )
        while True:
            try:
                # Ждём события в очереди
                if not self._heap:
                    self._wake.clear()
                    await self._wake.wait()

                if not self._heap:
                    continue

                item = heapq.heappop(self._heap)
                self._in_queue.discard(item.symbol)

                # Double-check cooldown (мог пройти пока был в очереди)
                last = self._cooldowns.get(item.symbol)
                if last:
                    elapsed = (datetime.now(timezone.utc) - last).total_seconds() / 60
                    if elapsed < self.cooldown_min:
                        logger.debug("[EventBus] %s: skip (cooldown в момент consume)", item.symbol)
                        continue

                if self.shadow:
                    logger.info(
                        "[EventBus][SHADOW] WOULD_FIRE %s event=%s prio=%d",
                        item.symbol, item.event_type, item.priority,
                    )
                else:
                    # Обновляем cooldown ДО fire (чтобы параллельные publish блокировались)
                    self._cooldowns[item.symbol] = datetime.now(timezone.utc)
                    logger.info(
                        "[EventBus] CONSUMED %s event=%s prio=%d -> launching Full CALL",
                        item.symbol, item.event_type, item.priority,
                    )
                    asyncio.create_task(
                        self._fire_with_semaphore(bot, item)
                    )

            except asyncio.CancelledError:
                logger.info("[EventBus] consume_loop остановлен")
                break
            except Exception as e:
                logger.warning("[EventBus] consume_loop ошибка: %s", e)
                await asyncio.sleep(1)

    async def _fire_with_semaphore(self, bot, item: _QueueItem) -> None:
        """Запускает Full CALL с семафором (не перегружать scan)."""
        async with self._semaphore:
            await _fire_analysis(bot, item.symbol, item.event_type)

    def queue_size(self) -> int:
        return len(self._heap)

    def stats(self) -> dict:
        return {
            "enabled":      self.enabled,
            "shadow":       self.shadow,
            "queue_size":   len(self._heap),
            "cooldowns":    len(self._cooldowns),
            "in_queue":     len(self._in_queue),
        }


async def _fire_analysis(bot, symbol: str, event_type: str) -> None:
    """
    ARCH-71: Real Full CALL — расширенный анализ на всех 6 TF.
    trade_closed — feedback-событие, не запускает Full CALL (только NarrativeBuilder).
    """
    # trade_closed: ARCH-72 Feedback Loop — обновляем веса и ML, не запускаем Full CALL
    if event_type == "trade_closed":
        try:
            ti = getattr(bot, "trading_intelligence", None)
            if ti is not None:
                ti.update_signal_weights()
                logger.info("[EventBus][ARCH-72] trade_closed %s → update_signal_weights OK", symbol)
                # Раз в 10 закрытых сделок — переобучаем OutcomePredictor + WTSpecialist + SMCSpecialist
                _closed_count = getattr(bot, "_eb_closed_count", 0) + 1
                bot._eb_closed_count = _closed_count
                if _closed_count % 10 == 0:
                    import asyncio as _aio
                    _op = getattr(ti, "outcome_predictor", None)
                    if _op is not None:
                        _aio.create_task(_aio.to_thread(_op.fit, ti._db_path))
                    _wts = getattr(ti, "_wt_specialist", None)
                    if _wts is not None:
                        _aio.create_task(_aio.to_thread(_wts.fit, ti._db_path))
                    _smcs = getattr(ti, "_smc_specialist", None)
                    if _smcs is not None:
                        _aio.create_task(_aio.to_thread(_smcs.fit, ti._db_path))
                    logger.info("[EventBus][ARCH-72] trade_closed → retrain OP+WT+SMC (%d closed)", _closed_count)
        except Exception as _e72:
            logger.debug("[EventBus][ARCH-72] trade_closed feedback error: %s", _e72)
        return

    # ARCH-71: загружаем все 6 TF + дивергенции → analyze_symbol(pre_fetched_dfs)
    # OTE swing/scalp и SMC на 4h/1d автоматически используют pre_fetched_dfs
    try:
        t0 = asyncio.get_event_loop().time()
        logger.info("[EventBus] FIRE %s event=%s", symbol, event_type)

        # ── 1. Загрузить все 6 TF параллельно ──────────────────────────────
        _ALL_TFS = ["3m", "5m", "15m", "1h", "4h", "1d"]
        _limits  = {"3m": 100, "5m": 100, "15m": 160, "1h": 160, "4h": 100, "1d": 100}
        raw_dfs = await asyncio.gather(
            *[bot.data_collector.get_ohlcv(symbol, tf, limit=_limits[tf]) for tf in _ALL_TFS],
            return_exceptions=True,
        )
        pre_fetched_dfs: dict = {}
        for tf, df in zip(_ALL_TFS, raw_dfs):
            if not isinstance(df, Exception) and df is not None and not df.empty:
                pre_fetched_dfs[tf] = df

        tf_loaded = list(pre_fetched_dfs.keys())
        logger.info(
            "[EventBus] FIRE %s: TF загружены %s (%.2fs)",
            symbol, tf_loaded, asyncio.get_event_loop().time() - t0,
        )

        # ── 2. Дивергенции на 15m / 1h / 4h → собираем как SignalData ──────
        div_signals: List[Any] = []
        div_detector = getattr(bot, "divergence_detector", None)
        if div_detector is not None:
            try:
                from core.signals.signal_models import SignalData, SignalType, SignalDirection
                _div_signal_type = SignalType.DIVERGENCE
                _dir_map = {"LONG": SignalDirection.LONG, "SHORT": SignalDirection.SHORT}
            except ImportError:
                _div_signal_type = None

            for _div_tf in ("15m", "1h", "4h"):
                if _div_tf not in pre_fetched_dfs:
                    continue
                try:
                    has_div, _div_info = await div_detector.detect_divergence(
                        symbol, bot.data_collector, timeframe=_div_tf
                    )
                    if has_div and _div_info:
                        logger.info(
                            "[EventBus] FIRE %s: дивергенция на %s — %s",
                            symbol, _div_tf, _div_info,
                        )
                        if _div_signal_type is not None:
                            _str = min(int(_div_info.get("strength", 30)), 100)
                            _dir_str = _div_info.get("direction", "LONG")
                            _div_sig = SignalData(
                                symbol=symbol,
                                signal_type=_div_signal_type,
                                direction=_dir_map.get(_dir_str, SignalDirection.NEUTRAL),
                                strength=_str,
                                confidence=round(0.55 + _str / 300, 3),  # 0.55..0.88
                                timestamp=datetime.now(timezone.utc),
                                data=_div_info,
                                timeframe=_div_tf,
                                description=_div_info.get("description", "Дивергенция"),
                            )
                            div_signals.append(_div_sig)
                except Exception as _de:
                    logger.debug("[EventBus] %s div %s: %s", symbol, _div_tf, _de)

        # ── 3. analyze_symbol с pre_fetched_dfs + extra div сигналами ─────────
        recommendation = await bot.trading_intelligence.analyze_symbol(
            symbol,
            pre_fetched_dfs=pre_fetched_dfs if pre_fetched_dfs else None,
            extra_pre_signals=div_signals if div_signals else None,
        )

        elapsed = asyncio.get_event_loop().time() - t0
        if recommendation is None:
            logger.info(
                "[EventBus] %s event=%s -> analyze_symbol returned None (%.2fs)",
                symbol, event_type, elapsed,
            )
            return

        action    = getattr(recommendation, "action", "WATCH")
        strength  = getattr(recommendation, "overall_strength", 0)
        direction = (
            getattr(recommendation.direction, "value", "NEUTRAL")
            if recommendation.direction else "NEUTRAL"
        )
        min_str = int(bot.config.get("signal_quality.min_strength", 50))

        if action in ("BUY", "SELL") and direction != "NEUTRAL" and strength >= min_str:
            trade_id = await bot.trade_simulator.register_trade_async(
                recommendation, bot.data_collector,
                extra_features={"trigger_source": f"event_bus:{event_type}"},
            )
            if trade_id:
                logger.info(
                    "[EventBus] %s event=%s → trade_id=%d strength=%.0f (%.2fs)",
                    symbol, event_type, trade_id, strength, elapsed,
                )
        else:
            logger.info(
                "[EventBus] %s event=%s -> not actionable (action=%s dir=%s str=%.0f %.2fs)",
                symbol, event_type, action, direction, strength, elapsed,
            )
    except Exception as e:
        logger.warning("[EventBus] _fire_analysis %s event=%s: %s", symbol, event_type, e)
