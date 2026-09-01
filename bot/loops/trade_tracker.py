"""
trade_tracker_loop — фоновый цикл трекинга открытых сделок.

Отвечает ТОЛЬКО за симуляторную логику: TSL, SL/TP, безубыток.
Весь биржевой код живёт в core/exchange/:
  - position_sync.py  → sync_positions
  - tsl_updater.py    → update_tsl_on_exchange
"""
import asyncio
import logging

from core.exchange.position_sync import sync_positions
from core.exchange.tsl_updater import update_tsl_on_exchange, repair_missing_sl, repair_missing_tp
from core.infra.trading_settings import is_live as _is_live_fn

logger = logging.getLogger(__name__)


async def trade_tracker_loop(bot) -> None:
    """Каждые 60 сек:
    1. VST/LIVE: sync биржи → симулятор (position_sync)
    2. Симулятор: TSL/SL/TP/BE трекинг (check_open_trades_with_tsl)
    3. VST/LIVE: обновить SL на бирже если TSL двинулся (tsl_updater)
    """
    use_tsl                = bot.config.get("trading.use_tsl", True)
    tsl_activation_r       = bot.config.get("trading.tsl_activation_r", 1.0)
    use_breakeven          = bot.config.get("trading.use_breakeven", False)
    breakeven_activation_r = bot.config.get("trading.breakeven_activation_r", 0.5)
    use_be_after_tp1       = bot.config.get("trading.use_be_after_tp1", False)
    cascade_tsl            = bot.config.get("trading.cascade_tsl", True)

    _is_live = _is_live_fn(bot.config)

    def _hb(name: str = "tracker") -> None:
        """Пульс лупа. Никогда не бросает — трекинг позиций важнее наблюдаемости."""
        try:
            from core.infra.heartbeat import beat
            beat(name)
        except Exception:
            pass

    # 01.09 ПРИБОР: тайминг каждого шага. Итерация трекера растёт с числом открытых сделок
    # (REST на сделку в 4 обходах), и без разбивки по шагам нельзя сказать, ЧТО именно её
    # растит — гадать здесь запрещено, поэтому меряем.
    _step_warn = float(bot.config.get("performance.tracker_step_warn_sec", 60.0))

    async def _step(name: str, coro):
        import time as _t
        _t0 = _t.monotonic()
        try:
            return await coro
        finally:
            _el = _t.monotonic() - _t0
            _hb("tracker")
            if _el >= _step_warn:
                logger.warning("[tracker] шаг %s: %.1fs (порог %.0fs)", name, _el, _step_warn)
            else:
                logger.debug("[tracker] шаг %s: %.1fs", name, _el)

    while True:
        try:
            await asyncio.sleep(60)
            # 16.07 HEARTBEAT: пульс ведения позиций (TSL/BE/sync) — критичнее скана
            _hb("tracker")
            _iter_t0 = __import__("time").monotonic()

            # ── Шаг 1: биржевой sync (VST/LIVE only) ──────────────────────
            if _is_live:
                await _step("sync_positions", sync_positions(bot))

            # ── Шаг 1.5: repair — поставить SL/TP на бирже для сделок без него
            if _is_live and hasattr(bot, "order_executor"):
                await _step("repair_sl", repair_missing_sl(bot))
                await _step("repair_tp", repair_missing_tp(bot))
            # 🔴 01.09 ТОТ ЖЕ ДЕФЕКТ, ЧТО В scan_loop: пульс бился ОДИН раз в начале
            # итерации, поэтому «тишина tracker» = длительность итерации, а не смерть.
            # Итерация (sync + repair + check_open_trades по 25-46 сделкам с REST на
            # каждую) занимала до 24 мин — вотчдог считал это смертью и рестартил.
            # Пульс бьётся ВНУТРИ каждого обхода (см. trade_simulator._proc, tsl_updater,
            # position_sync) и после каждого шага здесь (_step): тишина теперь означает,
            # что шаг реально встал, а не что работы много.

            # ── Шаг 2: симуляторный трекинг ───────────────────────────────
            closed, tsl_moved = await _step("check_open_trades",
                bot.trade_simulator.check_open_trades_with_tsl(
                    bot.data_collector,
                    use_tsl=use_tsl,
                    tsl_activation_r=tsl_activation_r,
                    use_breakeven=use_breakeven,
                    breakeven_activation_r=breakeven_activation_r,
                    use_be_after_tp1=use_be_after_tp1,
                    cascade_tsl=cascade_tsl,
                ))
            if closed > 0:
                logger.info("TradeSimulator: закрыто сделок за цикл: %d", closed)

            # ── Шаг 2.5: CHoCH-перенос SL для ote_nested (validated struct_choch_tp1
            #    +0.315R). После первого LTF-CHoCH → SL за структуру (один раз, сужение).
            try:
                from core.trading.choch_sl_transfer import apply_choch_transfer
                choch_moved = await _step("choch_sl", apply_choch_transfer(bot))
                if choch_moved:
                    tsl_moved = (tsl_moved or []) + choch_moved
            except Exception as _e:
                logger.warning("[CHoCH-SL] apply error: %s", _e)

            # ── Шаг 3: обновить SL на бирже (VST/LIVE only) ───────────────
            if _is_live and tsl_moved and hasattr(bot, "order_executor"):
                await _step("update_tsl", update_tsl_on_exchange(bot, tsl_moved))

            _iter_el = __import__("time").monotonic() - _iter_t0
            if _iter_el >= _step_warn:
                logger.warning("[tracker] ИТЕРАЦИЯ %.1fs (шаги выше)", _iter_el)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("trade_tracker_loop: %s", e)
