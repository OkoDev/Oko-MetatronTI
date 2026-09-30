"""30.09: биржа не отдала список пар на старте → мониторинг запускается фоновыми повторами, а не никогда."""
import asyncio
import sys
import types
from types import SimpleNamespace

import pytest

import bot.monitoring as mon


class _DC:
    def __init__(self, answers):
        self._answers = list(answers)
        self.calls = 0

    async def load_markets(self, min_volume_usd=0):
        self.calls += 1
        return self._answers.pop(0) if self._answers else []


def _bot(answers):
    return SimpleNamespace(
        is_monitoring=False, subscribers={1}, monitor_task=None,
        config=SimpleNamespace(get=lambda k, d=None: d),
        data_collector=_DC(answers),
        subscription_manager=SimpleNamespace(get_subscription_info=lambda uid: {"tier": "admin"}),
    )


def _msg():
    sent = []

    async def answer(text, **kw):
        sent.append(text)
    return SimpleNamespace(from_user=SimpleNamespace(id=1), answer=answer), sent


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(mon, "_PAIRS_RETRY_DELAYS", (0,))
    stub = types.ModuleType("bot.loops.scan_loop")

    async def _noop(bot):
        return None
    stub.monitor_market = _noop
    stub._prefetch_pivots = _noop
    monkeypatch.setitem(sys.modules, "bot.loops.scan_loop", stub)


def test_pairs_loaded_after_retries_start_monitoring():
    async def run():
        b = _bot([[], [], ["A/USDT:USDT", "B/USDT:USDT"]])
        m, sent = _msg()
        await mon.start_monitoring(b, m)
        assert b.monitoring_starting is True and b.is_monitoring is False       # старт не ждёт повторов
        await asyncio.wait_for(b.pairs_retry_task, 5)
        assert b.is_monitoring and b.monitored_pairs == ["A/USDT:USDT", "B/USDT:USDT"]
        assert b.data_collector.calls == 3 and b.monitoring_starting is False
        assert "повторяю в фоне" in sent[0] and "Запущен мониторинг 2 пар" in sent[-1]
    asyncio.new_event_loop().run_until_complete(run())


def test_stop_cancels_retries_and_second_start_is_refused():
    async def run():
        b = _bot([])                                    # биржа молчит всегда
        mon._PAIRS_RETRY_DELAYS = (0.05,)
        m, sent = _msg()
        await mon.start_monitoring(b, m)
        await mon.start_monitoring(b, m)                # второй /start во время повторов
        assert "уже запускается" in sent[-1]
        await mon.stop_monitoring(b, m)
        assert "Повторы запуска мониторинга остановлены" in sent[-1]
        await asyncio.wait_for(b.pairs_retry_task, 5)
        assert b.is_monitoring is False and b.monitoring_starting is False
    asyncio.new_event_loop().run_until_complete(run())


def test_pairs_on_first_try_start_immediately():
    async def run():
        b = _bot([["A/USDT:USDT"]])
        m, sent = _msg()
        await mon.start_monitoring(b, m)
        assert b.is_monitoring and not getattr(b, "monitoring_starting", False)
        assert b.data_collector.calls == 1 and "Запущен мониторинг 1 пар" in sent[-1]
    asyncio.new_event_loop().run_until_complete(run())
