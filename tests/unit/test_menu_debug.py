#!/usr/bin/env python3
"""
Тестовый скрипт для отладки работы меню бота
"""

import asyncio
import logging
import sys
import os
import pytest

pytest.importorskip("aiogram")

# Добавляем путь к проекту
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.config_loader import config
from bot.menus import MenuHandler

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("menu_debug.log", encoding="utf-8")
    ]
)

logger = logging.getLogger(__name__)

class MockMessage:
    """Мок-объект для имитации сообщения Telegram"""
    def __init__(self, text: str, user_id: int = 12345, username: str = "test_user"):
        self.text = text
        self.from_user = MockUser(user_id, username)
        self.message_id = 1
        self.chat = MockChat()
    
    async def answer(self, text: str, reply_markup=None):
        print(f"📱 [BOT RESPONSE] {text}")
        if reply_markup:
            print(f"⌨️ [KEYBOARD] {type(reply_markup).__name__}")

class MockUser:
    """Мок-объект для пользователя"""
    def __init__(self, user_id: int, username: str):
        self.id = user_id
        self.username = username

class MockChat:
    """Мок-объект для чата"""
    def __init__(self):
        self.id = 12345

class MockState:
    """Мок-объект для FSM состояния"""
    def __init__(self):
        pass
    
    async def set_state(self, state):
        print(f"🔄 [FSM] Установлено состояние: {state}")
    
    async def clear(self):
        print("🔄 [FSM] Состояние очищено")

class MockBot:
    """Мок-объект для бота"""
    def __init__(self):
        self.monitored_pairs = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    
    async def cmd_monitor(self, message):
        print("🟢 [BOT] Запуск мониторинга...")
        await message.answer("✅ Мониторинг запущен!")
    
    async def cmd_stats(self, message):
        print("📊 [BOT] Показ статистики...")
        await message.answer("📊 Статистика бота...")
    
    async def cmd_top(self, message):
        print("🏆 [BOT] Показ ТОП-10...")
        await message.answer("🏆 ТОП-10 по объему...")

async def test_menu_buttons():
    """Тестирование всех кнопок меню"""
    print("🧪 [TEST] Начинаем тестирование меню...")
    
    # Создаем мок-объекты
    mock_bot = MockBot()
    menu_handler = MenuHandler(mock_bot)
    
    # Тестовые кнопки главного меню
    main_menu_buttons = [
        "🟢 Мониторинг",
        "⏹ Остановить", 
        "🧠 AI Анализ",
        "📊 Статистика",
        "📈 Сигналы",
        "🎯 Пивоты",
        "🛡️ Риски",
        "📚 История",
        "💎 Подписки",
        "⚙️ Настройки",
        "ℹ️ Помощь"
    ]
    
    print("\n🏠 [TEST] Тестирование главного меню...")
    for button_text in main_menu_buttons:
        print(f"\n🔍 [TEST] Тестируем кнопку: '{button_text}'")
        message = MockMessage(button_text)
        state = MockState()
        
        try:
            await menu_handler.handle_main_menu_buttons(message, state)
            print(f"✅ [TEST] Кнопка '{button_text}' обработана успешно")
        except Exception as e:
            print(f"❌ [TEST] Ошибка при обработке кнопки '{button_text}': {e}")
    
    # Тестовые кнопки подменю
    submenu_buttons = [
        "🟢 Запустить мониторинг",
        "⏹ Остановить мониторинг",
        "📊 Статистика мониторинга",
        "🏆 ТОП-10 по объему",
        "🔍 Найти пару",
        "📈 Активные сигналы",
        "⬅️ Назад в главное меню"
    ]
    
    print("\n📊 [TEST] Тестирование меню мониторинга...")
    for button_text in submenu_buttons:
        print(f"\n🔍 [TEST] Тестируем кнопку: '{button_text}'")
        message = MockMessage(button_text)
        state = MockState()
        
        try:
            await menu_handler.handle_monitoring_menu_buttons(message, state)
            print(f"✅ [TEST] Кнопка '{button_text}' обработана успешно")
        except Exception as e:
            print(f"❌ [TEST] Ошибка при обработке кнопки '{button_text}': {e}")
    
    # Тестирование универсального обработчика
    print("\n🔧 [TEST] Тестирование универсального обработчика...")
    test_buttons = [
        "🟢 Мониторинг",
        "🧠 AI Анализ", 
        "📊 Статистика",
        "🟢 Запустить мониторинг",
        "📊 Статистика мониторинга",
        "Неизвестная кнопка"
    ]
    
    for button_text in test_buttons:
        print(f"\n🔍 [TEST] Универсальный обработчик для: '{button_text}'")
        message = MockMessage(button_text)
        state = MockState()
        
        try:
            await menu_handler.handle_any_button(message, state)
            print(f"✅ [TEST] Универсальный обработчик для '{button_text}' работает")
        except Exception as e:
            print(f"❌ [TEST] Ошибка в универсальном обработчике для '{button_text}': {e}")
    
    print("\n🎉 [TEST] Тестирование завершено!")

async def test_detection():
    """Тестирование определения типа меню"""
    print("\n🎯 [TEST] Тестирование определения типа меню...")
    
    mock_bot = MockBot()
    menu_handler = MenuHandler(mock_bot)
    
    test_cases = [
        ("🟢 Мониторинг", "main"),
        ("🧠 AI Анализ", "main"),
        ("🟢 Запустить мониторинг", "monitoring"),
        ("📊 Статистика мониторинга", "monitoring"),
        ("🧠 Комплексный анализ", "ai_analysis"),
        ("🤖 ML предсказания", "ai_analysis"),
        ("🚨 Аномалии", "signals"),
        ("📊 WT сигналы", "signals"),
        ("📊 Недельные пивоты", "pivots"),
        ("🔍 Проверить пивоты", "pivots"),
        ("🛡️ Профиль риска", "risk_management"),
        ("📊 Позиции", "risk_management"),
        ("📊 Эффективность", "history"),
        ("📈 Тренд производительности", "history"),
        ("💎 Моя подписка", "subscriptions"),
        ("🛒 Купить подписку", "subscriptions"),
        ("⚙️ Общие настройки", "settings"),
        ("🔔 Уведомления", "settings"),
        ("Неизвестная кнопка", "unknown")
    ]
    
    for button_text, expected_type in test_cases:
        detected_type = menu_handler._detect_menu_type(button_text)
        status = "✅" if detected_type == expected_type else "❌"
        print(f"{status} [DETECTION] '{button_text}' -> {detected_type} (ожидалось: {expected_type})")
    
    print("\n🎯 [TEST] Тестирование определения типа завершено!")

async def main():
    """Главная функция тестирования"""
    print("[DEBUG] Запуск отладки меню бота...")
    print("=" * 60)
    
    try:
        await test_detection()
        await test_menu_buttons()
        
        print("\n" + "=" * 60)
        print("[DEBUG] Отладка завершена успешно!")
        print("[DEBUG] Проверьте файл menu_debug.log для детальных логов")
        
    except Exception as e:
        print(f"\n[DEBUG] Критическая ошибка при тестировании: {e}")
        logger.exception("Полная трассировка ошибки:")
        return 1
    
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
