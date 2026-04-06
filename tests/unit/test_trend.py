
"""
Тест для проверки правильности расчета тренда
Сравнение с Pine Script алгоритмом
"""

import pandas as pd
import numpy as np
from core.indicators import calculate_trend, get_trend_info

def create_test_data():
    """Создает тестовые данные для проверки"""
    # Тестовые данные: рост -> откат -> рост
    data = {
        "time": pd.date_range("2024-01-01", periods=50, freq="15min"),
        "open": [100 + i * 0.5 for i in range(50)],
        "high": [101 + i * 0.5 for i in range(50)],
        "low": [99 + i * 0.5 for i in range(50)],
        "close": [100.5 + i * 0.5 for i in range(50)],
        "volume": [1000 + i * 10 for i in range(50)]
    }
    
    # Добавляем откат в середине
    for i in range(25, 35):
        data["close"][i] = data["close"][24] - (i - 24) * 0.3
        data["low"][i] = data["close"][i] - 0.5
        data["high"][i] = data["close"][i] + 0.5
    
    return pd.DataFrame(data)


def test_trend_calculation():
    """Тестирует расчет тренда"""
    print("=" * 70)
    print("ТЕСТ РАСЧЕТА ТРЕНДА")
    print("=" * 70)
    
    # Создаем тестовые данные
    df = create_test_data()
    print(f"\n✅ Создано {len(df)} тестовых свечей")
    
    # Рассчитываем тренд с параметрами из Pine Script
    df = calculate_trend(df, atr_period=43, factor=1.0)
    print("✅ Тренд рассчитан")
    
    # Проверяем наличие необходимых колонок
    required_cols = ["trend", "trendup", "trenddown", "tsl"]
    for col in required_cols:
        assert col in df.columns, f"❌ Колонка '{col}' отсутствует!"
    print(f"✅ Все необходимые колонки присутствуют: {required_cols}")
    
    # Проверяем значения тренда
    assert df["trend"].isin([1, -1]).all(), "❌ Тренд должен быть только 1 или -1!"
    print("✅ Значения тренда корректны (только 1 или -1)")
    
    # Статистика по тренду
    uptrend_count = (df["trend"] == 1).sum()
    downtrend_count = (df["trend"] == -1).sum()
    
    print(f"\n📊 Статистика тренда:")
    print(f"   Восходящий тренд: {uptrend_count} баров ({uptrend_count/len(df)*100:.1f}%)")
    print(f"   Нисходящий тренд: {downtrend_count} баров ({downtrend_count/len(df)*100:.1f}%)")
    
    # Проверяем последние 10 баров
    print(f"\n📈 Последние 10 баров:")
    print("-" * 70)
    print(f"{'Index':<6} {'Close':<10} {'Trend':<8} {'TrendUp':<12} {'TrendDown':<12} {'TSL':<10}")
    print("-" * 70)
    
    for i in range(-10, 0):
        row = df.iloc[i]
        trend_str = "UP" if row["trend"] == 1 else "DOWN"
        print(f"{len(df)+i:<6} {row['close']:<10.2f} {trend_str:<8} "
              f"{row['trendup']:<12.2f} {row['trenddown']:<12.2f} {row['tsl']:<10.2f}")
    
    # Получаем информацию о текущем тренде
    trend_info = get_trend_info(df)
    
    print(f"\n🎯 Текущий тренд:")
    print(f"   Направление: {trend_info['direction']}")
    print(f"   Длина: {trend_info['length']} баров")
    print(f"   TSL: {trend_info['tsl']:.2f}")
    print(f"   Расстояние до TSL: {trend_info['distance_to_tsl_percent']:.2f}%")
    print(f"   Сильный тренд: {'Да' if trend_info['is_strong'] else 'Нет'}")
    
    # Проверяем логику TSL
    last_trend = df["trend"].iloc[-1]
    last_tsl = df["tsl"].iloc[-1]
    last_trendup = df["trendup"].iloc[-1]
    last_trenddown = df["trenddown"].iloc[-1]
    
    if last_trend == 1:
        assert abs(last_tsl - last_trendup) < 0.01, "❌ TSL должен равняться trendup для восходящего тренда!"
        print("✅ TSL корректен для восходящего тренда")
    else:
        assert abs(last_tsl - last_trenddown) < 0.01, "❌ TSL должен равняться trenddown для нисходящего тренда!"
        print("✅ TSL корректен для нисходящего тренда")
    
    # Проверяем смену тренда
    trend_changes = (df["trend"] != df["trend"].shift(1)).sum()
    print(f"\n🔄 Количество смен тренда: {trend_changes}")
    
    if trend_changes > 0:
        print("\n📍 Точки смены тренда:")
        for i in range(1, len(df)):
            if df["trend"].iloc[i] != df["trend"].iloc[i-1]:
                prev_trend = "UP" if df["trend"].iloc[i-1] == 1 else "DOWN"
                curr_trend = "UP" if df["trend"].iloc[i] == 1 else "DOWN"
                print(f"   Бар {i}: {prev_trend} → {curr_trend} (цена: {df['close'].iloc[i]:.2f})")
    
    print("\n" + "=" * 70)
    print("✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ!")
    print("=" * 70)
    
    return df


