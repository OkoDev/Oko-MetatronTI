import os
from dotenv import load_dotenv

load_dotenv()

CONFIG = {
    'TELEGRAM_TOKEN': os.getenv('TELEGRAM_TOKEN'),
    'ADMIN_ID': os.getenv('ADMIN_CHAT_ID'),
    'EXCHANGES': ['binance', 'bybit', 'bingx'],
    'THRESHOLD': 2.0,
    'HISTORY_SIZE': 50,
    'LIQUIDITY_LIMIT': 10000,
    'CHECK_INTERVAL': 200,
    'LOG_LEVEL': 'INFO',
    'VOLUME_MULTIPLIER': 5.0,  # Более строгий порог для аномального объема 5
    'PRICE_THRESHOLD': 7.0,    # Более высокий порог для изменения цены 7
    'BINGX': {
        'api_key': os.getenv('BINGX_API_KEY'),
        'secret': os.getenv('BINGX_SECRET_KEY')
    }
}