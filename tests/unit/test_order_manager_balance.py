import pytest
from unittest.mock import AsyncMock, patch

from core.exchange.bingx_client import BingXClient
from core.exchange.order_manager import OrderManager


@pytest.mark.asyncio
async def test_bingx_client_get_balance_resyncs_on_timestamp_invalid():
    client = BingXClient("key", "secret", "https://open-api-vst.bingx.com")
    client.get = AsyncMock(side_effect=[
        {"code": 109400, "msg": "timestamp is invalid", "data": {}},
        {"code": 0, "data": {"balance": {"availableMargin": "12.34"}}},
    ])
    client.sync_time = AsyncMock(return_value=0)

    balance = await client.get_balance()

    assert balance == 12.34
    client.sync_time.assert_awaited_once()
    assert client.get.await_count == 2


@pytest.mark.asyncio
async def test_order_manager_falls_back_to_config_deposit_when_exchange_balance_is_zero():
    class DummyConfig:
        def get(self, key, default=None):
            values = {
                "trading.execution_mode": "vst",
                "trading.deposit_usdt": 110.0,
                "trading.tp1_close_pct": 0.2,
            }
            return values.get(key, default)

    om = OrderManager(DummyConfig())
    fake_client = type("FakeClient", (), {"get_balance": AsyncMock(return_value=None)})()

    with patch.object(om, "_get_client_synced", AsyncMock(return_value=fake_client)):
        balance = await om.get_available_balance()

    assert balance == 110.0


@pytest.mark.asyncio
async def test_order_manager_keeps_real_zero_balance_without_fallback():
    class DummyConfig:
        def get(self, key, default=None):
            values = {
                "trading.execution_mode": "vst",
                "trading.deposit_usdt": 110.0,
                "trading.tp1_close_pct": 0.2,
            }
            return values.get(key, default)

    om = OrderManager(DummyConfig())
    fake_client = type("FakeClient", (), {"get_balance": AsyncMock(return_value=0.0)})()

    with patch.object(om, "_get_client_synced", AsyncMock(return_value=fake_client)):
        balance = await om.get_available_balance()

    assert balance == 0.0
