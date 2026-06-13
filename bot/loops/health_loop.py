"""
DEV-103 / ARCH-65 Слои 1+2 — Exchange Health Guard.

Слой 1: пинг BingX каждые 30 сек → статус HEALTHY/DEGRADED/DOWN.
Слой 2: TG-алерты при деградации + пауза скана при DOWN.
Слой 3 (Dead-Man Timer) — DEV-104, только перед LIVE.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ─── Константы ───────────────────────────────────────────────────────────────

PING_SYMBOL         = "BTC/USDT:USDT"
PING_INTERVAL_SEC   = 30
PING_TIMEOUT_SEC    = 5.0

LATENCY_DEGRADED_MS = 2000
LATENCY_DOWN_MS     = 10000

ALERT_DEGRADED_AFTER_SEC = 60     # сколько сек DEGRADED до WARNING в TG
ALERT_DOWN_AFTER_SEC     = 300    # сколько сек DOWN до CRITICAL в TG
ALERT_COOLDOWN_SEC       = 600    # min интервал между повторными алертами одного типа


class ExchangeHealth:
    HEALTHY  = "HEALTHY"
    DEGRADED = "DEGRADED"
    DOWN     = "DOWN"


# ─── Ping ─────────────────────────────────────────────────────────────────────

PING_SAMPLES         = 3      # median из N пингов — сглаживает выбросы
PING_SAMPLE_GAP_SEC  = 0.4    # интервал между сэмплами (попасть в разные моменты загрузки)


async def _single_ping(data_collector, bot=None) -> float:
    """Один ping BingX → latency_ms.

    ⚡ PERF-LOOP-DRIFT: при активном торговом loop пингуем через него (server/time,
    изолированный) — мерит РЕАЛЬНУЮ доступность биржи. Fallback на ccxt fetch_ticker.
    """
    t0 = time.monotonic()
    try:
        _pinged = False
        try:
            from core.infra.trading_loop import get_trading_loop
            _oe = getattr(bot, "order_executor", None) if bot is not None else None
            if (get_trading_loop() is not None and _oe is not None
                    and getattr(_oe, "is_live", lambda: False)()):
                await asyncio.wait_for(_oe._get_client().ping(), timeout=PING_TIMEOUT_SEC)
                _pinged = True
        except Exception:
            _pinged = False  # любой сбой торгового ping → fallback на ccxt
        if not _pinged:
            await asyncio.wait_for(
                data_collector._engine._exchange.fetch_ticker(PING_SYMBOL),
                timeout=PING_TIMEOUT_SEC,
            )
        return (time.monotonic() - t0) * 1000
    except Exception:
        return (time.monotonic() - t0) * 1000  # timeout/сбой = высокая latency


async def _ping_exchange(data_collector, bot=None) -> tuple[str, float]:
    """⚡ PERF-LOOP-DRIFT (B): MEDIAN из N пингов → (status, latency_ms).

    Сглаживает выбросы: торговый loop сериализует health-ping с repair/get_positions →
    один пинг может попасть в занятый момент (2-3с) при доступной бирже. Median из 3
    пингов берёт типичную latency, убирая разовые скачки DEGRADED↔HEALTHY.
    """
    samples = []
    for i in range(PING_SAMPLES):
        samples.append(await _single_ping(data_collector, bot))
        if i < PING_SAMPLES - 1:
            await asyncio.sleep(PING_SAMPLE_GAP_SEC)
    samples.sort()
    latency_ms = samples[len(samples) // 2]  # median
    if latency_ms < LATENCY_DEGRADED_MS:
        return ExchangeHealth.HEALTHY, latency_ms
    if latency_ms < LATENCY_DOWN_MS:
        return ExchangeHealth.DEGRADED, latency_ms
    return ExchangeHealth.DOWN, latency_ms


# ─── Алерты ───────────────────────────────────────────────────────────────────

def _open_trades_count(bot) -> int:
    try:
        trades = bot.trade_simulator.get_open_trades()
        return len(trades)
    except Exception:
        return -1


async def _send_health_alert(bot, text: str) -> None:
    """Рассылает алерт всем подписчикам."""
    try:
        from bot.monitoring import broadcast_with_subscription_check
        await broadcast_with_subscription_check(bot, text, "health_alert")
    except Exception as e:
        logger.error("[health] Ошибка отправки алерта: %s", e)


# ─── Главный цикл ─────────────────────────────────────────────────────────────

async def health_check_loop(bot) -> None:
    """
    Слои 1+2 ARCH-65.
    Обновляет bot.exchange_health / bot.exchange_latency_ms / bot.down_since.
    Отправляет TG-алерты при деградации.
    """
    _degraded_since: datetime | None = None
    _last_alert_warning: datetime | None = None
    _last_alert_critical: datetime | None = None
    _was_down = False           # для RECOVER-алерта

    logger.info("[health] Exchange Health Loop запущен (ping каждые %ds)", PING_INTERVAL_SEC)

    while True:
        try:
            status, latency_ms = await _ping_exchange(bot.data_collector, bot)
        except Exception as e:
            logger.error("[health] Неожиданная ошибка ping: %s", e)
            status, latency_ms = ExchangeHealth.DOWN, 9999.0

        now = datetime.now(timezone.utc)
        prev_status = getattr(bot, "exchange_health", ExchangeHealth.HEALTHY)

        # Обновляем поля бота
        bot.exchange_health     = status
        bot.exchange_latency_ms = latency_ms

        if status == ExchangeHealth.DOWN:
            if bot.down_since is None:
                bot.down_since = now
                logger.warning("[health] ⬇️ BingX DOWN — latency=%.0fms", latency_ms)
            _degraded_since = _degraded_since or now
        elif status == ExchangeHealth.DEGRADED:
            bot.down_since = None
            if _degraded_since is None:
                _degraded_since = now
                logger.warning("[health] ⚠️ BingX DEGRADED — latency=%.0fms", latency_ms)
        else:
            # HEALTHY
            if prev_status != ExchangeHealth.HEALTHY and _was_down:
                n = _open_trades_count(bot)
                asyncio.create_task(_send_health_alert(
                    bot,
                    f"✅ BingX восстановлен. Latency={latency_ms:.0f}ms. Открытых сделок: {n}."
                ))
                logger.info("[health] ✅ BingX восстановлен (latency=%.0fms)", latency_ms)
            bot.down_since = None
            _degraded_since = None
            _was_down = False

        # ── Алерты ────────────────────────────────────────────────────────────

        if status == ExchangeHealth.DEGRADED and _degraded_since:
            degraded_sec = (now - _degraded_since).total_seconds()
            if degraded_sec >= ALERT_DEGRADED_AFTER_SEC:
                cooldown_ok = (
                    _last_alert_warning is None
                    or (now - _last_alert_warning).total_seconds() >= ALERT_COOLDOWN_SEC
                )
                if cooldown_ok:
                    n = _open_trades_count(bot)
                    asyncio.create_task(_send_health_alert(
                        bot,
                        f"⚠️ BingX DEGRADED — latency={latency_ms:.0f}ms. "
                        f"Открытых сделок: {n}."
                    ))
                    _last_alert_warning = now
                    logger.warning("[health] TG WARNING отправлен (degraded %.0f сек)", degraded_sec)

        if status == ExchangeHealth.DOWN and bot.down_since:
            down_sec = (now - bot.down_since).total_seconds()
            if down_sec >= ALERT_DOWN_AFTER_SEC:
                cooldown_ok = (
                    _last_alert_critical is None
                    or (now - _last_alert_critical).total_seconds() >= ALERT_COOLDOWN_SEC
                )
                if cooldown_ok:
                    n = _open_trades_count(bot)
                    asyncio.create_task(_send_health_alert(
                        bot,
                        f"🚨 BingX DOWN {down_sec/60:.0f} мин. "
                        f"Открытых сделок: {n}. Скан приостановлен."
                    ))
                    _last_alert_critical = now
                    _was_down = True
                    logger.error("[health] TG CRITICAL отправлен (down %.0f сек)", down_sec)

        await asyncio.sleep(PING_INTERVAL_SEC)
