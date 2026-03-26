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
    label = symbol.replace(":USDT", "")
    return f'<a href="{url}">{label}</a>'

def anomaly_message(symbol: str, info: dict) -> str:
    """Форматирует сообщение об аномалии"""
    parts = [
        "\n",
        f"🚨 <b>АНОМАЛИЯ · {tv_link(symbol, interval=1)}</b>",
        "",
    ]
    if not info:
        parts += [f"⏰ {datetime.now().strftime('%d.%m %H:%M')}", "\n"]
        return "\n".join(parts)
    if "volume" in info:
        v = info["volume"]
        try:
            parts += [
                "<b>📊 Объём</b>",
                f"  Текущий:   {float(v['current']):.2f}",
                f"  Средний:   {float(v['average']):.2f}",
                f"  Превышение: <b>{float(v['ratio']):.1f}×</b>",
                "",
            ]
        except (TypeError, KeyError, ValueError, IndexError):
            pass
    if "price_change" in info:
        p = info["price_change"]
        try:
            ch = float(p['current'])
            thr = float(p['threshold'])
            ch_emoji = "📈" if ch > 0 else "📉"
            parts += [f"{ch_emoji} Цена: <b>{ch:+.2f}%</b>  (порог {thr:.1f}%)", ""]
        except (TypeError, KeyError, ValueError, IndexError):
            pass
    parts += [f"⏰ {datetime.now().strftime('%d.%m %H:%M')}", "\n"]
    return "\n".join(parts)

def wt_message(symbol: str, info: dict) -> str:
    """Форматирует WT сигнал"""
    is_long = "LONG" in info.get("type", "")
    emoji = "🟢" if is_long else "🔴"
    tf = info.get("timeframe", "15m")
    dir_label = "LONG ↑" if is_long else "SHORT ↓"

    try:
        interval = int(tf.replace("h", "")) * 60 if "h" in tf else int(tf.replace("m", ""))
    except Exception:
        interval = 15

    wt1 = info.get('wt1', 0)
    wt2 = info.get('wt2', 0)
    try:
        wt_str = f"WT1 <b>{float(wt1):.1f}</b>  WT2 {float(wt2):.1f}"
    except (TypeError, ValueError):
        wt_str = f"WT1 {wt1}  WT2 {wt2}"

    parts = [
        "\n",
        f"{emoji} <b>WT · {tv_link(symbol, interval=interval)} · {dir_label} · {tf}</b>",
        "",
        f"  {wt_str}",
        f"⏰ {datetime.now().strftime('%d.%m %H:%M')}",
        "\n",
    ]
    return "\n".join(parts)

def mtf_message(symbol: str, info: dict) -> str:
    """Форматирует MTF сигнал"""
    is_long = info.get("type") in ("LONG", "WT_LONG")
    emoji = "🟢" if is_long else "🔴"
    dir_label = "LONG ↑" if is_long else "SHORT ↓"

    parts = [
        "\n",
        f"{emoji} <b>MTF · {tv_link(symbol, interval=3)} · {dir_label}</b>",
        "",
        f"  Тренд 1h:   {info.get('trend', '—')}",
        f"  WT 15m:     {info.get('wt', '—')}",
        f"  Zone/FVG:   {info.get('zone', '—')} / {info.get('fvg', '—')}",
    ]

    entry = info.get('entry_price')
    if entry and entry != 0:
        try:
            parts.append(f"  🎯 Вход:    <code>{float(entry):.5f}</code>")
        except (TypeError, ValueError):
            pass

    parts += [f"⏰ {datetime.now().strftime('%d.%m %H:%M')}", "\n"]
    return "\n".join(parts)


def funding_extreme_message(symbol: str, sig: "SignalData") -> str:
    """DEV-81: Форматирует сигнал экстремального funding rate."""
    from core.signal_models import SignalDirection
    is_long = sig.direction == SignalDirection.LONG
    emoji = "💰"
    dir_label = "LONG ↑" if is_long else "SHORT ↓"
    d = sig.data or {}
    fr = d.get("funding_rate", 0)
    wt1 = d.get("wt1", 0)
    fr_pct = fr * 100
    squeeze = "шорт-сквиз ↑" if is_long else "лонг-сквиз ↓"

    parts = [
        "\n",
        f"{emoji} <b>FUNDING EXTREME · {tv_link(symbol, interval=240)} · {dir_label}</b>",
        f"  📊 Funding: <b>{fr_pct:+.4f}%</b> / 8h",
        f"  WT1: {wt1:.1f}  ⚡ {squeeze}",
        f"  💪 Сила: <b>{sig.strength}/100</b>  conf={sig.confidence:.2f}",
        f"⏰ {datetime.now().strftime('%d.%m %H:%M')}",
        "\n",
    ]
    return "\n".join(parts)


def liquidity_sweep_message(symbol: str, sig: "SignalData") -> str:
    """DEV-82: Форматирует сигнал вынос ликвидности (liquidity sweep)."""
    from core.signal_models import SignalDirection
    is_long = sig.direction == SignalDirection.LONG
    emoji = "🌊"
    dir_label = "LONG ↑" if is_long else "SHORT ↓"
    d = sig.data or {}
    sweep_lvl = d.get("sweep_level", 0)
    depth = d.get("sweep_depth_pct", 0)
    wt1 = d.get("wt1", 0)
    pivot_bonus = d.get("pivot_bonus", False)
    side = "sell-side" if is_long else "buy-side"

    parts = [
        "\n",
        f"{emoji} <b>LIQUIDITY SWEEP · {tv_link(symbol, interval=15)} · {dir_label}</b>",
        f"  🎯 Sweep {side} @ <b>{sweep_lvl:.6g}</b>",
        f"  📏 Глубина: <b>{depth:.2f}%</b>  WT1: {wt1:.1f}",
    ]
    if pivot_bonus:
        parts.append("  ⭐ Совпадение с Weekly пивотом")
    parts += [
        f"  💪 Сила: <b>{sig.strength}/100</b>  conf={sig.confidence:.2f}",
        f"⏰ {datetime.now().strftime('%d.%m %H:%M')}",
        "\n",
    ]
    return "\n".join(parts)


def wt_b_message(symbol: str, sig: "SignalData") -> str:
    """Форматирует WT-B (1h) сигнал — адаптивный OS/OB + дивергенция."""
    from core.signal_models import SignalDirection
    is_long = sig.direction == SignalDirection.LONG
    emoji   = "🔵"   # WT-B синий — отличается от стандартного WT
    dir_label = "LONG ↑" if is_long else "SHORT ↓"
    d = sig.data or {}

    strength = int(sig.strength or 0)
    div_str  = d.get("div_strength", 0)
    wt1_val  = d.get("wt1", 0)
    depth    = d.get("depth", 0)
    zone_thr = d.get("os_adaptive") or d.get("ob_adaptive") or 0
    fire     = "🔥🔥🔥" if strength >= 90 else "🔥🔥" if strength >= 80 else "🔥"

    parts = [
        "\n",
        f"{emoji} <b>WT-B · {tv_link(symbol, interval=60)} · {dir_label}</b>",
        f"  ⏱ 1h  {fire} <b>{strength}/100</b>",
        f"  📊 WT1={wt1_val:.1f}  адапт.={'OS' if is_long else 'OB'}={zone_thr:.1f}",
        f"  🔄 Дивер: div_str={div_str:.1f}  depth={depth:.1f}",
        f"  ✅ confidence={sig.confidence:.2f}",
        f"⏰ {datetime.now().strftime('%d.%m %H:%M')}",
        "\n",
    ]
    return "\n".join(parts)