#!/usr/bin/env python3
"""
Проверка импортов рабочих модулей core/ и bot/.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def test_imports():
    tests = [
        ("core.config_loader", "from core.config_loader import config"),
        ("core.signal_checkers", "from core.signal_checkers import check_anomaly_signals, check_wt_signals"),
        ("core.trading_intelligence", "from core.trading_intelligence import TradingIntelligence"),
        ("core.trade_simulator", "from core.trade_simulator import TradeSimulator"),
        ("core.performance_engine", "from core.performance_engine import PerformanceEngine"),
        ("core.market_regime", "from core.market_regime import MarketRegimeClassifier"),
        ("core.outcome_predictor", "from core.outcome_predictor import OutcomePredictor"),
        ("core.watchlist_manager", "from core.watchlist_manager import WatchlistManager"),
        ("bot.keyboards", "from bot.keyboards import main_menu"),
        ("bot.menus", "from bot.menus import MenuHandler"),
    ]

    passed = failed = 0
    for name, stmt in tests:
        try:
            exec(stmt)
            print(f"[OK] {name}")
            passed += 1
        except Exception as e:
            print(f"[FAIL] {name}: {e}")
            failed += 1

    print(f"\nTotal: {len(tests)}, Passed: {passed}, Failed: {failed}")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if test_imports() else 1)
