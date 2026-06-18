"""
Notification Sender — TG-отправка уведомлений пользователю.

Быстрый путь (evaluate + send в одном вызове):
    from bot.notifications.sender import notify
    await notify(bot, "strategy_fire_ote", symbol, entry=1.23, ...)

Раздельный путь:
    from core.notifications.evaluate import evaluate
    from bot.notifications.sender import send_notification
    text = evaluate(...)
    if text:
        await send_notification(bot, text)
"""
import logging
from typing import Any

from core.notifications.evaluate import evaluate
from core.notifications.notif_config import notif_config

logger = logging.getLogger(__name__)


async def send_notification(bot: Any, text: str) -> None:
    """Отправляет готовый текст пользователю (telegram.admin_id из bot.config)."""
    try:
        admin_id = bot.config.get("telegram.admin_id")
        if not admin_id:
            return
        await bot.bot.send_message(int(admin_id), text, parse_mode="HTML")
    except Exception as e:
        logger.debug("[NOTIF] send error: %s", e)


async def notify(bot: Any, rule_name: str, symbol: str, **kwargs) -> None:
    """Evaluate (из notifications.yaml) + send. Молча пропускает если правило выключено/cooldown."""
    text = evaluate(rule_name, symbol, notif_config, **kwargs)
    if text:
        await send_notification(bot, text)
