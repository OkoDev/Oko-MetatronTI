"""
Регрессия WaveService (ARCH-132, 29.08.2026).

Сервис реализует спецификацию `docs/CUBE_SUBCUBES.md` §Sub-куб 2, которая была написана
08.06.2026 и провисела 11 недель, пока панель Куба показывала сферу готовой.

Тесты охраняют то, что отличает эту реализацию от спеки и что легко сломать:
  · ПАМЯТЬ разметки (требование Егора) — история и счётчик пересчётов;
  · публикацию в шину РЕАЛЬНО существующими полями (иначе `update()` роняет их в debug —
    ровно класс «молчаливый отказ», из-за которого поля пришлось заводить заранее);
  · причинность: хвост ряда длиной `period` баров не подтверждён и помечается.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.context.pair_context import PairContextBus, PairState      # noqa: E402
from core.intelligence.wave_service import (SWING_PERIOD_4H, WavePhase,  # noqa: E402
                                            WaveService, WaveSnapshot)


def _df(n=120, seed=7, drift=-0.4):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(drift, 1.0, n))
    wick = np.abs(rng.normal(0, 0.6, n))
    idx = pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC")
    return pd.DataFrame({"open": close, "close": close,
                         "high": close + wick, "low": close - wick,
                         "volume": 100.0}, index=idx)


def test_publishes_into_existing_bus_fields():
    """
    🔴 ГЛАВНЫЙ: поля должны РЕАЛЬНО существовать в PairState.

    `PairContextBus.update()` молча отбрасывает неизвестные ключи в debug-лог. Если поля
    не заведены, сервис будет «работать», а в шине не появится ничего — молчаливый отказ.
    """
    bus = PairContextBus()
    svc = WaveService()
    svc.compute_and_publish("TEST/USDT", _df(), _df(n=200), _df(n=300), bus)
    st = bus.get("TEST/USDT")
    for f in ("elliott_n_down", "elliott_n_up", "elliott_phase",
              "elliott_conf", "wave_snap", "wave_recounts", "wave_updated_at"):
        assert hasattr(st, f), f"поля {f} нет в PairState — публикация уйдёт в никуда"
    assert st.wave_snap is not None and st.wave_updated_at is not None
    assert st.elliott_phase


def test_history_accumulates():
    """Требование Егора: волны хранятся ВО ВРЕМЕНИ, а не только последняя."""
    svc = WaveService()
    bus = PairContextBus()
    assert svc.history("X/USDT") == []
    for i in range(5):
        svc.compute_and_publish("X/USDT", _df(seed=i), None, None, bus)
    h = svc.history("X/USDT")
    assert len(h) == 5, f"история не копится: {len(h)}"
    assert all(isinstance(s, WaveSnapshot) for s in h)
    assert h[-1] is svc.last("X/USDT")


def test_recount_detected_and_counted():
    """
    🔴 Слом счёта — отдельное событие, а не смена числа. По канону он означает, что
    прошлая разметка была неверной; сейчас его не видит никто, потому что каждый прогон
    считает с нуля.
    """
    svc = WaveService()
    prev = WaveSnapshot(ts=pd.Timestamp("2026-01-01", tz="UTC"), n_down=4, phase="wave3_mid")
    # падение номера волны больше чем на 1 = вершины пересчитаны
    assert svc._is_recount(prev, WaveSnapshot(ts=prev.ts, n_down=1, phase="wave3_mid"))
    # нормальное развитие сломом НЕ является
    assert not svc._is_recount(prev, WaveSnapshot(ts=prev.ts, n_down=5, phase="wave3_mid"))
    assert not svc._is_recount(prev, WaveSnapshot(ts=prev.ts, n_down=3, phase="wave3_mid"))
    # «через голову»: финал волны 5 сразу в середину волны 3
    p5 = WaveSnapshot(ts=prev.ts, n_down=4, phase="wave5_final")
    assert svc._is_recount(p5, WaveSnapshot(ts=prev.ts, n_down=4, phase="wave3_mid"))


def test_recount_counter_grows_in_bus():
    """Счётчик пересчётов доходит до шины — иначе его никто не увидит."""
    svc = WaveService()
    bus = PairContextBus()
    svc._history["Y/USDT"] = __import__("collections").deque(
        [WaveSnapshot(ts=pd.Timestamp("2026-01-01", tz="UTC"), n_down=9,
                      phase="wave3_mid")], maxlen=8)
    svc.compute_and_publish("Y/USDT", _df(), None, None, bus)   # n_down упадёт с 9
    assert svc.recount_count("Y/USDT") >= 1
    assert bus.get("Y/USDT").wave_recounts >= 1
    assert bus.get("Y/USDT").wave_recount_ts is not None


def test_unconfirmed_tail_is_marked():
    """
    🔴 ПРИЧИННОСТЬ: `find_swing_highs` подтверждает пивот через `period` баров с каждой
    стороны, поэтому хвост ряда не окончателен. Сервис обязан это помечать, иначе
    потребитель примет неподтверждённую разметку за факт.
    """
    svc = WaveService()
    bus = PairContextBus()
    svc.compute_and_publish("Z/USDT", _df(), None, None, bus)
    assert svc.last("Z/USDT").unconfirmed_bars == SWING_PERIOD_4H


def test_short_series_does_not_crash():
    """Меньше MIN_BARS — сервис отдаёт undefined, а не падает."""
    svc = WaveService()
    bus = PairContextBus()
    ph = svc.compute_and_publish("S/USDT", _df(n=5), None, None, bus)
    assert isinstance(ph, WavePhase) and ph.phase == "undefined"


def test_phase_rules_match_spec():
    """Правила фазы — из спецификации, а не переизобретены."""
    svc = WaveService()

    class Ctx:
        htf_price_dir = "up"; smc_snap = {"choch": True}; active_divergence = None
    assert svc._detect_phase({"n_down": 3}, Ctx()).phase == "ABC_waveB"

    class Ctx2:
        htf_price_dir = "down"; smc_snap = {}; active_divergence = {"k": 1}
    assert svc._detect_phase({"n_down": 3}, Ctx2()).phase == "wave5_final"

    class Ctx3:
        htf_price_dir = "down"; smc_snap = {}; active_divergence = None
    assert svc._detect_phase({"n_down": 0}, Ctx3()).phase == "impulse_start"
    assert svc._detect_phase({"n_down": 2}, Ctx3()).phase == "wave3_mid"
    assert svc._detect_phase({"n_down": 0}, None).phase == "undefined"


def test_htf_dir_is_self_computed():
    """
    🔴 Спецификация брала `htf_price_dir` из шины, но такого поля НЕТ нигде в проекте
    (грep 29.08: единственное упоминание — в самом сервисе). По спеке фаза всегда была бы
    `undefined`. Сервис обязан считать направление сам — иначе он «работает» вхолостую.
    """
    svc = WaveService()
    n = 40
    idx = pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC")
    up = pd.DataFrame({"close": np.linspace(100, 130, n),
                       "high": np.linspace(101, 131, n),
                       "low": np.linspace(99, 129, n)}, index=idx)
    dn = pd.DataFrame({"close": np.linspace(130, 100, n),
                       "high": np.linspace(131, 101, n),
                       "low": np.linspace(129, 99, n)}, index=idx)
    flat = pd.DataFrame({"close": np.full(n, 100.0),
                         "high": np.full(n, 101.0),
                         "low": np.full(n, 99.0)}, index=idx)
    assert svc._htf_dir(up) == "up"
    assert svc._htf_dir(dn) == "down"
    assert svc._htf_dir(flat) == "flat"
    assert svc._htf_dir(None) == "flat"          # нет данных — не падаем
    assert svc._htf_dir(up.head(3)) == "flat"    # слишком короткий ряд


def test_phase_is_not_always_undefined():
    """
    Негативный к предыдущему: на трендовом ряду фаза обязана определиться.
    Если снова всё `undefined` — значит htf_dir опять не доезжает до правил.
    """
    svc, bus = WaveService(), PairContextBus()
    n = 200
    rng = np.random.default_rng(3)
    close = 200 - np.cumsum(np.abs(rng.normal(0.5, 0.3, n)))   # устойчиво вниз
    idx = pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC")
    df = pd.DataFrame({"open": close, "close": close,
                       "high": close + 1, "low": close - 1, "volume": 1.0}, index=idx)
    ph = svc.compute_and_publish("D/USDT", df, None, None, bus)
    assert ph.phase != "undefined", "фаза не определяется даже на явном тренде"


def test_works_without_bus_and_event_bus():
    """Сервис не обязан требовать шину — иначе его нельзя прогнать в исследовании."""
    svc = WaveService()
    ph = svc.compute_and_publish("N/USDT", _df(), None, None, None, None)
    assert isinstance(ph, WavePhase)
    assert len(svc.history("N/USDT")) == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
