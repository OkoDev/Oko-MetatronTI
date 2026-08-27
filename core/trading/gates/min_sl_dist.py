"""
HARD gate: SL дистанция от entry не должна быть слишком близкой.

Блокирует если |entry - sl| / entry < min_sl_dist_pct (default 0.1%).
Соответствует DEV-157/164 в trade_simulator.py:368-384.
"""
from __future__ import annotations

from core.trading.gates.base import Gate, GateContext, GateResult, GateType


class MinSlDistGate(Gate):
    name = "min_sl_dist"
    gate_type = GateType.HARD

    async def check(self, ctx: GateContext) -> GateResult:
        rec = ctx.rec
        entry = _get(rec, "entry_price")
        sl    = _get(rec, "stop_loss")
        if entry is None or sl is None or float(entry) <= 0:
            return self._pass()   # пропускаем валидацию — validate_inputs ловит

        try:
            # 13.08.2026 PER-SOURCE (по образцу rr_filter.min_rr_per_strategy).
            # Повод: глобальный порог 4% верен для большинства источников, но ПРОТИВОПОЛОЖЕН
            # для фейда. Замер по боевым сделкам:
            #   rangefade4h: стоп <2% → PF 6.30 · 2-4% → 3.03 · 4-6% → 0.00 · >6% → 0.18
            #   radar_pump : стоп <2% → PF 0.82 · 2-4% → 0.45 · 4-6% → 0.31 · >6% → 3.01
            # Один глобальный порог убил бы прибыльную зону rangefade целиком.
            # 22.08 (реестр, фаза 2): порог резолвит РЕЕСТР — по source и trade_mode
            # одновременно, чтобы три места кода не расходились из-за имени ключа.
            from core.trading.source_registry import min_sl_dist_pct
            min_pct = min_sl_dist_pct(
                source=getattr(ctx, "source", "") or "",
                trade_mode=str(getattr(getattr(ctx, "policy", None), "trade_mode", "") or ""),
                cfg=ctx.bot.config,
            )
        except Exception:
            min_pct = 0.5

        entry_f = float(entry); sl_f = float(sl)
        sl_dist = abs(entry_f - sl_f)
        sl_dist_pct = (sl_dist / entry_f) * 100.0

        # OTE-RBUG (14.06): валидация СТОРОНЫ SL. LONG: SL должен быть НИЖЕ entry,
        # SHORT: ВЫШЕ. Инвертный SL (HOME LONG sl>entry) → R/size взрыв. REJECT.
        direction = _get(rec, "direction")
        dir_str = str(getattr(direction, "value", direction) or "").upper()
        if dir_str in ("LONG", "BUY") and sl_f >= entry_f:
            return self._drop(
                f"SL на неверной стороне (LONG): sl={sl_f} >= entry={entry_f}",
                features={"entry": entry_f, "sl": sl_f, "direction": dir_str},
            )
        if dir_str in ("SHORT", "SELL") and sl_f <= entry_f:
            return self._drop(
                f"SL на неверной стороне (SHORT): sl={sl_f} <= entry={entry_f}",
                features={"entry": entry_f, "sl": sl_f, "direction": dir_str},
            )

        if sl_dist_pct < min_pct:
            return self._drop(
                f"SL too close: {sl_dist_pct:.4f}% < {min_pct:.2f}%",
                features={"sl_dist_pct": sl_dist_pct, "min_sl_dist_pct": min_pct, "entry": entry_f, "sl": sl_f},
            )
        return self._pass(features={"sl_dist_pct": sl_dist_pct})


def _get(obj, name):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)
