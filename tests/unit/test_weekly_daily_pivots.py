"""
Тест получения НЕДЕЛЬНЫХ и ДНЕВНЫХ пивотов
Запуск: python test_weekly_daily_pivots.py
"""

import asyncio
import sys
from pathlib import Path
import logging

# Добавляем путь к проекту
sys.path.insert(0, str(Path(__file__).parent))

from core.data_collector import RealTimeData
from core.pivot_calculator_fixed import PivotCalculatorFixed

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


async def test_weekly_daily_pivots():
    """Тестирование недельных и дневных пивотов"""
    
    print("=" * 70)
    print("🧪 ТЕСТ НЕДЕЛЬНЫХ И ДНЕВНЫХ ПИВОТОВ")
    print("=" * 70)
    print()
    
    # Инициализация
    data_collector = RealTimeData(exchange_id="bingx")
    pivot_calculator = PivotCalculatorFixed()
    
    try:
        # Загрузка рынков
        print("⏳ Загрузка рынков...")
        pairs = await data_collector.load_markets()
        
        if not pairs:
            print("❌ Не удалось загрузить пары")
            return
        
        print(f"✅ Загружено {len(pairs)} пар")
        print()
        
        # Тестируем на нескольких популярных парах
        test_symbols = [
            pairs[0],  # Первая пара
            "BTC/USDT:USDT" if "BTC/USDT:USDT" in pairs else pairs[1],
            "ETH/USDT:USDT" if "ETH/USDT:USDT" in pairs else pairs[2],
        ]
        
        for symbol in test_symbols:
            print("=" * 70)
            print(f"📊 Тестирование: {symbol}")
            print("=" * 70)
            
            # Получаем текущую цену
            df_current = await data_collector.get_ohlcv(symbol, "1m", limit=1)
            if df_current is not None and not df_current.empty:
                current_price = float(df_current['close'].iloc[-1])
                print(f"💰 Текущая цена: {current_price:.6f}")
            else:
                current_price = 0
                print("⚠️  Не удалось получить текущую цену")
            
            print()
            
            # === ТЕСТ 1: Недельные пивоты ===
            print("--- ТЕСТ 1: Недельные пивоты (1W) ---")
            
            weekly = await pivot_calculator.get_weekly_pivots(symbol, data_collector)
            
            if weekly:
                print(f"✅ Недельные пивоты рассчитаны")
                print(f"   Метод: {weekly.get('method', 'N/A')}")
                print(f"   PP: {weekly.get('PP', 0):.6f}")
                print(f"   S1: {weekly.get('S1', 0):.6f}")
                print(f"   S2: {weekly.get('S2', 0):.6f}")
                print(f"   S3: {weekly.get('S3', 0):.6f}")
                print(f"   R1: {weekly.get('R1', 0):.6f}")
                print(f"   R2: {weekly.get('R2', 0):.6f}")
                print(f"   R3: {weekly.get('R3', 0):.6f}")
            else:
                print("❌ Не удалось рассчитать недельные пивоты")
            
            print()
            
            # === ТЕСТ 2: Дневные пивоты ===
            print("--- ТЕСТ 2: Дневные пивоты (1D) ---")
            
            daily = await pivot_calculator.get_daily_pivots(symbol, data_collector)
            
            if daily:
                print(f"✅ Дневные пивоты рассчитаны")
                print(f"   Метод: {daily.get('method', 'N/A')}")
                print(f"   PP: {daily.get('PP', 0):.6f}")
                print(f"   S1: {daily.get('S1', 0):.6f}")
                print(f"   S2: {daily.get('S2', 0):.6f}")
                print(f"   S3: {daily.get('S3', 0):.6f}")
                print(f"   R1: {daily.get('R1', 0):.6f}")
                print(f"   R2: {daily.get('R2', 0):.6f}")
                print(f"   R3: {daily.get('R3', 0):.6f}")
            else:
                print("❌ Не удалось рассчитать дневные пивоты")
            
            print()
            
            # === ТЕСТ 3: MTF + конфлюэнции ===
            print("--- ТЕСТ 3: MTF (1W + 1D) + Конфлюэнции ---")
            
            mtf_pivots = await pivot_calculator.get_multi_timeframe_pivots(
                symbol, data_collector
            )
            
            if mtf_pivots:
                print(f"✅ MTF пивоты получены")
                print(f"   Недельные: {'Да' if '1W' in mtf_pivots else 'Нет'}")
                print(f"   Дневные: {'Да' if '1D' in mtf_pivots else 'Нет'}")
                
                confluences = mtf_pivots.get('confluence', [])
                if confluences:
                    print(f"\n🎯 Найдено {len(confluences)} конфлюэнций:")
                    for i, conf in enumerate(confluences[:3], 1):
                        print(f"   {i}. {conf['weekly_level']} (1W) ≈ {conf['daily_level']} (1D)")
                        print(f"      Цена: {conf['weekly_price']:.6f}")
                        print(f"      Расстояние: {conf['distance_percent']:.3f}%")
                        print(f"      Сила: {conf['strength']}")
                else:
                    print("   Конфлюэнций не найдено (это нормально)")
            else:
                print("❌ Не удалось получить MTF пивоты")
            
            print()
            
            # === ТЕСТ 4: Близость к уровню ===
            if current_price > 0 and weekly:
                print("--- ТЕСТ 4: Близость к недельным уровням ---")
                
                near = pivot_calculator.is_near_level(
                    current_price,
                    weekly,
                    threshold_percent=0.5
                )
                
                if near:
                    print(f"⚠️  ЦЕНА БЛИЗКО К УРОВНЮ!")
                    print(f"   Уровень: {near['level']} ({near['level_type']})")
                    print(f"   Цена уровня: {near['price']:.6f}")
                    print(f"   Расстояние: {near['distance_percent']:.3f}%")
                    print(f"   → Потенциальная точка входа!")
                else:
                    print("   Цена не рядом с уровнями (>0.5%)")
                
                # Показываем ближайшие уровни
                nearest = pivot_calculator.get_nearest_levels(current_price, weekly, count=2)
                
                if nearest['resistance']:
                    print(f"\n   🔴 Ближайшее сопротивление:")
                    for name, price, dist in nearest['resistance'][:1]:
                        print(f"      {name}: {price:.6f} (+{dist:.2f}%)")
                
                if nearest['support']:
                    print(f"   🟢 Ближайшая поддержка:")
                    for name, price, dist in nearest['support'][:1]:
                        print(f"      {name}: {price:.6f} (-{dist:.2f}%)")
            
            print()
            
            # === ТЕСТ 5: Полное сообщение ===
            if current_price > 0 and mtf_pivots:
                print("--- ТЕСТ 5: Форматированное сообщение ---")
                
                message = pivot_calculator.format_pivot_message(
                    symbol,
                    mtf_pivots,
                    current_price
                )
                
                print("✅ Сообщение сформировано:")
                print()
                print(message)
            
            print()
            print()
        
        # === ИТОГОВАЯ СТАТИСТИКА ===
        print("=" * 70)
        print("📊 ИТОГОВАЯ СТАТИСТИКА")
        print("=" * 70)
        
        success_count = 0
        failed_count = 0
        
        for symbol in test_symbols[:5]:  # Проверяем первые 5 пар
            try:
                mtf = await pivot_calculator.get_multi_timeframe_pivots(
                    symbol, data_collector
                )
                if mtf and '1W' in mtf:
                    success_count += 1
                else:
                    failed_count += 1
            except Exception:
                failed_count += 1
        
        total = success_count + failed_count
        success_rate = (success_count / total * 100) if total > 0 else 0
        
        print(f"Проверено пар: {total}")
        print(f"Успешно: {success_count}")
        print(f"Ошибок: {failed_count}")
        print(f"Процент успеха: {success_rate:.1f}%")
        print()
        
        if success_rate >= 80:
            print("✅ ОТЛИЧНО! Система работает стабильно")
        elif success_rate >= 50:
            print("⚠️  УДОВЛЕТВОРИТЕЛЬНО. Некоторые пары могут не работать")
        else:
            print("❌ ПРОБЛЕМЫ. Требуется дополнительная настройка")
        
    except Exception as e:
        print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Закрываем соединение
        await data_collector.close()
        print()
        print("=" * 70)
        print("✅ ТЕСТЫ ЗАВЕРШЕНЫ")
        print("=" * 70)


