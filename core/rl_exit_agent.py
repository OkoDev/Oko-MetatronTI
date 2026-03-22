"""
DEV-16: RL Exit Strategy — скелет / stub.

Концепция: RL-агент решает HOLD / TIGHTEN_TSL / CLOSE_NOW на основе
текущего состояния сделки (price, tsl_line, wt_spread, regime, R_current, max_R).

Reward = captured_R_pct (0–100%): насколько хорошо захватили доступный потенциал.

⚠️ ЗАБЛОКИРОВАНО — требует 3000+ закрытых сделок с MFE-данными.
   Текущее состояние: ~2375 сделок, из них с max_R_possible — меньше.
   Активация: когда PerformanceEngine.mfe_ready_count() >= 3000.

Алгоритм: PPO (stable-baselines3) — стабилен на финансовых задачах.
Зависимости: pip install stable-baselines3 gymnasium

Архитектура (для ARCH):
  - RLExitEnv(gymnasium.Env) — среда на исторических данных из БД
  - RLExitAgent — обёртка: train() + predict(state) + save/load
  - Интеграция в check_open_trades_with_tsl: вместо фиксированного TSL порога
    вызвать agent.predict(current_state) → action

TODO (для ARCH когда данных >= 3000):
  1. Реализовать RLExitEnv.step() — replay сделки свечу за свечой
  2. Подобрать гиперпараметры PPO (learning_rate, n_steps, clip_range)
  3. Добавить reward shaping: штраф за CLOSE_NOW в прибыльный момент
  4. Walk-forward validation: train на первых 70%, test на последних 30%
"""
import logging
import sqlite3
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# Минимум MFE-сделок для обучения
MIN_MFE_TRADES = 3000

# Действия агента
ACTION_HOLD = 0
ACTION_TIGHTEN_TSL = 1
ACTION_CLOSE_NOW = 2
ACTION_NAMES = {ACTION_HOLD: "HOLD", ACTION_TIGHTEN_TSL: "TIGHTEN_TSL", ACTION_CLOSE_NOW: "CLOSE_NOW"}


def mfe_ready_count(db_path: str) -> int:
    """Возвращает количество закрытых сделок с MFE-данными (max_R_possible IS NOT NULL).

    Используется для проверки готовности данных перед обучением RL.
    """
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM simulated_trades "
                "WHERE status IN ('TP','SL','TSL') AND max_R_possible IS NOT NULL"
            ).fetchone()
        return row[0] if row else 0
    except Exception as e:
        logger.debug("mfe_ready_count: %s", e)
        return 0


def is_rl_ready(db_path: str) -> bool:
    """True если данных достаточно для обучения RL-агента."""
    n = mfe_ready_count(db_path)
    if n < MIN_MFE_TRADES:
        logger.info("RLExitAgent: недостаточно данных (%d/%d MFE-сделок)", n, MIN_MFE_TRADES)
        return False
    return True


class RLExitAgent:
    """
    Stub RL-агента выхода из сделки.

    Пока данных < MIN_MFE_TRADES — возвращает ACTION_HOLD (не мешает текущей логике).
    Когда данных достаточно — ARCH реализует train() / fit() через PPO.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._model = None
        self._trained = False
        self._n_samples = 0

    # ------------------------------------------------------------------
    def is_ready(self) -> bool:
        return is_rl_ready(self.db_path)

    def train(self) -> bool:
        """
        Обучает RL-агента на исторических MFE-данных.

        STUB — реализовать после накопления 3000+ MFE-сделок.

        Шаги реализации (ARCH):
        1. Загрузить закрытые сделки с max_price/min_price/max_R_possible из БД
        2. Создать RLExitEnv(gymnasium.Env) — симулировать сделку свечу за свечой
        3. Обучить PPO через stable_baselines3.PPO
        4. Сохранить модель в rl_exit_model.zip рядом с БД
        5. Установить self._trained = True
        """
        if not self.is_ready():
            return False

        # TODO: реализовать когда данных >= MIN_MFE_TRADES
        # from stable_baselines3 import PPO
        # env = RLExitEnv(self._load_mfe_trades())
        # model = PPO("MlpPolicy", env, learning_rate=3e-4, n_steps=2048)
        # model.learn(total_timesteps=500_000)
        # model.save(self._model_path())
        # self._model = model
        # self._trained = True
        logger.info("RLExitAgent.train: STUB — реализовать после накопления %d MFE-сделок", MIN_MFE_TRADES)
        return False

    def predict(self, state: Dict[str, Any]) -> int:
        """
        Предсказывает действие для текущего состояния сделки.

        Args:
            state: {
                "current_r": float,      # текущий R-multiple
                "max_r_seen": float,     # максимальный R за время жизни
                "wt_spread": float,      # WT1 - WT2 (индикатор разворота)
                "regime": str,           # TREND_UP / RANGE / HIGH_VOL
                "bars_since_entry": int, # сколько свечей прошло
                "tsl_distance_pct": float, # расстояние до TSL в %
            }

        Returns:
            ACTION_HOLD (0) | ACTION_TIGHTEN_TSL (1) | ACTION_CLOSE_NOW (2)
        """
        if not self._trained or self._model is None:
            # Stub: всегда HOLD — не мешает текущей TSL логике
            return ACTION_HOLD

        # TODO: после обучения
        # obs = self._state_to_obs(state)
        # action, _ = self._model.predict(obs, deterministic=True)
        # return int(action)
        return ACTION_HOLD

    # ------------------------------------------------------------------
    def _load_mfe_trades(self) -> List[Dict]:
        """Загружает MFE-сделки для обучения (ARCH: использовать в train())."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT id, direction, signal_type, regime,
                       entry_price, stop_loss, take_profit,
                       max_price, min_price, max_R_possible, captured_R_pct,
                       R_multiple, duration_minutes, features_json
                FROM simulated_trades
                WHERE status IN ('TP','SL','TSL')
                  AND max_R_possible IS NOT NULL
                ORDER BY closed_at
            """).fetchall()
        return [dict(r) for r in rows]

    def _model_path(self) -> str:
        import os
        return os.path.join(os.path.dirname(self.db_path) or ".", "rl_exit_model.zip")

    def info(self) -> Dict[str, Any]:
        n = mfe_ready_count(self.db_path)
        return {
            "trained": self._trained,
            "n_samples": self._n_samples,
            "mfe_ready": n,
            "mfe_needed": MIN_MFE_TRADES,
            "ready_pct": round(n / MIN_MFE_TRADES * 100, 1),
        }
