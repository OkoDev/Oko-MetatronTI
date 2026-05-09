"""
MessageComposer — автоматическая генерация интерпретации торговых сигналов.

Приоритет источников для секции "Что произошло":
  1. signal.interpretation  — если детектор уже заполнил поле
  2. Claude haiku           — AI генерирует по данным сигнала (если ANTHROPIC_API_KEY задан)
  3. Static fallback dict   — для обратной совместимости

Кеш in-memory: ключ (signal_type, direction, description) → текст.
При новом signal_type AI автоматически объясняет его без изменений кода.
"""
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
        api_key = os.environ.get("ANTHROPIC_API_KEY") or _load_key_from_config()
        if not api_key:
            logger.debug("MessageComposer: ANTHROPIC_API_KEY не задан — используется static fallback")
            return
        try:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=api_key)
            self._ai_available = True
            logger.info("MessageComposer: Claude haiku подключён")
        except ImportError:
            logger.debug("MessageComposer: anthropic не установлен — pip install anthropic")

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

        # 2. AI с кешем
        if self._ai_available:
            cache_key = (signal_type, direction, description)
            if cache_key in self._cache:
                return self._cache[cache_key]
            result = await self._ask_ai(signal_type, direction, description)
            if result:
                self._cache[cache_key] = result
                return result

        # 3. Static fallback
        return _STATIC.get(signal_type, {}).get(direction, "")

    async def _ask_ai(self, signal_type: str, direction: str, description: str) -> str:
        dir_ru = "LONG (рост)" if direction == "LONG" else "SHORT (падение)"
        desc_part = f' Детали: "{description}".' if description else ""
        user_msg = (
            f"Сигнал: {signal_type}, направление: {dir_ru}.{desc_part} "
            "Объясни что произошло на рынке одним предложением."
        )
        try:
            response = await self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=80,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            text = response.content[0].text.strip()
            logger.debug("MessageComposer AI [%s/%s]: %s", signal_type, direction, text)
            return text
        except Exception as e:
            logger.debug("MessageComposer AI error: %s", e)
            return ""

    def cache_stats(self) -> dict:
        return {"cached": len(self._cache), "ai_available": self._ai_available}


def _load_key_from_config() -> Optional[str]:
    """Ищет anthropic_api_key в config.yaml."""
    try:
        from core.infra.config_loader import load_config
        cfg = load_config()
        return cfg.get("anthropic_api_key") or cfg.get("ai", {}).get("anthropic_api_key")
    except Exception:
        return None


# ─── Singleton ─────────────────────────────────────────────────────────────────
_composer: Optional[MessageComposer] = None


def get_composer() -> MessageComposer:
    global _composer
    if _composer is None:
        _composer = MessageComposer()
    return _composer
