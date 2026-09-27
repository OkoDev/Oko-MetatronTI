# -*- coding: utf-8 -*-
"""Защита локальных веб-серверов от CSRF и DNS-rebinding (аудит 26.09.2026, BACKLOG N1).

«Только localhost» по `req.remote` защищает от соседей по сети, но не от браузера самого Егора:
любая открытая страница может отправить «простой» POST (text/plain, без preflight) на
http://localhost:PORT — и запрос придёт с 127.0.0.1. Отличить его можно по заголовкам:
  · Origin — браузер шлёт его на любой POST; у чужой страницы он не локальный;
  · Host   — при DNS-rebinding (домен атакующего → 127.0.0.1) в нём остаётся домен атакующего.
Правило для изменяющих запросов: Host локальный, Origin локальный или отсутствует.
Скрипты без Origin (curl, python, прокси oko-api → бот) работают как раньше.

Где стоит (все три входа, иначе обход через прокси):
  :8010 терминал — внутри `_is_local` (торговые /api/trade|protect|close, /api/account, /api/levinfo);
  :8000 дашборд  — middleware на все изменяющие методы;
  :8001 oko-api  — middleware (он проксирует на :8000 без Origin, Next :3000 проксирует сюда).
"""
from __future__ import annotations

from urllib.parse import urlsplit

from aiohttp import web

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _hostname(value: str) -> str:
    """Имя хоста из заголовка Host ('localhost:8010') или Origin ('http://localhost:3000')."""
    try:
        return (urlsplit(value if "//" in value else "//" + value).hostname or "").lower()
    except ValueError:
        return ""


def is_local_origin(req: web.Request) -> bool:
    """True, если запрос пришёл со страницы на этой же машине (или вообще не из браузера)."""
    if _hostname(req.headers.get("Host", "")) not in _LOCAL_HOSTS:
        return False
    origin = req.headers.get("Origin")
    return origin is None or _hostname(origin) in _LOCAL_HOSTS   # Origin: null → запрет


@web.middleware
async def local_origin_guard(request: web.Request, handler):
    if request.method not in _SAFE_METHODS and not is_local_origin(request):
        return web.json_response({"error": "запрос не с локальной страницы (CSRF-защита)"}, status=403)
    return await handler(request)
