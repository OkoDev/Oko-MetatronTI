"""
DEV-156: Circuit Breaker — повышает min_strength когда rolling WR < 15% за 50 сделок.

Singleton. Проверяется каждые 15 мин через _cb_check_loop() в bot.
Влияет на is_actionable() в bot/monitoring.py через cb.strength_floor_bonus.
"""
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """
    Singleton circuit breaker для торговых сигналов.

    Алгоритм:
    1. check(db_path) — считает WR за последние N закрытых сделок
    2. WR < wr_trigger_pct → активируется: strength_floor_bonus = +bonus
    3. Держится cooldown_minutes (30 мин), сбрасывается если WR вернулся > wr_reset_pct
    """

    _instance: Optional["CircuitBreaker"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.strength_floor_bonus: int = 0      # 0 в норме, +10 при активации
        self._active_since: Optional[datetime] = None
        self._last_check: Optional[datetime] = None
        self._last_wr: Optional[float] = None

    # ── Конфиг-дефолты (переопределяются через config.yaml) ──────────────
    @staticmethod
    def _get_cfg():
        try:
            from core.config_loader import config as _cfg
            cb = (_cfg.get("trading.circuit_breaker") or {}) if _cfg else {}
            return {
                "lookback_trades": int(cb.get("lookback_trades", 50)),
                "wr_trigger_pct": float(cb.get("wr_trigger_pct", 15.0)),
                "wr_reset_pct":   float(cb.get("wr_reset_pct", 20.0)),
                "cooldown_minutes": int(cb.get("cooldown_minutes", 30)),
                "strength_bonus":  int(cb.get("strength_bonus", 10)),
                "enabled": bool(cb.get("enabled", True)),
            }
        except Exception:
            return {
                "lookback_trades": 50,
                "wr_trigger_pct": 15.0,
                "wr_reset_pct": 20.0,
                "cooldown_minutes": 30,
                "strength_bonus": 10,
                "enabled": True,
            }

    def check(self, db_path: str = "subscriptions.db") -> None:
        """
        Обновляет состояние Circuit Breaker по текущему WR.
        Вызывается каждые 15 мин из _cb_check_loop() в bot.
        """
        cfg = self._get_cfg()
        if not cfg["enabled"]:
            if self.strength_floor_bonus != 0:
                self.strength_floor_bonus = 0
                self._active_since = None
            return

        now = datetime.now(timezone.utc)
        self._last_check = now

        # Считаем WR за последние N сделок
        try:
            with sqlite3.connect(db_path, timeout=30) as conn:
                conn.execute("PRAGMA busy_timeout=10000")  # DEV-148
                row = conn.execute(
                    """
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN status IN ('TP', 'TSL') THEN 1 ELSE 0 END) as wins
                    FROM (
                        SELECT status FROM simulated_trades
                        WHERE status IN ('TP', 'TSL', 'SL', 'EXPIRED')
                        ORDER BY closed_at DESC
                        LIMIT ?
                    )
                    """,
                    (cfg["lookback_trades"],),
                ).fetchone()
        except Exception as e:
            logger.warning("[CircuitBreaker] DB error (check пропущен): %s", e)
            return

        if not row or not row[0]:
            return

        total, wins = int(row[0]), int(row[1] or 0)
        if total < 5:
            # DEV-163: WR=0% fast-trigger — если 3+ сделок и ни одной победы
            if total >= 3 and wins == 0 and cfg["enabled"]:
                wr_pct = 0.0
                self._last_wr = wr_pct
                if self._active_since is None:
                    logger.warning(
                        "[CircuitBreaker] ON (WR=0%% fast-trigger) — n=%d сделок, все убыточные, +%d к min_strength",
                        total, cfg["strength_bonus"],
                    )
                    self._active_since = datetime.now(timezone.utc)
                    self.strength_floor_bonus = cfg["strength_bonus"]
            return

        wr_pct = wins / total * 100
        self._last_wr = wr_pct

        # Сброс если cooldown истёк И WR вернулся
        if self._active_since is not None:
            elapsed = (now - self._active_since).total_seconds() / 60
            if elapsed >= cfg["cooldown_minutes"] and wr_pct >= cfg["wr_reset_pct"]:
                logger.info(
                    "[CircuitBreaker] OFF — WR=%.1f%% >= %.0f%%, elapsed=%.0f мин",
                    wr_pct, cfg["wr_reset_pct"], elapsed,
                )
                self.strength_floor_bonus = 0
                self._active_since = None
                return

        # Активация если WR слишком низкий
        if wr_pct < cfg["wr_trigger_pct"]:
            if self._active_since is None:
                logger.warning(
                    "[CircuitBreaker] ON — WR=%.1f%% < %.0f%%, порог +%d на %d мин (n=%d сделок)",
                    wr_pct, cfg["wr_trigger_pct"], cfg["strength_bonus"],
                    cfg["cooldown_minutes"], total,
                )
                self._active_since = now
                self.strength_floor_bonus = cfg["strength_bonus"]
            else:
                # Уже активен — обновляем бонус на случай если config изменился
                if self.strength_floor_bonus != cfg["strength_bonus"]:
                    self.strength_floor_bonus = cfg["strength_bonus"]
                elapsed = (now - self._active_since).total_seconds() / 60
                logger.info(
                    "[CircuitBreaker] ACTIVE — WR=%.1f%% (n=%d), active %.0f мин, +%d к min_strength",
                    wr_pct, total, elapsed, self.strength_floor_bonus,
                )
        else:
            # WR в норме, CB не активен — ничего не делать
            if self._active_since is None:
                logger.info("[CircuitBreaker] OK — WR=%.1f%% (n=%d)", wr_pct, total)

    def status_text(self) -> str:
        """Краткий статус для логов/диагностики."""
        if self._active_since is None:
            return f"OFF (WR={self._last_wr:.1f}%)" if self._last_wr is not None else "OFF (no data)"
        elapsed = (datetime.now(timezone.utc) - self._active_since).total_seconds() / 60
        return (f"ON +{self.strength_floor_bonus} (WR={self._last_wr:.1f}%, "
                f"active {elapsed:.0f} мин)")
