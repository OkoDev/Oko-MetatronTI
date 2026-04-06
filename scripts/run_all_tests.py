#!/usr/bin/env python3
"""
Быстрый запуск всех тестов системы.
Запуск: python scripts/run_all_tests.py (из корня проекта)
"""
import asyncio
import os
import sys
import time
from datetime import datetime

# Добавляем корень проекта и scripts/ в sys.path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

async def run_indicator_tests():
    """Запуск тестирования индикаторов"""
    print("🧪 Запуск тестирования индикаторов...")
    start_time = time.time()

    try:
        from test_indicators import main as indicator_main
        await indicator_main()
        print(f"✅ Тестирование индикаторов завершено за {time.time() - start_time:.2f} сек")
    except Exception as e:
        print(f"❌ Ошибка тестирования индикаторов: {e}")
        return False

    return True

async def run_backtest():
    """Запуск бэктестинга"""
    print("\n📊 Запуск бэктестинга стратегий...")
    start_time = time.time()

    try:
        from backtesting_engine import run_comprehensive_backtest
        await run_comprehensive_backtest()
        print(f"✅ Бэктестинг завершен за {time.time() - start_time:.2f} сек")
    except Exception as e:
        print(f"❌ Ошибка бэктестинга: {e}")
        return False

    return True

async def run_strategy_comparison():
    """Запуск сравнения стратегий"""
    print("\n🏆 Запуск сравнения стратегий...")
    start_time = time.time()

    try:
        from strategy_comparison import main as comparison_main
        await comparison_main()
        print(f"✅ Сравнение стратегий завершено за {time.time() - start_time:.2f} сек")
    except Exception as e:
        print(f"❌ Ошибка сравнения стратегий: {e}")
        return False

    return True

async def run_tsl_test():
    """Запуск теста TSL"""
    print("\n🎯 Запуск теста TSL...")
    start_time = time.time()

    try:
        from test_tsl import main as tsl_main
        await tsl_main()
        print(f"✅ Тест TSL завершен за {time.time() - start_time:.2f} сек")
    except Exception as e:
        print(f"❌ Ошибка теста TSL: {e}")
        return False

    return True

async def main():
    """Основная функция запуска всех тестов"""
    print("🚀 ЗАПУСК КОМПЛЕКСНОГО ТЕСТИРОВАНИЯ СИСТЕМЫ")
    print("=" * 60)
    print(f"Время начала: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    total_start = time.time()
    results = []

    # Тест 1: Индикаторы
    results.append(await run_indicator_tests())

    # Тест 2: TSL
    results.append(await run_tsl_test())

    # Тест 3: Бэктестинг
    results.append(await run_backtest())

    # Тест 4: Сравнение стратегий
    results.append(await run_strategy_comparison())

    # Итоги
    total_time = time.time() - total_start
    passed = sum(results)
    total = len(results)

    print("\n" + "=" * 60)
    print("📊 ИТОГИ ТЕСТИРОВАНИЯ")
    print("=" * 60)
    print(f"Всего тестов: {total}")
    print(f"Пройдено: {passed}")
    print(f"Провалено: {total - passed}")
    print(f"Общее время: {total_time:.2f} сек")
    print(f"Среднее время на тест: {total_time/total:.1f} сек")
    if passed == total:
        print("✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!")
        print("\n🎯 Система готова к использованию!")
        print("📈 Рекомендуется запустить бота: python bot_with_subscriptions.py")
    else:
        print("⚠️ НЕКОТОРЫЕ ТЕСТЫ ПРОВАЛЕНЫ!")
        print("🔧 Проверьте логи выше и исправьте проблемы.")

    print(f"\nВремя окончания: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    return passed == total

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)