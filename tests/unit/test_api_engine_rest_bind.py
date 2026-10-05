"""N11: REST мимо VPN — ccxt получает сессию, привязанную к домашнему IP.

Потоки (свечи, цена) уже ходят напрямую, REST остался единственным жильцом платного
туннеля. Замер 05.10: прокси работают мимо VPN не хуже (1064-1070 мс против 1094-1103),
прямой запрос вдвое быстрее (305 против 530 мс).

Важное: при любой осечке транспорт обязан работать как раньше — экономия трафика
не стоит ни одного несделанного запроса.
"""
from types import SimpleNamespace

import pytest

from core.infra.api_engine import ApiEngine


def _engine(prefix, session=None):
    ex = SimpleNamespace(session=session, ssl_context=None)
    eng = ApiEngine(ex, semaphore_size=2, rps=5.0)
    eng._bind_prefix = prefix
    eng._bind_done = False
    return eng, ex


@pytest.mark.asyncio
async def test_disabled_by_default_does_nothing():
    """Пустой префикс — поведение не меняется, сессию ccxt создаёт сам."""
    eng, ex = _engine("")
    await eng._ensure_bound_session()
    assert ex.session is None


@pytest.mark.asyncio
async def test_binds_session_when_prefix_matches(monkeypatch):
    import core.infra.market_ws as mws
    monkeypatch.setattr(mws, "local_ip_by_prefix", lambda p: "192.168.1.216")
    eng, ex = _engine("192.168.1.")
    await eng._ensure_bound_session()
    assert ex.session is not None
    conn = ex.session.connector
    assert conn._local_addr == ("192.168.1.216", 0)
    await ex.session.close()


@pytest.mark.asyncio
async def test_no_local_ip_keeps_old_behaviour(monkeypatch):
    """Адреса с таким префиксом нет (сменилась сеть) — работаем через туннель."""
    import core.infra.market_ws as mws
    monkeypatch.setattr(mws, "local_ip_by_prefix", lambda p: None)
    eng, ex = _engine("10.99.")
    await eng._ensure_bound_session()
    assert ex.session is None


@pytest.mark.asyncio
async def test_existing_session_is_not_replaced(monkeypatch):
    """Если сессию кто-то уже поставил — не отбираем, иначе порвём его запросы."""
    import core.infra.market_ws as mws
    monkeypatch.setattr(mws, "local_ip_by_prefix", lambda p: "192.168.1.216")
    marker = object()
    eng, ex = _engine("192.168.1.", session=marker)
    await eng._ensure_bound_session()
    assert ex.session is marker


@pytest.mark.asyncio
async def test_runs_only_once(monkeypatch):
    import core.infra.market_ws as mws
    calls = []
    monkeypatch.setattr(mws, "local_ip_by_prefix", lambda p: (calls.append(p), "192.168.1.216")[1])
    eng, ex = _engine("192.168.1.")
    await eng._ensure_bound_session()
    await eng._ensure_bound_session()
    await eng._ensure_bound_session()
    assert len(calls) == 1
    await ex.session.close()


@pytest.mark.asyncio
async def test_failure_does_not_break_transport(monkeypatch):
    """Сломался bind — REST обязан продолжать работать, просто через туннель."""
    import core.infra.market_ws as mws

    def _boom(_p):
        raise RuntimeError("сеть недоступна")

    monkeypatch.setattr(mws, "local_ip_by_prefix", _boom)
    eng, ex = _engine("192.168.1.")
    await eng._ensure_bound_session()        # не бросает
    assert ex.session is None
