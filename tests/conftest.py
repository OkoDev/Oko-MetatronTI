"""
Общие фикстуры для тестов.
"""
import os
import sys
import tempfile
import pytest
import pandas as pd

# Добавляем корень проекта в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def make_ohlcv(n=100, base_price=100.0, trend=0.0, volatility=1.0) -> pd.DataFrame:
    """Генерирует синтетический OHLCV DataFrame."""
    import numpy as np
    np.random.seed(42)
    times = [1_700_000_000_000 + i * 60_000 for i in range(n)]
    closes = base_price + trend * pd.Series(range(n)) + np.random.randn(n) * volatility
    highs = closes + abs(np.random.randn(n)) * volatility * 0.5
    lows = closes - abs(np.random.randn(n)) * volatility * 0.5
    opens = closes.shift(1).fillna(base_price)
    volumes = abs(np.random.randn(n)) * 1000 + 5000
    return pd.DataFrame({
        "time": times,
        "open": opens.values,
        "high": highs.values,
        "low": lows.values,
        "close": closes.values,
        "volume": volumes,
    })


@pytest.fixture
def ohlcv_flat():
    """Флэтовый рынок — 100 свечей без тренда."""
    return make_ohlcv(n=100, base_price=100.0, trend=0.0, volatility=0.5)


@pytest.fixture
def ohlcv_uptrend():
    """Восходящий тренд — цена растёт."""
    return make_ohlcv(n=100, base_price=100.0, trend=0.1, volatility=0.3)


@pytest.fixture
def ohlcv_downtrend():
    """Нисходящий тренд — цена падает."""
    return make_ohlcv(n=100, base_price=100.0, trend=-0.1, volatility=0.3)


@pytest.fixture
def ohlcv_volatile():
    """Высокая волатильность."""
    return make_ohlcv(n=100, base_price=100.0, trend=0.0, volatility=3.0)


@pytest.fixture
def tmp_db(tmp_path):
    """Временная БД SQLite для тестов trade_simulator / subscription_manager."""
    db_path = str(tmp_path / "test.db")
    from core.db.subscription_manager import SubscriptionManager
    SubscriptionManager(db_path)  # создаёт таблицы
    return db_path
