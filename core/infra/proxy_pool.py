"""
proxy_pool.py — ротация IP для market-data запросов (ARCH: DataInfraSphere).

ЗАЧЕМ: BingX лимитит rps ПО IP, не по ключу. Один IP = один rps-бюджет → потолок ~531 пары.
Пул прокси даёт N независимых IP → N× throughput для сканирования.

🔴 ПРАВИЛО: ТОЛЬКО публичные market-data (fetch_ohlcv/tickers — ключ не нужен).
   Торговые запросы (ордера/баланс) — ВСЕГДА прямой IP (ключ привязан к whitelist IP биржи,
   запрос с чужого IP → бан ключа). Этот модуль торговлю НЕ обслуживает.

Изолирован: round-robin least-loaded + per-proxy rate limiter + health-check + fallback на direct.
Интеграция в ApiEngine — отдельный осторожный шаг (ApiEngine = дверь всей торговли).

Конфиг (config.yaml):
  proxy_pool:
    enabled: false              # выкл по умолчанию — нулевой риск пока не настроен
    proxies: []                 # ['http://user:pass@ip:port', 'socks5://ip:port']
    rps_per_proxy: 8.0          # бюджет на КАЖДЫЙ IP (как api_rps на прямой)
    health_cooldown_sec: 30.0   # пауза мёртвого прокси перед повторной попыткой
"""
from __future__ import annotations

import re
import time
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional, List

logger = logging.getLogger(__name__)


def _mask(url: Optional[str]) -> str:
    """Прячет логин и пароль: http://user:pass@1.2.3.4:59100 → http://***@1.2.3.4:59100."""
    if not url:
        return "—"
    return re.sub(r"//[^@/]+@", "//***@", url)


@dataclass
class _ProxyState:
    url: str
    rps: float
    _tokens: float = 0.0          # токен-бакет (rps-бюджет этого IP)
    _last_refill: float = field(default_factory=time.monotonic)
    inflight: int = 0             # текущие запросы (для least-loaded выбора)
    dead_until: float = 0.0       # health: «мёртв» до этого времени (monotonic)
    fails: int = 0

    def _refill(self) -> None:
        now = time.monotonic()
        self._tokens = min(self.rps, self._tokens + (now - self._last_refill) * self.rps)
        self._last_refill = now

    def is_alive(self) -> bool:
        return time.monotonic() >= self.dead_until

    async def acquire(self) -> None:
        """Token-bucket: ждём свободный слот в rps-бюджете ЭТОГО IP."""
        while True:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            await asyncio.sleep(max(0.01, (1.0 - self._tokens) / self.rps))


class ProxyPool:
    """Пул прокси для market-data. round-robin least-loaded среди живых + fallback на direct.

    `direct` (None-url) НЕ входит в пул — это явный fallback когда все прокси мертвы
    (лучше грузить с основного IP, чем не грузить вовсе).
    """

    def __init__(self, proxies: List[str], rps_per_proxy: float = 8.0,
                 health_cooldown_sec: float = 30.0):
        self._states = [_ProxyState(url=p, rps=rps_per_proxy) for p in proxies if p]
        self._cooldown = health_cooldown_sec
        self._rr = 0  # round-robin указатель
        logger.info("[ProxyPool] инициализирован: %d прокси, rps_per_proxy=%.1f",
                    len(self._states), rps_per_proxy)

    @property
    def size(self) -> int:
        return len(self._states)

    @property
    def alive_count(self) -> int:
        return sum(1 for s in self._states if s.is_alive())

    def _pick(self) -> Optional[_ProxyState]:
        """Живой прокси с наименьшим inflight (балансировка), round-robin при равенстве."""
        alive = [s for s in self._states if s.is_alive()]
        if not alive:
            return None
        # round-robin старт + least-loaded: стабильное распределение
        self._rr = (self._rr + 1) % len(alive)
        ordered = alive[self._rr:] + alive[:self._rr]
        return min(ordered, key=lambda s: s.inflight)

    async def acquire(self) -> Optional[str]:
        """Возвращает url прокси (с учётом его rps-бюджета) или None = direct fallback.

        Использование:
            url = await pool.acquire()
            try:
                ... fetch через proxy=url (или прямой, если url is None) ...
                pool.release(url, ok=True)
            except Exception:
                pool.release(url, ok=False)
        """
        st = self._pick()
        if st is None:
            return None  # все мертвы → direct
        await st.acquire()      # rps-бюджет этого IP
        st.inflight += 1
        return st.url

    def release(self, url: Optional[str], ok: bool = True) -> None:
        if url is None:
            return
        for s in self._states:
            if s.url == url:
                s.inflight = max(0, s.inflight - 1)
                if ok:
                    s.fails = 0
                else:
                    s.fails += 1
                    if s.fails >= 3:  # 3 подряд → в карантин
                        s.dead_until = time.monotonic() + self._cooldown
                        # 🔴 02.09.2026: логировался ПОЛНЫЙ url с логином и паролем.
                        # Логи не в git, но пароль в открытом файле — лишний риск,
                        # а для диагностики достаточно хоста.
                        logger.warning("[ProxyPool] прокси в карантине %.0fs: %s (fails=%d)",
                                       self._cooldown, _mask(url), s.fails)
                return

    def stats(self) -> dict:
        return {
            "size": self.size,
            "alive": self.alive_count,
            # url маскируется: stats() уходит в логи и на дашборд — пароль там не нужен
            "per_proxy": [{"url": _mask(s.url), "inflight": s.inflight, "alive": s.is_alive(),
                           "fails": s.fails} for s in self._states],
        }


def build_proxy_pool(config) -> Optional[ProxyPool]:
    """Фабрика из config. Возвращает None если выключено/пусто (→ работа без прокси, как сейчас).
    Прокси: config.proxy_pool.proxies ИЛИ env PROXY_LIST (url1,url2,... — пароли НЕ в git)."""
    if not config.get("proxy_pool.enabled", False):
        return None
    proxies = config.get("proxy_pool.proxies", []) or []
    if not proxies:
        import os
        env_list = os.getenv("PROXY_LIST", "")
        if env_list:
            proxies = [p.strip() for p in env_list.split(",") if p.strip()]
    if not proxies:
        logger.info("[ProxyPool] enabled, но список proxies пуст (config + PROXY_LIST) — работаем direct")
        return None
    return ProxyPool(
        proxies=proxies,
        rps_per_proxy=float(config.get("proxy_pool.rps_per_proxy", 8.0)),
        health_cooldown_sec=float(config.get("proxy_pool.health_cooldown_sec", 30.0)),
    )
