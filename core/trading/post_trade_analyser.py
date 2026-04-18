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

    def __init__(
        self,
        pair_context: "PairContextBus",
        data_collector=None,
        intelligence=None,   # ARCH-72: TradingIntelligence для update_signal_weights()
        event_bus=None,      # ARCH-72: EventBus для publish "trade_closed"
        db_path: str = "subscriptions.db",  # ARCH-88: для pair_avg_r_last_20 из simulated_trades
    ) -> None:
        self._ctx         = pair_context
        self._dc          = data_collector
        self._intelligence = intelligence
        self._event_bus    = event_bus
        self._close_count  = 0  # ARCH-72: счётчик для adaptive weights
        self._db_path      = db_path

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
        import asyncio
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

            # ARCH-88: Per-pair Loss Memory — обновление после любого закрытия
            try:
                self._update_loss_memory(symbol, status, r_multiple)
            except Exception as _lme:
                logger.debug("[PTA][ARCH-88] loss_memory error %s: %s", symbol, _lme)

            # ARCH-91: lost_reason + narrative_outcome feedback
            self._update_narrative_outcome(symbol, trade_id, status, r_multiple)

            # ARCH-72: адаптивные веса каждые 50 закрытий
            self._close_count += 1
            if self._close_count % 50 == 0 and self._intelligence is not None:
                try:
                    self._intelligence.update_signal_weights()
                    logger.info(
                        "[PTA][ARCH-72] update_signal_weights() после %d закрытий",
                        self._close_count,
                    )
                except Exception as _we:
                    logger.debug("[PTA][ARCH-72] update_signal_weights error: %s", _we)

            # ARCH-72: EventBus publish "trade_closed" → NarrativeBuilder
            if self._event_bus is not None and status != STATUS_EXPIRED:
                try:
                    await self._event_bus.publish(
                        symbol,
                        "trade_closed",
                        priority=5,
                        data={"status": status, "r_multiple": r_multiple,
                              "direction": direction, "trade_id": trade_id},
                    )
                except Exception as _ee:
                    logger.debug("[PTA][ARCH-72] event_bus.publish error: %s", _ee)

        except Exception as e:
            logger.warning("[PostTradeAnalyser] on_trade_closed %s: %s", symbol, e)

    # ─────────────── ARCH-91: lost_reason + narrative_outcome ────────────────

    @staticmethod
    def classify_lost_reason(
        status: str,
        r_multiple: float,
        max_r_possible: Optional[float] = None,
        tp1_hit: bool = False,
    ) -> Optional[str]:
        """ARCH-91: классифицировать причину потери сделки.

        Категории:
          None        — TP (нет потери)
          TIMEOUT     — EXPIRED
          SL_GAPPED   — R < -2 (gap/slippage)
          TSL_LATE    — max_R > 1 при SL (профит был, TSL не защитил)
          BAD_ENTRY   — стандартный -1R без движения и без tp1_hit
          SL_STANDARD — остальные SL
        """
        if status == STATUS_TP:
            return None
        if status == STATUS_EXPIRED:
            return "TIMEOUT"
        r = float(r_multiple or 0)
        if r < -2.0:
            return "SL_GAPPED"
        if (max_r_possible or 0) > 1.0 and status == STATUS_SL:
            return "TSL_LATE"
        if -1.1 <= r <= -0.9 and not tp1_hit:
            return "BAD_ENTRY"
        return "SL_STANDARD"

    def _update_narrative_outcome(self, symbol: str, trade_id: int, status: str, r_multiple: float) -> None:
        """ARCH-91: читает trade из БД, классифицирует lost_reason, обновляет PairState и features_json."""
        try:
            import sqlite3 as _sl3, json as _json
            conn = _sl3.connect(self._db_path)
            try:
                row = conn.execute(
                    "SELECT max_R_possible, tp1_hit_at, features_json"
                    "  FROM simulated_trades WHERE id = ?",
                    (trade_id,),
                ).fetchone()
                if row is None:
                    return
                max_r = float(row[0] or 0)
                tp1_hit = bool(row[1])
                features_raw = row[2]
            finally:
                conn.close()

            lost_reason = self.classify_lost_reason(status, r_multiple, max_r, tp1_hit)

            # Обновить PairState
            state = self._ctx.get(symbol)
            state.last_narrative_outcome = {
                "status": status,
                "R": round(r_multiple, 2),
                "lost_reason": lost_reason,
                "closed_at": datetime.now(timezone.utc).isoformat(),
            }

            # Записать lost_reason в features_json
            if features_raw:
                try:
                    fj = _json.loads(features_raw)
                    fj["lost_reason"] = lost_reason
                    conn2 = _sl3.connect(self._db_path)
                    try:
                        conn2.execute(
                            "UPDATE simulated_trades SET features_json=? WHERE id=?",
                            (_json.dumps(fj), trade_id),
                        )
                        conn2.commit()
                    finally:
                        conn2.close()
                except Exception as _e_fj:
                    logger.debug("[PTA][ARCH-91] features_json update %s: %s", symbol, _e_fj)

            logger.debug(
                "[PTA][ARCH-91] %s trade=%d status=%s R=%.2f lost_reason=%s",
                symbol, trade_id, status, r_multiple, lost_reason,
            )
        except Exception as e:
            logger.debug("[PTA][ARCH-91] _update_narrative_outcome %s: %s", symbol, e)

    # ─────────────── ARCH-88: Per-pair Loss Memory ────────────────────────────

    def _update_loss_memory(self, symbol: str, status: str, r_multiple: float) -> None:
        """ARCH-88: обновить sl_streak_count / last_n_outcomes / pair_avg_r_last_20.

        Правила:
          - SL: sl_streak_count += 1, last_sl_at = now
          - TP/TSL с R > 0: sl_streak_count = 0
          - всегда: last_n_outcomes.append(status), пересчёт pair_avg_r_last_20 из БД
        """
        state = self._ctx.get(symbol)

        if status == STATUS_SL:
            state.sl_streak_count += 1
            state.last_sl_at = datetime.now(timezone.utc)
        elif status in (STATUS_TP, STATUS_TSL) and r_multiple > 0:
            state.sl_streak_count = 0
        # EXPIRED и TP/TSL с R<=0 — sl_streak не трогаем

        state.last_n_outcomes.append(status)

        try:
            import sqlite3
            conn = sqlite3.connect(self._db_path)
            try:
                row = conn.execute(
                    "SELECT AVG(r_multiple) FROM ("
                    "  SELECT r_multiple FROM simulated_trades"
                    "   WHERE symbol = ? AND status IN ('SL','TP','TSL')"
                    "     AND r_multiple IS NOT NULL"
                    "   ORDER BY closed_at DESC LIMIT 20"
                    ")",
                    (symbol,),
                ).fetchone()
                state.pair_avg_r_last_20 = float(row[0] or 0.0)
            finally:
                conn.close()
        except Exception as e:
            logger.debug("[PTA][ARCH-88] pair_avg_r_last_20 %s: %s", symbol, e)

        logger.debug(
            "[PTA][ARCH-88] %s status=%s r=%.2f sl_streak=%d last10=%s avg_r_20=%.2f",
            symbol, status, r_multiple, state.sl_streak_count,
            list(state.last_n_outcomes), state.pair_avg_r_last_20,
        )

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
        # Куб: Сфера 11 → bus: CASCADE_UPDATED + OTE_ZONE_SET
        try:
            from core.context.pair_context import SphereEvent
            self._ctx.publish(symbol, SphereEvent.CASCADE_UPDATED, {
                "cascade_count": new_cascade, "avg_r": new_avg_r, "direction": direction,
            })
            if post_tsl_data:
                self._ctx.publish(symbol, SphereEvent.OTE_ZONE_SET, post_tsl_data)
        except Exception:
            pass
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
        # Куб: Сфера 11 → bus: CASCADE_UPDATED
        try:
            from core.context.pair_context import SphereEvent
            self._ctx.publish(symbol, SphereEvent.CASCADE_UPDATED, {
                "cascade_count": new_cascade, "avg_r": new_avg_r, "direction": direction,
            })
        except Exception:
            pass
        logger.info(
            "[PTA][TP] %s: r=%.2fR cascade=%d avg_r=%.2f",
            symbol, r_multiple, new_cascade, new_avg_r,
        )
