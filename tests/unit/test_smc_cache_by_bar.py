# -*- coding: utf-8 -*-
"""SMC считается раз на закрытый бар, а не каждый цикл (05.10.2026, «прореживание»).

Повод — замер `[SCAN-PERF]`, трижды давший один ответ: SMC единственный настоящий потребитель
цикла скана (1.2-1.4 с на пару × 565 пар ≈ 750 с CPU за круг, 98% блока «детекторы и прочее»).
Структура (OB/FVG/BOS/CHoCH/OTE) строится по ЗАКРЫТЫМ барам, а цикл идёт 3-7 минут против
15-минутного бара — одно и то же считалось по 2-5 раз подряд.

Кэшировать можно целиком, потому что `current_price` в расчёте не участвует: он лишь кладётся
в готовый snap. Тесты закрепляют оба свойства — и экономию, и свежесть цены.
"""
from __future__ import annotations

import pandas as pd
import pytest

from core.smc import sub_cube as sc


@pytest.fixture()
def bars():
    idx = pd.date_range("2026-10-05 10:00", periods=50, freq="15min")
    return pd.DataFrame({"open": range(50), "high": range(1, 51),
                         "low": range(50), "close": range(1, 51)}, index=idx)


@pytest.fixture()
def cube(monkeypatch):
    calls = {"n": 0}

    def _fake_build(symbol, ohlcv_by_tf):
        calls["n"] += 1
        return {"ob": "x", "built_for": symbol}

    monkeypatch.setattr(sc, "build_smc_snapshot", _fake_build)
    monkeypatch.setattr(sc, "fast_smc_verdict", lambda a, b: "NEUTRAL")
    return sc.SMCSubCube(), calls


def test_second_call_on_same_bar_does_not_recompute(cube, bars):
    c, calls = cube
    c.compute_and_publish("BTC/USDT:USDT", {"15m": bars}, current_price=100.0)
    c.compute_and_publish("BTC/USDT:USDT", {"15m": bars}, current_price=101.0)
    c.compute_and_publish("BTC/USDT:USDT", {"15m": bars}, current_price=102.0)
    assert calls["n"] == 1, "структура пересчитана на том же баре — прореживание не работает"
    assert c.cache_stats()["hit"] == 2


def test_price_is_fresh_on_cache_hit(cube, bars):
    """Главное условие: экономим расчёт, но цена в снимке обязана быть СВЕЖЕЙ."""
    c, _ = cube
    first = c.compute_and_publish("BTC/USDT:USDT", {"15m": bars}, current_price=100.0)
    second = c.compute_and_publish("BTC/USDT:USDT", {"15m": bars}, current_price=777.0)
    assert first["_current_price"] == 100.0
    assert second["_current_price"] == 777.0, "из кэша вернулась устаревшая цена"


def test_new_bar_invalidates(cube, bars):
    c, calls = cube
    c.compute_and_publish("BTC/USDT:USDT", {"15m": bars}, current_price=100.0)
    grown = pd.concat([bars, bars.tail(1).rename(index={bars.index[-1]: bars.index[-1] + pd.Timedelta(minutes=15)})])
    c.compute_and_publish("BTC/USDT:USDT", {"15m": grown}, current_price=100.0)
    assert calls["n"] == 2, "новый закрытый бар обязан инвалидировать кэш"


def test_other_tf_update_invalidates(cube, bars):
    """Обновился ЛЮБОЙ ТФ — ключ меняется: структура считается по всем сразу."""
    c, calls = cube
    c.compute_and_publish("BTC/USDT:USDT", {"15m": bars, "1h": bars}, current_price=100.0)
    c.compute_and_publish("BTC/USDT:USDT", {"15m": bars, "1h": bars.head(49)}, current_price=100.0)
    assert calls["n"] == 2


def test_cache_is_per_symbol(cube, bars):
    c, calls = cube
    c.compute_and_publish("BTC/USDT:USDT", {"15m": bars}, current_price=100.0)
    c.compute_and_publish("ETH/USDT:USDT", {"15m": bars}, current_price=100.0)
    assert calls["n"] == 2, "кэш одной монеты не должен отдаваться другой"


def test_cached_snap_is_a_copy(cube, bars):
    """Подписчик шины правит свой словарь — кэш не должен портиться."""
    c, _ = cube
    first = c.compute_and_publish("BTC/USDT:USDT", {"15m": bars}, current_price=100.0)
    first["ob"] = "ИСПОРЧЕНО"
    second = c.compute_and_publish("BTC/USDT:USDT", {"15m": bars}, current_price=100.0)
    assert second["ob"] == "x"


def _bot_bars(t0_ms: int, n: int = 50, step_ms: int = 900_000) -> pd.DataFrame:
    """ФОРМАТ БОТА из общей заготовки (паспорт данных, правило 8): окно из `n` свечей, первая открылась в `t0_ms`."""
    from tests.factories import bot_bars
    return bot_bars(n=n, tf="15m", last_open_ms=t0_ms + (n - 1) * step_ms)


def test_bot_format_new_bar_invalidates(cube):
    """F01 внешнего аудита (10.2026): окно сдвинулось на бар, длина и номер последней строки те же —
    ключ обязан измениться. Тесты выше этого не ловили: они на DatetimeIndex и на растущем окне."""
    c, calls = cube
    a = _bot_bars(1_760_000_000_000)
    b = _bot_bars(1_760_000_000_000 + 900_000)
    assert len(a) == len(b) and a.index[-1] == b.index[-1], "тест должен повторять формат бота"
    c.compute_and_publish("BTC/USDT:USDT", {"15m": a}, current_price=100.0)
    c.compute_and_publish("BTC/USDT:USDT", {"15m": b}, current_price=100.0)
    assert calls["n"] == 2, "новый бар на формате бота не инвалидировал кэш — структура замёрзнет"


def test_bot_format_same_bar_hits(cube):
    c, calls = cube
    a = _bot_bars(1_760_000_000_000)
    c.compute_and_publish("BTC/USDT:USDT", {"15m": a}, current_price=100.0)
    c.compute_and_publish("BTC/USDT:USDT", {"15m": a.copy()}, current_price=101.0)
    assert calls["n"] == 1 and c.cache_stats()["hit"] == 1


def test_no_bar_time_disables_cache(cube):
    """Нет колонки `time` и индекс не временной — номер строки временем не считаем, кэш выключен."""
    c, calls = cube
    df = _bot_bars(1_760_000_000_000).drop(columns=["time"])
    assert c._bars_key({"15m": df}) is None
    c.compute_and_publish("BTC/USDT:USDT", {"15m": df}, current_price=100.0)
    c.compute_and_publish("BTC/USDT:USDT", {"15m": df}, current_price=100.0)
    assert calls["n"] == 2


def test_no_data_disables_cache(cube):
    """Пустой вход — кэш не применяется, молчаливых «снимков из ниоткуда» быть не должно."""
    c, calls = cube
    assert c._bars_key({}) is None
    c.compute_and_publish("BTC/USDT:USDT", {}, current_price=100.0)
    c.compute_and_publish("BTC/USDT:USDT", {}, current_price=100.0)
    assert calls["n"] == 2
