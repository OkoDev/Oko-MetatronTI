"""
NotifConfig — singleton для config/notifications.yaml.

Независим от config_loader (тот читает только config.yaml).
Предоставляет .get(), .reload(), .toggle_rule(), .set_paused().
In-memory toggle: изменения активны до рестарта (файл не перезаписывается).
"""
import logging
import os
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)

_NOTIF_YAML = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "notifications.yaml"
)


class NotifConfig:
    def __init__(self, path: str = _NOTIF_YAML):
        self._path = os.path.abspath(path)
        self._data: dict = {}
        self._paused: bool = False
        self.reload()

    # ── публичный API ──────────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        """
        Dot-path доступ: get("notifications.enabled") или get("notifications", {}).
        Корневой ключ "notifications" возвращает весь блок с применением _paused.
        """
        if "." not in key:
            val = self._data.get(key, default)
            # Если запрашивают весь блок notifications — применяем _paused
            if key == "notifications" and isinstance(val, dict):
                val = dict(val)
                if self._paused:
                    val["enabled"] = False
            return val

        parts = key.split(".")
        node = self._data
        for part in parts:
            if not isinstance(node, dict):
                return default
            node = node.get(part, default)
        return node

    def reload(self) -> None:
        """Перечитывает файл с диска. Сбрасывает in-memory toggles."""
        try:
            with open(self._path, encoding="utf-8") as f:
                self._data = yaml.safe_load(f) or {}
            self._paused = False
            logger.info("[NOTIF] config loaded: %s", self._path)
        except Exception as e:
            logger.error("[NOTIF] config load error: %s", e)

    def set_paused(self, paused: bool) -> None:
        """Глобальная пауза/резюме (in-memory, без записи в файл)."""
        self._paused = paused
        logger.info("[NOTIF] %s", "PAUSED" if paused else "RESUMED")

    def is_paused(self) -> bool:
        return self._paused

    def toggle_rule(self, rule_name: str) -> Optional[bool]:
        """
        Переключает enabled у правила in-memory.
        Возвращает новое значение или None если правило не найдено.
        """
        rules = self._data.get("notifications", {}).get("rules", {})
        if rule_name not in rules:
            return None
        current = rules[rule_name].get("enabled", False)
        rules[rule_name]["enabled"] = not current
        logger.info("[NOTIF] rule %s → %s", rule_name, not current)
        return not current

    def rules_summary(self) -> list[dict]:
        """Список правил для отображения в TG-меню."""
        rules = self._data.get("notifications", {}).get("rules", {})
        out = []
        for name, cfg in rules.items():
            out.append({
                "name": name,
                "enabled": cfg.get("enabled", False),
                "tier": cfg.get("tier", 0),
                "symbols": cfg.get("symbols", []),
                "directions": cfg.get("directions", []),
                "tf": cfg.get("tf", []),
                "cooldown_sec": cfg.get("cooldown_sec", 0),
            })
        return out

    def fired_count(self) -> int:
        """Сколько нотификаций отправлено за последний час."""
        from core.notifications.evaluate import _hour_log
        import time
        cutoff = time.time() - 3600
        return sum(1 for t in _hour_log if t >= cutoff)


# Singleton
notif_config = NotifConfig()