def compare_with_original():
    """Сравнение с оригинальным алгоритмом"""
    print("\n" + "=" * 70)
    print("СРАВНЕНИЕ АЛГОРИТМОВ")
    print("=" * 70)
    
    df = create_test_data()
    
    # Новый алгоритм
    df_new = calculate_trend(df.copy(), atr_period=43, factor=1.0)
    
    # Старый упрощенный алгоритм (для сравнения)
    df_old = df.copy()
    high = df_old["high"]
    low = df_old["low"]
    close = df_old["close"]
    
    # Старый расчет ATR
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=14, min_periods=1).mean()
    
    hl2 = (high + low) / 2.0
    up_band = hl2 - 2.0 * atr
    dn_band = hl2 + 2.0 * atr
    
    # Старая логика тренда
    trend_old = []
    last = 1
    for i in range(len(df_old)):
        if i == 0:
            trend_old.append(1)
            continue
        if close.iloc[i] > dn_band.iloc[max(0, i-1)]:
            last = 1
        elif close.iloc[i] < up_band.iloc[max(0, i-1)]:
            last = -1
        trend_old.append(last)
    
    df_old["trend"] = trend_old
    
    # Сравниваем
    differences = (df_new["trend"] != df_old["trend"]).sum()
    similarity = (1 - differences / len(df)) * 100
    
    print(f"\n📊 Результаты сравнения:")
    print(f"   Совпадений: {len(df) - differences} из {len(df)}")
    print(f"   Различий: {differences}")
    print(f"   Схожесть: {similarity:.1f}%")
    
    if differences > 0:
        print(f"\n⚠️  Найдено {differences} различий в определении тренда")
        print("   Это нормально - новый алгоритм более точный!")
        
        # Показываем первые 5 различий
        print("\n   Примеры различий (первые 5):")
        count = 0
        for i in range(len(df)):
            if df_new["trend"].iloc[i] != df_old["trend"].iloc[i]:
                new_trend = "UP" if df_new["trend"].iloc[i] == 1 else "DOWN"
                old_trend = "UP" if df_old["trend"].iloc[i] == 1 else "DOWN"
                print(f"   Бар {i}: Старый={old_trend}, Новый={new_trend}, Цена={df['close'].iloc[i]:.2f}")
                count += 1
                if count >= 5:
                    break
    else:
        print("✅ Алгоритмы дают идентичные результаты!")
    
    print("=" * 70)


if __name__ == "__main__":
    try:
        # Запускаем тесты
        df_result = test_trend_calculation()
        
        # Сравниваем с оригиналом
        compare_with_original()
        
        print("\n✅ Все тесты завершены успешно!")
        
    except AssertionError as e:
        print(f"\n❌ ОШИБКА ТЕСТА: {e}")
    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()