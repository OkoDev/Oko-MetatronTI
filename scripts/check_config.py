#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для проверки конфигурации
"""
import os
from dotenv import load_dotenv

# Загружаем .env файл
load_dotenv()

print("Проверка конфигурации...")
print("=" * 40)

# Проверяем переменные окружения
telegram_token = os.getenv('TELEGRAM_TOKEN')
admin_id = os.getenv('ADMIN_ID')
bingx_api_key = os.getenv('BINGX_API_KEY')
bingx_secret_key = os.getenv('BINGX_SECRET_KEY')

print(f"TELEGRAM_TOKEN: {'Установлен' if telegram_token else 'НЕ УСТАНОВЛЕН'}")
if telegram_token:
    print(f"  Длина: {len(telegram_token)} символов")
    print(f"  Начинается с: {telegram_token[:10]}...")

print(f"ADMIN_ID: {'Установлен' if admin_id else 'НЕ УСТАНОВЛЕН'}")
if admin_id:
    print(f"  Значение: {admin_id}")

print(f"BINGX_API_KEY: {'Установлен' if bingx_api_key else 'НЕ УСТАНОВЛЕН'}")
print(f"BINGX_SECRET_KEY: {'Установлен' if bingx_secret_key else 'НЕ УСТАНОВЛЕН'}")

print("\n" + "=" * 40)

if not telegram_token:
    print("ОШИБКА: TELEGRAM_TOKEN не установлен!")
    print("\nКак получить токен:")
    print("1. Напишите @BotFather в Telegram")
    print("2. Отправьте команду /newbot")
    print("3. Выберите имя для бота")
    print("4. Скопируйте полученный токен в .env файл")
    print("5. Формат: TELEGRAM_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz")
elif not admin_id:
    print("ОШИБКА: ADMIN_ID не установлен!")
    print("\nКак получить ваш ID:")
    print("1. Напишите @userinfobot в Telegram")
    print("2. Скопируйте ваш ID в .env файл")
    print("3. Формат: ADMIN_ID=123456789")
else:
    print("OK - Основные переменные настроены!")
    print("Можете запускать бота: python bot_with_subscriptions.py")
