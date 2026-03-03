# 🚀 Crypto Volume Bot - Торговый бот с подписками

Профессиональный Telegram-бот для анализа криптовалютных рынков с системой подписок.

## ✨ Возможности

### 📊 Типы сигналов
- 🚨 **Аномалии** - всплески объёма и цены
- 📊 **WT сигналы** - Wavetrend индикатор
- 🔄 **MTF анализ** - мультитаймфреймный анализ
- 🎯 **MTF точки разворота** - продвинутый анализ
- 📈 **Тренд-сигналы** - работа по тренду
- 💎 **Дивергенции** - расхождения цены и индикатора
- 📊 **Пивотные уровни** - поддержка и сопротивление
- 🔄 **Развороты от пивотов** - недельные уровни + FVG
- 🧠 **Комплексный анализ** - объединение всех сигналов в единую рекомендацию

### 🧠 Trading Intelligence Layer
- **Объединение сигналов** - все типы сигналов в одном анализе
- **Оценка силы** - численная оценка от 0 до 100 баллов
- **Анализ уверенности** - вероятность успеха от 0.0 до 1.0
- **Определение риска** - LOW, MEDIUM, HIGH
- **Торговые уровни** - готовые точки входа, стоп-лосса и тейк-профита
- **Обоснование** - детальное объяснение торгового решения
- **Команда**: `/intelligence BTCUSDT`

### 💎 Система подписок
- 🆓 **Бесплатно** - 5 сигналов в день, только аномалии
- 💎 **Basic** - $9.99/месяц, 10 сигналов в день
- 🚀 **Premium** - $29.99/месяц, 50 сигналов в день
- 👑 **Pro** - $99.99/месяц, неограниченно сигналов

## 🛠️ Установка и запуск

### 1. Клонирование репозитория
```bash
git clone <repository-url>
cd crypto_volume_bot
```

### 2. Установка зависимостей
```bash
pip install -r requirements.txt
```

### 3. Настройка конфигурации
Создайте файл `.env` на основе `.env.example`:
```bash
cp .env.example .env
```

Заполните переменные окружения:
```env
TELEGRAM_TOKEN=your_telegram_bot_token_here
ADMIN_ID=your_telegram_user_id_here
BINGX_API_KEY=your_bingx_api_key_here
BINGX_SECRET_KEY=your_bingx_secret_key_here
```

### 4. Запуск бота

#### Обычный запуск:
```bash
python bot_with_subscriptions.py
```

#### Запуск через Docker:
```bash
docker-compose up -d
```

## 📱 Команды бота

### 🔧 Основные команды
- `/start` - Главное меню
- `/help` - Справка по командам
- `/monitor` - Запуск/остановка мониторинга
- `/stats` - Статистика бота
- `/top` - Топ-10 пар по объёму
- `/reset` - Сбросить счетчики

### 💎 Команды подписок
- `/subscribe` - Подписаться бесплатно
- `/unsubscribe` - Отписаться
- `/my_subscription` - Моя подписка
- `/buy_subscription` - Купить подписку

### 📊 Команды анализа
- `/pivots` - Недельные и дневные пивоты
- `/check_pivot` - Проверка близости к пивотам

## 🏗️ Архитектура проекта

```
crypto_volume_bot/
├── bot_with_subscriptions.py    # Главный файл бота
├── config.yaml                  # Конфигурация
├── requirements.txt             # Зависимости
├── Dockerfile                   # Docker образ
├── docker-compose.yml           # Docker Compose
├── core/                        # Ядро системы
│   ├── config_loader.py         # Загрузчик конфигурации
│   ├── subscription_manager.py  # Менеджер подписок
│   ├── data_collector.py        # Сбор данных
│   ├── anomaly_detector.py      # Детектор аномалий
│   ├── indicators.py            # Технические индикаторы
│   ├── mtf_checker.py           # MTF анализ
│   ├── divergence_detector.py   # Детектор дивергенций
│   ├── trend_signals.py         # Тренд-сигналы
│   ├── pivot_calculator_fixed.py # Расчет пивотов
│   ├── message_builder.py       # Форматирование сообщений
│   └── keyboards.py             # Клавиатуры Telegram
└── modules/                     # Дополнительные модули
    ├── ml_analytycs.py          # ML аналитика
    └── price_monitor.py         # Мониторинг цен
```

## 🔧 Настройка

### Конфигурация в config.yaml
```yaml
# Telegram Bot
telegram:
  token: "${TELEGRAM_TOKEN}"
  admin_id: "${ADMIN_ID}"

# Подписки
subscriptions:
  free:
    daily_limit: 5
    signals: ["anomaly"]
    price: 0
  basic:
    daily_limit: 10
    signals: ["anomaly", "wt_signal", "mtf_signal"]
    price: 9.99
  # ... и т.д.
```

### Параметры анализа
```yaml
analysis:
  volume_multiplier: 50.0    # Множитель для аномалий объёма
  price_threshold: 40.0      # Порог изменения цены
  history_size: 200          # Размер истории данных
  check_interval: 60         # Интервал проверки (секунды)
```

## 📊 Мониторинг и логи

### Логи
- Файл: `crypto_bot.log`
- Уровень: INFO (настраивается в config.yaml)
- Ротация: 10MB, 5 файлов

### База данных
- SQLite: `subscriptions.db`
- Таблицы: users, subscriptions, signal_stats
- Автоматическое создание при первом запуске

## 🚀 Развертывание в продакшене

### 1. Подготовка сервера
```bash
# Установка Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Установка Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/download/v2.20.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

### 2. Настройка переменных окружения
```bash
# Создание .env файла
nano .env

# Установка прав доступа
chmod 600 .env
```

### 3. Запуск в продакшене
```bash
# Запуск в фоновом режиме
docker-compose up -d

# Просмотр логов
docker-compose logs -f

# Остановка
docker-compose down
```

## 🔒 Безопасность

### Рекомендации
- Никогда не коммитьте файл `.env`
- Используйте сильные пароли для API ключей
- Регулярно обновляйте зависимости
- Мониторьте логи на предмет подозрительной активности

### Переменные окружения
```bash
# Обязательные
TELEGRAM_TOKEN=your_bot_token
ADMIN_ID=your_user_id

# Опциональные (для расширенной функциональности)
BINGX_API_KEY=your_api_key
BINGX_SECRET_KEY=your_secret_key
```

## 📈 Монетизация

### Модель подписки
- **Freemium** - базовые сигналы бесплатно
- **Tiered** - разные уровни доступа
- **Pay-per-use** - плата за дополнительные функции

### Интеграция платежей
- Telegram Payments (в разработке)
- Stripe (планируется)
- PayPal (планируется)

## 🤝 Поддержка

### Получение помощи
- 📧 Email: support@cryptovolume.com
- 💬 Telegram: @cryptovolume_support
- 🐛 Issues: GitHub Issues

### Сообщество
- 📱 Telegram канал: @cryptovolume_signals
- 💬 Discord: Crypto Volume Community
- 📺 YouTube: Crypto Volume Bot

## 📄 Лицензия

MIT License - см. файл LICENSE для деталей.

## 🙏 Благодарности

- Команде aiogram за отличную библиотеку
- Сообществу ccxt за поддержку бирж
- Всем контрибьюторам проекта

---

**Создано с ❤️ для криптотрейдеров**
