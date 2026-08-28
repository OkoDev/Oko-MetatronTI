"""
TradeRouter — единый узел регистрации сделок (Сфера 9 Куба Метатрона, Phase 1).

Принимает recommendation из любого источника (atr_change/monitoring/wt_sideways/...)
и проходит единый pipeline:
  1. Build context (regime + open_trades snapshot)
  2. Run HARD gates → если drop → record_drop + publish POSITION_DROPPED → return
  3. Run SOFT gates → аккумулируем strength_penalty
  4. Persist trade в БД через trade_simulator.register_trade_async()
  5. Exchange placement (если policy.exchange_enabled и strength >= min_strength)
  6. Publish POSITION_OPENED в PairContextBus

Pipeline соответствует плану в C:\\Users\\yogoru\\.claude\\plans\\nifty-spinning-engelbart.md
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Optional

# 🔴 28.08: пауза по паре, которую БИРЖА объявила недоступной (не наш отказ, а её).
# Час — заметно длиннее цикла любого лупа (600 с у OTE), поэтому повтор не проскочит.
SYMBOL_COOLDOWN_SEC = 3600.0

from core.trading.gates.base import Gate, GateContext, GateResult, GateType, SubmitResult
from core.trading.gates.validate_inputs import ValidateInputsGate
from core.trading.gates.dedup_open import DedupOpenGate
from core.trading.gates.sl_cooldown import SlCooldownGate
from core.trading.gates.min_sl_dist import MinSlDistGate
from core.trading.gates.rr_filter import RrFilterGate
from core.trading.gates.loss_streak_halt import LossStreakHaltGate
from core.trading.gates.strength_threshold import StrengthThresholdGate
from core.trading.gates.regime_safety import RegimeSafetyGate
from core.trading.gates.btc_market import BtcMarketGate
from core.trading.gates.time_gate import TimeGate
from core.trading.gates.correlation_guard import CorrelationGuardGate
from core.trading.gates.market_stress import MarketStressGate
from core.trading.gates.pair_cooldown_streak import PairCooldownStreakGate
from core.trading.source_policies import SourcePolicy
from core.infra.trading_settings import is_live as _is_live_fn, get_risk_pct, get_leverage

logger = logging.getLogger(__name__)

STATUS_OPEN = "OPEN"


class TradeRouter:
    """Единый узел регистрации сделок и открытия биржевых ордеров."""

    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self.config = bot.config
        # symbol → до какого времени (unix) пара на паузе после отказа биржи.
        # In-memory: после рестарта пробуем снова — биржа могла вернуть пару в строй.
        self._symbol_cooldown: dict[str, float] = {}

        # HARD gates — выполняются первыми, любой drop → break pipeline
        self._hard_gates: list[Gate] = [
            ValidateInputsGate(),
            DedupOpenGate(),
            SlCooldownGate(),
            MinSlDistGate(),
            RrFilterGate(),
            # ПРЕДОХРАНИТЕЛЬ (13.08.2026): пауза источника после серии убытков.
            # Ставится ПОСЛЕДНИМ среди HARD — единственный ходит в БД, пусть
            # дешёвые проверки отсеют раньше. Выключен по умолчанию (enabled: false).
            LossStreakHaltGate(),
        ]
        # SOFT gates — аккумулируют strength_penalty
        self._soft_gates: dict[str, Gate] = {
            "strength_threshold":   StrengthThresholdGate(),
            "regime_safety":        RegimeSafetyGate(),
            "btc_market":           BtcMarketGate(),
            "time_gate":            TimeGate(),
            "correlation_guard":    CorrelationGuardGate(),
            "market_stress":        MarketStressGate(),
            "pair_cooldown_streak": PairCooldownStreakGate(),
        }

    # ─────────────────────────────────────────────────────────────────────
    async def submit(
        self,
        recommendation: Any,
        *,
        source: str,
        extra_features: Optional[dict] = None,
    ) -> SubmitResult:
        """
        Главная точка входа — заменяет 8 разрозненных вызовов
        register_trade_async + open_bracket.
        """
        extra = dict(extra_features or {})
        # 🔴 28.08: пара на паузе после отказа биржи «symbol offline» — не тратим
        # ни запрос, ни строку в БД. Кулдаун ставится ниже, в ветке open_bracket_fail.
        _sym = getattr(recommendation, "symbol", "") or ""
        _until = getattr(self, "_symbol_cooldown", {}).get(_sym, 0.0)
        if _until and time.time() < _until:
            logger.info("[TradeRouter] %s пропуск: биржа объявила пару недоступной, "
                        "пауза ещё %.0f мин", _sym, (_until - time.time()) / 60)
            return SubmitResult(trade_id=None, exchange_order_id=None,
                                hard_drops=[("symbol_offline_cooldown",
                                             "пара недоступна на бирже")])
        policy = SourcePolicy.from_config(self.config, source)

        # ── Build context ────────────────────────────────────────────────
        symbol = _get(recommendation, "symbol") or extra.get("symbol", "?")
        direction = _direction_str(_get(recommendation, "direction"))
        signal_type = _signal_type_from(recommendation, extra)
        strength = int(_get(recommendation, "overall_strength") or 0)
        regime = await _safe_regime(self.bot, symbol)
        open_trades = self._snapshot_open_trades()

        ctx = GateContext(
            rec=recommendation,
            symbol=symbol,
            direction=direction,
            signal_type=signal_type,
            strength=strength,
            source=source,
            extra_features=extra,
            policy=policy,
            regime=regime,
            open_trades=open_trades,
            bot=self.bot,
        )

        # ── Run HARD gates ───────────────────────────────────────────────
        hard_drops: list[tuple[str, str]] = []
        for gate in self._hard_gates:
            res = await _run_gate_safe(gate, ctx)
            if not res.passed:
                hard_drops.append((res.gate_name, res.reason))
                await self._record_drop(ctx, res)
                await self._publish_position_dropped(ctx, hard_drops, [])
                return SubmitResult(
                    trade_id=None,
                    exchange_order_id=None,
                    soft_penalties=[],
                    hard_drops=hard_drops,
                    final_strength=ctx.strength,
                    is_registered=False,
                )

        # ── Run SOFT gates ───────────────────────────────────────────────
        soft_penalties: list[tuple[str, int, str]] = []
        for gate_name in policy.soft_gates_enabled:
            gate = self._soft_gates.get(gate_name)
            if gate is None:
                continue
            res = await _run_gate_safe(gate, ctx)
            if res.strength_penalty > 0:
                soft_penalties.append((res.gate_name, res.strength_penalty, res.reason))
                ctx.strength = max(0, ctx.strength - res.strength_penalty)
            # Записываем features даже при passed=True
            if res.features:
                ctx.extra_features.setdefault("gate_features", {})[res.gate_name] = res.features

        ctx.extra_features["soft_penalties"] = [
            {"gate": g, "penalty": p, "reason": r} for g, p, r in soft_penalties
        ]
        ctx.extra_features["source_router"] = source
        ctx.extra_features["router_version"] = 1
        ctx.extra_features["router_final_strength"] = ctx.strength
        # trade_mode из policy (для дальнейшего dedup)
        if policy.trade_mode and "trade_mode" not in ctx.extra_features:
            ctx.extra_features["trade_mode"] = policy.trade_mode

        # ── Pre-registration strength check ──────────────────────────────
        if ctx.strength < policy.min_strength:
            reason = f"str={ctx.strength} < min={policy.min_strength}"
            hard_drops.append(("below_min_strength", reason))
            logger.info("[TradeRouter] %s DROP %s %s: %s", symbol, direction, source, reason)
            await self._record_drop_plain(ctx, "below_min_strength", reason)
            await self._publish_position_dropped(ctx, hard_drops, soft_penalties)
            return SubmitResult(
                trade_id=None,
                exchange_order_id=None,
                soft_penalties=soft_penalties,
                hard_drops=hard_drops,
                final_strength=ctx.strength,
                is_registered=False,
            )

        # ── Persist ──────────────────────────────────────────────────────
        _reg_reason: list = []
        try:
            trade_id = await self.bot.trade_simulator.register_trade_async(
                recommendation, self.bot.data_collector, extra_features=ctx.extra_features,
                _reason_out=_reg_reason,
            )
        except Exception as e:
            logger.warning("[TradeRouter] %s/%s register_trade_async error: %s",
                           symbol, source, e)
            trade_id = None

        if not trade_id:
            # trade_simulator вернул None — внутренние gates ещё работают
            _internal_reason = _reg_reason[0] if _reg_reason else "unknown"
            hard_drops.append(("register_returned_none", f"{source}: register_trade_async() returned None ({_internal_reason})"))
            await self._record_drop_register_none(ctx, reason=_internal_reason)
            await self._publish_position_dropped(ctx, hard_drops, soft_penalties)
            return SubmitResult(
                trade_id=None,
                exchange_order_id=None,
                soft_penalties=soft_penalties,
                hard_drops=hard_drops,
                final_strength=ctx.strength,
                is_registered=False,
            )

        # ── Exchange placement ───────────────────────────────────────────
        exchange_order_id = None
        below_min = ctx.strength < policy.min_strength
        can_open = (
            policy.exchange_enabled
            and not below_min
            and _is_live_fn(self.config)
            and hasattr(self.bot, "order_executor")
            and hasattr(self.bot, "position_sizer")
        )

        if can_open:
            exchange_order_id = await self._place_exchange_order(ctx, trade_id)

        # ── Clear aggregator ─────────────────────────────────────────────
        ca = getattr(self.bot, "confirmation_aggregator", None)
        if ca is not None:
            try:
                ca.clear(symbol, direction)
            except Exception:
                pass

        # ── Publish POSITION_OPENED ──────────────────────────────────────
        await self._publish_position_opened(ctx, trade_id, exchange_order_id, soft_penalties)

        logger.info(
            "[TradeRouter] %s %s %s → #%d str=%d source=%s soft=%d exch=%s",
            symbol, direction, signal_type, trade_id, ctx.strength, source,
            len(soft_penalties), exchange_order_id or "none",
        )

        return SubmitResult(
            trade_id=trade_id,
            exchange_order_id=exchange_order_id,
            soft_penalties=soft_penalties,
            hard_drops=[],
            final_strength=ctx.strength,
            is_registered=True,
        )

    # ─────────────────────────────────────────────────────────────────────
    async def _place_exchange_order(self, ctx: GateContext, trade_id: int) -> Optional[str]:
        """Открывает биржевой ордер через order_executor.open_bracket()."""
        rec = ctx.rec
        entry = float(_get(rec, "entry_price") or 0)
        sl    = float(_get(rec, "stop_loss") or 0)
        tp    = float(_get(rec, "take_profit") or 0)
        # tsl-only fallback: TP=15R
        if tp <= 0 and entry > 0 and sl > 0:
            sl_dist = abs(entry - sl)
            tp = entry + 15 * sl_dist if ctx.direction == "LONG" else entry - 15 * sl_dist

        if entry <= 0 or sl <= 0 or tp <= 0:
            await self._record_drop_plain(ctx, "order_params_zero",
                                          f"entry={entry} sl={sl} tp={tp}")
            return None

        try:
            oe = self.bot.order_executor
            deposit  = await oe.get_available_balance()
            # per-source sizing (19.06): плечо/риск из policy источника, иначе глобальный
            # fallback. Корень: глобальный leverage тёк бы на любую новую стратегию.
            _pol = ctx.policy
            risk_pct = _pol.risk_pct if getattr(_pol, "risk_pct", None) is not None else get_risk_pct(self.config)
            leverage = _pol.leverage if getattr(_pol, "leverage", None) is not None else get_leverage(self.config)
            # 07.08 Егор: множитель риска из extra_features (кондиционеры funding/AC-режим).
            # Основной сайзинг отложен до 20-30 чистых net+; пока ×1.5 с потолком и только
            # там, где источник сам его выставил (bigflush15). Потолок жёсткий — защита от
            # раздувания риска на кластере (88% сигналов приходят пачками).
            try:
                _rm = float((getattr(ctx, "extra_features", None) or {}).get("risk_mult") or 1.0)
                if _rm != 1.0:
                    # 10.08: нижняя граница 0.25 — гибрид-выход шлёт ДВЕ половины по 0.5×
                    # (одна на TP1R, вторая раннером под TSL). Верх по-прежнему под потолком.
                    _rm = max(0.25, min(_rm, float(self.config.get("trading.risk_mult_cap", 1.5))))
                    risk_pct = round(risk_pct * _rm, 4)
            except Exception:
                pass
            qty = self.bot.position_sizer.calc_qty(
                entry_price=entry, sl_price=sl,
                deposit=deposit, risk_pct=risk_pct, leverage=leverage,
            )
            if qty <= 0:
                await self._record_drop_plain(ctx, "qty_zero",
                                              f"deposit={deposit:.2f} risk={risk_pct}%")
                return None

            br = await oe.open_bracket(
                symbol=ctx.symbol, direction=ctx.direction,
                entry_price=entry, sl=sl, tp1=tp, tp2=None, qty=qty,
                leverage=leverage,   # per-source плечо → биржа (кламп к max пары внутри)
                entry_order_type=getattr(_pol, "entry_order_type", "MARKET"),  # oko_ote → LIMIT (Фаза 1)
                lev_set_to_max=getattr(_pol, "lev_set_to_max", True),  # radar → False (уважать 20×)
                source=ctx.source,   # 20.08: per-strategy min_sl_dist внутри open_bracket
            )
            if not br.success:
                if br.error != "position_already_open":
                    logger.warning("[TradeRouter] %s OrderExecutor: %s", ctx.symbol, br.error)
                    await self._record_drop_plain(ctx, "open_bracket_fail", br.error or "unknown")
                    # 🔴 28.08 КУЛДАУН ПО НЕДОСТУПНОМУ СИМВОЛУ. Вселенная сигналов шире
                    # вселенной ТОРГУЕМЫХ пар: детектор берёт свечи из кэша, а биржа
                    # отвечает «ICP-USDT is offline currently». Без кулдауна один и тот же
                    # сигнал долбится по кругу — за 4 часа 28.08 ICP ушёл на биржу 8 раз,
                    # ILV 6 раз, все впустую ([[universe_mismatch_backtest_vs_live]]).
                    # Отказ ПО СИМВОЛУ (а не по нашим параметрам) → пара молчит SYMBOL_COOLDOWN_SEC.
                    _e = str(br.error or "").lower()
                    if any(k in _e for k in ("offline", "not exist", "validted symbols",
                                             "invalid symbol", "symbol not")):
                        self._symbol_cooldown[ctx.symbol] = time.time() + SYMBOL_COOLDOWN_SEC
                        logger.warning("[TradeRouter] %s недоступен на бирже → пауза %.0f мин",
                                       ctx.symbol, SYMBOL_COOLDOWN_SEC / 60)
                else:
                    # 27.05.2026: position_already_open ранее был молчаливым → невидимый блок.
                    # Теперь видим в логе и в signal_drops (отдельный gate чтобы отличать).
                    logger.info("[TradeRouter] %s %s position_already_open — exchange skipped (SIM-only)",
                                ctx.symbol, ctx.direction)
                    await self._record_drop_plain(ctx, "exchange_position_already_open",
                                                  f"{ctx.direction} skipped (other direction already on exchange)")
                return None

            order_id = br.order_id
            logger.info(
                "[TradeRouter] [%s] bracket: %s qty=%.6f entry=%.6f SL=%.6f TP=%.6f order_id=%s notional=%.2f",
                br.mode.upper(), ctx.direction, qty, entry, sl, tp, order_id, br.notional_usdt,
            )

            # ARCH-94: записать exchange_order_id в БД (ранее не делалось через router)
            # OPS-06 ч.3 (11.06): + qty (размер позиции) — router заменил link_exchange_order,
            # но qty не переносил → qty=NULL с конца мая → реальный $ P&L не считался. qty>0 (guard :257).
            try:
                import sqlite3 as _sq
                # ARCH-DB-V2 Ф1: order_id записан = сделка РЕАЛЬНО на бирже → execution_mode по
                # ФАКТУ исполнения = режим бота (VST/LIVE). Shadow (без order_id) остаётся SIM.
                from core.infra.config_loader import config as _cfg_dbv2
                _raw_em = str(_cfg_dbv2.get("trading.execution_mode", "vst")).upper()
                _em = {"VST": "VST", "LIVE": "LIVE"}.get(_raw_em, "VST")
                with _sq.connect(self.bot.trade_simulator.db_path) as _conn:
                    # leverage в БД (19.06): ФАКТИЧЕСКОЕ плечо после клампа к max пары (br.leverage),
                    # не запрошенное и не глобальный конфиг. Дашборд берёт из факта (bus→БД→config).
                    _act_lev = br.leverage if getattr(br, "leverage", None) is not None else leverage
                    # actual_entry_price = ФАКТ. цена филла (br.entry_price=avgPrice). Без неё R
                    # считался от СИГНАЛЬНОЙ entry → фантом ×50 (2-й фронт лжи метрик 20.06). OTE-путь
                    # её не писал. WS 2a уточнит из o.ap. Пишем если >0 (иначе оставляем NULL→fallback).
                    _aep = float(getattr(br, "entry_price", 0) or 0)
                    if _aep > 0:
                        _conn.execute(
                            "UPDATE simulated_trades SET exchange_order_id=?, qty=?, execution_mode=?, leverage=?, actual_entry_price=? WHERE id=?",
                            (order_id, qty, _em, _act_lev, _aep, trade_id),
                        )
                    else:
                        _conn.execute(
                            "UPDATE simulated_trades SET exchange_order_id=?, qty=?, execution_mode=?, leverage=? WHERE id=?",
                            (order_id, qty, _em, _act_lev, trade_id),
                        )
            except Exception as _upd_e:
                logger.warning("[TradeRouter] exchange_order_id/qty update failed for #%d: %s",
                               trade_id, _upd_e)

            if hasattr(self.bot, "position_manager"):
                try:
                    self.bot.position_manager.register(
                        symbol=ctx.symbol, side=ctx.direction, qty=qty,
                        sim_trade_id=trade_id,
                        exchange_order_id=order_id,
                    )
                except Exception as _pm_e:
                    logger.debug("[TradeRouter] position_manager.register: %s", _pm_e)

            # TSL tracker — только для live (vst тоже подходит)
            if _is_live_fn(self.config):
                try:
                    from core.exchange.tsl_updater import (
                        fetch_and_save_sl_order_id, fetch_and_save_tp_order_id,
                        fetch_and_save_position_id,
                    )
                    asyncio.create_task(fetch_and_save_sl_order_id(
                        self.bot, trade_id, ctx.symbol, ctx.direction))
                    # radar (multi-TP): om.get_tp_order_id считает >1 TP дубликатами и ОТМЕНЯЕТ
                    # «лишние» → при мгновенном LIMIT-fill порезал бы частичные TP1/TP2 (04.07)
                    if getattr(ctx.policy, "trade_mode", "") != "radar":
                        asyncio.create_task(fetch_and_save_tp_order_id(
                            self.bot, trade_id, ctx.symbol, ctx.direction))
                    # fake-R фикс (19.06): захват positionID — якорь exit'а в _resolve_exit
                    asyncio.create_task(fetch_and_save_position_id(
                        self.bot, trade_id, ctx.symbol, ctx.direction))
                except Exception as _tsl_e:
                    logger.debug("[TradeRouter] tsl_updater: %s", _tsl_e)

            return order_id

        except Exception as e:
            logger.warning("[TradeRouter] %s open_bracket exception: %s", ctx.symbol, e)
            await self._record_drop_plain(ctx, "open_bracket_fail", f"{type(e).__name__}: {e}")
            return None

    # ─────────────────────────────────────────────────────────────────────
    def _snapshot_open_trades(self) -> list[dict]:
        """Снимок открытых сделок (id, symbol, direction, features_json)."""
        try:
            db_path = self.bot.trade_simulator.db_path
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                # 🔴 20.08: PENDING_ENTRY ОБЯЗАН попадать в снимок. Раньше брали только
                # OPEN, и выставленная лимитка была НЕВИДИМА для dedup_open: другой
                # источник открывал MARKET по тому же символу и стороне, а чекер лимиток
                # (`radar_armed_loop._check_pending`) видел позицию в агрегате и
                # засчитывал ЧУЖУЮ позицию как наш фил — записывал чужую цену входа,
                # привязывал чужой position_id, после чего `repair_missing_sl` ставил
                # наш стоп на чужую позицию. Своя лимитка при этом оставалась на бирже
                # без надзора: строка уже OPEN, TTL её не отменит.
                rows = conn.execute(
                    "SELECT id, symbol, direction, features_json FROM simulated_trades "
                    "WHERE status IN (?, 'PENDING_ENTRY') LIMIT 500",
                    (STATUS_OPEN,),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.debug("[TradeRouter] snapshot_open_trades err: %s", e)
            return []

    async def _record_drop(self, ctx: GateContext, res: GateResult) -> None:
        try:
            from core.observability.decision_trace import record_drop
            asyncio.create_task(record_drop(
                symbol=ctx.symbol, gate_name=res.gate_name,
                drop_reason=f"{ctx.source}/{ctx.direction}: {res.reason}",
                signal_type=ctx.signal_type, direction=ctx.direction,
                strength=ctx.strength, features={**res.features, "source": ctx.source},
            ))
        except Exception:
            pass

    async def _record_drop_register_none(self, ctx: GateContext, reason: str = "") -> None:
        try:
            from core.observability.decision_trace import record_drop
            asyncio.create_task(record_drop(
                symbol=ctx.symbol, gate_name="register_returned_none",
                drop_reason=f"{ctx.source}/{ctx.direction}: {reason or 'register_trade_async() returned None'}",
                signal_type=ctx.signal_type, direction=ctx.direction,
                strength=ctx.strength,
                features={
                    "source": ctx.source,
                    "soft_penalties": ctx.extra_features.get("soft_penalties", []),
                    "internal_reason": reason,
                },
            ))
        except Exception:
            pass

    async def _record_drop_plain(self, ctx: GateContext, gate_name: str, reason: str) -> None:
        try:
            from core.observability.decision_trace import record_drop
            asyncio.create_task(record_drop(
                symbol=ctx.symbol, gate_name=gate_name,
                drop_reason=f"{ctx.source}/{ctx.direction}: {reason}",
                signal_type=ctx.signal_type, direction=ctx.direction,
                strength=ctx.strength, features={"source": ctx.source},
            ))
        except Exception:
            pass

    async def _publish_position_opened(
        self, ctx: GateContext, trade_id: int, order_id: Optional[str],
        soft_penalties: list[tuple[str, int, str]],
    ) -> None:
        bus = getattr(self.bot, "pair_context", None) or getattr(self.bot, "pair_context_bus", None)
        if bus is None:
            return
        try:
            from core.context.pair_context import SphereEvent
            bus.publish(ctx.symbol, SphereEvent.POSITION_OPENED, {
                "side": ctx.direction,
                "source": ctx.source,
                "trade_id": trade_id,
                "exchange_order_id": order_id,
                "final_strength": ctx.strength,
                "soft_penalties": [{"gate": g, "penalty": p, "reason": r} for g, p, r in soft_penalties],
                "regime": ctx.regime,
                "ts_ms": int(ctx.timestamp_utc.timestamp() * 1000),
            })
        except Exception as e:
            logger.debug("[TradeRouter] publish POSITION_OPENED err: %s", e)

    async def _publish_position_dropped(
        self, ctx: GateContext,
        hard_drops: list[tuple[str, str]],
        soft_penalties: list[tuple[str, int, str]],
    ) -> None:
        bus = getattr(self.bot, "pair_context", None) or getattr(self.bot, "pair_context_bus", None)
        if bus is None:
            return
        try:
            from core.context.pair_context import SphereEvent
            bus.publish(ctx.symbol, SphereEvent.POSITION_DROPPED, {
                "side": ctx.direction,
                "source": ctx.source,
                "hard_drops": [{"gate": g, "reason": r} for g, r in hard_drops],
                "soft_penalties": [{"gate": g, "penalty": p, "reason": r} for g, p, r in soft_penalties],
                "strength": ctx.strength,
                "regime": ctx.regime,
                "ts_ms": int(ctx.timestamp_utc.timestamp() * 1000),
            })
        except Exception as e:
            logger.debug("[TradeRouter] publish POSITION_DROPPED err: %s", e)


# ── helpers ──────────────────────────────────────────────────────────────
def _get(obj: Any, name: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _direction_str(direction: Any) -> str:
    """Legacy wrapper над core.signals.signal_models.to_direction (DRY 27.05.2026)."""
    from core.signals.signal_models import to_direction
    return to_direction(direction)


def _signal_type_from(rec: Any, extra: dict) -> str:
    if extra.get("signal_type_override"):
        return str(extra["signal_type_override"])
    st = _get(rec, "signal_type")
    if st is not None:
        return str(getattr(st, "value", None) or st)
    sigs = _get(rec, "supporting_signals") or []
    if sigs:
        s0 = sigs[0]
        st = getattr(s0, "signal_type", None)
        if st is not None:
            return str(getattr(st, "value", None) or st)
    return "unknown"


async def _safe_regime(bot: Any, symbol: str) -> Optional[str]:
    """Берёт regime из MarketRegimeClassifier один раз."""
    try:
        from core.indicators.market_regime import MarketRegimeClassifier
        # Берём из data_collector кеш
        df = None
        try:
            df = await bot.data_collector.get_ohlcv(symbol, "1h", limit=50)
        except Exception:
            pass
        if df is not None and not df.empty:
            return MarketRegimeClassifier().classify_from_ohlcv(df.values.tolist())
    except Exception:
        pass
    return None


async def _run_gate_safe(gate: Gate, ctx: GateContext) -> GateResult:
    """Запускает gate.check с защитой от исключений."""
    try:
        return await gate.check(ctx)
    except Exception as e:
        logger.warning("[TradeRouter] gate %s error: %s", gate.name, e)
        # Безопасно пропускаем (gate не должен ломать pipeline)
        return GateResult(
            passed=True, gate_name=gate.name, gate_type=gate.gate_type,
            reason=f"gate exception: {e}",
            features={"gate_exception": str(e)},
        )
