"""
Notification Engine — оценка правил, cooldown, circuit breaker.

Использование:
    from core.notifications.evaluate import evaluate
    text = evaluate("strategy_fire_ote", symbol, config, entry=1.23, ...)
    if text:
        await send_notification(bot, text)
"""
import time
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# per-rule-per-symbol → unix timestamp последнего срабатывания
_last_fired: dict[str, float] = {}

# кольцо временных меток последних N нотификаций (circuit breaker)
_hour_log: list[float] = []


def _circuit_ok(max_per_hour: int) -> bool:
    now = time.time()
    cutoff = now - 3600.0
    # вычищаем старые записи
    while _hour_log and _hour_log[0] < cutoff:
        _hour_log.pop(0)
    return len(_hour_log) < max_per_hour


def _cooldown_ok(rule_name: str, symbol: str, cooldown_sec: int) -> bool:
    if cooldown_sec <= 0:
        return True
    key = f"{rule_name}:{symbol}"
    return (time.time() - _last_fired.get(key, 0.0)) >= cooldown_sec


def _mark(rule_name: str, symbol: str) -> None:
    key = f"{rule_name}:{symbol}"
    now = time.time()
    _last_fired[key] = now
    _hour_log.append(now)


def _norm_symbol(symbol: str) -> str:
    """Нормализует ccxt-формат в YAML-формат: "XLM/USDT:USDT" → "XLM-USDT"."""
    try:
        base, rest = symbol.split("/", 1)
        quote = rest.split(":")[0]
        return f"{base}-{quote}"
    except Exception:
        return symbol


def evaluate(rule_name: str, symbol: str, config: Any, **kwargs) -> Optional[str]:
    """
    Проверяет правило из notifications.yaml, cooldown и circuit breaker.
    Возвращает отформатированный текст уведомления или None.

    config — объект с методом .get(path, default).
    symbol — ccxt-формат ("XLM/USDT:USDT") или YAML-формат ("XLM-USDT"), оба поддерживаются.
    """
    symbol_norm = _norm_symbol(symbol)  # для фильтра symbols в YAML
    notif_cfg = config.get("notifications", {})
    if not notif_cfg.get("enabled", False):
        return None

    rule = notif_cfg.get("rules", {}).get(rule_name)
    if not rule or not rule.get("enabled", False):
        return None

    max_per_hour = notif_cfg.get("global_circuit_breaker", {}).get("max_per_hour", 100)
    if not _circuit_ok(max_per_hour):
        logger.warning("[NOTIF] circuit breaker (%d/ч): пропуск %s/%s", max_per_hour, rule_name, symbol)
        return None

    cooldown = int(rule.get("cooldown_sec", 0))
    if not _cooldown_ok(rule_name, symbol, cooldown):
        return None

    # Фильтр по символам: symbols: [] = все, [XLM-USDT] = только эта пара
    # Поддерживаем и ccxt ("XLM/USDT:USDT") и YAML ("XLM-USDT") форматы
    allowed_symbols = rule.get("symbols", [])
    if allowed_symbols and symbol not in allowed_symbols and symbol_norm not in allowed_symbols:
        return None

    # Фильтр по направлению: directions: [] = оба, [LONG] или [SHORT]
    allowed_dirs = rule.get("directions", [])
    if allowed_dirs and kwargs.get("direction") not in allowed_dirs:
        return None

    # Фильтр по таймфрейму: tf: [] = все, [3m, 5m] = только эти
    allowed_tfs = rule.get("tf", [])
    if allowed_tfs and kwargs.get("tf") not in allowed_tfs:
        return None

    template = rule.get("template", "")
    try:
        text = template.format(symbol=symbol, **kwargs).strip()
    except KeyError as e:
        logger.warning("[NOTIF] template error %s: missing key %s (kwargs=%s)", rule_name, e, list(kwargs))
        return None

    _mark(rule_name, symbol)
    return text
