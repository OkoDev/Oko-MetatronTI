"""
Multi-TF Conflict Resolver (ARCH-13).

Когда бот работает на нескольких entry TF одновременно (["5m", "15m", "1h"]),
один и тот же move может порождать сигналы на нескольких ТФ.
Resolver решает конфликты:

1. ДУБЛИ — один move, сигналы на 5m и 15m → берём лучший
2. ПРОТИВОРЕЧИЯ — 5m LONG vs 1h SHORT → старший побеждает
3. КАСКАД — уже есть открытая сделка, младший ТФ даёт тот же сигнал → пропуск
4. RATE LIMIT — контролируем количество пар × ТФ

Принцип: старший ТФ ВСЕГДА имеет приоритет.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Приоритет ТФ: чем выше индекс, тем старше (больший вес)
TF_PRIORITY = {
    "1m": 1, "3m": 2, "5m": 3, "15m": 5, "30m": 6,
    "45m": 7, "1h": 8, "4h": 10, "1d": 12, "1W": 15,
}


@dataclass
class TFSignal:
    """Сигнал с конкретного ТФ."""
    symbol: str
    timeframe: str
    direction: str          # "LONG" / "SHORT"
    signal_type: str        # "wt_signal", "confluence", etc.
    strength: float = 0.0   # 0-100
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    rr_ratio: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    raw_signals: list = field(default_factory=list)
    raw_text: str = ""
    fallback_rec: object = None

    @property
    def tf_priority(self) -> int:
        return TF_PRIORITY.get(self.timeframe, 0)


@dataclass
class ResolverDecision:
    """Решение Resolver-а по группе сигналов для одного символа."""
    symbol: str
    action: str               # "ACCEPT", "REJECT", "UPGRADE", "SPLIT"
    chosen_signal: Optional[TFSignal] = None
    bounce_signal: Optional[TFSignal] = None  # SPLIT: контртренд-отскок (SCALP)
    rejected_signals: List[TFSignal] = field(default_factory=list)
    reason: str = ""
    conflict_type: str = ""   # "duplicate", "contradiction", "cascade", "clean", "bounce_split"


class MultiTFResolver:
    """
    Собирает сигналы со всех entry TF и разрешает конфликты
    перед отправкой в _broadcast_intelligence_alert.

    SPLIT-режим (ARCH-15): при включённом bounce_mode, контртренд на младшем ТФ
    не убивается, а проходит как SCALP-сделка параллельно с трендовой SWING-сделкой.
    """

    def __init__(self, config=None, bounce_detector=None):
        self.config = config or {}
        self.bounce_detector = bounce_detector
        # Окно дедупликации: если сигналы по одному символу пришли
        # в пределах этого окна — считаем их одним move
        self._dedup_window_sec = self._get_cfg("multi_tf.dedup_window_sec", 300)  # 5 мин
        # Буфер: symbol → [TFSignal]
        self._buffer: Dict[str, List[TFSignal]] = {}
        # MTF Bias cache: symbol → {"direction": "LONG"/"SHORT", "strength": 0-100}
        # Заполняется из MTFContext для разрешения неопределённостей
        self._mtf_bias: Dict[str, Dict] = {}
        # Лог решений для диагностики
        self._last_decisions: List[ResolverDecision] = []

    def _get_cfg(self, key: str, default):
        if hasattr(self.config, 'get'):
            return self.config.get(key, default)
        return default

    # ------------------------------------------------------------------
    # Основные методы
    # ------------------------------------------------------------------

    def set_mtf_bias(self, symbol: str, direction: str, strength: float) -> None:
        """
        Передать MTF Bias (из MTFContext/MTFInterpreter) для символа.
        Используется при разрешении неопределённостей (равный TF приоритет).
        """
        self._mtf_bias[symbol] = {"direction": direction, "strength": strength}

    def add_signal(self, signal: TFSignal) -> None:
        """Добавить сигнал в буфер для последующего resolve."""
        sym = signal.symbol
        if sym not in self._buffer:
            self._buffer[sym] = []
        # Очищаем старые сигналы за пределами окна
        cutoff = datetime.now() - timedelta(seconds=self._dedup_window_sec)
        self._buffer[sym] = [
            s for s in self._buffer[sym] if s.timestamp > cutoff
        ]
        self._buffer[sym].append(signal)

    def resolve(self, symbol: str) -> ResolverDecision:
        """
        Разрешить конфликты для символа.
        Вызывается после добавления нового сигнала.
        """
        signals = self._buffer.get(symbol, [])
        if not signals:
            return ResolverDecision(symbol=symbol, action="REJECT", reason="no_signals")

        # Один сигнал → без конфликтов
        if len(signals) == 1:
            return ResolverDecision(
                symbol=symbol,
                action="ACCEPT",
                chosen_signal=signals[0],
                conflict_type="clean",
                reason="единственный сигнал",
            )

        # Группируем по направлению
        longs = [s for s in signals if s.direction == "LONG"]
        shorts = [s for s in signals if s.direction == "SHORT"]

        # --- CASE 1: Все в одном направлении → ДУБЛЬ → берём лучший ---
        if longs and not shorts:
            return self._resolve_same_direction(symbol, longs)
        if shorts and not longs:
            return self._resolve_same_direction(symbol, shorts)

        # --- CASE 2: Противоречие → старший ТФ побеждает ---
        return self._resolve_contradiction(symbol, longs, shorts)

    def resolve_and_clear(self, symbol: str) -> ResolverDecision:
        """Resolve + очистить буфер для символа."""
        decision = self.resolve(symbol)
        self._buffer.pop(symbol, None)
        # Сохраняем для диагностики (последние 50)
        self._last_decisions.append(decision)
        if len(self._last_decisions) > 50:
            self._last_decisions = self._last_decisions[-50:]
        return decision

    def clear(self, symbol: str = None):
        """Очистить буфер."""
        if symbol:
            self._buffer.pop(symbol, None)
        else:
            self._buffer.clear()

    # ------------------------------------------------------------------
    # Внутренние стратегии
    # ------------------------------------------------------------------

    def _resolve_same_direction(self, symbol: str, signals: List[TFSignal]) -> ResolverDecision:
        """
        Все сигналы в одном направлении → берём лучший.
        Приоритет: старший ТФ > лучший R:R > большая сила.
        """
        # Сортируем: приоритет ТФ (desc), потом R:R (desc), потом strength (desc)
        ranked = sorted(
            signals,
            key=lambda s: (s.tf_priority, s.rr_ratio, s.strength),
            reverse=True,
        )
        best = ranked[0]
        rejected = ranked[1:]

        # Если старший ТФ подтверждает младший — UPGRADE (бонус к confidence)
        tfs_involved = sorted(set(s.timeframe for s in signals))
        if len(tfs_involved) > 1:
            reason = f"дубль на {', '.join(tfs_involved)} → выбран {best.timeframe} (старший)"
            action = "UPGRADE"  # Совпадение на нескольких ТФ = сильнее
        else:
            reason = f"дубль на {best.timeframe}"
            action = "ACCEPT"

        return ResolverDecision(
            symbol=symbol,
            action=action,
            chosen_signal=best,
            rejected_signals=rejected,
            conflict_type="duplicate",
            reason=reason,
        )

    def _resolve_contradiction(
        self, symbol: str,
        longs: List[TFSignal],
        shorts: List[TFSignal],
    ) -> ResolverDecision:
        """
        LONG vs SHORT:
        1. Разные ТФ + bounce_mode → SPLIT (тренд + отскок)
        2. Разные ТФ без bounce → старший побеждает
        3. Одинаковый приоритет → MTF Bias арбитраж или REJECT
        """
        best_long = max(longs, key=lambda s: (s.tf_priority, s.strength))
        best_short = max(shorts, key=lambda s: (s.tf_priority, s.strength))

        # Определяем кто старший, кто младший
        if best_long.tf_priority > best_short.tf_priority:
            senior, junior = best_long, best_short
        elif best_short.tf_priority > best_long.tf_priority:
            senior, junior = best_short, best_long
        else:
            senior, junior = None, None  # Одинаковый приоритет

        # === SPLIT: bounce mode — младший контртренд = отскок ===
        if senior and junior and self.bounce_detector:
            bounce = self._try_detect_bounce(symbol, senior, junior)
            if bounce:
                all_others = [s for s in longs + shorts if s is not senior and s is not junior]
                return ResolverDecision(
                    symbol=symbol,
                    action="SPLIT",
                    chosen_signal=senior,       # SWING: тренд
                    bounce_signal=junior,        # SCALP: отскок
                    rejected_signals=all_others,
                    conflict_type="bounce_split",
                    reason=(f"SPLIT: тренд {senior.direction} на {senior.timeframe} + "
                            f"отскок {junior.direction} на {junior.timeframe} "
                            f"(bounce #{bounce.bounce_number}, strength={bounce.strength:.0f})"),
                )

        # === Обычная логика: старший побеждает ===
        if best_long.tf_priority > best_short.tf_priority:
            winner = best_long
            losers = shorts + [s for s in longs if s is not best_long]
            reason = (f"противоречие: LONG ({best_long.timeframe}) vs "
                      f"SHORT ({best_short.timeframe}) → LONG побеждает (старший ТФ)")
        elif best_short.tf_priority > best_long.tf_priority:
            winner = best_short
            losers = longs + [s for s in shorts if s is not best_short]
            reason = (f"противоречие: SHORT ({best_short.timeframe}) vs "
                      f"LONG ({best_long.timeframe}) → SHORT побеждает (старший ТФ)")
        else:
            # Одинаковый приоритет → попробуем MTF Bias как арбитр
            bias = self._mtf_bias.get(symbol)
            if bias and bias["strength"] >= 60:
                bias_dir = bias["direction"]
                if bias_dir == "LONG":
                    winner = best_long
                    losers = shorts + [s for s in longs if s is not best_long]
                    reason = (f"противоречие на {best_long.timeframe} → "
                              f"MTF Bias LONG ({bias['strength']:.0f}%) разрешает в пользу LONG")
                elif bias_dir == "SHORT":
                    winner = best_short
                    losers = longs + [s for s in shorts if s is not best_short]
                    reason = (f"противоречие на {best_short.timeframe} → "
                              f"MTF Bias SHORT ({bias['strength']:.0f}%) разрешает в пользу SHORT")
                else:
                    # Bias NEUTRAL → всё ещё неопределённость
                    logger.warning(
                        "[%s] Противоречие LONG vs SHORT на %s, MTF Bias NEUTRAL — отклонено",
                        symbol, best_long.timeframe,
                    )
                    return ResolverDecision(
                        symbol=symbol, action="REJECT",
                        rejected_signals=longs + shorts,
                        conflict_type="contradiction",
                        reason=f"противоречие на {best_long.timeframe}, MTF Bias нейтральный",
                    )
                logger.info(
                    "[%s] Resolver: MTF Bias %s (%s%%) разрешает противоречие на %s",
                    symbol, bias_dir, bias["strength"], best_long.timeframe,
                )
                return ResolverDecision(
                    symbol=symbol, action="ACCEPT",
                    chosen_signal=winner, rejected_signals=losers,
                    conflict_type="contradiction_bias_resolved",
                    reason=reason,
                )
            # Нет MTF Bias или слабый → неопределённость, отклоняем
            logger.warning(
                "[%s] Противоречие LONG vs SHORT на одном ТФ %s — отклонено",
                symbol, best_long.timeframe,
            )
            return ResolverDecision(
                symbol=symbol,
                action="REJECT",
                rejected_signals=longs + shorts,
                conflict_type="contradiction",
                reason=f"противоречие LONG vs SHORT на {best_long.timeframe} — неопределённость",
            )

        logger.info(
            "[%s] Resolver: %s — %s побеждает (%s vs %s)",
            symbol, "contradiction", winner.direction,
            winner.timeframe, (best_short if winner is best_long else best_long).timeframe,
        )
        return ResolverDecision(
            symbol=symbol,
            action="ACCEPT",
            chosen_signal=winner,
            rejected_signals=losers,
            conflict_type="contradiction",
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Bounce detection bridge
    # ------------------------------------------------------------------

    def _try_detect_bounce(
        self, symbol: str, senior: TFSignal, junior: TFSignal,
    ) -> 'Optional[object]':
        """Пробуем определить отскок через BounceDetector."""
        if not self.bounce_detector or not self.bounce_detector.enabled:
            return None
        try:
            # Извлекаем WT-информацию из raw_signals или signal data
            # В scan_loop мы тегируем sig.timeframe — здесь используем его
            junior_wt_zone = getattr(junior, '_wt_zone', 'N')
            junior_wt_cross = getattr(junior, '_wt_cross', False)
            has_fvg = getattr(junior, '_has_fvg', False)

            return self.bounce_detector.detect_bounce(
                symbol=symbol,
                junior_tf=junior.timeframe,
                junior_direction=junior.direction,
                junior_wt_zone=junior_wt_zone,
                junior_wt_cross=junior_wt_cross,
                senior_tf=senior.timeframe,
                senior_direction=senior.direction,
                senior_trend_strength=senior.strength,
                has_fvg=has_fvg,
            )
        except Exception:
            logger.debug("[%s] Bounce detection error", symbol, exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Диагностика
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict:
        """Статистика решений для TG-отчёта."""
        if not self._last_decisions:
            return {"total": 0}
        total = len(self._last_decisions)
        by_type = {}
        by_action = {}
        for d in self._last_decisions:
            by_type[d.conflict_type] = by_type.get(d.conflict_type, 0) + 1
            by_action[d.action] = by_action.get(d.action, 0) + 1
        return {
            "total": total,
            "by_type": by_type,
            "by_action": by_action,
        }


def validate_multi_tf_config(entry_tfs: List[str]) -> Tuple[bool, str]:
    """
    Валидация конфига мульти-ТФ на старте.
    Возвращает (ok, message).
    """
    if not entry_tfs:
        return False, "entry_timeframe пуст"

    unknown = [tf for tf in entry_tfs if tf not in TF_PRIORITY]
    if unknown:
        return False, f"Неизвестные ТФ: {unknown}"

    # Проверяем что ТФ отсортированы от младшего к старшему
    priorities = [TF_PRIORITY[tf] for tf in entry_tfs]
    if priorities != sorted(priorities):
        return False, f"ТФ должны быть от младшего к старшему: {entry_tfs}"

    # Предупреждение о rate limits
    if len(entry_tfs) > 3:
        return False, f"Больше 3 entry TF ({len(entry_tfs)}) → перегрузка API"

    # Предупреждение о слишком близких ТФ
    if "1m" in entry_tfs and "3m" in entry_tfs:
        return False, "1m и 3m слишком близки — будут дубли"
    if "30m" in entry_tfs and "45m" in entry_tfs:
        return False, "30m и 45m слишком близки — будут дубли"

    return True, f"OK: {entry_tfs}"