async def quick_test():
    """Быстрый тест одной пары"""
    print("🚀 БЫСТРЫЙ ТЕСТ")
    print("=" * 70)
    
    data_collector = RealTimeData(exchange_id="bingx")
    pivot_calculator = PivotCalculatorFixed()
    
    try:
        pairs = await data_collector.load_markets()
        if not pairs:
            print("❌ Не удалось загрузить пары")
            return
        
        symbol = pairs[0]
        print(f"Тестируем: {symbol}")
        print()
        
        # Получаем пивоты
        mtf_pivots = await pivot_calculator.get_multi_timeframe_pivots(
            symbol, data_collector
        )
        
        if mtf_pivots and '1W' in mtf_pivots:
            print("✅ УСПЕХ!")
            print(f"   Недельные: PP = {mtf_pivots['1W']['PP']:.6f}")
            if '1D' in mtf_pivots:
                print(f"   Дневные: PP = {mtf_pivots['1D']['PP']:.6f}")
            
            confluences = mtf_pivots.get('confluence', [])
            if confluences:
                print(f"   Конфлюэнций: {len(confluences)}")
        else:
            print("❌ ОШИБКА: не удалось получить пивоты")
        
    except Exception as e:
        print(f"❌ ОШИБКА: {e}")
    finally:
        await data_collector.close()


if __name__ == "__main__":
    import sys
    
    # Можно запустить с аргументом --quick для быстрого теста
    if len(sys.argv) > 1 and sys.argv[1] == "--quick":
        asyncio.run(quick_test())
    else:
        asyncio.run(test_weekly_daily_pivots())