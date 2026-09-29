"""Общий GET для процессов на urllib: просит gzip и сам распаковывает.

🔴 29.09: весь трафик машины идёт через платный VPN (~1 ТБ/мес, почти весь — бот). ccxt/aiohttp
просит gzip сам, а ~20 спутников на urllib — нет, и получают ответы в 3.7 раза тяжелее
(свечи BingX 1h×500: 54 КБ против 14.6 КБ). Семантика та же, что у urlopen: HTTPError/URLError
пробрасываются, тело — bytes."""
from __future__ import annotations

import gzip
import json
import urllib.request


def fetch_bytes(url: str, headers: dict | None = None, timeout: float = 20, context=None) -> bytes:
    h = {"Accept-Encoding": "gzip"}
    h.update(headers or {})
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout, context=context) as r:
        body = r.read()
        gz = (r.headers.get("Content-Encoding") or "").lower() == "gzip"
    return gzip.decompress(body) if gz else body


def fetch_json(url: str, headers: dict | None = None, timeout: float = 20, context=None):
    return json.loads(fetch_bytes(url, headers, timeout, context))
