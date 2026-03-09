#!/usr/bin/env python3
"""
Сравнение стратегий с разными параметрами
"""
import asyncio
import pandas as pd
import numpy as np
import json
from datetime import datetime, timezone
from typing import Dict, List, Any
from backtesting_engine import BacktestingEngine, BacktestConfig


class StrategyComparator:
    """
    Сравнение различных торговых стратегий
    """

    def __init__(self):
        self.results = []

    async def compare_tsl_strategies(self) -> List[Dict[str, Any]]:
        """
        Сравнение стратегий с разными TSL параметрами
        """
        print("🔄 Сравнение TSL стратегий...")

        base_config = BacktestConfig(
            symbol="BTC/USDT",
            start_date=datetime(2024, 9, 1, tzinfo=timezone.utc),
            end_date=datetime(2024, 12, 31, tzinfo=timezone.utc),
            risk_per_trade_pct=1.0
        )

        # Разные конфигурации TSL
        configs = [
            base_config._replace(use_tsl=False),  # Без TSL
            base_config._replace(use_tsl=True, tsl_activation_r=0.5),  # TSL после 0.5R
            base_config._replace(use_tsl=True, tsl_activation_r=1.0),  # TSL после 1R
            base_config._replace(use_tsl=True, tsl_activation_r=1.5),  # TSL после 1.5R
            base_config._replace(use_tsl=True, tsl_activation_r=2.0),  # TSL после 2R
        ]

        results = []
        for config in configs:
            print(f"   Тестирование: {'Без TSL' if not config.use_tsl else f'TSL после {config.tsl_activation_r}R'}")

            engine = BacktestingEngine(config)
            result = await engine.run_backtest()
            results.append(result)

        return results

    async def compare_risk_levels(self) -> List[Dict[str, Any]]:
        """
        Сравнение разных уровней риска на сделку
        """
        print("⚠️ Сравнение уровней риска...")

        base_config = BacktestConfig(
            symbol="BTC/USDT",
            start_date=datetime(2024, 9, 1, tzinfo=timezone.utc),
            end_date=datetime(2024, 12, 31, tzinfo=timezone.utc),
            use_tsl=True,
            tsl_activation_r=1.0
        )

        configs = [
            base_config._replace(risk_per_trade_pct=0.5),  # 0.5% риска
            base_config._replace(risk_per_trade_pct=1.0),  # 1% риска
            base_config._replace(risk_per_trade_pct=1.5),  # 1.5% риска
            base_config._replace(risk_per_trade_pct=2.0),  # 2% риска
        ]

        results = []
        for config in configs:
            print(f"   Тестирование: {config.risk_per_trade_pct}% риска на сделку")

            engine = BacktestingEngine(config)
            result = await engine.run_backtest()
            results.append(result)

        return results

    async def compare_symbols(self) -> List[Dict[str, Any]]:
        """
        Сравнение производительности на разных символах
        """
        print("🪙 Сравнение символов...")

        symbols = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "ADA/USDT", "GRT/USDT"]
        results = []

        for symbol in symbols:
            print(f"   Тестирование: {symbol}")

            config = BacktestConfig(
                symbol=symbol,
                start_date=datetime(2024, 9, 1, tzinfo=timezone.utc),
                end_date=datetime(2024, 12, 31, tzinfo=timezone.utc),
                use_tsl=True,
                tsl_activation_r=1.0,
                risk_per_trade_pct=1.0
            )

            engine = BacktestingEngine(config)
            result = await engine.run_backtest()
            results.append(result)

        return results

    async def compare_timeframes(self) -> List[Dict[str, Any]]:
        """
        Сравнение разных таймфреймов
        """
        print("⏰ Сравнение таймфреймов...")

        timeframes = ["15m", "1h", "4h", "1d"]
        results = []

        for tf in timeframes:
            print(f"   Тестирование: {tf}")

            config = BacktestConfig(
                symbol="BTC/USDT",
                timeframe=tf,
                start_date=datetime(2024, 10, 1, tzinfo=timezone.utc),  # Короче для быстроты
                end_date=datetime(2024, 12, 31, tzinfo=timezone.utc),
                use_tsl=True,
                tsl_activation_r=1.0,
                risk_per_trade_pct=1.0
            )

            engine = BacktestingEngine(config)
            result = await engine.run_backtest()
            results.append(result)

        return results

    def print_comparison_table(self, results: List[Dict[str, Any]], title: str,
                             get_label_func):
        """
        Выводит таблицу сравнения результатов
        """
        print(f"\n🏆 {title}")
        print("-" * 80)
        print("<15")
        print("-" * 80)

        for result in results:
            config = result['config']
            metrics = result['metrics']
            label = get_label_func(config)

            print("<15")

        # Лучший результат
        best_result = max(results, key=lambda x: x['metrics']['total_return_pct'])
        best_config = best_result['config']
        best_metrics = best_result['metrics']
        best_label = get_label_func(best_config)

        print(f"\n🎯 Лучший результат: {best_label}")
        print(f"   Доход: {best_metrics['total_return_pct']}%")
        print(f"   Профит фактор: {best_metrics['profit_factor']}")
        print(f"   Sharpe: {best_metrics['sharpe_ratio']}")
        print(f"   Max DD: {best_metrics['max_drawdown_pct']}%")

    async def run_full_comparison(self):
        """
        Запускает полное сравнение всех стратегий
        """
        print("🚀 Запуск комплексного сравнения стратегий\n")

        # 1. Сравнение TSL
        tsl_results = await self.compare_tsl_strategies()
        self.print_comparison_table(
            tsl_results, "СРАВНЕНИЕ TSL СТРАТЕГИЙ",
            lambda c: f"{'Без TSL' if not c.use_tsl else f'После {c.tsl_activation_r}R'}"
        )

        # 2. Сравнение рисков
        risk_results = await self.compare_risk_levels()
        self.print_comparison_table(
            risk_results, "СРАВНЕНИЕ УРОВНЕЙ РИСКА",
            lambda c: f"{c.risk_per_trade_pct}% риска"
        )

        # 3. Сравнение символов
        symbol_results = await self.compare_symbols()
        self.print_comparison_table(
            symbol_results, "СРАВНЕНИЕ СИМВОЛОВ",
            lambda c: c.symbol
        )

        # 4. Сравнение таймфреймов
        timeframe_results = await self.compare_timeframes()
        self.print_comparison_table(
            timeframe_results, "СРАВНЕНИЕ ТАЙМФРЕЙМОВ",
            lambda c: c.timeframe
        )

        # Сохранение результатов
        all_results = {
            'tsl_comparison': tsl_results,
            'risk_comparison': risk_results,
            'symbol_comparison': symbol_results,
            'timeframe_comparison': timeframe_results,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }

        with open('strategy_comparison_results.json', 'w', encoding='utf-8') as f:
            json.dump(all_results, f, indent=2, default=str, ensure_ascii=False)

        print("\n💾 Результаты сохранены в 'strategy_comparison_results.json'")
        print("\n✅ Сравнение стратегий завершено!")

    def analyze_best_strategy(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Анализирует лучшую стратегию детально
        """
        best_result = max(results, key=lambda x: x['metrics']['total_return_pct'])
        metrics = best_result['metrics']
        trades = best_result['trades']

        # Анализ по месяцам
        monthly_returns = {}
        for trade in trades:
            month_key = trade.entry_time.strftime('%Y-%m')
            if month_key not in monthly_returns:
                monthly_returns[month_key] = []
            monthly_returns[month_key].append(trade.profit_pct)

        monthly_stats = {}
        for month, returns in monthly_returns.items():
            monthly_stats[month] = {
                'trades': len(returns),
                'avg_return': round(np.mean(returns), 2),
                'total_return': round(sum(returns), 2),
                'win_rate': round(len([r for r in returns if r > 0]) / len(returns) * 100, 1)
            }

        # Анализ по типам сигналов
        signal_analysis = {}
        for trade in trades:
            signal_type = trade.signal_type
            if signal_type not in signal_analysis:
                signal_analysis[signal_type] = []
            signal_analysis[signal_type].append(trade.r_multiple)

        signal_stats = {}
        for signal_type, r_multiples in signal_analysis.items():
            signal_stats[signal_type] = {
                'trades': len(r_multiples),
                'avg_r': round(np.mean(r_multiples), 2),
                'win_rate': round(len([r for r in r_multiples if r > 0]) / len(r_multiples) * 100, 1),
                'best_r': round(max(r_multiples), 2),
                'worst_r': round(min(r_multiples), 2)
            }

        return {
            'config': best_result['config'],
            'metrics': metrics,
            'monthly_performance': monthly_stats,
            'signal_analysis': signal_stats,
            'trade_samples': [
                {
                    'entry_time': t.entry_time.isoformat(),
                    'direction': t.direction,
                    'entry_price': t.entry_price,
                    'exit_price': t.exit_price,
                    'result': t.result.value,
                    'r_multiple': t.r_multiple,
                    'signal_type': t.signal_type
                } for t in trades[-5:]  # Последние 5 сделок
            ]
        }


async def main():
    """
    Основная функция сравнения стратегий
    """
    comparator = StrategyComparator()
    await comparator.run_full_comparison()

    # Детальный анализ лучшей стратегии
    print("\n🔍 Детальный анализ лучшей стратегии...")

    # Загружаем результаты и анализируем лучшую
    try:
        with open('strategy_comparison_results.json', 'r', encoding='utf-8') as f:
            all_results = json.load(f)

        # Находим лучшую стратегию из всех сравнений
        all_strategies = []
        all_strategies.extend(all_results['tsl_comparison'])
        all_strategies.extend(all_results['risk_comparison'])
        all_strategies.extend(all_results['symbol_comparison'])
        all_strategies.extend(all_results['timeframe_comparison'])

        best_analysis = comparator.analyze_best_strategy(all_strategies)

        print(f"\n🏆 ЛУЧШАЯ СТРАТЕГИЯ: {best_analysis['config']['symbol']} "
              f"{'с TSL' if best_analysis['config']['use_tsl'] else 'без TSL'}")

        print(f"📊 МЕТРИКИ:")
        m = best_analysis['metrics']
        print(f"   • Доход: {m['total_return_pct']}%")
        print(f"   • Win Rate: {m['win_rate']}%")
        print(f"   • Avg R: {m['avg_r_multiple']}")
        print(f"   • Sharpe: {m['sharpe_ratio']}")
        print(f"   • Max DD: {m['max_drawdown_pct']}%")
        print(f"   • Профит фактор: {m['profit_factor']}")

        print(f"\n📅 МЕСЯЧНАЯ ПРОИЗВОДИТЕЛЬНОСТЬ:")
        for month, stats in best_analysis['monthly_performance'].items():
            print(f"   {month}: {stats['trades']} сделок, {stats['avg_return']}% средний доход, {stats['win_rate']}% WR")

        print(f"\n🎯 АНАЛИЗ ПО ТИПАМ СИГНАЛОВ:")
        for signal_type, stats in best_analysis['signal_analysis'].items():
            print(f"   {signal_type}: {stats['trades']} сделок, {stats['avg_r']}R средний, {stats['win_rate']}% WR")

        print(f"\n📝 ПОСЛЕДНИЕ СДЕЛКИ:")
        for trade in best_analysis['trade_samples']:
            print(f"   {trade['entry_time'][:10]} {trade['direction']} {trade['signal_type']} -> {trade['result']} ({trade['r_multiple']}R)")

    except FileNotFoundError:
        print("❌ Файл с результатами не найден")


if __name__ == "__main__":
    asyncio.run(main())