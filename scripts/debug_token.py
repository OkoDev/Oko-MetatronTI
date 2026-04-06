#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для отладки токена Telegram
"""
import os
from dotenv import load_dotenv

# Загружаем .env файл
load_dotenv()

print("Отладка токена Telegram...")
print("=" * 50)

telegram_token = os.getenv('TELEGRAM_TOKEN')

if not telegram_token:
    print("ОШИБКА: TELEGRAM_TOKEN не найден в .env файле!")
    exit(1)

print(f"Токен (сырой): '{telegram_token}'")
print(f"Длина: {len(telegram_token)} символов")
print(f"Тип: {type(telegram_token)}")

# Проверяем на лишние символы
if telegram_token.startswith('"') and telegram_token.endswith('"'):
    print("ВНИМАНИЕ: Токен обернут в кавычки!")
    telegram_token = telegram_token.strip('"')
    print(f"Токен без кавычек: '{telegram_token}'")

if telegram_token.startswith("'") and telegram_token.endswith("'"):
    print("ВНИМАНИЕ: Токен обернут в одинарные кавычки!")
    telegram_token = telegram_token.strip("'")
    print(f"Токен без кавычек: '{telegram_token}'")

# Убираем пробелы
telegram_token = telegram_token.strip()
print(f"Токен без пробелов: '{telegram_token}'")

# Проверяем формат токена
if ':' not in telegram_token:
    print("ОШИБКА: Токен должен содержать двоеточие (:)")
    print("Правильный формат: 1234567890:ABCdefGHIjklMNOpqrsTUVwxyz")
    exit(1)

parts = telegram_token.split(':')
if len(parts) != 2:
    print("ОШИБКА: Токен должен содержать ровно одно двоеточие")
    exit(1)

bot_id, token_hash = parts
print(f"Bot ID: {bot_id}")
print(f"Token Hash: {token_hash}")

# Проверяем, что bot_id состоит только из цифр
if not bot_id.isdigit():
    print("ОШИБКА: Bot ID должен состоять только из цифр")
    exit(1)

# Проверяем длину token_hash
if len(token_hash) < 20:
    print("ОШИБКА: Token hash слишком короткий")
    exit(1)

print("\n" + "=" * 50)
print("Токен выглядит корректно!")

# Тестируем валидацию aiogram
try:
    from aiogram.utils.token import validate_token
    validate_token(telegram_token)
    print("OK - Токен прошел валидацию aiogram!")
except Exception as e:
    print(f"ERROR - Ошибка валидации aiogram: {e}")
    print("\nВозможные причины:")
    print("1. Токен устарел или был отозван")
    print("2. Токен неправильно скопирован")
    print("3. В токене есть невидимые символы")
    print("\nРешение:")
    print("1. Получите новый токен от @BotFather")
    print("2. Скопируйте токен точно, без лишних символов")
    print("3. Убедитесь, что в .env файле нет кавычек вокруг токена")
