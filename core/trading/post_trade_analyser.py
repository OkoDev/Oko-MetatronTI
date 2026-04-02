"""
PostTradeAnalyser — DEV-94 / ARCH-60 / Куб Метатрона Фаза 2.

Единственная ответственность: реагировать на закрытие сделок и обновлять PairContextBus.

Режим работы: shadow (2 недели) — логирует что «сделал бы», не меняет поведение скана.
Переключение в production: убрать [SHADOW] из логов + раскомментировать WL-вызовы.

Регистрация в боте (bot_with_subscriptions.py):
    bot.pair_context  = PairContextBus()
    bot.post_analyser = PostTradeAnalyser(bot.pair_context, bot.data_collector)
    bot.trade_simulator.set_post_trade_callback(bot.post_analyser.on_trade_closed)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.context.pair_context import PairContextBus

logger = logging.getLogger("PostTradeAnalyser")

STATUS_TSL      = "TSL"
STATUS_SL       = "SL"
STATUS_TP       = "TP"
STATUS_EXPIRED  = "EXPIRED"


class PostTradeAnalyser:
    """
    Реагирует на закрытие сделок через callback от TradeSimulator.

    Обновляет PairContextBus:
      - cascade_count — серия TSL/TP в одном направлении
      - avg_r_cascade — средний R по серии
      - post_tsl_data — OTE зона для re-entry после TSL
    """

    def __init__(self, pair_context: "PairContextBus", data_collector=None) -> None:
        self._ctx = pair_context
        self._dc  = data_collector  # для shadow-проверки дивергенций (опционально)

    def set_post_trade_callback(self) -> None:
        """Метод для обратной совместимости — callback устанавливается снаружи."""
        pass

    async def on_trade_closed(
        self,
        trade_id:    int,
        status:      str,
        symbol:      str,
        direction:   str,          # "LONG" / "SHORT"
        r_multiple:  float,
        entry_price: float,
        sl_dist:     float,
        max_price:   Optional[float] = None,
        min_price:   Optional[float] = None,
        entry_tf:    str = "15m",
    ) -> None:
        """Основной callback от TradeSimulator.close_trade()."""
        try:
            if status == STATUS_SL:
                await self._on_sl(symbol, direction, r_multiple, entry_tf)
            elif status == STATUS_TSL:
                await self._on_tsl(symbol, direction, r_multiple, entry_price, max_price, min_price)
            elif status == STATUS_TP:
                await self._on_tp(symbol, direction, r_multiple)
            # EXPIRED — не меняем cascade, просто логируем
            elif status == STATUS_EXPIRED:
                logger.debug("[PTA][EXPIRED] %s: r=%.2fR — cascade сохраняется", symbol, r_multiple)
        except Exception as e:
            logger.warning("[PostTradeAnalyser] on_trade_closed %s: %s", symbol, e)

    # ─────────────────────────── Сценарий 1: SL ───────────────────────────────

    async def _on_sl(
        self, symbol: str, direction: str, r_multiple: float, entry_tf: str
    ) -> None:
        """SL = направление не работало → сброс cascade."""
        self._ctx.update(symbol,
            last_close_status=STATUS_SL,
            last_close_time=datetime.now(timezone.utc),
            cascade_count=0,
            last_direction=direction,
            post_tsl_data=None,
        )

        # Shadow: проверяем дивергенции для потенциального reversal re-entry
        if self._dc:
            try:
                df = await self._dc.get_ohlcv(symbol, entry_tf, limit=50)
                if df is not None:
                    from core.signals.divergence_detector import detect_divergences
                    divs = detect_divergences(df)
                    rev_dir = "LONG" if direction == "SHORT" else "SHORT"
                    relevant = [d for d in divs if getattr(d, "div_type", "") in
                                (("bullish",) if rev_dir == "LONG" else ("bearish",))]
                    logger.info(
                        "[PTA][SL][SHADOW] %s: dir=%s r=%.2fR div_relevant=%d → "
                        "would_add_WL direction=%s",
                        symbol, direction, r_multiple, len(relevant), rev_dir,
                    )
            except Exception:
                pass

    # ─────────────────────────── Сценарий 2: TSL ──────────────────────────────

    async def _on_tsl(
        self,
        symbol:      str,
        direction:   str,
        r_multiple:  float,
        entry_price: float,
        max_price:   Optional[float],
        min_price:   Optional[float],
    ) -> None:
        """TSL = импульс завершён → обновить cascade + вычислить OTE зону."""
        state = self._ctx.get(symbol)

        if (state.last_direction == direction
                and state.last_close_status in (STATUS_TSL, STATUS_TP)):
            new_cascade = state.cascade_count + 1
            new_avg_r   = (state.avg_r_cascade * state.cascade_count + r_multiple) / new_cascade
        else:
            new_cascade = 1
            new_avg_r   = r_multiple

        # OTE зона для re-entry по спеку TR-010
        post_tsl_data = None
        if max_price and min_price:
            impulse_h = max_price if direction == "SHORT" else entry_price
            impulse_l = min_price if direction == "LONG"  else entry_price
            impulse   = impulse_h - impulse_l
            if impulse > 0:
                if direction == "SHORT":
                    ote_top = impulse_h - impulse * 0.705
                    ote_bot = impulse_h - impulse * 0.786
                else:
                    ote_bot = impulse_l + impulse * 0.705
                    ote_top = impulse_l + impulse * 0.786
                post_tsl_data = {
                    "direction":    direction,
                    "ote_top":      ote_top,
                    "ote_bot":      ote_bot,
                    "impulse_high": impulse_h,
                    "impulse_low":  impulse_l,
                    "exit_time":    datetime.now(timezone.utc),
                    "ttl_hours":    8,
                }

        self._ctx.update(symbol,
            last_close_status=STATUS_TSL,
            last_close_time=datetime.now(timezone.utc),
            last_direction=direction,
            cascade_count=new_cascade,
            avg_r_cascade=new_avg_r,
            post_tsl_data=post_tsl_data,
        )
        logger.info(
            "[PTA][TSL] %s: r=%.2fR cascade=%d avg_r=%.2f OTE=%s",
            symbol, r_multiple, new_cascade, new_avg_r,
            f"[{post_tsl_data['ote_bot']:.4f}, {post_tsl_data['ote_top']:.4f}]"
            if post_tsl_data else "None",
        )

    # ─────────────────────────── Сценарий 3: TP ───────────────────────────────

    async def _on_tp(self, symbol: str, direction: str, r_multiple: float) -> None:
        """TP = цель достигнута → обновить cascade, OTE не нужен."""
        state = self._ctx.get(symbol)

        if (state.last_direction == direction
                and state.last_close_status in (STATUS_TSL, STATUS_TP)):
            new_cascade = state.cascade_count + 1
            new_avg_r   = (state.avg_r_cascade * state.cascade_count + r_multiple) / new_cascade
        else:
            new_cascade = 1
            new_avg_r   = r_multiple

        self._ctx.update(symbol,
            last_close_status=STATUS_TP,
            last_close_time=datetime.now(timezone.utc),
            last_direction=direction,
            cascade_count=new_cascade,
            avg_r_cascade=new_avg_r,
            post_tsl_data=None,   # TP = impulse завершён, OTE не нужен
        )
        logger.info(
            "[PTA][TP] %s: r=%.2fR cascade=%d avg_r=%.2f",
            symbol, r_multiple, new_cascade, new_avg_r,
        )
