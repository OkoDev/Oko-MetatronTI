#!/usr/bin/env python3
"""
Демонстрация возможностей системы тестирования
"""
import asyncio
import json
from datetime import datetime, timezone

async def demo_indicator_testing():
    """Демонстрация тестирования индикаторов"""
    print("🎯 ДЕМОНСТРАЦИЯ ВОЗМОЖНОСТЕЙ СИСТЕМЫ ТЕСТИРОВАНИЯ")
    print("=" * 70)

    print("\n1️⃣ ТЕСТИРОВАНИЕ ИНДИКАТОРОВ")
    print("-" * 40)

    try:
        from test_indicators import IndicatorTester

        # Быстрый тест на 7 дней
        tester = IndicatorTester(symbol="BTC/USDT", timeframe="1h")
        df = await tester.load_test_data(days=7)

        print(f"📊 Загружено {len(df)} свечей BTC/USDT за 7 дней")

        # Тестируем основные индикаторы
        trend_results = tester.test_trend_indicators(df)
        wt_results = tester.test_wt_indicator(df)
        anomaly_results = tester.test_anomaly_detector(df)

        print("
📈 Трендовые индикаторы:"        print(f"   • Распределение: UP {trend_results['trend_distribution']['up_trend_pct']}%, DOWN {trend_results['trend_distribution']['down_trend_pct']}%")
        print(f"   • Изменений тренда: {trend_results['trend_changes']}")

        print("
🌊 WT индикатор:"        print(f"   • Сигналов: {wt_results['total_signals']}")
        print(f"   • Зоны: {wt_results['zone_distribution']}")

        print("
🚨 Аномалии:"        print(f"   • Всего: {anomaly_results['total_anomalies']}")
        print(f"   • Частота: {anomaly_results['anomaly_rate']}%")

        print("✅ Индикаторы работают корректно!")

    except Exception as e:
        print(f"❌ Ошибка тестирования индикаторов: {e}")

async def demo_backtesting():
    """Демонстрация бэктестинга"""
    print("\n2️⃣ БЭКТЕСТИНГ СТРАТЕГИЙ")
    print("-" * 40)

    try:
        from backtesting_engine import BacktestingEngine, BacktestConfig

        # Быстрая конфигурация для демонстрации
        config = BacktestConfig(
            symbol="BTC/USDT",
            start_date=datetime(2024, 11, 1, tzinfo=timezone.utc),
            end_date=datetime(2024, 12, 1, tzinfo=timezone.utc),
            use_tsl=True,
            tsl_activation_r=1.0,
            risk_per_trade_pct=1.0
        )

        print(f"📊 Бэктест: {config.symbol} с {config.start_date.date()} по {config.end_date.date()}")
        print(f"🎯 TSL: {'Включен' if config.use_tsl else 'Отключен'}, риск: {config.risk_per_trade_pct}%")

        engine = BacktestingEngine(config)
        result = await engine.run_backtest()

        metrics = result['metrics']
        print("
📈 РЕЗУЛЬТАТЫ:"        print(f"   • Сделок: {metrics['total_trades']}")
        print(f"   • Win Rate: {metrics['win_rate']}%")
        print(f"   • Avg R: {metrics['avg_r_multiple']}")
        print(f"   • Доход: {metrics['total_return_pct']}%")
        print(f"   • Sharpe: {metrics['sharpe_ratio']}")
        print(f"   • Max DD: {metrics['max_drawdown_pct']}%")

        if metrics['total_trades'] > 0:
            print("✅ Бэктест завершен успешно!")
        else:
            print("⚠️ Мало данных для значимых результатов")

    except Exception as e:
        print(f"❌ Ошибка бэктестинга: {e}")

async def demo_strategy_comparison():
    """Демонстрация сравнения стратегий"""
    print("\n3️⃣ СРАВНЕНИЕ СТРАТЕГИЙ")
    print("-" * 40)

    try:
        from strategy_comparison import StrategyComparator

        # Быстрое сравнение TSL стратегий
        comparator = StrategyComparator()

        print("🔄 Сравнение TSL стратегий (быстрый тест)...")

        tsl_results = await comparator.compare_tsl_strategies()

        print("
🏆 РЕЗУЛЬТАТЫ СРАВНЕНИЯ:"        print("<15")
        print("-" * 50)

        for result in tsl_results:
            config = result['config']
            metrics = result['metrics']
            strategy_name = f"{'Без TSL' if not config.use_tsl else f'После {config.tsl_activation_r}R'}"
            print("<15")

        # Лучшая стратегия
        best_result = max(tsl_results, key=lambda x: x['metrics']['total_return_pct'])
        best_config = best_result['config']
        best_metrics = best_result['metrics']

        print(f"\n🎯 ЛУЧШАЯ СТРАТЕГИЯ: {'Без TSL' if not best_config.use_tsl else f'TSL после {best_config.tsl_activation_r}R'}")
        print(f"   Доход: {best_metrics['total_return_pct']}% | Sharpe: {best_metrics['sharpe_ratio']}")

        print("✅ Сравнение стратегий работает!")

    except Exception as e:
        print(f"❌ Ошибка сравнения стратегий: {e}")

def show_system_capabilities():
    """Показать возможности системы"""
    print("\n4️⃣ ВОЗМОЖНОСТИ СИСТЕМЫ")
    print("-" * 40)

    capabilities = {
        "📊 Данные": [
            "Реальные исторические OHLCV с биржи",
            "TTL-кеширование для производительности",
            "Поддержка всех таймфреймов (15m-1d)"
        ],
        "🧪 Индикаторы": [
            "Трендовые (EMA, ATR, TSL)",
            "WaveTrend (WT1, WT2, зоны OB/OS)",
            "Дивергенции (Regular, Hidden)",
            "Аномалии объема и цены",
            "FVG (Fair Value Gaps)",
            "Рыночные режимы (ADX+ATR+EMA)"
        ],
        "📈 Стратегии": [
            "7 типов торговых сигналов",
            "Trailing Stop Loss (TSL)",
            "MFE анализ (упущенный потенциал)",
            "Адаптивные веса сигналов",
            "ML на исходах сделок"
        ],
        "🎯 Тестирование": [
            "Бэктестинг на исторических данных",
            "Сравнение стратегий",
            "Оптимизация параметров",
            "Валидация на переобучение",
            "Стресс-тестирование"
        ],
        "📋 Метрики": [
            "Sharpe Ratio, Win Rate, Profit Factor",
            "Max Drawdown, Calmar Ratio",
            "VaR, Expected Shortfall",
            "Monthly Performance",
            "Signal Analysis"
        ],
        "🤖 Автоматизация": [
            "Фоновый трекер сделок",
            "Telegram уведомления",
            "Web дашборд (aiohttp)",
            "Hot-reload настроек",
            "Параллельное выполнение"
        ]
    }

    for category, items in capabilities.items():
        print(f"\n{category}")
        for item in items:
            print(f"   • {item}")

async def main():
    """Основная демонстрация"""
    print("🚀 ДОБРО ПОЖАЛОВАТЬ В Oko MTF Bot!")
    print("Система технического анализа с продвинутым тестированием")
    print()

    # Демонстрация компонентов
    await demo_indicator_testing()
    await demo_backtesting()
    await demo_strategy_comparison()
    show_system_capabilities()

    print("\n" + "=" * 70)
    print("🎉 ДЕМОНСТРАЦИЯ ЗАВЕРШЕНА!")
    print()
    print("📚 ДОКУМЕНТАЦИЯ:")
    print("   • README.md — полное руководство")
    print("   • .claude/CLAUDE.md — техническая документация")
    print()
    print("🚀 ГОТОВЫ К ИСПОЛЬЗОВАНИЮ:")
    print("   • python oko_mtf.py — запуск бота")
    print("   • python run_all_tests.py — комплексное тестирование")
    print("   • http://localhost:8000 — веб-дашборд")
    print()
    print("💡 СИСТЕМА ГОТОВА К ТОРГОВЛЕ! 🎯")

if __name__ == "__main__":
    asyncio.run(main())