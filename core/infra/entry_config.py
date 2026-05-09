"""
Единая точка конфигурации Entry Timeframe.

Все файлы, которым нужен entry TF, импортируют:
    from core.infra.entry_config import get_entry_timeframes, get_primary_entry_tf

Конфигурация через config.yaml:
    trading:
      entry_timeframe: "15m"           # один ТФ
      # entry_timeframe: ["5m", "15m"] # multi-TF (несколько entry одновременно)

Multi-TF entry: scan_loop запускает параллельный скан по каждому entry TF.
Каждый ТФ генерирует свои сигналы, все сливаются в общий поток.
"""

from typing import List, Optional

# Дефолт если в конфиге не указано
_DEFAULT_ENTRY_TF = "15m"

# Маппинг entry TF → TF для ATR-based TP1 (DEV-40), cap 1h
ENTRY_TO_TP1_TF = {
    "1m":  "15m",
    "3m":  "15m",
    "5m":  "15m",
    "15m": "15m",
    "30m": "1h",
    "45m": "1h",
    "1h":  "1h",
    "4h":  "1h",
    "1D":  "1h",
    "1d":  "1h",
}

# Маппинг entry TF → TSL TF (каскадный TSL начинается с этого ТФ)
ENTRY_TO_TSL_TF = {
    "1m":  "15m",
    "3m":  "15m",
    "5m":  "15m",
    "15m": "1h",
    "30m": "1h",
    "45m": "1h",
    "1h":  "4h",
}

# Каскадный TSL: от entry TF вверх
CASCADE_TFS_MAP = {
    "1m":  ["5m", "15m", "1h"],
    "3m":  ["15m", "1h", "4h"],
    "5m":  ["15m", "1h", "4h"],
    "15m": ["15m", "1h", "4h"],
    "30m": ["1h", "4h", "1d"],
    "45m": ["1h", "4h", "1d"],
    "1h":  ["1h", "4h", "1d"],
}


def get_entry_timeframes(config=None) -> List[str]:
    """
    Возвращает список entry timeframes из конфига.
    Поддерживает как строку ("15m"), так и список (["5m", "15m"]).
    """
    if config is None:
        return [_DEFAULT_ENTRY_TF]

    val = config.get("trading.entry_timeframe") if hasattr(config, 'get') else None
    if val is None:
        # Попробуем вложенную структуру
        trading = config.get("trading", {}) if isinstance(config, dict) else {}
        val = trading.get("entry_timeframe", _DEFAULT_ENTRY_TF)

    if isinstance(val, list):
        return [str(v) for v in val] if val else [_DEFAULT_ENTRY_TF]
    return [str(val)] if val else [_DEFAULT_ENTRY_TF]


def get_primary_entry_tf(config=None) -> str:
    """Возвращает основной (первый) entry timeframe."""
    tfs = get_entry_timeframes(config)
    return tfs[0]


def get_cascade_tfs(entry_tf: Optional[str] = None) -> List[str]:
    """Возвращает список ТФ для каскадного TSL, начиная от entry TF."""
    tf = entry_tf or _DEFAULT_ENTRY_TF
    return CASCADE_TFS_MAP.get(tf, ["15m", "1h", "4h"])


def get_tsl_tf(entry_tf: Optional[str] = None) -> str:
    """Возвращает ТФ для TSL по entry TF."""
    tf = entry_tf or _DEFAULT_ENTRY_TF
    return ENTRY_TO_TSL_TF.get(tf, "1h")
