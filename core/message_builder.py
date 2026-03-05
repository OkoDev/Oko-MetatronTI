from datetime import datetime
import urllib.parse
import re
from core.config_loader import config

def _normalize_to_tv(symbol: str) -> str:
    """
    Преобразует входной symbol в формат для TradingView:
    Примеры:
      "BTC/USDT:USDT" -> "BTCUSDT.P"
      "BROCCOLI/USDT:USDT" -> "BROCCOLIUSDT.P"
      "BTC/USDT-P" -> "BTCUSDT.P"
    """
    s = symbol.upper()
    # если есть '/', берём до '/'
    if "/" in s:
        base = s.split("/")[0]
    else:
        # fallback: remove non-alnum
        base = "".join(ch for ch in s if ch.isalnum())
    base = re.sub(r'[^A-Z0-9]', '', base)
    tv_symbol = f"{base}USDT.P"
    return tv_symbol

def tv_link(symbol: str, interval: int = 15) -> str:
    """Создает ссылку на TradingView"""
    # Берем первую биржу из списка EXCHANGES
    exchanges = config.get("exchanges.supported", ["binance", "bybit", "bingx"])
    exchange = exchanges[2].upper() if isinstance(exchanges, list) and len(exchanges) > 2 else "BINGX"
    
    tv_sym = _normalize_to_tv(symbol)
    encoded = urllib.parse.quote(f"{exchange}:{tv_sym}", safe='')
    url = f"https://ru.tradingview.com/chart/?symbol={encoded}&interval={interval}"
    return f'<a href="{url}">{symbol}</a>'

def anomaly_message(symbol: str, info: dict) -> str:
    """Форматирует сообщение об аномалии"""
    parts = [
        "🚨 <b>АНОМАЛИЯ</b> 🚨",
        f"Пара: {tv_link(symbol, interval=1)}",
        f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    ]
    if not info:
        return "\n\n".join(parts)
    if "volume" in info:
        v = info["volume"]
        parts.append(
            f"📊 <b>Объем</b>\n"
            f"Текущий: {v['current']:.2f}\n"
            f"Средний: {v['average']:.2f}\n"
            f"Превышение: {v['ratio']:.1f}x"
        )
    if "price_change" in info:
        p = info["price_change"]
        parts.append(
            f"💹 <b>Цена</b> изменилась на {p['current']:.2f}% "
            f"(порог {p['threshold']:.1f}%)"
        )
    return "\n\n".join(parts)

def wt_message(symbol: str, info: dict) -> str:
    """Форматирует WT сигнал"""
    emoji = "🟢" if "LONG" in info.get("type","") else "🔴"
    tf = info.get("timeframe","15m")
    
    # Преобразуем таймфрейм в минуты для interval
    try:
        if "h" in tf:
            interval = int(tf.replace("h","")) * 60
        else:
            interval = int(tf.replace("m",""))
    except Exception:
        interval = 15
    
    parts = [
        f"{emoji} <b>WT СИГНАЛ {tf}</b> {emoji}",
        f"Пара: {tv_link(symbol, interval=interval)}",
        f"Тип: {info.get('type')}",
        f"WT1={info.get('wt1'):.2f}, WT2={info.get('wt2'):.2f}",
        f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    ]
    
    if info.get("volume_details"):
        vols = info['volume_details']
        parts.append(f"📊 Объемы: {vols}")
    
    return "\n".join(parts)

def mtf_message(symbol: str, info: dict) -> str:
    """Форматирует MTF сигнал"""
    emoji = "🟢" if info.get("type") in ("LONG","WT_LONG") else "🔴"
    
    parts = [
        f"{emoji} <b>MTF СИГНАЛ</b> {emoji}",
        f"Пара: {tv_link(symbol, interval=3)}",
        f"Тип: {info.get('type')}",
        f"Тренд: {info.get('trend')} (1h)",
        f"WT (15m): {info.get('wt')}",
        f"Zone/FVG (3m): {info.get('zone')} + {info.get('fvg')}",
    ]
    
    entry = info.get('entry_price')
    if entry and entry != 0:
        parts.append(f"🎯 Вход: {entry:.4f}")
    
    parts.append(f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if info.get("volume_details"):
        vols = info['volume_details']
        parts.append(f"📊 Объемы: {vols}")
    
    return "\n".join(parts)