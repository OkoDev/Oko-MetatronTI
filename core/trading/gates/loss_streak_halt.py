"""
HARD gate: ПРЕДОХРАНИТЕЛЬ — пауза источника после серии убытков подряд.

Зачем (замер 13.08.2026 на РЕАЛЬНОЙ боевой базе, 19 039 закрытых сделок с exchange_order_id):
    без предохранителя  −4462.6%
    с предохранителем   −201.7%   ← спасено +4260.9%, то есть 95% всего убытка
Правило намеренно тупое — «3 убытка подряд по источнику → пауза 72ч». Оно ничего не
предсказывает: три класса признаков периода (собственная доходность механики,
корреляционный режим, объём рынка) НЕ отличают прибыльный период от убыточного
(memory/period_signal_self_adaptive_dead). Поэтому защита строится по ФАКТУ убытка.

Почему это не дублирует существующее:
  • pair_cooldown_streak — SOFT penalty и по ПАРЕ (symbol), а не по источнику;
  • trading.circuit_breaker — не останавливает торговлю, а поднимает min_strength на 10
    при WR<15%; за 96 дней НИ ОДНОГО срабатывания;
  • sl_cooldown — по паре и только после SL, без учёта серии.
Здесь: по ИСТОЧНИКУ (source_router = имя policy, которое луп передаёт в submit),
серия подряд, жёсткая пауза.

Мотив из данных: ote_nested отработал ДВЕ недели (PF 2.69, +864%) и умер (PF 0.53, −752%),
а бот продолжал его лить месяц — потому что выключателя нет.

Конфиг (trading.loss_streak_halt):
    enabled       — вкл/выкл (default false: включать осознанно)
    streak        — сколько убытков подряд (default 3)
    pause_hours   — длительность паузы (default 72)
    per_source    — {источник: {streak, pause_hours}} — точечные переопределения
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from core.trading.gates.base import Gate, GateContext, GateResult, GateType

_LOSS_STATUSES = ("SL",)          # что считаем убытком: SL. TSL/EXPIRED могут быть в плюсе.


class LossStreakHaltGate(Gate):
    name = "loss_streak_halt"
    gate_type = GateType.HARD

    async def check(self, ctx: GateContext) -> GateResult:
        cfg = ctx.bot.config
        try:
            base = cfg.get("trading.loss_streak_halt", {}) or {}
        except Exception:
            return self._pass()
        if not base.get("enabled", False):
            return self._pass()

        src = (getattr(ctx, "source", "") or "").strip()
        if not src:
            return self._pass()

        # точечные переопределения по источнику
        per = base.get("per_source", {}) or {}
        own = per.get(src, {}) if isinstance(per, dict) else {}
        try:
            streak = int(own.get("streak", base.get("streak", 3)))
            pause_h = float(own.get("pause_hours", base.get("pause_hours", 72)))
        except Exception:
            streak, pause_h = 3, 72.0
        if streak <= 0 or pause_h <= 0:
            return self._pass()

        # Последние закрытые сделки ЭТОГО источника, новейшие первыми.
        # source_router — имя policy (проверено: 'radar' покрывает radar_pump/radar_spring).
        try:
            db_path = ctx.bot.trade_simulator.db_path
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT status, closed_at FROM simulated_trades "
                    "WHERE source_router=? AND status IN ('TP','TSL','SL','EXPIRED') "
                    "AND closed_at IS NOT NULL "
                    "ORDER BY closed_at DESC LIMIT ?",
                    (src, streak),
                ).fetchall()
        except Exception:
            return self._pass()          # прибор сломан — не мешаем торговле

        if len(rows) < streak:
            return self._pass()
        if not all(r[0] in _LOSS_STATUSES for r in rows):
            return self._pass()          # серия прервана прибыльной сделкой

        # серия набрана: пауза отсчитывается от ЗАКРЫТИЯ последней убыточной
        last_closed_raw = rows[0][1]
        try:
            last_closed = datetime.fromisoformat(str(last_closed_raw).replace("Z", "+00:00"))
            if last_closed.tzinfo is None:
                last_closed = last_closed.replace(tzinfo=timezone.utc)
        except Exception:
            return self._pass()

        now = datetime.now(timezone.utc)
        until = last_closed + timedelta(hours=pause_h)
        if now >= until:
            return self._pass()          # пауза истекла

        left_h = (until - now).total_seconds() / 3600.0
        return self._drop(
            f"{src}: {streak} убытка подряд → пауза ещё {left_h:.1f}ч (до {until:%Y-%m-%d %H:%M} UTC)",
            features={
                "source": src,
                "streak": streak,
                "pause_hours": pause_h,
                "hours_left": round(left_h, 2),
                "last_loss_closed_at": str(last_closed_raw),
            },
        )
