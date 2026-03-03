#!/usr/bin/env python3
"""
Test script for refactored architecture
"""

import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """Test all imports"""
    print("Testing refactored architecture imports...")
    print("=" * 60)
    
    tests = [
        ("Infrastructure - Config", "from infrastructure.config.loader import ConfigLoader"),
        ("Infrastructure - Database", "from infrastructure.database.connection import DatabaseConnection"),
        ("Infrastructure - BingX", "from infrastructure.bingx.client import DataCollector"),
        ("Domain - Signals", "from domain.signals.adapters import AnomalyDetector"),
        ("Domain - Intelligence", "from domain.intelligence.adapters import TradingIntelligence"),
        ("Domain - Pivots", "from domain.pivots.adapters import PivotCalculator"),
        ("Domain - Subscriptions", "from domain.subscriptions.adapter import SubscriptionManager"),
        ("Presentation - Keyboards", "from presentation.keyboards.adapter import main_menu"),
        ("Presentation - Messages", "from presentation.messages.adapter import MessageBuilder"),
        ("Bot - Handlers", "from bot.handlers.menu import MenuHandler"),
    ]
    
    passed = 0
    failed = 0
    
    for name, import_stmt in tests:
        try:
            exec(import_stmt)
            print(f"[OK] {name}")
            passed += 1
        except Exception as e:
            print(f"[FAIL] {name}: {e}")
            failed += 1
    
    print("=" * 60)
    print(f"Total: {len(tests)}, Passed: {passed}, Failed: {failed}")
    
    return failed == 0

def main():
    """Main test function"""
    print("\n" + "=" * 60)
    print("REFACTORED ARCHITECTURE TEST")
    print("=" * 60 + "\n")
    
    success = test_imports()
    
    if success:
        print("\n" + "=" * 60)
        print("[SUCCESS] All imports work correctly!")
        print("=" * 60)
        print("\nYou can now run:")
        print("  python bot/main.py          # New refactored bot")
        print("  python bot_with_subscriptions.py  # Old bot (still works)")
        return 0
    else:
        print("\n" + "=" * 60)
        print("[FAILED] Some imports failed!")
        print("=" * 60)
        return 1

if __name__ == "__main__":
    sys.exit(main())
