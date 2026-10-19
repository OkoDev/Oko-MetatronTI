"""
MessageComposer — автоматическая генерация интерпретации торговых сигналов.

Приоритет источников для секции "Что произошло":
  1. signal.interpretation  — если детектор уже заполнил поле
  2. Рой (llm_ask, роль chat_fast) — AI генерирует объяснение типа сигнала, с кешем
  3. Static fallback dict   — для обратной совместимости

Кеш in-memory: ключ (signal_type, direction) → текст.
19.10: БЫЛ Claude haiku (пакет anthropic не установлен → AI не вызывался ни разу, работал словарь).
Переведён на бесплатный рой. Ключ кеша БЕЗ description: замер показал ~7800 вызовов/сутки с description
(в нём числа — sweep_level/funding → кеш не работал) против ≤28 без него (14 типов × 2 направления).
Поэтому объяснение — общее для типа сигнала (как словарь, но генерируется и для новых типов).
"""
import asyncio
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Static fallback ───────────────────────────────────────────────────────────
_STATIC = {
    "trend_signal": {
        "LONG": "EMA-тренд направлен вверх — цена откатила и возобновила рост",
        "SHORT": "EMA-тренд направлен вниз — цена отскочила и возобновила падение",
    },
    "wt_signal": {
        "LONG": "WaveTrend вышел из зоны перепроданности — покупатели перехватывают инициативу",
        "SHORT": "WaveTrend вышел из зоны перекупленности — продавцы перехватывают инициативу",
    },
    "anomaly": {
        "LONG": "Аномальный объём при росте цены — крупные игроки покупают",
        "SHORT": "Аномальный объём при падении цены — крупные игроки продают",
    },
    "divergence": {
        "LONG": "Дивергенция: цена падает, но индикатор растёт — давление продавцов слабеет",
        "SHORT": "Дивергенция: цена растёт, но индикатор падает — давление покупателей слабеет",
    },
    "mtf_divergence": {
        "LONG": "Скрытая дивергенция (1h) + регулярная (15m) — тренд вверх, точная точка входа",
        "SHORT": "Скрытая дивергенция (1h) + регулярная (15m) — тренд вниз, точная точка входа",
    },
    "pivot_reversal": {
        "LONG": "Цена отскакивает от уровня поддержки (пивот) — разворот вверх",
        "SHORT": "Цена отскакивает от уровня сопротивления (пивот) — разворот вниз",
    },
    "mtf_alert": {
        "LONG": "Разворот подтверждён на 4 таймфреймах одновременно — сильный сигнал",
        "SHORT": "Разворот подтверждён на 4 таймфреймах одновременно — сильный сигнал",
    },
}

_SYSTEM_PROMPT = (
    "Ты — помощник трейдера в торговом боте. Объясняй торговые сигналы "
    "простым языком для начинающих. Одно предложение, максимум 15 слов. "
    "Без технического жаргона. На русском языке."
)


class MessageComposer:
    """
    Генерирует интерпретацию сигнала.
    Singleton — инициализируется один раз, переиспользуется через get_composer().
    """

    def __init__(self):
        self._cache: dict[tuple, str] = {}
        self._client = None
        self._ai_available = False
        self._init_ai()

    def _init_ai(self):
        # 19.10: рой (llm_ask.ask_role) вместо прямого anthropic. Живость кандидата роли не
        # проверяем при старте (это стоило бы вызова) — ask_role сам переберёт живых, а при
        # полном отказе interpret() упадёт на статический словарь. Проверяем лишь импорт модуля.
        try:
            import sys
            from pathlib import Path
            _tools = str(Path(__file__).resolve().parents[2] / "tools")
            if _tools not in sys.path:
                sys.path.insert(0, _tools)
            from llm_ask import ask_role, load_env  # noqa: F401
            load_env()                               # ключи в os.environ (ask_role → has_key)
            self._ai_available = True
            logger.info("MessageComposer: AI-интерпретация через рой (роль chat_fast)")
        except Exception as e:                              # noqa: BLE001
            logger.warning("MessageComposer: llm_ask недоступен (%s) — работает статический словарь", e)

    async def interpret(
        self,
        signal_type: str,
        direction: str,
        description: str = "",
        signal_interpretation: str = "",
    ) -> str:
        """
        Возвращает текст интерпретации для секции «Что произошло».

        Порядок:
          1. Поле interpretation из самого сигнала (заполнено детектором)
          2. Claude haiku (если доступен) — с кешем
          3. Static fallback dict
        """
        # 1. Детектор уже объяснил
        if signal_interpretation:
            return signal_interpretation

        # 2. AI с кешем. Ключ БЕЗ description (см. docstring): объяснение общее для типа сигнала.
        if self._ai_available:
            cache_key = (signal_type, direction)
            if cache_key in self._cache:
                return self._cache[cache_key]
            result = await self._ask_ai(signal_type, direction)
            if result:
                self._cache[cache_key] = result
                return result

        # 3. Static fallback
        return _STATIC.get(signal_type, {}).get(direction, "")

    async def _ask_ai(self, signal_type: str, direction: str) -> str:
        dir_ru = "LONG (рост)" if direction == "LONG" else "SHORT (падение)"
        user_msg = (
            f"{_SYSTEM_PROMPT}\n\n"
            f"Сигнал: {signal_type}, направление: {dir_ru}. "
            "Объясни что произошло на рынке одним предложением."
        )
        try:
            from llm_ask import ask_role
            # ask_role синхронный → в поток, чтобы не блокировать событийный цикл бота
            text, _who = await asyncio.to_thread(ask_role, "chat_fast", user_msg, 120)
            text = (text or "").strip()
            logger.debug("MessageComposer AI [%s/%s]: %s", signal_type, direction, text)
            return text
        except Exception as e:
            logger.debug("MessageComposer AI error: %s", e)
            return ""

    def cache_stats(self) -> dict:
        return {"cached": len(self._cache), "ai_available": self._ai_available}


# ─── Singleton ─────────────────────────────────────────────────────────────────
_composer: Optional[MessageComposer] = None


def get_composer() -> MessageComposer:
    global _composer
    if _composer is None:
        _composer = MessageComposer()
    return _composer
