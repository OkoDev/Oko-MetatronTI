# -*- coding: utf-8 -*-
"""
F05 (аудит 10.10): торговый бот — только для владельца, всё остальное запрещено.

Подписка на сигналы не заменяет авторизацию управления: любой, кто найдёт бота поиском,
мог вызвать /reset и другие служебные команды. Проверка стоит на входе ВСЕХ апдейтов
(outer-middleware уровня update), поэтому новые роутеры защищены без доработок.
Публичные люди идут в отдельный бот-приёмную (ARCH-150.4), не сюда.
"""
import logging
import time

from aiogram import BaseMiddleware

logger = logging.getLogger(__name__)

DENY_TEXT = "Это закрытый служебный бот. Ранний доступ к Metatron — metatronti.com"
_NOTICE_EVERY_SEC = 600


def owner_ids_from_config(config) -> frozenset:
    """telegram.admin_id + необязательный список telegram.allowed_user_ids."""
    raw = [config.get("telegram.admin_id", "")]
    raw += list(config.get("telegram.allowed_user_ids", []) or [])
    return frozenset(int(s) for s in (str(v).strip() for v in raw) if s.isdigit())


class OwnerOnlyMiddleware(BaseMiddleware):
    def __init__(self, owner_ids):
        self.owner_ids = frozenset(owner_ids)
        self._last_notice = {}
        if not self.owner_ids:
            logger.error("[ACCESS] список владельцев пуст — бот отклонит ВСЕ апдейты "
                         "(проверь telegram.admin_id)")

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user is not None and user.id in self.owner_ids:
            return await handler(event, data)
        uid = getattr(user, "id", None)
        # D-009 (152-ФЗ): id и имя чужого человека — персональные данные, в лог их не пишем
        logger.warning("[ACCESS] отказ чужому аккаунту (тип=%s)", getattr(event, "event_type", "?"))
        await self._notice(event, uid)
        return None

    async def _notice(self, event, uid):
        """Одно сообщение раз в 10 минут — только в личке и на нажатие кнопки."""
        if uid is None:
            return
        now = time.monotonic()
        if now - self._last_notice.get(uid, now - _NOTICE_EVERY_SEC) < _NOTICE_EVERY_SEC:
            return
        self._last_notice[uid] = now
        try:
            msg = getattr(event, "message", None)
            cb = getattr(event, "callback_query", None)
            if msg is not None and msg.chat.type == "private":
                await msg.answer(DENY_TEXT)
            elif cb is not None:
                await cb.answer(DENY_TEXT, show_alert=True)
        except Exception as e:
            logger.debug("[ACCESS] не смог ответить чужому аккаунту: %s", e)
