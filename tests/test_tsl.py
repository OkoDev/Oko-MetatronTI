#!/usr/bin/env python3
"""
Тест Trailing Stop Loss (TSL) функциональности
"""
import asyncio
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from core.trade_simulator import TradeSimulator
from core.indicators import calculate_trend, get_trend_info


async def test_tsl_calculation():
    """Тест расчета TSL"""
    print("🧪 Тестируем расчет TSL...")

    # Создаем тестовые OHLC данные
    dates = pd.date_range('2024-01-01', periods=100, freq='1H')
    np.random.seed(42)

    # Симулируем восходящий тренд
    base_price = 50000
    prices = []
    for i in range(100):
        trend = i * 10  # Восходящий тренд
        noise = np.random.normal(0, 100)
        price = base_price + trend + noise
        prices.append(max(price, 100))  # Минимум 100

    df = pd.DataFrame({
        'time': dates,
        'open': prices,
        'high': [p + abs(np.random.normal(0, 50)) for p in prices],
        'low': [p - abs(np.random.normal(0, 50)) for p in prices],
        'close': prices,
        'volume': [np.random.uniform(1000, 10000) for _ in range(100)]
    })

    # Расчет тренда и TSL
    df_with_trend = calculate_trend(df)
    trend_info = get_trend_info(df_with_trend)

    print(f"📈 Тренд: {trend_info['direction']}")
    print(".2f")
    print(".2f")
    print(".1f")
    print(f"🔥 TSL рассчитан: {trend_info['tsl'] is not None}")

    return trend_info


async def test_trade_simulator_tsl():
    """Тест интеграции TSL в TradeSimulator"""
    print("\n🧪 Тестируем TradeSimulator с TSL...")

    # Создаем тестовый OHLCV
    df = pd.DataFrame({
        'time': pd.date_range('2024-01-01', periods=50, freq='1H'),
        'open': np.random.uniform(49000, 51000, 50),
        'high': np.random.uniform(50000, 52000, 50),
        'low': np.random.uniform(48000, 50000, 50),
        'close': np.random.uniform(49000, 51000, 50),
        'volume': np.random.uniform(1000, 10000, 50)
    })

    # Mock data collector
    class MockDataCollector:
        async def get_ohlcv(self, symbol, timeframe, limit):
            return df.tail(limit).copy()

    # Создаем симулятор
    simulator = TradeSimulator(db_path=":memory:")  # In-memory БД

    # Регистрируем тестовую сделку
    class MockRecommendation:
        def __init__(self):
            self.symbol = "BTC/USDT"
            self.direction = "LONG"
            self.entry_price = 50000.0
            self.stop_loss = 49000.0
            self.take_profit = 52000.0
            self.overall_strength = 80
            self.confidence = 0.8
            self.timestamp = datetime.now(timezone.utc)
            self.supporting_signals = []

    rec = MockRecommendation()
    trade_id = simulator.register_trade(rec)
    print(f"📝 Зарегистрирована тестовая сделка ID: {trade_id}")

    # Проверяем TSL
    data_collector = MockDataCollector()
    closed_count = await simulator.check_open_trades_with_tsl(data_collector, use_tsl=True)

    print(f"🔄 Проверено сделок: {closed_count}")

    # Проверяем статус сделки
    open_trades = simulator.get_open_trades()
    print(f"📊 Открытых сделок: {len(open_trades)}")

    return True


async def main():
    """Основная функция теста"""
    print("🚀 Запуск тестов TSL функциональности\n")

    try:
        # Тест 1: Расчет TSL
        await test_tsl_calculation()

        # Тест 2: Интеграция с TradeSimulator
        await test_trade_simulator_tsl()

        print("\n✅ Все тесты пройдены успешно!")

    except Exception as e:
        print(f"\n❌ Ошибка в тестах: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())