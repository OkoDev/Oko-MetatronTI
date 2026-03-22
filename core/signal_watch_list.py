"""
SignalWatchList — in-memory наблюдение за WATCH-сигналами.

Принцип: если signal.action == "WATCH" (сигнал слабоват для входа, но идея хорошая) →
бот добавляет пару в список наблюдения (TTL 4h) и при каждом новом скане проверяет:
  - Улучшились ли условия? (score вырос, новая дивергенция, MTF сдвинулся)  → эскалировать в BUY/SELL
  - Пробит ли пивот-уровень?  → идея провалилась, удалить
  - MTF повернул против направления? → идея устарела, удалить
  - TTL истёк? → удалить

DEV-22.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

WL_TTL_HOURS: int = 4
# Минимальный прирост score для эскалации
WL_ESCALATE_SCORE_DELTA: int = 5


@dataclass
class WatchEntry:
    symbol: str
    direction: str          # "LONG" | "SHORT"
    score: float
    reason: str             # почему WATCH (напр. "MTF NEUTRAL 57%")
    pivot_key: str          # "1D_S3", "1W_S1", "" если нет
    pivot_level: float      # абсолютный уровень для проверки пробоя (0 если нет)
    div_count: int          # кол-во дивергенций в момент добавления
    added_at: datetime
    expires_at: datetime


class SignalWatchList:
    """
    In-memory список наблюдения WATCH-сигналов.

    Жизненный цикл записи:
        add() → check_escalation() или check_breach() или check_against_direction()
        или cleanup_expired() → remove()

    Thread-safety: asyncio-safe (нет blocking IO), concurrent задачи не конкурируют.
    """

    def __init__(self, ttl_hours: int = WL_TTL_HOURS):
        self._entries: Dict[str, WatchEntry] = {}
        self._ttl_hours = ttl_hours

    # ── Публичный API ──────────────────────────────────────────────────────────

    def add(
        self,
        symbol: str,
        direction: str,
        score: float,
        reason: str,
        pivot_key: str = "",
        pivot_level: float = 0.0,
        div_count: int = 0,
    ) -> None:
        """Добавить или обновить запись в WL."""
        now = datetime.now(tz=timezone.utc)
        self._entries[symbol] = WatchEntry(
            symbol=symbol,
            direction=direction,
            score=score,
            reason=reason,
            pivot_key=pivot_key,
            pivot_level=pivot_level,
            div_count=div_count,
            added_at=now,
            expires_at=now + timedelta(hours=self._ttl_hours),
        )
        logger.info(
            "[WL] ✚ %s %s score=%.0f pivot=%s=%.4f reason='%s' TTL=%dh",
            symbol, direction, score, pivot_key or "none", pivot_level,
            reason, self._ttl_hours,
        )

    def has(self, symbol: str) -> bool:
        return symbol in self._entries and not self._is_expired(symbol)

    def get(self, symbol: str) -> Optional[WatchEntry]:
        if not self.has(symbol):
            return None
        return self._entries.get(symbol)

    def remove(self, symbol: str, reason: str = "") -> None:
        if symbol in self._entries:
            del self._entries[symbol]
            logger.info("[WL] ✖ %s удалён: %s", symbol, reason)

    def check_escalation(
        self,
        symbol: str,
        new_score: float,
        new_action: str,
        mtf_direction: str,
        new_div_count: int = 0,
    ) -> bool:
        """
        Проверяет нужна ли эскалация WATCH → BUY/SELL.

        Триггеры:
          1. Score вырос на WL_ESCALATE_SCORE_DELTA или более
          2. Новая дивергенция (new_div_count > entry.div_count)
          3. MTF сдвинулся в сторону WATCH-направления (был NEUTRAL, стал совпадать)

        Returns True если нужна эскалация.
        """
        entry = self.get(symbol)
        if entry is None:
            return False

        # Триггер 1: score вырос
        if new_score >= entry.score + WL_ESCALATE_SCORE_DELTA:
            logger.info(
                "[WL] ⬆ %s эскалация: score %.0f → %.0f (+%.0f)",
                symbol, entry.score, new_score, new_score - entry.score,
            )
            return True

        # Триггер 2: новая дивергенция
        if new_div_count > entry.div_count:
            logger.info(
                "[WL] ⬆ %s эскалация: новая дивергенция (div_count %d → %d)",
                symbol, entry.div_count, new_div_count,
            )
            return True

        # Триггер 3: MTF совпал с направлением (раньше был нейтральным)
        if mtf_direction == entry.direction and "NEUTRAL" in entry.reason:
            logger.info(
                "[WL] ⬆ %s эскалация: MTF сдвинулся в %s (было: %s)",
                symbol, mtf_direction, entry.reason,
            )
            return True

        return False

    def check_breach(
        self,
        symbol: str,
        current_price: float,
        breach_pct: float = 1.0,
    ) -> bool:
        """
        Проверяет пробой пивот-уровня.

        breach_pct: процент отступа от уровня для подтверждения пробоя (default 1.0%).
        Returns True если уровень пробит → нужно удалить из WL.
        """
        entry = self.get(symbol)
        if entry is None or entry.pivot_level <= 0:
            return False

        threshold = entry.pivot_level * breach_pct / 100
        if entry.direction == "LONG" and current_price < entry.pivot_level - threshold:
            logger.info(
                "[WL] 🔴 %s пробой LONG pivot: price=%.6f < %.6f (пробой -%.1f%%)",
                symbol, current_price, entry.pivot_level, breach_pct,
            )
            return True
        if entry.direction == "SHORT" and current_price > entry.pivot_level + threshold:
            logger.info(
                "[WL] 🔴 %s пробой SHORT pivot: price=%.6f > %.6f (пробой +%.1f%%)",
                symbol, current_price, entry.pivot_level, breach_pct,
            )
            return True
        return False

    def check_against_direction(self, symbol: str, mtf_direction: str) -> bool:
        """
        Проверяет повернул ли MTF против направления WATCH.
        Returns True → нужно удалить из WL.
        """
        entry = self.get(symbol)
        if entry is None or not mtf_direction:
            return False
        opposite = "SHORT" if entry.direction == "LONG" else "LONG"
        if mtf_direction == opposite:
            logger.info(
                "[WL] ↩ %s MTF против: entry=%s, MTF=%s",
                symbol, entry.direction, mtf_direction,
            )
            return True
        return False

    def cleanup_expired(self) -> List[str]:
        """Удаляет истёкшие записи. Возвращает список удалённых символов."""
        now = datetime.now(tz=timezone.utc)
        expired = [sym for sym, e in list(self._entries.items()) if now > e.expires_at]
        for sym in expired:
            self.remove(sym, "TTL истёк")
        return expired

    def get_all(self) -> List[dict]:
        """Данные для команды /watchlist."""
        now = datetime.now(tz=timezone.utc)
        result = []
        for sym, e in list(self._entries.items()):
            if now > e.expires_at:
                continue
            ttl_left = e.expires_at - now
            result.append({
                "symbol": sym,
                "direction": e.direction,
                "score": e.score,
                "reason": e.reason,
                "pivot_key": e.pivot_key,
                "pivot_level": e.pivot_level,
                "div_count": e.div_count,
                "added_at": e.added_at,
                "ttl_minutes": int(ttl_left.total_seconds() / 60),
            })
        return sorted(result, key=lambda x: -x["score"])

    def __len__(self) -> int:
        now = datetime.now(tz=timezone.utc)
        return sum(1 for e in self._entries.values() if now <= e.expires_at)

    # ── Приватные ──────────────────────────────────────────────────────────────

    def _is_expired(self, symbol: str) -> bool:
        e = self._entries.get(symbol)
        if e is None:
            return True
        return datetime.now(tz=timezone.utc) > e.expires_at
