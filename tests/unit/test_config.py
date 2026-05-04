#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тест конфигурации
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.infra.config_loader import config

print("Тест конфигурации...")
print("=" * 40)

token = config.get_telegram_token()
print(f"Токен из config: '{token}'")
print(f"Длина: {len(token)}")
print(f"Пустой: {not token}")

if not token:
    print("ПРОБЛЕМА: config.get_telegram_token() возвращает пустую строку!")
    print("Проверьте config.yaml и .env файлы")
else:
    print("OK - Токен получен из конфигурации")
    
    # Тестируем валидацию
    try:
        from aiogram.utils.token import validate_token
        validate_token(token)
        print("OK - Токен прошел валидацию!")
    except Exception as e:
        print(f"ERROR - Ошибка валидации: {e}")
