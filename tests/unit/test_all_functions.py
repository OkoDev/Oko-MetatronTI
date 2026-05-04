#!/usr/bin/env python3
"""
Тестовый скрипт для проверки всех функций Crypto Volume Bot
"""

import asyncio
import logging
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

class BotTester:
    """Класс для тестирования функций бота"""
    
    def __init__(self):
        self.test_results = []
        self.start_time = datetime.now()
    
    def log_test(self, test_name: str, status: str, details: str = ""):
        """Логирование результата теста"""
        result = {
            "test": test_name,
            "status": status,
            "details": details,
            "timestamp": datetime.now()
        }
        self.test_results.append(result)
        
        status_emoji = "✅" if status == "PASS" else "❌" if status == "FAIL" else "⚠️"
        logger.info(f"{status_emoji} {test_name}: {status} {details}")
    
    async def test_menu_detection(self):
        """Тест определения типов меню"""
        logger.info("🧪 Тестирование определения типов меню...")
        
        try:
            from bot.menus import MenuHandler
            
            # Создаем экземпляр MenuHandler
            menu_handler = MenuHandler(None)
            
            # Тестируем различные кнопки
            test_buttons = [
                ("🟢 Мониторинг", "monitoring"),
                ("🧠 AI Анализ", "main"),
                ("📈 Сигналы", "main"),
                ("🎯 Пивоты", "main"),
                ("🛡️ Риски", "main"),
                ("📚 История", "main"),
                ("💎 Подписки", "main"),
                ("⚙️ Настройки", "main"),
                ("ℹ️ Помощь", "main"),
                ("🟢 Запустить мониторинг", "monitoring"),
                ("📊 Недельные пивоты", "pivots"),
                ("🔍 Проверить пивоты", "pivots"),
                ("🧠 Комплексный анализ", "ai_analysis"),
                ("📊 Анализ пары", "ai_analysis"),
                ("🚨 Аномалии", "signals"),
                ("📊 WT сигналы", "signals"),
                ("🛡️ Профиль риска", "risk_management"),
                ("📊 Эффективность", "history"),
                ("💎 Моя подписка", "subscriptions"),
                ("⚙️ Общие настройки", "settings"),
                ("unknown_button", "unknown")
            ]
            
            passed = 0
            failed = 0
            
            for button_text, expected_type in test_buttons:
                detected_type = menu_handler._detect_menu_type(button_text)
                if detected_type == expected_type:
                    passed += 1
                    self.log_test(f"Menu Detection: {button_text}", "PASS", f"Detected: {detected_type}")
                else:
                    failed += 1
                    self.log_test(f"Menu Detection: {button_text}", "FAIL", f"Expected: {expected_type}, Got: {detected_type}")
            
            self.log_test("Menu Detection Overall", "PASS" if failed == 0 else "FAIL", f"Passed: {passed}, Failed: {failed}")
            
        except Exception as e:
            self.log_test("Menu Detection", "FAIL", f"Exception: {e}")
    
    async def test_keyboard_generation(self):
        """Тест генерации клавиатур"""
        logger.info("🧪 Тестирование генерации клавиатур...")
        
        try:
            from bot.keyboards import (
                main_menu, monitoring_menu, ai_analysis_menu, signals_menu,
                pivots_menu, risk_management_menu, history_menu,
                subscriptions_menu, settings_menu
            )
            
            keyboards = [
                ("main_menu", main_menu()),
                ("monitoring_menu", monitoring_menu()),
                ("ai_analysis_menu", ai_analysis_menu()),
                ("signals_menu", signals_menu()),
                ("pivots_menu", pivots_menu()),
                ("risk_management_menu", risk_management_menu()),
                ("history_menu", history_menu()),
                ("subscriptions_menu", subscriptions_menu()),
                ("settings_menu", settings_menu())
            ]
            
            passed = 0
            failed = 0
            
            for name, keyboard in keyboards:
                try:
                    # Проверяем, что клавиатура создана
                    if keyboard and hasattr(keyboard, 'keyboard'):
                        passed += 1
                        self.log_test(f"Keyboard: {name}", "PASS", f"Generated successfully")
                    else:
                        failed += 1
                        self.log_test(f"Keyboard: {name}", "FAIL", "Invalid keyboard object")
                except Exception as e:
                    failed += 1
                    self.log_test(f"Keyboard: {name}", "FAIL", f"Exception: {e}")
            
            self.log_test("Keyboard Generation Overall", "PASS" if failed == 0 else "FAIL", f"Passed: {passed}, Failed: {failed}")
            
        except Exception as e:
            self.log_test("Keyboard Generation", "FAIL", f"Exception: {e}")
    
    async def test_fsm_states(self):
        """Тест FSM состояний"""
        logger.info("🧪 Тестирование FSM состояний...")
        
        try:
            from bot_with_subscriptions import PivotStates, SubscriptionStates, AIAnalysisStates
            
            # Проверяем, что состояния определены
            states = [
                ("PivotStates.waiting_for_pivots", PivotStates.waiting_for_pivots),
                ("PivotStates.waiting_for_check", PivotStates.waiting_for_check),
                ("SubscriptionStates.waiting_for_payment", SubscriptionStates.waiting_for_payment),
                ("AIAnalysisStates.waiting_for_symbol", AIAnalysisStates.waiting_for_symbol),
                ("AIAnalysisStates.waiting_for_symbol_search", AIAnalysisStates.waiting_for_symbol_search)
            ]
            
            passed = 0
            failed = 0
            
            for name, state in states:
                try:
                    if state is not None:
                        passed += 1
                        self.log_test(f"FSM State: {name}", "PASS", "State defined")
                    else:
                        failed += 1
                        self.log_test(f"FSM State: {name}", "FAIL", "State is None")
                except Exception as e:
                    failed += 1
                    self.log_test(f"FSM State: {name}", "FAIL", f"Exception: {e}")
            
            self.log_test("FSM States Overall", "PASS" if failed == 0 else "FAIL", f"Passed: {passed}, Failed: {failed}")
            
        except Exception as e:
            self.log_test("FSM States", "FAIL", f"Exception: {e}")
    
    async def test_config_loading(self):
        """Тест загрузки конфигурации"""
        logger.info("🧪 Тестирование загрузки конфигурации...")
        
        try:
            from core.infra.config_loader import ConfigLoader
            
            config_loader = ConfigLoader()
            config = config_loader.load_config()
            
            required_keys = [
                "bot.token",
                "bot.username",
                "bingx.api_key",
                "bingx.secret_key",
                "bingx.base_url",
                "logging.level"
            ]
            
            passed = 0
            failed = 0
            
            for key in required_keys:
                try:
                    keys = key.split('.')
                    value = config
                    for k in keys:
                        value = value[k]
                    
                    if value is not None and value != "":
                        passed += 1
                        self.log_test(f"Config: {key}", "PASS", f"Value: {str(value)[:20]}...")
                    else:
                        failed += 1
                        self.log_test(f"Config: {key}", "FAIL", "Empty or None value")
                except KeyError:
                    failed += 1
                    self.log_test(f"Config: {key}", "FAIL", "Key not found")
                except Exception as e:
                    failed += 1
                    self.log_test(f"Config: {key}", "FAIL", f"Exception: {e}")
            
            self.log_test("Config Loading Overall", "PASS" if failed == 0 else "FAIL", f"Passed: {passed}, Failed: {failed}")
            
        except Exception as e:
            self.log_test("Config Loading", "FAIL", f"Exception: {e}")
    
    async def test_subscription_manager(self):
        """Тест менеджера подписок"""
        logger.info("🧪 Тестирование менеджера подписок...")
        
        try:
            from core.db.subscription_manager import SubscriptionManager
            
            subscription_manager = SubscriptionManager()
            
            # Тестируем основные методы
            test_user_id = 123456789
            
            # Тест добавления пользователя
            subscription_manager.add_user(test_user_id, "test_user", "Test", "User")
            self.log_test("Subscription Manager: add_user", "PASS", "User added successfully")
            
            # Тест получения информации о подписке
            sub_info = subscription_manager.get_subscription_info(test_user_id)
            if sub_info:
                self.log_test("Subscription Manager: get_subscription_info", "PASS", "Subscription info retrieved")
            else:
                self.log_test("Subscription Manager: get_subscription_info", "FAIL", "No subscription info")
            
            # Тест проверки возможности получения сигнала
            can_receive = subscription_manager.can_receive_signal(test_user_id, "anomaly")
            if isinstance(can_receive, bool):
                self.log_test("Subscription Manager: can_receive_signal", "PASS", f"Result: {can_receive}")
            else:
                self.log_test("Subscription Manager: can_receive_signal", "FAIL", "Invalid return type")
            
            # Тест проверки дневного лимита
            can_receive_today = subscription_manager.can_receive_signal_today(test_user_id)
            if isinstance(can_receive_today, bool):
                self.log_test("Subscription Manager: can_receive_signal_today", "PASS", f"Result: {can_receive_today}")
            else:
                self.log_test("Subscription Manager: can_receive_signal_today", "FAIL", "Invalid return type")
            
        except Exception as e:
            self.log_test("Subscription Manager", "FAIL", f"Exception: {e}")
    
    async def test_data_collector(self):
        """Тест сборщика данных"""
        logger.info("🧪 Тестирование сборщика данных...")
        
        try:
            from core.infra.data_collector import DataCollector
            
            data_collector = DataCollector()
            
            # Тест получения списка пар
            pairs = await data_collector.get_pairs()
            if pairs and len(pairs) > 0:
                self.log_test("Data Collector: get_pairs", "PASS", f"Retrieved {len(pairs)} pairs")
            else:
                self.log_test("Data Collector: get_pairs", "FAIL", "No pairs retrieved")
            
            # Тест получения OHLCV данных
            if pairs:
                test_pair = pairs[0]
                ohlcv = await data_collector.get_ohlcv(test_pair, "1m", limit=10)
                if ohlcv is not None and not ohlcv.empty:
                    self.log_test("Data Collector: get_ohlcv", "PASS", f"Retrieved {len(ohlcv)} candles")
                else:
                    self.log_test("Data Collector: get_ohlcv", "FAIL", "No OHLCV data")
            
        except Exception as e:
            self.log_test("Data Collector", "FAIL", f"Exception: {e}")
    
    async def test_indicators(self):
        """Тест технических индикаторов"""
        logger.info("🧪 Тестирование технических индикаторов...")
        
        try:
            from core.indicators.indicators import Indicators
            import pandas as pd
            import numpy as np
            
            # Создаем тестовые данные
            test_data = pd.DataFrame({
                'open': np.random.uniform(100, 200, 100),
                'high': np.random.uniform(150, 250, 100),
                'low': np.random.uniform(50, 150, 100),
                'close': np.random.uniform(100, 200, 100),
                'volume': np.random.uniform(1000, 10000, 100)
            })
            
            indicators = Indicators()
            
            # Тест расчета RSI
            rsi = indicators.calculate_rsi(test_data['close'])
            if rsi is not None and len(rsi) > 0:
                self.log_test("Indicators: RSI", "PASS", f"Calculated RSI for {len(rsi)} periods")
            else:
                self.log_test("Indicators: RSI", "FAIL", "RSI calculation failed")
            
            # Тест расчета Wavetrend
            wt = indicators.calculate_wavetrend(test_data)
            if wt is not None and len(wt) > 0:
                self.log_test("Indicators: Wavetrend", "PASS", f"Calculated WT for {len(wt)} periods")
            else:
                self.log_test("Indicators: Wavetrend", "FAIL", "WT calculation failed")
            
        except Exception as e:
            self.log_test("Indicators", "FAIL", f"Exception: {e}")
    
    async def run_all_tests(self):
        """Запуск всех тестов"""
        logger.info("🚀 Запуск полного тестирования Crypto Volume Bot...")
        logger.info(f"⏰ Время начала: {self.start_time}")
        
        tests = [
            self.test_menu_detection,
            self.test_keyboard_generation,
            self.test_fsm_states,
            self.test_config_loading,
            self.test_subscription_manager,
            self.test_data_collector,
            self.test_indicators
        ]
        
        for test in tests:
            try:
                await test()
            except Exception as e:
                logger.error(f"❌ Критическая ошибка в тесте {test.__name__}: {e}")
        
        # Подсчет результатов
        total_tests = len(self.test_results)
        passed_tests = len([r for r in self.test_results if r["status"] == "PASS"])
        failed_tests = len([r for r in self.test_results if r["status"] == "FAIL"])
        
        end_time = datetime.now()
        duration = end_time - self.start_time
        
        logger.info("=" * 60)
        logger.info("📊 РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ")
        logger.info("=" * 60)
        logger.info(f"⏰ Время выполнения: {duration}")
        logger.info(f"📊 Всего тестов: {total_tests}")
        logger.info(f"✅ Пройдено: {passed_tests}")
        logger.info(f"❌ Провалено: {failed_tests}")
        logger.info(f"📈 Успешность: {(passed_tests/total_tests*100):.1f}%")
        
        if failed_tests > 0:
            logger.info("\n❌ ПРОВАЛЕННЫЕ ТЕСТЫ:")
            for result in self.test_results:
                if result["status"] == "FAIL":
                    logger.info(f"  • {result['test']}: {result['details']}")
        
        logger.info("=" * 60)
        
        return passed_tests, failed_tests

async def main():
    """Основная функция"""
    tester = BotTester()
    passed, failed = await tester.run_all_tests()
    
    if failed == 0:
        logger.info("🎉 Все тесты пройдены успешно!")
        return 0
    else:
        logger.warning(f"⚠️ {failed} тестов провалено")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
