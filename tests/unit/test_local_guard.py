# -*- coding: utf-8 -*-
"""CSRF / DNS-rebinding защита локальных серверов (web/local_guard.py, аудит 26.09 N1)."""
import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from web.local_guard import is_local_origin, local_origin_guard


def _req(method="POST", host="localhost:8010", origin=None):
    headers = {"Host": host}
    if origin is not None:
        headers["Origin"] = origin
    return make_mocked_request(method, "/api/trade", headers=headers)


@pytest.mark.parametrize("host,origin", [
    ("localhost:8010", None),                       # скрипт / curl
    ("127.0.0.1:8000", "http://localhost:3000"),    # Next-дашборд через прокси
    ("127.0.0.1:8010", "http://127.0.0.1:8010"),    # родная страница терминала
    ("[::1]:8010", "http://[::1]:8010"),
])
def test_local_requests_pass(host, origin):
    assert is_local_origin(_req(host=host, origin=origin))


@pytest.mark.parametrize("host,origin", [
    ("localhost:8010", "https://evil.example"),     # CSRF: чужая страница в том же браузере
    ("evil.example:8010", "http://evil.example:8010"),  # DNS-rebinding
    ("evil.example:8010", None),
    ("localhost:8010", "null"),                     # sandbox-iframe / file://
    ("192.168.1.5:3000", "http://192.168.1.5:3000"),  # LAN — изменяющие запросы только с этой машины
])
def test_foreign_requests_blocked(host, origin):
    assert not is_local_origin(_req(host=host, origin=origin))


def _run(req):
    async def handler(_):
        return web.Response(text="ok")
    return asyncio.run(local_origin_guard(req, handler))


def test_middleware_blocks_foreign_post():
    assert _run(_req("POST", origin="https://evil.example")).status == 403


def test_middleware_lets_get_through():
    assert _run(_req("GET", origin="https://evil.example")).status == 200


def test_middleware_lets_local_post_through():
    assert _run(_req("POST", origin="http://localhost:8010")).status == 200
