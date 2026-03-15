#!/usr/bin/env python3
"""
Тестирование всех индикаторов на исторических данных
"""
import asyncio
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any

from core.data_collector import RealTimeData
from core.indicators import (
    calculate_trend, calculate_wt, get_trend_info,
    calculate_trend_strength, detect_fvg
)
from core.signal_checkers import check_anomaly_signals, check_divergence_signals
from core.market_regime import MarketRegimeClassifier

logger = logging.getLogger(__name__)


class IndicatorTester:
    """
    Тестирование всех индикаторов на исторических данных
    """

    def __init__(self, symbol: str = "BTC/USDT", timeframe: str = "1h"):
        self.symbol = symbol
        self.timeframe = timeframe
        self.data_collector = RealTimeData()

    async def load_test_data(self, days: int = 90) -> pd.DataFrame:
        """
        Загружает тестовые данные за последние N дней
        """
        print(f"📥 Загрузка данных {self.symbol} за {days} дней...")

        # Конвертируем в timestamp
        end_time = datetime.now(timezone.utc)
        start_time = end_time - pd.Timedelta(days=days)
        since = int(start_time.timestamp() * 1000)

        all_data = []
        current_since = since
        batch_size = 1000

        while True:
            try:
                df_batch = await self.data_collector.get_ohlcv(
                    self.symbol, self.timeframe, limit=batch_size, since=current_since
                )

                if df_batch is None or df_batch.empty:
                    break

                all_data.append(df_batch)

                # Обновляем since для следующей пачки
                last_time = df_batch['time'].max()
                current_since = int(last_time) + 1

                # Не перегружаем API
                await asyncio.sleep(0.1)

            except Exception as e:
                logger.error(f"Ошибка загрузки: {e}")
                break

        if not all_data:
            raise ValueError("Не удалось загрузить данные")

        # Объединяем и чистим
        df = pd.concat(all_data, ignore_index=True)
        df = df.drop_duplicates(subset=['time']).sort_values('time')
        df['datetime'] = pd.to_datetime(df['time'], unit='ms', utc=True)

        print(f"✅ Загружено {len(df)} свечей")
        return df

    def test_trend_indicators(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Тестирование трендовых индикаторов
        """
        print("📈 Тестирование трендовых индикаторов...")

        # Расчет тренда
        df_trend = calculate_trend(df.copy())
        df_trend = calculate_trend_strength(df_trend)

        # Анализ трендов
        trend_changes = []
        current_trend = None

        for i in range(1, len(df_trend)):
            prev_trend = df_trend.iloc[i-1]['trend']
            curr_trend = df_trend.iloc[i]['trend']

            if prev_trend != curr_trend:
                trend_changes.append({
                    'datetime': df_trend.iloc[i]['datetime'],
                    'from_trend': 'UP' if prev_trend == 1 else 'DOWN',
                    'to_trend': 'UP' if curr_trend == 1 else 'DOWN',
                    'strength': df_trend.iloc[i]['trend_strength']
                })

        # Статистика трендов
        up_trends = len(df_trend[df_trend['trend'] == 1])
        down_trends = len(df_trend[df_trend['trend'] == -1])
        total_bars = len(df_trend)

        # Анализ TSL
        tsl_analysis = []
        for i in range(-10, 0):  # Последние 10 свечей
            if i == -1:
                continue
            trend_info = get_trend_info(df_trend.iloc[:i])
            if trend_info:
                tsl_analysis.append({
                    'datetime': df_trend.iloc[i]['datetime'],
                    'trend': trend_info['direction'],
                    'tsl': trend_info['tsl'],
                    'distance_pct': trend_info['distance_to_tsl_percent'],
                    'strength': trend_info['is_strong']
                })

        return {
            'trend_distribution': {
                'up_trend_pct': round(up_trends / total_bars * 100, 1),
                'down_trend_pct': round(down_trends / total_bars * 100, 1)
            },
            'trend_changes': len(trend_changes),
            'avg_trend_length': round(total_bars / len(trend_changes), 1) if trend_changes else 0,
            'tsl_analysis': tsl_analysis[-5:],  # Последние 5
            'trend_changes_sample': trend_changes[-3:]  # Последние 3 изменения
        }

    def test_wt_indicator(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Тестирование WT индикатора
        """
        print("🌊 Тестирование WT индикатора...")

        df_wt = calculate_wt(df.copy())

        # Анализ зон
        zones = []
        signals = []

        for i in range(4, len(df_wt)):  # WT2 начинается с 4-го бара
            wt1 = df_wt.iloc[i]['wt1']
            wt2 = df_wt.iloc[i]['wt2']

            # Определяем зону
            if wt2 >= 60:
                zone = 'OB'
            elif wt2 <= -60:
                zone = 'OS'
            else:
                zone = 'N'

            zones.append({
                'datetime': df_wt.iloc[i]['datetime'],
                'wt1': round(wt1, 2),
                'wt2': round(wt2, 2),
                'zone': zone
            })

            # Ищем сигналы
            if i > 4:
                prev_wt2 = df_wt.iloc[i-1]['wt2']

                # Бычий сигнал
                if prev_wt2 <= -60 and wt2 > -60 and wt1 > wt2:
                    signals.append({
                        'datetime': df_wt.iloc[i]['datetime'],
                        'type': 'BULLISH',
                        'price': df_wt.iloc[i]['close']
                    })

                # Медвежий сигнал
                elif prev_wt2 >= 60 and wt2 < 60 and wt1 < wt2:
                    signals.append({
                        'datetime': df_wt.iloc[i]['datetime'],
                        'type': 'BEARISH',
                        'price': df_wt.iloc[i]['close']
                    })

        # Статистика зон
        zone_counts = {}
        for zone_data in zones:
            zone = zone_data['zone']
            zone_counts[zone] = zone_counts.get(zone, 0) + 1

        return {
            'total_signals': len(signals),
            'zone_distribution': {k: round(v/len(zones)*100, 1) for k, v in zone_counts.items()},
            'recent_signals': signals[-5:],  # Последние 5 сигналов
            'wt_stats': {
                'wt1_mean': round(df_wt['wt1'].mean(), 2),
                'wt1_std': round(df_wt['wt1'].std(), 2),
                'wt2_mean': round(df_wt['wt2'].mean(), 2),
                'wt2_std': round(df_wt['wt2'].std(), 2)
            }
        }

    def test_divergence_detector(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Тестирование детектора дивергенций через check_divergence_signals
        """
        print("🔄 Тестирование детектора дивергенций...")

        divergences = []
        WINDOW = 50

        for i in range(WINDOW, len(df), 10):  # Каждые 10 свечей для скорости
            context_df = df.iloc[i-WINDOW:i+1].reset_index(drop=True)
            try:
                import asyncio
                sigs = asyncio.get_event_loop().run_until_complete(
                    check_divergence_signals(self.symbol, context_df)
                )
                for sig in sigs:
                    divergences.append({
                        'datetime': df.iloc[i].get('datetime', i),
                        'type': sig.signal_type.value,
                        'direction': sig.direction.value,
                        'strength': sig.strength
                    })
            except Exception as e:
                logger.debug(f"Ошибка анализа дивергенций: {e}")

        div_types: Dict[str, int] = {}
        for div in divergences:
            div_type = div['type']
            div_types[div_type] = div_types.get(div_type, 0) + 1

        return {
            'total_divergences': len(divergences),
            'divergence_types': div_types,
            'recent_divergences': divergences[-5:],
            'avg_per_100bars': round(len(divergences) / max(1, len(df) // 100), 1)
        }

    def test_anomaly_detector(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Тестирование детектора аномалий через check_anomaly_signals
        """
        print("🚨 Тестирование детектора аномалий...")

        import asyncio
        anomalies = []
        WINDOW = 50

        for i in range(WINDOW, len(df), 5):
            context_df = df.iloc[i-WINDOW:i+1].reset_index(drop=True)
            try:
                sigs = asyncio.get_event_loop().run_until_complete(
                    check_anomaly_signals(self.symbol, context_df)
                )
                for sig in sigs:
                    anomalies.append({
                        'datetime': df.iloc[i].get('datetime', i),
                        'type': sig.signal_type.value,
                        'direction': sig.direction.value,
                        'strength': sig.strength
                    })
            except Exception as e:
                logger.debug(f"Ошибка анализа аномалий: {e}")

        return {
            'total_anomalies': len(anomalies),
            'recent_anomalies': anomalies[-5:],
            'anomaly_rate': round(len(anomalies) / max(1, len(df)) * 100, 2)
        }

    def test_fvg_detector(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Тестирование детектора FVG
        """
        print("🎯 Тестирование детектора FVG...")

        fvgs = []

        for i in range(2, len(df)):
            context_df = df.iloc[i-2:i+1]
            fvg_type, entry_price = detect_fvg(context_df)

            if fvg_type:
                fvgs.append({
                    'datetime': df.iloc[i]['datetime'],
                    'type': fvg_type,
                    'entry_price': entry_price,
                    'high': context_df.iloc[0]['high'],
                    'low': context_df.iloc[0]['low']
                })

        fvg_types = {}
        for fvg in fvgs:
            fvg_type = fvg['type']
            fvg_types[fvg_type] = fvg_types.get(fvg_type, 0) + 1

        return {
            'total_fvgs': len(fvgs),
            'fvg_types': fvg_types,
            'recent_fvgs': fvgs[-5:],
            'fvg_rate': round(len(fvgs) / len(df) * 100, 2)
        }

    def test_market_regime(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Тестирование классификатора рыночных режимов
        """
        print("📊 Тестирование классификатора рыночных режимов...")

        classifier = MarketRegimeClassifier()
        regimes = []

        for i in range(50, len(df), 10):  # Каждые 10 свечей
            context_df = df.iloc[max(0, i-50):i+1]
            try:
                regime = classifier.classify_from_ohlcv(context_df)
                if regime:
                    regimes.append({
                        'datetime': df.iloc[i]['datetime'],
                        'regime': regime
                    })
            except Exception as e:
                logger.debug(f"Ошибка классификации режима: {e}")

        regime_counts = {}
        for reg in regimes:
            regime = reg['regime']
            regime_counts[regime] = regime_counts.get(regime, 0) + 1

        return {
            'total_classifications': len(regimes),
            'regime_distribution': {k: round(v/len(regimes)*100, 1) for k, v in regime_counts.items()} if regimes else {},
            'recent_regimes': regimes[-5:]
        }

    async def run_full_test(self) -> Dict[str, Any]:
        """
        Запускает полный тест всех индикаторов
        """
        print("🧪 Запуск комплексного тестирования индикаторов\n")

        # Загружаем данные
        df = await self.load_test_data(days=30)  # 30 дней для быстрого тестирования

        # Тестируем все индикаторы
        results = {
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'data_points': len(df),
            'date_range': {
                'start': df['datetime'].min().strftime('%Y-%m-%d'),
                'end': df['datetime'].max().strftime('%Y-%m-%d')
            },
            'trend_indicators': self.test_trend_indicators(df),
            'wt_indicator': self.test_wt_indicator(df),
            'divergence_detector': self.test_divergence_detector(df),
            'anomaly_detector': self.test_anomaly_detector(df),
            'fvg_detector': self.test_fvg_detector(df),
            'market_regime': self.test_market_regime(df)
        }

        return results

    def print_results(self, results: Dict[str, Any]):
        """
        Выводит результаты тестирования в читаемом формате
        """
        print("\n" + "="*60)
        print("📊 РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ ИНДИКАТОРОВ")
        print("="*60)

        print(f"📈 Символ: {results['symbol']}")
        print(f"⏰ Таймфрейм: {results['timeframe']}")
        print(f"📊 Данных: {results['data_points']} свечей")
        print(f"📅 Период: {results['date_range']['start']} — {results['date_range']['end']}")
        print()

        # Трендовые индикаторы
        trend = results['trend_indicators']
        print("📈 ТРЕНДОВЫЕ ИНДИКАТОРЫ:")
        print(f"   Распределение: UP {trend['trend_distribution']['up_trend_pct']}%, DOWN {trend['trend_distribution']['down_trend_pct']}%")
        print(f"   Изменений тренда: {trend['trend_changes']}")
        print(f"   Средняя длина тренда: {trend['avg_trend_length']} баров")
        print("   TSL анализ (последние):")
        for tsl in trend['tsl_analysis'][-3:]:
            print(f"     {tsl['datetime'].strftime('%m-%d %H:%M')}: {tsl['trend']} TSL:{tsl['tsl']:.2f} ({tsl['distance_pct']:.1f}%)")
        print()

        # WT индикатор
        wt = results['wt_indicator']
        print("🌊 WT ИНДИКАТОР:")
        print(f"   Сигналов: {wt['total_signals']}")
        print(f"   Зоны: {wt['zone_distribution']}")
        print(f"   WT1: μ={wt['wt_stats']['wt1_mean']}, σ={wt['wt_stats']['wt1_std']}")
        print(f"   WT2: μ={wt['wt_stats']['wt2_mean']}, σ={wt['wt_stats']['wt2_std']}")
        print()

        # Дивергенции
        div = results['divergence_detector']
        print("🔄 ДИВЕРГЕНЦИИ:")
        print(f"   Всего: {div['total_divergences']}")
        print(f"   Типы: {div['divergence_types']}")
        print()

        # Аномалии
        anom = results['anomaly_detector']
        print("🚨 АНОМАЛИИ:")
        print(f"   Всего: {anom['total_anomalies']}")
        print(f"   Частота: {anom['anomaly_rate']}%")
        print()

        # FVG
        fvg = results['fvg_detector']
        print("🎯 FVG:")
        print(f"   Всего: {fvg['total_fvgs']}")
        print(f"   Типы: {fvg['fvg_types']}")
        print(f"   Частота: {fvg['fvg_rate']}%")
        print()

        # Рыночные режимы
        regime = results['market_regime']
        print("📊 РЫНОЧНЫЕ РЕЖИМЫ:")
        print(f"   Классификаций: {regime['total_classifications']}")
        print(f"   Распределение: {regime['regime_distribution']}")
        print()

        print("✅ Тестирование завершено!")


async def main():
    """
    Основная функция тестирования
    """
    tester = IndicatorTester(symbol="BTC/USDT", timeframe="1h")
    results = await tester.run_full_test()
    tester.print_results(results)


if __name__ == "__main__":
    asyncio.run(main())