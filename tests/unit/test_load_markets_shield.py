# -*- coding: utf-8 -*-
"""29.09: самопроизвольные выходы бота (04:17, 17:41). SelfTest звал load_markets под wait_for(timeout=10);
при медленном BingX таймаут отменял ОБЩУЮ задачу ccxt markets_loading — её же ждал главный старт
(start_monitoring) → CancelledError → бот выходил. Отмена одного ожидающего не должна ронять остальных."""
import asyncio

from core.infra.data_collector import RealTimeData


class _SlowExchange:
    """Как ccxt: одна общая задача загрузки рынков на всех вызывающих."""
    markets_loading = None
    symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    markets: dict = {}

    async def _helper(self):
        await asyncio.sleep(0.5)
        return {}

    async def load_markets(self):
        if self.markets_loading is None:
            self.markets_loading = asyncio.ensure_future(self._helper())
        return await self.markets_loading


def test_timeout_of_one_caller_does_not_cancel_main_startup():
    async def run():
        dc = RealTimeData()
        dc.exchange = _SlowExchange()
        main = asyncio.create_task(dc.load_markets())                       # главный старт
        try:
            await asyncio.wait_for(dc.load_markets(), timeout=0.1)          # SelfTest с коротким таймаутом
        except asyncio.TimeoutError:
            pass
        return await main
    assert asyncio.run(run()) == ["BTC/USDT:USDT", "ETH/USDT:USDT"]
