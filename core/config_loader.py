"""
Модуль для загрузки конфигурации из YAML файла
"""
import os
import yaml
import logging
from typing import Dict, Any
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

logger = logging.getLogger(__name__)

class ConfigLoader:
    """Загрузчик конфигурации"""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.config = self.load_config()
    
    def load_config(self) -> Dict[str, Any]:
        """Загружает конфигурацию из YAML файла"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as file:
                config = yaml.safe_load(file)
            
            # Заменяем переменные окружения
            config = self._replace_env_vars(config)
            
            logger.info("Конфигурация загружена успешно")
            return config
        except Exception as e:
            logger.error(f"Ошибка загрузки конфигурации: {e}")
            return self._get_default_config()
    
    def _replace_env_vars(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Заменяет переменные окружения в конфигурации"""
        def replace_recursive(obj):
            if isinstance(obj, dict):
                return {k: replace_recursive(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [replace_recursive(item) for item in obj]
            elif isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
                env_var = obj[2:-1]
                return os.getenv(env_var, obj)
            else:
                return obj
        
        return replace_recursive(config)
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Возвращает конфигурацию по умолчанию"""
        return {
            "telegram": {
                "token": os.getenv("TELEGRAM_TOKEN", ""),
                "admin_id": os.getenv("ADMIN_ID", "")
            },
            "exchanges": {
                "default": "bingx",
                "supported": ["binance", "bybit", "bingx"]
            },
            "analysis": {
                "volume_multiplier": 5.0,
                "price_threshold": 7.0,
                "history_size": 200,
                "check_interval": 60
            },
            "subscriptions": {
                "free": {"daily_limit": 5, "signals": ["anomaly"], "price": 0},
                "basic": {"daily_limit": 10, "signals": ["anomaly", "wt_signal"], "price": 9.99},
                "premium": {"daily_limit": 50, "signals": ["anomaly", "wt_signal", "mtf_signal"], "price": 29.99},
                "pro": {"daily_limit": 999999, "signals": ["all"], "price": 99.99}
            },
            "logging": {
                "level": "INFO",
                "file": "crypto_bot.log",
                "max_size": "10MB",
                "backup_count": 5
            }
        }
    
    def get(self, key: str, default: Any = None) -> Any:
        """Получает значение по ключу (поддержка вложенных ключей)"""
        keys = key.split('.')
        value = self.config
        
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default
    
    def get_telegram_token(self) -> str:
        """Получает токен Telegram бота"""
        return self.get("telegram.token", "")
    
    def get_admin_id(self) -> str:
        """Получает ID администратора"""
        return self.get("telegram.admin_id", "")
    
    def get_exchange_config(self) -> Dict[str, Any]:
        """Получает конфигурацию бирж"""
        return self.get("exchanges", {})
    
    def get_analysis_config(self) -> Dict[str, Any]:
        """Получает конфигурацию анализа"""
        return self.get("analysis", {})
    
    def get_subscription_config(self) -> Dict[str, Any]:
        """Получает конфигурацию подписок"""
        return self.get("subscriptions", {})
    
    def get_logging_config(self) -> Dict[str, Any]:
        """Получает конфигурацию логирования"""
        return self.get("logging", {})
    
    def get_all(self) -> Dict[str, Any]:
        """Получает всю конфигурацию"""
        return self.config

# Глобальный экземпляр конфигурации
config = ConfigLoader()
