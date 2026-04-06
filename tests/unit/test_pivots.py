
"""
Скрипт для тестирования расчета пивотов
Запуск: python test_pivots.py
"""

import asyncio
import sys
from pathlib import Path

# Добавляем путь к проекту
sys.path.insert(0, str(Path(__file__).parent))

from core.data_collector import RealTimeData
from core.pivot_levels import PivotLevels


async def test_pivots():
    """Тестирует расчет пивотов"""
    print("=" * 60)
    print("🧪 ТЕСТ РАСЧЕТА ПИВОТОВ")
    print("=" * 60)
    
    # Инициализируем
    data_collector = RealTimeData(exchange_id="bingx")
    pivot_calculator = PivotLevels()
    
    try:
        # Загружаем пары
        print("\n⏳ Загрузка рынков...")
        pairs = await data_collector.load_markets()
        
        if not pairs:
            print("❌ Не удалось загрузить пары")
            return
        
        print(f"✅ Загружено {len(pairs)} пар")
        
        # Берем первую пару для теста
        test_symbol = "AVAX/USDT:USDT"
        print(f"\n📊 Тестируем на: {test_symbol}")
        
        # === ТЕСТ 1: Дневные пивоты ===
        print("\n--- ТЕСТ 1: Дневные пивоты (1D) ---")
        
        daily_pivots = await pivot_calculator.get_pivot_levels(
            data_collector, test_symbol, '1D'
        )
        
        if daily_pivots:
            print("✅ Дневные пивоты рассчитаны:")
            print(f"   PP: {daily_pivots.get('PP', 0):.6f}")
            print(f"   S1: {daily_pivots.get('S1', 0):.6f}")
            print(f"   R1: {daily_pivots.get('R1', 0):.6f}")
        else:
            print("❌ Не удалось рассчитать дневные пивоты")
        
        # === ТЕСТ 2: Недельные пивоты ===
        print("\n--- ТЕСТ 2: Недельные пивоты (1W) ---")
        
        weekly_pivots = await pivot_calculator.get_pivot_levels(
            data_collector, test_symbol, '1W'
        )
        
        if weekly_pivots:
            print("✅ Недельные пивоты рассчитаны:")
            print(f"   PP: {weekly_pivots.get('PP', 0):.6f}")
            print(f"   S1: {weekly_pivots.get('S1', 0):.6f}")
            print(f"   S2: {weekly_pivots.get('S2', 0):.6f}")
            print(f"   S3: {weekly_pivots.get('S3', 0):.6f}")
            print(f"   R1: {weekly_pivots.get('R1', 0):.6f}")
            print(f"   R2: {weekly_pivots.get('R2', 0):.6f}")
            print(f"   R3: {weekly_pivots.get('R3', 0):.6f}")
        else:
            print("❌ Не удалось рассчитать недельные пивоты")
        
        # === ТЕСТ 3: Мультитаймфрейм + конфлюэнция ===
        print("\n--- ТЕСТ 3: MTF + конфлюэнция ---")
        
        mtf_pivots = await pivot_calculator.get_multi_timeframe_pivots(
            data_collector, test_symbol
        )
        
        if mtf_pivots and '1W' in mtf_pivots:
            print("✅ MTF пивоты получены")
            
            if '1D' in mtf_pivots:
                print("✅ Дневные тоже получены")
            
            confluence = mtf_pivots.get('confluence', [])
            if confluence:
                print(f"\n⭐ Найдено {len(confluence)} конфлюэнций:")
                for c in confluence[:3]:
                    print(f"   {c['weekly_level']} ≈ {c['daily_level']}: "
                          f"{c['weekly_price']:.6f} ({c['strength']})")
            else:
                print("   Конфлюэнций не найдено")
        else:
            print("❌ Не удалось получить MTF пивоты")
        
        # === ТЕСТ 4: Текущая цена и близость к уровню ===
        print("\n--- ТЕСТ 4: Близость к уровню ---")
        
        df = await data_collector.get_ohlcv(test_symbol, "1m", limit=1)
        
        if df is not None and not df.empty:
            current_price = float(df['close'].iloc[-1])
            print(f"Текущая цена: {current_price:.6f}")
            
            if weekly_pivots:
                near_level = pivot_calculator.is_near_level(
                    current_price, weekly_pivots, threshold_percent=0.5
                )
                
                if near_level:
                    print(f"⚠️  ЦЕНА У УРОВНЯ!")
                    print(f"   Уровень: {near_level['level']} ({near_level['level_type']})")
                    print(f"   Расстояние: {near_level['distance_percent']:.3f}%")
                else:
                    print("   Цена не у уровня (>0.5%)")
        
        print("\n" + "=" * 60)
        print("✅ ВСЕ ТЕСТЫ ЗАВЕРШЕНЫ")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Закрываем соединение
        await data_collector.close()


if __name__ == "__main__":
    try:
        asyncio.run(test_pivots())
    except KeyboardInterrupt:
        print("\n\n⏹  Тест прерван пользователем")
    except Exception as e:
        print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()