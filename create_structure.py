#!/usr/bin/env python3
"""
Скрипт для создания новой структуры проекта
"""

import os

# Структура директорий
DIRECTORIES = {
    'bot': [
        'bot/filters',
        'bot/handlers',
    ],
    'commands': [],
    'domain': [
        'domain/signals',
        'domain/intelligence',
        'domain/pivots',
        'domain/subscriptions',
    ],
    'infrastructure': [
        'infrastructure/bingx',
        'infrastructure/database',
        'infrastructure/config',
    ],
    'presentation': [
        'presentation/keyboards',
        'presentation/messages',
        'presentation/builders',
    ],
    'utils': [],
    'tests': [
        'tests/unit',
        'tests/integration',
        'tests/fixtures',
    ],
    'docs': [
        'docs/api',
        'docs/guides',
        'docs/architecture',
    ],
}

# Файлы для создания
FILES = {
    # Bot
    'bot/__init__.py': '# Bot module',
    'bot/handlers/__init__.py': '# Handlers module',
    'bot/filters/__init__.py': '# Filters module',
    
    # Commands
    'commands/__init__.py': '# Commands module',
    
    # Domain
    'domain/signals/__init__.py': '# Signals module',
    'domain/intelligence/__init__.py': '# Intelligence module',
    'domain/pivots/__init__.py': '# Pivots module',
    'domain/subscriptions/__init__.py': '# Subscriptions module',
    
    # Infrastructure
    'infrastructure/bingx/__init__.py': '# BingX module',
    'infrastructure/database/__init__.py': '# Database module',
    'infrastructure/config/__init__.py': '# Config module',
    
    # Presentation
    'presentation/keyboards/__init__.py': '# Keyboards module',
    'presentation/messages/__init__.py': '# Messages module',
    'presentation/builders/__init__.py': '# Builders module',
    
    # Utils
    'utils/__init__.py': '# Utils module',
    
    # Tests
    'tests/__init__.py': '# Tests module',
    'tests/unit/__init__.py': '# Unit tests',
    'tests/integration/__init__.py': '# Integration tests',
    'tests/fixtures/__init__.py': '# Fixtures',
    
    # Docs
    'docs/api/README.md': '# API Documentation',
    'docs/guides/README.md': '# User Guides',
    'docs/architecture/README.md': '# Architecture Documentation',
}

def create_structure():
    """Создание структуры проекта"""
    print("Creating new project structure...")
    
    # Создание директорий
    for base_dir, subdirs in DIRECTORIES.items():
        if not os.path.exists(base_dir):
            os.makedirs(base_dir)
            print(f"[+] Created directory: {base_dir}")
        
        for subdir in subdirs:
            if not os.path.exists(subdir):
                os.makedirs(subdir)
                print(f"[+] Created subdirectory: {subdir}")
    
    # Создание файлов
    for file_path, content in FILES.items():
        dir_path = os.path.dirname(file_path)
        if dir_path and not os.path.exists(dir_path):
            os.makedirs(dir_path)
        
        if not os.path.exists(file_path):
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"[+] Created file: {file_path}")
    
    print("\n[+] Project structure created successfully!")
    print("\n[*] New structure:")
    for base_dir in DIRECTORIES.keys():
        print(f"   {base_dir}/")

if __name__ == "__main__":
    create_structure()
