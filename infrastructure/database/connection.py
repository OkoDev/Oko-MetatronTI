"""
Infrastructure - Database
Адаптер для работы с базой данных
"""

import sqlite3
from typing import Optional
import os

class DatabaseConnection:
    """Управление подключением к базе данных"""
    
    def __init__(self, db_path: str = "subscriptions.db"):
        self.db_path = db_path
        self.connection: Optional[sqlite3.Connection] = None
    
    def connect(self) -> sqlite3.Connection:
        """Установить подключение"""
        if self.connection is None:
            self.connection = sqlite3.connect(self.db_path)
        return self.connection
    
    def close(self):
        """Закрыть подключение"""
        if self.connection:
            self.connection.close()
            self.connection = None
    
    def __enter__(self):
        return self.connect()
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

__all__ = ['DatabaseConnection']
