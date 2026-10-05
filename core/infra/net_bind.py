# -*- coding: utf-8 -*-
"""Привязка исходящих соединений к домашнему IP — трафик мимо платного VPN.

Зачем (05.10, N11/N21): весь трафик машины идёт через туннель Happ, он платный
(~1 ТБ/мес). Сокет, привязанный к адресу домашней сети, уходит напрямую.
Приём уже доказан на свечном потоке (`market_ws.py`, 29.09: VPN 33 → 12 ГБ/сут)
и на цене (`price_ws.py`), здесь он собран в одном месте для остальных каналов.

🔴 ЧЕГО НЕЛЬЗЯ ПРИВЯЗЫВАТЬ: торговые запросы и user-data WS. Ключ BingX привязан
к whitelist-IP биржи, и смена выходного адреса = бан ключа (`proxy_pool.py:8`).
Этот модуль — только для ПУБЛИЧНЫХ рыночных данных.

Использование:
    from core.infra.net_bind import aiohttp_connector, install_urllib_bind
    async with aiohttp.ClientSession(connector=aiohttp_connector()) as s: ...
    install_urllib_bind()        # один раз на процесс, дальше urlopen идёт мимо VPN
"""
from __future__ import annotations

import http.client
import logging
import socket
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_PREFIX = "192.168.1."


def _prefix(explicit: Optional[str] = None) -> str:
    """Префикс берём из конфига (`market_ws.bind_ip_prefix`) — он один на весь проект."""
    if explicit is not None:
        return explicit
    try:
        from core.infra.config_loader import config
        return str(config.get("market_ws.bind_ip_prefix", "") or "")
    except Exception:                                # noqa: BLE001 — спутник живёт без конфига
        return _DEFAULT_PREFIX


def local_ip(prefix: Optional[str] = None) -> Optional[str]:
    """Локальный IPv4 с нужным префиксом. Ищем каждый раз: адрес от DHCP может смениться."""
    pref = _prefix(prefix)
    if not pref:
        return None
    try:
        return next((ip for ip in socket.gethostbyname_ex(socket.gethostname())[2]
                     if ip.startswith(pref)), None)
    except OSError:
        return None


def aiohttp_connector(prefix: Optional[str] = None, **kw):
    """TCPConnector с привязкой к домашнему IP; None — если адреса нет (идём как все)."""
    ip = local_ip(prefix)
    if not ip:
        return None
    try:
        import aiohttp
        return aiohttp.TCPConnector(local_addr=(ip, 0), family=socket.AF_INET, **kw)
    except Exception as e:                           # noqa: BLE001 — связь важнее экономии
        logger.debug("[net_bind] коннектор не создан: %s", e)
        return None


class _BoundHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS-соединение с source_address — тот же bind, только для urllib."""
    _bind_ip: Optional[str] = None

    def __init__(self, *a, **kw):
        if self._bind_ip:
            kw.setdefault("source_address", (self._bind_ip, 0))
        super().__init__(*a, **kw)


class _BoundHTTPConnection(http.client.HTTPConnection):
    _bind_ip: Optional[str] = None

    def __init__(self, *a, **kw):
        if self._bind_ip:
            kw.setdefault("source_address", (self._bind_ip, 0))
        super().__init__(*a, **kw)


_installed = False


def install_urllib_bind(prefix: Optional[str] = None) -> Optional[str]:
    """Ставит глобальный opener: urlopen в этом процессе пойдёт мимо туннеля.

    Возвращает использованный IP или None. Безопасно звать повторно.
    """
    global _installed
    if _installed:
        return _BoundHTTPSConnection._bind_ip
    ip = local_ip(prefix)
    if not ip:
        return None
    try:
        _BoundHTTPSConnection._bind_ip = ip
        _BoundHTTPConnection._bind_ip = ip

        class _HTTPSHandler(urllib.request.HTTPSHandler):
            def https_open(self, req):
                return self.do_open(_BoundHTTPSConnection, req, context=self._context)

        class _HTTPHandler(urllib.request.HTTPHandler):
            def http_open(self, req):
                return self.do_open(_BoundHTTPConnection, req)

        urllib.request.install_opener(urllib.request.build_opener(_HTTPSHandler(), _HTTPHandler()))
        _installed = True
        logger.info("[net_bind] urllib идёт МИМО VPN: bind %s", ip)
        return ip
    except Exception as e:                           # noqa: BLE001
        logger.warning("[net_bind] urllib bind не включился: %s — идём как раньше", e)
        return None
