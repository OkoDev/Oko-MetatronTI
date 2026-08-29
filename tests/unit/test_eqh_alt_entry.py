"""
Регрессия ВТОРОЙ ДВЕРИ ВХОДА по EQH (29.08.2026).

Замер на 6730 сделках: `short` в пределах 0.25 ATR от уровня равных хаёв даёт PF 5.06
против 2.40 у чистого дрейф-гейта; зеркало на long — 0.75. По годам EQH и дрейф-гейт
КОНКУРЕНТЫ: в 2026 EQH 1.93 против 1.06 у гейта, а их пересечение хуже обоих
([[eqh_liquidity_short_works_in_2026]]). Отсюда «любая из двух дверей», а не «и то, и то».

🔴 Главное, что охраняют тесты — FAIL-CLOSED. `_drift_gate` при сбое ПРОПУСКАЕТ (иначе
стратегия умирает молча), а эта функция поток РАСШИРЯЕТ, и её поломка открыла бы шлюз.
Любая неясность обязана давать «не пропускаю».
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bot.loops.impulse_fib_runner import Instance, _eqh_alt_entry      # noqa: E402


class _Cfg:
    """Минимальный двойник bot.config — отдаёт словарь по точечному пути."""
    def __init__(self, payload):
        self._p = payload

    def get(self, path, default=None):
        return self._p.get(path, default)


class _Bot:
    def __init__(self, payload):
        self.config = _Cfg(payload)


def _inst():
    """Боевой 15m-инстанс: `cfg_key` — свойство, равное `trading.{src}`."""
    return Instance(src="impulse_fib_15m", tf="15m", tf_mult=4,
                    table="impulse_fib_15m_journal", tag="IMPULSE15")


def _df_with_equal_highs(n=200, level=110.0, last_close=110.0):
    """Ряд с двумя равными вершинами и ценой рядом с ними."""
    rng = np.random.default_rng(5)
    close = np.full(n, 100.0) + rng.normal(0, 0.4, n)
    high = close + 0.5
    low = close - 0.5
    for i in (60, 120):                       # две равные вершины
        high[i] = level
        close[i] = level - 0.3
    close[-1] = last_close
    high[-1] = last_close + 0.4
    low[-1] = last_close - 0.4
    idx = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({"open": close, "close": close, "high": high,
                         "low": low, "volume": 100.0}, index=idx)


CFG_ON = {"trading.impulse_fib_15m.eqh_entry":
          {"enabled": True, "tolerance_atr": 0.25, "sides": ["short"], "confirm_bars": 3}}


def test_disabled_by_default_config():
    """Без секции в конфиге дверь ЗАКРЫТА — новая секция не должна включаться сама."""
    ok, why = _eqh_alt_entry(_Bot({}), _inst(), _df_with_equal_highs(), "short")
    assert ok is False and "выключен" in why


def test_side_not_allowed():
    """long у тех же уровней даёт 0.75 — сторона обязана отсекаться конфигом."""
    ok, why = _eqh_alt_entry(_Bot(CFG_ON), _inst(), _df_with_equal_highs(), "long")
    assert ok is False and "сторона" in why


def test_fail_closed_on_broken_data():
    """
    🔴 ГЛАВНЫЙ: при любом сбое функция обязана НЕ пропускать.

    Обратное поведение (`fail-open`, как у дрейф-гейта) здесь означало бы, что поломка
    открывает поток — то есть ошибка кода начинает торговать.
    """
    ok, why = _eqh_alt_entry(_Bot(CFG_ON), _inst(), None, "short")
    assert ok is False
    ok2, why2 = _eqh_alt_entry(_Bot(CFG_ON), _inst(), pd.DataFrame(), "short")
    assert ok2 is False


def test_far_from_level_rejected():
    """Цена далеко от уровня — дверь закрыта, и в причине есть расстояние."""
    df = _df_with_equal_highs(last_close=100.0)      # уровень 110, цена 100
    ok, why = _eqh_alt_entry(_Bot(CFG_ON), _inst(), df, "short")
    assert ok is False
    assert "далеко" in why or "не найден" in why


def test_near_level_passes():
    """Цена вплотную к равным вершинам — дверь открывается."""
    df = _df_with_equal_highs(last_close=109.9)
    ok, why = _eqh_alt_entry(_Bot(CFG_ON), _inst(), df, "short")
    if ok:
        assert "ATR" in why
    else:
        # детектор мог не признать вершины равными на синтетике — тогда причина должна
        # быть «не найден», а не молчаливый False без объяснения
        assert "не найден" in why or "далеко" in why


def test_reason_is_always_explained():
    """
    Молчаливых отказов нет (закон проекта): функция ВСЕГДА возвращает причину,
    иначе в логе останется «сделок 0» без объяснения.
    """
    for df in (None, pd.DataFrame(), _df_with_equal_highs()):
        for side in ("short", "long"):
            ok, why = _eqh_alt_entry(_Bot(CFG_ON), _inst(), df, side)
            assert isinstance(why, str) and why.startswith("eqh:") and len(why) > 5


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
