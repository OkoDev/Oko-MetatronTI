"""
Тест исправленного детектора дивергенций
Проверяет работу по алгоритму из Pine Script
"""

import asyncio
import sys
from pathlib import Path
import pandas as pd

# Добавляем путь к проекту
sys.path.insert(0, str(Path(__file__).parent))

from core.data_collector import RealTimeData
from core.divergence_detector import DivergenceDetector
from core.indicators import calculate_wt


def print_divergence_details(div_info, symbol):
    """Красивый вывод информации о дивергенции"""
    if not div_info:
        print("❌ Дивергенция не найдена")
        return
    
    print("\n" + "="*70)
    print(f"✅ НАЙДЕНА ДИВЕРГЕНЦИЯ: {symbol}")
    print("="*70)
    
    print(f"\n📊 Тип: {div_info['type']}")
    print(f"📊 Направление: {div_info['direction']}")
    print(f"📊 Сила: {div_info['strength']}/100")
    print(f"📊 Таймфрейм: {div_info['timeframe']}")
    print(f"📊 Описание: {div_info['description']}")
    
    details = div_info.get('details', {})
    if details:
        print(f"\n🔍 Детали:")
        print(f"  • Расстояние: {details['distance']} баров")
        print(f"  • WT текущий: {details['ind_current']:.2f}")
        print(f"  • WT пивот: {details['ind_pivot']:.2f}")
        print(f"  • Изменение WT: {details['ind_change']:+.2f}")
        print(f"  • Цена текущая: {details['price_current']:.6f}")
        print(f"  • Цена пивот: {details['price_pivot']:.6f}")
        print(f"  • Изменение цены: {details['price_change_pct']:+.2f}%")
        
        # Проверка зон
        print(f"\n🎯 Проверка зон:")
        if 'BULLISH' in div_info['type']:
            curr_in_os = details['ind_current'] < -60
            pivot_in_os = details['ind_pivot'] < -60
            print(f"  • Текущий WT в OS (<-60): {'✅' if curr_in_os else '❌'}")
            print(f"  • Пивот WT в OS (<-60): {'✅' if pivot_in_os else '❌'}")
            
            if curr_in_os and pivot_in_os:
                print(f"  • 🎉 ОБА в зоне OS - СИЛЬНЫЙ сигнал!")
            else:
                print(f"  • ⚠️ Не оба в OS - сигнал СЛАБЕЕ")
        
        elif 'BEARISH' in div_info['type']:
            curr_in_ob = details['ind_current'] > 60
            pivot_in_ob = details['ind_pivot'] > 60
            print(f"  • Текущий WT в OB (>60): {'✅' if curr_in_ob else '❌'}")
            print(f"  • Пивот WT в OB (>60): {'✅' if pivot_in_ob else '❌'}")
            
            if curr_in_ob and pivot_in_ob:
                print(f"  • 🎉 ОБА в зоне OB - СИЛЬНЫЙ сигнал!")
            else:
                print(f"  • ⚠️ Не оба в OB - сигнал СЛАБЕЕ")
    
    # Интерпретация силы
    strength = div_info['strength']
    print(f"\n💪 Оценка силы:")
    if strength >= 75:
        print(f"  🔥🔥🔥 Очень сильная ({strength}/100)")
        print(f"  ✅ Можно входить стандартным объемом")
    elif strength >= 60:
        print(f"  🔥🔥 Сильная ({strength}/100)")
        print(f"  ✅ Хороший сигнал для входа")
    elif strength >= 40:
        print(f"  🔥 Средняя ({strength}/100)")
        print(f"  ⚠️ Требуется подтверждение")
    else:
        print(f"  ⚠️ Слабая ({strength}/100)")
        print(f"  ❌ Не рекомендуется вход")


