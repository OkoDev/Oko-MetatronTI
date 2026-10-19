# -*- coding: utf-8 -*-
"""Торговый бот только для владельца (bot/filters/owner_only.py, аудит 10.10 F05)."""
import asyncio

from aiogram.types import User

from bot.filters.owner_only import DENY_TEXT, OwnerOnlyMiddleware, owner_ids_from_config

OWNER, STRANGER = 111, 999


class _Msg:
    def __init__(self, chat_type="private"):
        self.chat = type("Chat", (), {"type": chat_type})()
        self.sent = []

    async def answer(self, text, **kw):
        self.sent.append(text)


class _Cb:
    def __init__(self):
        self.sent = []

    async def answer(self, text=None, **kw):
        self.sent.append((text, kw.get("show_alert")))


class _Update:
    def __init__(self, message=None, callback_query=None, event_type="message"):
        self.message, self.callback_query, self.event_type = message, callback_query, event_type


def _user(uid):
    return User(id=uid, is_bot=False, first_name="x")


def _run(mw, event, user):
    called = []

    async def handler(ev, data):
        called.append(ev)
        return "ok"

    data = {} if user is None else {"event_from_user": user}
    return asyncio.run(mw(handler, event, data)), called


def test_owner_passes():
    res, called = _run(OwnerOnlyMiddleware({OWNER}), _Update(_Msg()), _user(OWNER))
    assert res == "ok" and len(called) == 1


def test_stranger_blocked_and_told_once():
    mw, msg = OwnerOnlyMiddleware({OWNER}), _Msg()
    res, called = _run(mw, _Update(msg), _user(STRANGER))
    assert res is None and not called and msg.sent == [DENY_TEXT]
    _run(mw, _Update(msg), _user(STRANGER))       # повтор в течение 10 минут — без ответа
    assert msg.sent == [DENY_TEXT]


def test_stranger_in_group_blocked_silently():
    msg = _Msg(chat_type="supergroup")
    res, called = _run(OwnerOnlyMiddleware({OWNER}), _Update(msg), _user(STRANGER))
    assert res is None and not called and msg.sent == []


def test_stranger_button_blocked_with_alert():
    cb = _Cb()
    res, called = _run(OwnerOnlyMiddleware({OWNER}), _Update(callback_query=cb, event_type="callback_query"),
                       _user(STRANGER))
    assert res is None and not called and cb.sent == [(DENY_TEXT, True)]


def test_update_without_user_blocked():
    res, called = _run(OwnerOnlyMiddleware({OWNER}), _Update(event_type="channel_post"), None)
    assert res is None and not called


def test_empty_owner_list_denies_everyone():
    res, called = _run(OwnerOnlyMiddleware(set()), _Update(_Msg()), _user(OWNER))
    assert res is None and not called


def test_owner_ids_from_config():
    cfg = {"telegram.admin_id": " 111 ", "telegram.allowed_user_ids": [222, "333", "", "abc", None]}

    class _Cfg:
        def get(self, key, default=None):
            return cfg.get(key, default)

    assert owner_ids_from_config(_Cfg()) == frozenset({111, 222, 333})
