# -*- coding: utf-8 -*-
"""Тесты Сферы 19 (Market Data, ARCH-129.1).

Ловушки, ради которых тесты написаны, — реальные, не выдуманные:
  · единицы: ccxt и `funding_rates` дают ДОЛЮ, а `risk_intelligence` ждёт ПРОЦЕНТЫ;
  · интервалы 1/2/4/8ч сосуществуют в данных — приводить обязательно;
  · поля должны реально доезжать до PairState (`update()` молча роняет неизвестные).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.context.market_data_sphere import (  # noqa: E402
    MarketDataSphere, build_state, cumulative, percentile_of, sign_streak, to_8h,
)
from core.context.pair_context import PairContextBus  # noqa: E402


class TestUnits:
    def test_fraction_to_percent_8h(self):
        # BTC: доля 0.00007 за 8ч = 0.007%
        assert to_8h(0.00007, 8) == pytest.approx(0.007, abs=1e-6)

    def test_interval_normalisation(self):
        # HYPE 30.08: −0.0064% за 4ч → вдвое больше за 8ч
        assert to_8h(-0.000064, 4) == pytest.approx(-0.0128, abs=1e-6)

    def test_already_percent_not_scaled(self):
        assert to_8h(0.007, 8, as_fraction=False) == pytest.approx(0.007, abs=1e-9)

    def test_unknown_interval_keeps_scale(self):
        # интервал неизвестен — масштаб не выдумываем, но в проценты переводим
        assert to_8h(0.0001, 0) == pytest.approx(0.01, abs=1e-9)


class TestStreak:
    def test_positive_streak(self):
        assert sign_streak([0.1, 0.2, 0.3]) == 3

    def test_negative_streak_signed(self):
        assert sign_streak([0.1, -0.2, -0.3]) == -2

    def test_break_resets(self):
        assert sign_streak([-0.1, -0.2, 0.3]) == 1

    def test_empty_and_zero(self):
        assert sign_streak([]) == 0
        assert sign_streak([0.1, 0.0]) == 0


class TestDerived:
    def test_percentile_needs_history(self):
        assert percentile_of(0.5, [0.1] * 10) is None      # <20 точек — не врём

    def test_percentile_mid(self):
        hist = [i / 100 for i in range(100)]
        assert percentile_of(0.5, hist) == pytest.approx(50.0, abs=1.0)

    def test_cumulative_window(self):
        # 8ч интервал, окно 72ч → последние 9 значений
        assert cumulative([1.0] * 20, 8, hours=72.0) == pytest.approx(9.0)

    def test_cumulative_needs_interval(self):
        assert cumulative([1.0], 0) is None


class TestBusIntegration:
    def test_fields_reach_pairstate(self):
        """Главная проверка: публикация не уходит в никуда."""
        bus = PairContextBus()
        sph = MarketDataSphere(bus)
        sph.observe_and_publish("TEST/USDT", -0.000097, interval_h=4, source="bingx")
        st = bus.get("TEST/USDT")
        assert st.funding_rate == pytest.approx(-0.000097)
        assert st.funding_interval_h == 4
        assert st.funding_source == "bingx"
        assert st.funding_pct_8h == pytest.approx(-0.0194, abs=1e-4)
        assert st.funding_updated_at is not None

    def test_streak_accumulates_across_calls(self):
        sph = MarketDataSphere()
        for _ in range(3):
            st = sph.observe("X/USDT", -0.0001, 8, "cache")
        assert st.streak == -3

    def test_warmup_feeds_history(self):
        sph = MarketDataSphere()
        sph.warmup("Y/USDT", [0.0001] * 30, 8)
        st = sph.observe("Y/USDT", 0.0001, 8, "cache")
        assert st.pctile_90d is not None      # история есть → перцентиль считается
        assert st.streak == 31

    def test_no_bus_does_not_crash(self):
        MarketDataSphere().observe_and_publish("Z/USDT", 0.0001, 8, "cache")


def test_build_state_shape():
    st = build_state(0.0001, 8, "binance", history=[0.0001] * 25)
    p = st.as_bus_payload()
    assert set(p) == {"rate", "interval_h", "source", "pct_8h", "streak",
                      "pctile_90d", "cum_3d"}


class TestOpenInterest:
    """ARCH-129.2. Метки взяты ИЗ `radar_state.quadrant`, а не придуманы:
    формат «PUP+OIDN», состояний три (UP/DN/FL) — проверено на 389 живых строках."""

    def test_short_squeeze(self):
        from core.context.market_data_sphere import squeeze_flag
        assert squeeze_flag("PUP+OIDN") == "short_squeeze"

    def test_long_flush(self):
        from core.context.market_data_sphere import squeeze_flag
        assert squeeze_flag("PDN+OIDN") == "long_flush"

    def test_confirmed_move_is_not_squeeze(self):
        from core.context.market_data_sphere import squeeze_flag
        assert squeeze_flag("PUP+OIUP") is None      # рост на растущем OI — подтверждён
        assert squeeze_flag("PDN+OIUP") is None

    def test_flat_oi_is_not_squeeze(self):
        from core.context.market_data_sphere import squeeze_flag
        for q in ("PUP+OIFL", "PDN+OIFL", "PFL+OIFL", "PFL+OIUP", "PFL+OIDN"):
            assert squeeze_flag(q) is None

    def test_missing_quadrant(self):
        from core.context.market_data_sphere import squeeze_flag
        assert squeeze_flag(None) is None
        assert squeeze_flag("") is None

    def test_oi_reaches_pairstate(self):
        bus = PairContextBus()
        sph = MarketDataSphere(bus)
        sq = sph.publish_oi("OI/USDT", d5=-0.8, d15=-2.1, d1d=-11.4, quadrant="PUP+OIDN")
        st = bus.get("OI/USDT")
        assert sq == "short_squeeze"
        assert st.oi_d5 == pytest.approx(-0.8)
        assert st.oi_d1d == pytest.approx(-11.4)
        assert st.oi_px_quadrant == "PUP+OIDN"
        assert st.oi_updated_at is not None


class TestMarketState:
    """ARCH-129.6 — L3 рыночное измерение шины (глобальное, не per-pair)."""

    def test_container_is_single(self):
        bus = PairContextBus()
        assert bus.get_market() is bus.get_market()      # один на весь рынок

    def test_never_none(self):
        assert PairContextBus().get_market() is not None

    def test_update_and_read(self):
        bus = PairContextBus()
        bus.update_market(usdt_d=6.96, btc_d=58.85, n_coins=499)
        m = bus.get_market()
        assert m.usdt_d == pytest.approx(6.96)
        assert m.btc_d == pytest.approx(58.85)
        assert m.n_coins == 499
        assert m.updated_at is not None

    def test_unknown_key_ignored_not_crashed(self):
        bus = PairContextBus()
        bus.update_market(usdt_d=7.0, no_such_field=1)
        assert bus.get_market().usdt_d == pytest.approx(7.0)
        assert not hasattr(bus.get_market(), "no_such_field")

    def test_partial_update_keeps_previous(self):
        bus = PairContextBus()
        bus.update_market(usdt_d=7.0, btc_d=58.0)
        bus.update_market(usdt_d=7.1)
        assert bus.get_market().btc_d == pytest.approx(58.0)   # не затёрли

    def test_percentile_depth_is_published(self):
        """Глубина истории обязана ехать рядом с перцентилем: её всего 37 дней,
        а спека просила «за 120 дней» — без глубины число врало бы молча."""
        bus = PairContextBus()
        bus.update_market(usdt_d_pctile=16.2, usdt_d_hist_days=37)
        m = bus.get_market()
        assert m.usdt_d_pctile == pytest.approx(16.2)
        assert m.usdt_d_hist_days == 37

    def test_two_drifts_are_separate_fields(self):
        """🔴 В проекте ДВА дрейфа: дневной по 437 монетам (боевой гейт) и часовой
        по 48 (радар). Путаница между ними уже случалась однажды. Поля обязаны
        существовать раздельно и не затирать друг друга."""
        bus = PairContextBus()
        bus.update_market(ud_drift30=11.68, ud_short_zone=True,
                          regime_drift_1h=0.124, regime_label="НЕЙТРАЛЬ")
        m = bus.get_market()
        assert m.ud_drift30 == pytest.approx(11.68)      # дневной, 437 монет
        assert m.regime_drift_1h == pytest.approx(0.124)  # часовой, 48 монет
        assert m.ud_drift30 != m.regime_drift_1h
        assert m.ud_short_zone is True
        assert m.regime_label == "НЕЙТРАЛЬ"

    def test_drift_day_is_published(self):
        """Дрейф ДНЕВНОЙ — без даты не видно, что число может быть вчерашним."""
        bus = PairContextBus()
        bus.update_market(ud_drift30=11.68, ud_day="2026-08-31")
        assert bus.get_market().ud_day == "2026-08-31"
