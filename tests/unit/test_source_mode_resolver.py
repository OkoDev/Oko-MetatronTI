"""Режим источника — единая точка правды (`source_registry.mode_of`).

Повод (29.09.2026): в config.yaml шесть раз стояло `mode: off`, а YAML 1.1 читает голое
`off` как boolean False. Резолвер делал `str(False or "")` → пустая строка → канон молча
терялся, и «торгует или нет» решал только старый ключ `exchange_enabled`. То есть контракт
«конфиг = источник истины» не работал именно там, где выключает.

Второй повод: источник, которого НЕТ в `source_policies`, считался разрешённым на биржу.

Тесты держат обе двери закрытыми и проверяют боевой config.yaml на возврат ловушки.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.trading.source_registry import MODE_LIVE, MODE_OFF, MODE_SHADOW, mode_of


class _Cfg:
    """Минимальный двойник config_loader: get() по точечному ключу."""

    def __init__(self, data: dict):
        self._d = data

    def get(self, key: str, default=None):
        cur = self._d
        for part in key.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur


def _cfg(policies: dict, trading: dict | None = None) -> _Cfg:
    return _Cfg({"signal_router": {"source_policies": policies}, "trading": trading or {}})


# ── ловушка YAML: голое off/on ────────────────────────────────────────────────

def test_bool_false_is_off():
    """`mode: off` без кавычек приходит как False — обязан читаться как off, а не теряться."""
    cfg = _cfg({"src": {"mode": False, "exchange_enabled": True}})
    assert mode_of("src", cfg=cfg) == MODE_OFF, "boolean False не распознан как off"


def test_bool_false_beats_legacy_exchange_enabled():
    """Ключевой случай: `exchange_enabled: true` рядом с `mode: off` НЕ должен пустить на биржу."""
    from core.trading.source_registry import trades_on_exchange
    cfg = _cfg({"src": {"mode": False, "exchange_enabled": True}})
    assert trades_on_exchange("src", cfg=cfg) is False, "mode: off проигнорирован — источник торгует"


def test_bool_true_falls_back_not_live():
    """`mode: on` (True) неоднозначен: live или shadow? В деньгах не угадываем."""
    cfg = _cfg({"src": {"mode": True, "exchange_enabled": False}})
    assert mode_of("src", cfg=cfg) == MODE_OFF


def test_quoted_off_is_off():
    cfg = _cfg({"src": {"mode": "off", "exchange_enabled": True}})
    assert mode_of("src", cfg=cfg) == MODE_OFF


@pytest.mark.parametrize("declared,expected", [
    ("live", MODE_LIVE), ("shadow", MODE_SHADOW), ("off", MODE_OFF),
    (" LIVE ", MODE_LIVE),
])
def test_declared_modes(declared, expected):
    cfg = _cfg({"src": {"mode": declared, "exchange_enabled": True}})
    assert mode_of("src", cfg=cfg) == expected


# ── дефолт: незнакомый источник не торгует ────────────────────────────────────

def test_unknown_source_is_off():
    """Источника нет в конфиге → off. Было MODE_LIVE: новый луп торговал бы, не будучи описан."""
    cfg = _cfg({"other": {"mode": "live", "exchange_enabled": True}})
    assert mode_of("src", cfg=cfg) == MODE_OFF


def test_known_source_without_mode_uses_legacy():
    """Старые ключи ещё работают: описан, exchange_enabled=true → live."""
    cfg = _cfg({"src": {"exchange_enabled": True}})
    assert mode_of("src", cfg=cfg) == MODE_LIVE


def test_legacy_shadow_flag():
    cfg = _cfg({"src": {"exchange_enabled": True}}, {"src": {"shadow": True}})
    assert mode_of("src", cfg=cfg) == MODE_SHADOW


# ── боевой конфиг: ловушка не должна вернуться ────────────────────────────────

def test_live_config_has_no_boolean_modes():
    """В config.yaml ни один `mode` не смеет быть boolean (значит кавычки на месте)."""
    p = Path(__file__).resolve().parents[2] / "config.yaml"
    cfg = yaml.safe_load(p.read_text(encoding="utf-8"))
    pol = (cfg.get("signal_router") or {}).get("source_policies") or {}
    bad = {k: (v or {}).get("mode") for k, v in pol.items()
           if isinstance((v or {}).get("mode"), bool)}
    assert not bad, f"голое off/on в config.yaml (YAML читает как boolean): {bad}"


def test_live_config_modes_agree_with_exchange_enabled():
    """Канон и старый ключ обязаны совпадать — расхождение и есть корень всей проблемы."""
    p = Path(__file__).resolve().parents[2] / "config.yaml"
    cfg = yaml.safe_load(p.read_text(encoding="utf-8"))
    pol = (cfg.get("signal_router") or {}).get("source_policies") or {}
    clash = {
        k: (v.get("mode"), v.get("exchange_enabled"))
        for k, v in pol.items()
        if isinstance(v, dict) and isinstance(v.get("mode"), str)
        and (v["mode"].strip().lower() == "live") != bool(v.get("exchange_enabled"))
    }
    assert not clash, f"mode и exchange_enabled расходятся: {clash}"
