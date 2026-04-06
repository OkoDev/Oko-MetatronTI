"""
Bot - Main Entry Point (Refactored)
Главная точка входа в новую архитектуру
"""

import asyncio
import logging
import sys
import os

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from infrastructure.config.loader import ConfigLoader
from bot.handlers.menu import MenuHandler
from presentation.keyboards.adapter import main_menu

# Windows fix for asyncio
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("crypto_bot.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)

# Принудительная перенастройка stdout/stderr для Windows не требуется

logger = logging.getLogger(__name__)

class CryptoVolumeBot:
    """
    Refactored Bot - новая архитектура
    Использует модульную структуру с разделением по слоям
    """
    
    def __init__(self):
        logger.info("Initializing Refactored Crypto Volume Bot...")
        
        # Загрузка конфигурации
        self.config_loader = ConfigLoader()
        self.config = self.config_loader.load_config()
        
        # Импорты для работы с aiogram
        from aiogram import Bot, Dispatcher
        from aiogram.fsm.storage.memory import MemoryStorage
        
        # Создание бота и диспетчера
        bot_token = self.config_loader.get_telegram_token()
        if not bot_token:
            raise ValueError("Bot token not found in config")
        
        self.bot = Bot(token=bot_token)
        self.storage = MemoryStorage()
        self.dp = Dispatcher(storage=self.storage)
        
        # Инициализация обработчиков
        self._setup_handlers()
        
        logger.info("Refactored Crypto Volume Bot initialized successfully!")
    
    def _setup_handlers(self):
        """Настройка обработчиков"""
        # Регистрация базовых команд
        self._register_commands()
    
    def _register_commands(self):
        """Регистрация команд бота"""
        from aiogram import F
        from aiogram.filters import Command
        
        # Регистрация команды /start
        @self.dp.message(Command("start"))
        async def cmd_start(message):
            await message.answer(
                "Welcome to Crypto Volume Bot (Refactored)!\n\n"
                "Use /help for more information.",
                reply_markup=main_menu()
            )
        
        # Регистрация команды /help
        @self.dp.message(Command("help"))
        async def cmd_help(message):
            help_text = (
                "Crypto Volume Bot - Refactored Architecture\n\n"
                "Available commands:\n"
                "/start - Start the bot\n"
                "/help - Show this help\n"
                "/stats - Show statistics\n\n"
                "Use menu buttons to navigate."
            )
            await message.answer(help_text, reply_markup=main_menu())
    
    async def start(self):
        """Запуск бота"""
        logger.info("Starting Refactored Crypto Volume Bot...")
        await self.dp.start_polling(self.bot)
    
    def run(self):
        """Запуск бота (sync wrapper)"""
        asyncio.run(self.start())

if __name__ == "__main__":
    try:
        bot = CryptoVolumeBot()
        bot.run()
    except Exception as e:
        logger.exception(f"Failed to start bot: {e}")
        sys.exit(1)