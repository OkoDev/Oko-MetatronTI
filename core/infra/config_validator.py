"""
⚠️ DEPRECATED (DS-325, 18.06.2026): функциональность поглощена pydantic_config.py.
OkoConfig.model_validate() + extra="forbid" заменяет 15 ручных правил validate_and_log.
Больше не вызывается из config_loader.py.

Валидатор критичных полей config.yaml — без внешних зависимостей.
Вызывается при старте из config_loader.load_config().
Логирует WARNING на каждую аномалию; не останавливает бот.
"""
from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Схема критичных полей ──────────────────────────────────────────────────
# (dot-path, expected_type, min_val, max_val, required)
_RULES: list[tuple[str, type, Any, Any, bool]] = [
    # trading
    ("trading",                         dict,  None,  None,  True),
    ("trading.risk_pct",                float, 0.01,  20.0,  False),
    ("trading.leverage",                int,   1,     125,   False),
    ("trading.deposit_usdt",            float, 0.0,   None,  False),
    ("trading.min_rr",                  float, 0.5,   20.0,  False),
    # sl_tp_engine
    ("sl_tp_engine",                    dict,  None,  None,  False),
    # performance
    ("performance",                     dict,  None,  None,  True),
    ("performance.scan_semaphore_size", int,   1,     100,   False),
    ("performance.api_rps",             float, 0.1,   100.0, False),
    # signal_quality
    ("signal_quality",                  dict,  None,  None,  True),
    ("signal_quality.min_strength",     int,   0,     100,   False),
    ("signal_quality.min_strength_register", int, 0,  100,   False),
    ("signal_quality.dedup_minutes",    int,   0,     1440,  False),
    # market_ws
    ("market_ws.enabled",               bool,  None,  None,  False),
]


def _get_nested(cfg: dict, path: str) -> tuple[bool, Any]:
    """Возвращает (found, value) по dot-path."""
    keys = path.split(".")
    node = cfg
    for k in keys:
        if not isinstance(node, dict) or k not in node:
            return False, None
        node = node[k]
    return True, node


def validate_config(cfg: dict) -> list[str]:
    """
    Проверяет cfg по _RULES.
    Возвращает список строк-предупреждений (пустой = всё ок).
    """
    warnings: list[str] = []

    for path, typ, lo, hi, required in _RULES:
        found, val = _get_nested(cfg, path)

        if not found:
            if required:
                warnings.append(f"[CONFIG] ОТСУТСТВУЕТ обязательная секция: {path}")
            continue

        # Тип
        if typ is float and isinstance(val, int):
            val = float(val)  # int → float допустим
        if not isinstance(val, typ):
            warnings.append(
                f"[CONFIG] {path}: ожидался {typ.__name__}, получен {type(val).__name__} = {val!r}"
            )
            continue

        # Диапазон (только для чисел)
        if lo is not None and val < lo:
            warnings.append(f"[CONFIG] {path} = {val} < min={lo}")
        if hi is not None and val > hi:
            warnings.append(f"[CONFIG] {path} = {val} > max={hi}")

    return warnings


def validate_and_log(cfg: dict) -> None:
    """Валидирует конфиг и логирует предупреждения. Вызвать из load_config()."""
    issues = validate_config(cfg)
    if not issues:
        logger.info("[CONFIG] Валидация пройдена ✓")
        return
    for w in issues:
        logger.warning(w)
    logger.warning("[CONFIG] %d проблем(а) в конфиге. Исправь до рестарта.", len(issues))