async def _run_single_pair(symbol, timeframe="1h"):
    """Тестирует поиск дивергенций на одной паре"""
    print(f"\n{'='*70}")
    print(f"ТЕСТ: {symbol} на {timeframe}")
    print(f"{'='*70}")
    
    # Инициализируем
    data_collector = RealTimeData(exchange_id="bingx")
    detector = DivergenceDetector(
        pivot_period=5,
        max_pivot_points=10,
        max_bars=100,
        min_bars_between=5
    )
    
    try:
        # Загружаем рынки
        print("\n⏳ Загрузка рынков...")
        await data_collector.load_markets()
        
        # Ищем дивергенцию
        print(f"⏳ Поиск дивергенций на {symbol}...")
        has_div, div_info = await detector.detect_divergence(
            symbol, data_collector, timeframe=timeframe
        )
        
        if has_div:
            print_divergence_details(div_info, symbol)
        else:
            print(f"❌ Дивергенций не найдено на {symbol} {timeframe}")
        
    except Exception as e:
        print(f"❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await data_collector.close()


async def test_multiple_pairs():
    """Сканирует несколько популярных пар"""
    print("\n" + "="*70)
    print("🔍 МАССОВОЕ СКАНИРОВАНИЕ ДИВЕРГЕНЦИЙ")
    print("="*70)
    
    # Популярные пары для теста
    test_pairs = [
        "BTC/USDT:USDT",
        "ETH/USDT:USDT",
        "SOL/USDT:USDT",
        "BNB/USDT:USDT",
        "XRP/USDT:USDT",
        "ADA/USDT:USDT",
        "AVAX/USDT:USDT",
        "DOT/USDT:USDT",
        "MATIC/USDT:USDT",
        "LINK/USDT:USDT"
    ]
    
    timeframes = ["1h", "15m"]
    
    data_collector = RealTimeData(exchange_id="bingx")
    detector = DivergenceDetector(
        pivot_period=5,
        max_pivot_points=10,
        max_bars=100,
        min_bars_between=5
    )
    
    try:
        print("\n⏳ Загрузка рынков...")
        await data_collector.load_markets()
        
        found_count = 0
        
        for symbol in test_pairs:
            for tf in timeframes:
                try:
                    print(f"\n🔍 Проверяем {symbol} на {tf}...", end=" ")
                    
                    has_div, div_info = await detector.detect_divergence(
                        symbol, data_collector, timeframe=tf
                    )
                    
                    if has_div:
                        found_count += 1
                        print(f"✅ НАЙДЕНА!")
                        print_divergence_details(div_info, f"{symbol} {tf}")
                    else:
                        print("❌")
                    
                except Exception as e:
                    print(f"⚠️ Ошибка: {e}")
                
                # Небольшая задержка между запросами
                await asyncio.sleep(0.5)
        
        print("\n" + "="*70)
        print(f"📊 ИТОГО: Найдено {found_count} дивергенций")
        print("="*70)
        
    except Exception as e:
        print(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await data_collector.close()


async def test_with_manual_data():
    """
    Тест с вручную созданными данными
    Проверяем что алгоритм правильно определяет дивергенции
    """
    print("\n" + "="*70)
    print("🧪 ТЕСТ С СИНТЕТИЧЕСКИМИ ДАННЫМИ")
    print("="*70)
    
    detector = DivergenceDetector(
        pivot_period=3,
        max_pivot_points=10,
        max_bars=50,
        min_bars_between=5
    )
    
    # === ТЕСТ 1: Regular Bearish (HH цена, LH индикатор) ===
    print("\n📊 ТЕСТ 1: Regular Bearish Divergence")
    print("-" * 70)
    
    # Создаем данные
    data = {
        'time': range(50),
        'open': [100 + i * 0.5 for i in range(50)],
        'high': [101 + i * 0.5 for i in range(50)],
        'low': [99 + i * 0.5 for i in range(50)],
        'close': [100.5 + i * 0.5 for i in range(50)],
        'volume': [1000] * 50
    }
    
    df = pd.DataFrame(data)
    df = calculate_wt(df, n1=10, n2=21)
    
    # Вручную создаем паттерн Regular Bearish:
    # Индекс 20: WT = 75, цена = 110
    # Индекс 40: WT = 65, цена = 120 (HH цена, LH индикатор)
    df.loc[20, 'wt1'] = 75.0
    df.loc[40, 'wt1'] = 65.0
    df.loc[20, 'high'] = 110.0
    df.loc[40, 'high'] = 120.0
    
    # Делаем пивоты явными (окружаем меньшими значениями)
    for i in range(15, 25):
        if i != 20:
            df.loc[i, 'wt1'] = 70.0
            df.loc[i, 'high'] = 105.0
    
    for i in range(35, 45):
        if i != 40:
            df.loc[i, 'wt1'] = 60.0
            df.loc[i, 'high'] = 115.0
    
    # Проверяем детекцию
    result = detector.detect_regular_bearish(df, indicator_col='wt1')
    
    if result:
        print("✅ Дивергенция НАЙДЕНА!")
        print(f"  • WT: {result['ind_pivot']:.1f} → {result['ind_current']:.1f} (LH)")
        print(f"  • Цена: {result['price_pivot']:.2f} → {result['price_current']:.2f} (HH)")
        print(f"  • Расстояние: {result['distance']} баров")
        
        strength = detector._calculate_strength(result, 'REGULAR_BEARISH')
        print(f"  • Сила: {strength}/100")
        
        if result['ind_current'] > 60 and result['ind_pivot'] > 60:
            print(f"  • ✅ ОБА в зоне OB - правильно!")
        else:
            print(f"  • ⚠️ Не оба в OB")
    else:
        print("❌ Дивергенция НЕ НАЙДЕНА (ошибка алгоритма?)")
    
    # === ТЕСТ 2: Regular Bullish (LL цена, HL индикатор) ===
    print("\n📊 ТЕСТ 2: Regular Bullish Divergence")
    print("-" * 70)
    
    data2 = {
        'time': range(50),
        'open': [100 - i * 0.3 for i in range(50)],
        'high': [101 - i * 0.3 for i in range(50)],
        'low': [99 - i * 0.3 for i in range(50)],
        'close': [100 - i * 0.3 for i in range(50)],
        'volume': [1000] * 50
    }
    
    df2 = pd.DataFrame(data2)
    df2 = calculate_wt(df2, n1=10, n2=21)
    
    # Индекс 20: WT = -70, цена = 94
    # Индекс 40: WT = -65, цена = 88 (LL цена, HL индикатор)
    df2.loc[20, 'wt1'] = -70.0
    df2.loc[40, 'wt1'] = -65.0
    df2.loc[20, 'low'] = 94.0
    df2.loc[40, 'low'] = 88.0
    
    for i in range(15, 25):
        if i != 20:
            df2.loc[i, 'wt1'] = -68.0
            df2.loc[i, 'low'] = 95.0
    
    for i in range(35, 45):
        if i != 40:
            df2.loc[i, 'wt1'] = -67.0
            df2.loc[i, 'low'] = 90.0
    
    result2 = detector.detect_regular_bullish(df2, indicator_col='wt1')
    
    if result2:
        print("✅ Дивергенция НАЙДЕНА!")
        print(f"  • WT: {result2['ind_pivot']:.1f} → {result2['ind_current']:.1f} (HL)")
        print(f"  • Цена: {result2['price_pivot']:.2f} → {result2['price_current']:.2f} (LL)")
        print(f"  • Расстояние: {result2['distance']} баров")
        
        strength2 = detector._calculate_strength(result2, 'REGULAR_BULLISH')
        print(f"  • Сила: {strength2}/100")
        
        if result2['ind_current'] < -60 and result2['ind_pivot'] < -60:
            print(f"  • ✅ ОБА в зоне OS - правильно!")
        else:
            print(f"  • ⚠️ Не оба в OS")
    else:
        print("❌ Дивергенция НЕ НАЙДЕНА (ошибка алгоритма?)")
    
    print("\n" + "="*70)


async def main():
    """Главная функция"""
    print("\n" + "="*70)
    print("🚀 ТЕСТ ДЕТЕКТОРА ДИВЕРГЕНЦИЙ (Pine Script алгоритм)")
    print("="*70)
    
    # Выбираем режим теста
    print("\nВыберите режим теста:")
    print("1. Тест на одной паре (EDU/USDT)")
    print("2. Массовое сканирование (10 топ пар)")
    print("3. Тест с синтетическими данными")
    print("4. Все тесты")
    
    choice = input("\nВведите номер (1-4): ").strip()
    
    if choice == "1":
        await test_single_pair("EDU/USDT:USDT", "1h")
    
    elif choice == "2":
        await test_multiple_pairs()
    
    elif choice == "3":
        await test_with_manual_data()
    
    elif choice == "4":
        print("\n🔥 ЗАПУСК ВСЕХ ТЕСТОВ")
        await test_with_manual_data()
        await test_single_pair("EDU/USDT:USDT", "1h")
        await test_multiple_pairs()
    
    else:
        print("❌ Неверный выбор, запускаем тест на одной паре...")
        await test_single_pair("EDU/USDT:USDT", "1h")
    
    print("\n✅ ВСЕ ТЕСТЫ ЗАВЕРШЕНЫ!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⏹  Тест прерван пользователем")
    except Exception as e:
        print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()