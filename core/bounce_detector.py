"""
Bounce Detector (ARCH-15): Обнаружение коррекционных отскоков.

Сценарий:
  Старший ТФ: тренд SHORT (импульс)
  Младший ТФ: отскок LONG → WT в OS + кросс вверх
  → SCALP LONG: tight TSL, быстрый выход
  → Потом ищем SHORT для сопровождения основного движения

Принципы:
  - Отскок торгуется ТОЛЬКО при подтверждённом тренде на старшем ТФ
  - Вход: WT экстремальная зона (OS/OB) + WT кросс на младшем ТФ
  - FVG на младшем — бонус, не обязательно
  - Макс 2 отскока за импульс (волновая теория: волны 2 и 4)
  - Выход: TSL (без фиксированного TP)

Подключаемый модуль: включается/отключается через config.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class TradeMode(str, Enum):
    """Режим сделки — определяет стратегию управления."""
    SWING = "swing"     # По тренду старшего ТФ: широкий SL, каскадный TSL
    SCALP = "scalp"     # Контртренд-отскок на младшем ТФ: tight TSL, быстрый выход


@dataclass
class BounceSignal:
    """Сигнал коррекционного отскока."""
    symbol: str
    bounce_direction: str        # "LONG" / "SHORT" — направление отскока
    trend_direction: str         # "SHORT" / "LONG" — направление тренда (противоположное)
    entry_tf: str                # ТФ входа (младший)
    trend_tf: str                # ТФ тренда (старший)
    trade_mode: TradeMode = TradeMode.SCALP

    # Подтверждения
    wt_zone: str = ""            # "OS" / "OB" на младшем ТФ
    wt_cross: bool = False       # WT кросс на младшем ТФ
    has_fvg: bool = False        # FVG на младшем ТФ (бонус)
    trend_strength: float = 0.0  # Сила тренда на старшем ТФ (0-100)

    # Волновой счёт
    bounce_number: int = 1       # Какой по счёту отскок в этом импульсе (1 или 2)

    # Метрики
    strength: float = 0.0        # Итоговая сила сигнала отскока
    atr_multiplier: float = 1.0  # ATR × multiplier для TSL (tight)

    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def is_valid(self) -> bool:
        """Базовая валидность: обязательные условия."""
        return (
            self.wt_cross
            and self.wt_zone in ("OS", "OB")
            and self.trend_strength >= 50
            and self.bounce_number <= 2
        )


@dataclass
class ImpulseTracker:
    """Отслеживает импульс (тренд) на старшем ТФ и считает коррекции."""
    symbol: str
    direction: str            # "LONG" / "SHORT" — направление импульса
    started_at: datetime = field(default_factory=datetime.now)
    bounce_count: int = 0     # Сколько отскоков уже было (макс 2)
    last_bounce_at: Optional[datetime] = None


class BounceDetector:
    """
    Определяет, является ли контртренд-сигнал на младшем ТФ
    валидным коррекционным отскоком.
    """

    def __init__(self, config=None):
        self.config = config or {}
        self.enabled = self._get_cfg("trading.bounce_mode.enabled", False)
        self._max_bounces = self._get_cfg("trading.bounce_mode.max_bounces", 2)
        self._min_trend_strength = self._get_cfg("trading.bounce_mode.min_trend_strength", 50)
        self._bounce_cooldown_sec = self._get_cfg("trading.bounce_mode.cooldown_sec", 300)
        self._scalp_atr_mult = self._get_cfg("trading.bounce_mode.scalp_atr_multiplier", 1.0)
        # Импульс-трекер: symbol → ImpulseTracker
        self._impulses: Dict[str, ImpulseTracker] = {}

    def _get_cfg(self, key: str, default):
        if hasattr(self.config, 'get'):
            return self.config.get(key, default)
        return default

    def detect_bounce(
        self,
        symbol: str,
        junior_tf: str,
        junior_direction: str,
        junior_wt_zone: str,
        junior_wt_cross: bool,
        senior_tf: str,
        senior_direction: str,
        senior_trend_strength: float,
        has_fvg: bool = False,
    ) -> Optional[BounceSignal]:
        """
        Проверяет, является ли сигнал на младшем ТФ коррекционным отскоком.

        Args:
            junior_tf: ТФ младшего сигнала ("5m", "15m")
            junior_direction: направление сигнала на младшем ТФ ("LONG"/"SHORT")
            junior_wt_zone: зона WT на младшем ТФ ("OS"/"OB"/"N")
            junior_wt_cross: есть ли WT кросс на младшем ТФ
            senior_tf: ТФ старшего сигнала ("1h", "4h")
            senior_direction: направление тренда на старшем ТФ
            senior_trend_strength: сила тренда 0-100
            has_fvg: есть ли FVG на младшем ТФ

        Returns:
            BounceSignal если отскок валидный, None если нет
        """
        if not self.enabled:
            return None

        # Базовое условие: направления ПРОТИВОПОЛОЖНЫ
        if junior_direction == senior_direction:
            return None  # Не отскок, а подтверждение

        # Проверка: младший ТФ в экстремальной зоне
        expected_zone = "OS" if junior_direction == "LONG" else "OB"
        if junior_wt_zone != expected_zone:
            return None  # Не в экстреме → не отскок

        # WT кросс обязателен
        if not junior_wt_cross:
            return None

        # Тренд на старшем должен быть достаточно сильным
        if senior_trend_strength < self._min_trend_strength:
            return None

        # Волновой счёт: трекаем импульс
        impulse = self._get_or_create_impulse(symbol, senior_direction)
        if impulse.bounce_count >= self._max_bounces:
            logger.debug("[%s] Bounce: лимит %d отскоков за импульс достигнут",
                         symbol, self._max_bounces)
            return None

        # Cooldown: не чаще чем раз в N секунд
        if impulse.last_bounce_at:
            elapsed = (datetime.now() - impulse.last_bounce_at).total_seconds()
            if elapsed < self._bounce_cooldown_sec:
                logger.debug("[%s] Bounce: cooldown %.0fs < %ds",
                             symbol, elapsed, self._bounce_cooldown_sec)
                return None

        # Считаем силу отскока
        strength = self._calc_bounce_strength(
            senior_trend_strength, junior_wt_zone, junior_wt_cross, has_fvg,
        )

        bounce_number = impulse.bounce_count + 1
        sig = BounceSignal(
            symbol=symbol,
            bounce_direction=junior_direction,
            trend_direction=senior_direction,
            entry_tf=junior_tf,
            trend_tf=senior_tf,
            wt_zone=junior_wt_zone,
            wt_cross=junior_wt_cross,
            has_fvg=has_fvg,
            trend_strength=senior_trend_strength,
            bounce_number=bounce_number,
            strength=strength,
            atr_multiplier=self._scalp_atr_mult,
        )

        if sig.is_valid:
            # Обновляем трекер
            impulse.bounce_count = bounce_number
            impulse.last_bounce_at = datetime.now()
            logger.info(
                "[%s] Bounce #%d: %s отскок на %s (тренд %s на %s, strength=%.0f)",
                symbol, bounce_number, junior_direction, junior_tf,
                senior_direction, senior_tf, strength,
            )
            return sig

        return None

    def reset_impulse(self, symbol: str) -> None:
        """Сброс импульс-трекера при смене тренда на старшем ТФ."""
        if symbol in self._impulses:
            old = self._impulses[symbol]
            logger.info("[%s] Impulse reset: был %s с %d bounce(s)",
                        symbol, old.direction, old.bounce_count)
            del self._impulses[symbol]

    def notify_trend_change(self, symbol: str, new_direction: str) -> None:
        """Уведомление о смене тренда — сбрасывает счётчик."""
        existing = self._impulses.get(symbol)
        if existing and existing.direction != new_direction:
            self.reset_impulse(symbol)

    def get_impulse_info(self, symbol: str) -> Optional[Dict]:
        """Информация об импульсе для диагностики."""
        imp = self._impulses.get(symbol)
        if not imp:
            return None
        return {
            "direction": imp.direction,
            "bounce_count": imp.bounce_count,
            "started_at": imp.started_at.isoformat(),
            "last_bounce_at": imp.last_bounce_at.isoformat() if imp.last_bounce_at else None,
            "remaining_bounces": self._max_bounces - imp.bounce_count,
        }

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _get_or_create_impulse(self, symbol: str, trend_direction: str) -> ImpulseTracker:
        """Получить или создать трекер импульса."""
        existing = self._impulses.get(symbol)
        if existing and existing.direction == trend_direction:
            return existing
        # Новый импульс (или смена направления)
        tracker = ImpulseTracker(
            symbol=symbol,
            direction=trend_direction,
        )
        self._impulses[symbol] = tracker
        return tracker

    def _calc_bounce_strength(
        self,
        trend_strength: float,
        wt_zone: str,
        wt_cross: bool,
        has_fvg: bool,
    ) -> float:
        """
        Сила отскока: 0-100.
        Чем сильнее тренд + чем глубже экстрем + FVG = сильнее отскок.
        """
        # Базовая сила: пропорциональна силе тренда (сильный тренд → сильный отскок)
        base = min(trend_strength * 0.6, 60)  # макс 60 от тренда

        # Бонус за экстремальную зону
        zone_bonus = 15 if wt_zone in ("OS", "OB") else 0

        # Бонус за WT кросс (обязателен, но даём очки)
        cross_bonus = 10 if wt_cross else 0

        # Бонус за FVG (структурное подтверждение)
        fvg_bonus = 15 if has_fvg else 0

        return min(base + zone_bonus + cross_bonus + fvg_bonus, 100)

    # ------------------------------------------------------------------
    # Статистика
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict:
        """Статистика для мониторинга."""
        active = len(self._impulses)
        total_bounces = sum(imp.bounce_count for imp in self._impulses.values())
        return {
            "enabled": self.enabled,
            "active_impulses": active,
            "total_bounces_tracked": total_bounces,
            "impulses": {
                sym: {
                    "direction": imp.direction,
                    "bounces": imp.bounce_count,
                    "max": self._max_bounces,
                }
                for sym, imp in self._impulses.items()
            },
        }
