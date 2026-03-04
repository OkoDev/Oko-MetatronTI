"""
Действия меню настроек — standalone-функции вместо методов MenuHandler.
"""
import logging

from aiogram.types import Message

logger = logging.getLogger(__name__)


async def show_general_settings(bot, message: Message) -> None:
    """Показ общих настроек из config.yaml."""
    try:
        from core.config_loader import config
        cfg = config.get_all()
        lines = [
            "⚙️ <b>Общие настройки</b>",
            f"Биржа: {cfg.get('exchanges', {}).get('default', 'bingx')}",
        ]
        lvl = cfg.get("analysis", {}).get("volume_multiplier")
        if lvl is not None:
            lines.append(f"Множитель объема: {lvl}")
        lines.append(f"Логирование: {cfg.get('logging', {}).get('level', 'INFO')}")
        await message.answer("\n".join(lines))
    except Exception:
        await message.answer("⚙️ Настройки недоступны")


async def show_notification_settings(bot, message: Message) -> None:
    """Показ настроек уведомлений."""
    await message.answer("🔔 Уведомления отправляются подписчикам согласно лимитам уровня подписки.")


async def show_analysis_settings(bot, message: Message) -> None:
    """Показ параметров анализа из config."""
    from core.config_loader import config
    a = config.get("analysis", {})
    lines = [
        "📊 <b>Параметры анализа</b>",
        f"volume_multiplier={a.get('volume_multiplier', '-')}",
        f"price_threshold={a.get('price_threshold', '-')}",
    ]
    await message.answer("\n".join(lines))


async def show_signal_settings(bot, message: Message) -> None:
    """Показ настроек типов сигналов."""
    lines = ["🎯 <b>Типы сигналов</b>", "Аномалии, WT, MTF, Тренд, Дивергенции, Пивоты"]
    await message.answer("\n".join(lines))


async def show_interface_settings(bot, message: Message) -> None:
    """Показ настроек интерфейса."""
    await message.answer("📱 Интерфейс: кнопочное меню + inline-кнопки. Язык: RU.")


async def show_advanced_settings(bot, message: Message) -> None:
    """Показ дополнительных настроек."""
    await message.answer("🔧 Дополнительно: включена защита от дублей (PID lock), UTF-8 логирование.")
