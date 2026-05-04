"""
Тесты Bounce Detector (ARCH-15) и интеграции с MultiTFResolver.

Покрывает:
- Обнаружение валидных отскоков
- Фильтры (зона, кросс, сила тренда, cooldown)
- Волновой счёт (макс 2 отскока за импульс)
- Сброс импульса при смене тренда
- SPLIT решение в Resolver
- TradeSimulator dual trade_mode dedup
"""

import pytest
from datetime import datetime, timedelta
from core.indicators.bounce_detector import BounceDetector, BounceSignal, TradeMode, ImpulseTracker
from core.mtf.multi_tf_resolver import MultiTFResolver, TFSignal, ResolverDecision


# ---------------------------------------------------------------------------
# Фабрики
# ---------------------------------------------------------------------------

def _bounce_detector(enabled=True, max_bounces=2, cooldown=0, min_strength=50):
    return BounceDetector(config={
        "trading.bounce_mode.enabled": enabled,
        "trading.bounce_mode.max_bounces": max_bounces,
        "trading.bounce_mode.cooldown_sec": cooldown,
        "trading.bounce_mode.min_trend_strength": min_strength,
    })


def _sig(symbol="BTCUSDT", tf="15m", direction="LONG", strength=70,
         rr=3.0, signal_type="wt_signal", ts=None):
    s = TFSignal(
        symbol=symbol, timeframe=tf, direction=direction,
        signal_type=signal_type, strength=strength,
        rr_ratio=rr, timestamp=ts or datetime.now(),
    )
    return s


def _sig_with_wt(symbol="BTCUSDT", tf="5m", direction="LONG", strength=70,
                 wt_zone="OS", wt_cross=True, has_fvg=False):
    """Сигнал с WT-метаданными для bounce detection."""
    s = _sig(symbol=symbol, tf=tf, direction=direction, strength=strength)
    s._wt_zone = wt_zone
    s._wt_cross = wt_cross
    s._has_fvg = has_fvg
    return s


# ---------------------------------------------------------------------------
# TestBounceDetector — базовые тесты
# ---------------------------------------------------------------------------

class TestBounceDetectorBasic:
    def test_disabled_returns_none(self):
        bd = _bounce_detector(enabled=False)
        result = bd.detect_bounce(
            symbol="BTCUSDT", junior_tf="5m", junior_direction="LONG",
            junior_wt_zone="OS", junior_wt_cross=True,
            senior_tf="1h", senior_direction="SHORT", senior_trend_strength=80,
        )
        assert result is None

    def test_valid_bounce_long(self):
        """Тренд SHORT на 1h + LONG отскок на 5m в OS с кроссом → валидный bounce."""
        bd = _bounce_detector()
        result = bd.detect_bounce(
            symbol="BTCUSDT", junior_tf="5m", junior_direction="LONG",
            junior_wt_zone="OS", junior_wt_cross=True,
            senior_tf="1h", senior_direction="SHORT", senior_trend_strength=80,
        )
        assert result is not None
        assert result.bounce_direction == "LONG"
        assert result.trend_direction == "SHORT"
        assert result.trade_mode == TradeMode.SCALP
        assert result.bounce_number == 1
        assert result.is_valid

    def test_valid_bounce_short(self):
        """Тренд LONG на 1h + SHORT отскок на 5m в OB с кроссом."""
        bd = _bounce_detector()
        result = bd.detect_bounce(
            symbol="ETHUSDT", junior_tf="5m", junior_direction="SHORT",
            junior_wt_zone="OB", junior_wt_cross=True,
            senior_tf="1h", senior_direction="LONG", senior_trend_strength=75,
        )
        assert result is not None
        assert result.bounce_direction == "SHORT"
        assert result.trend_direction == "LONG"

    def test_same_direction_not_bounce(self):
        """Оба ТФ LONG → не отскок, а подтверждение."""
        bd = _bounce_detector()
        result = bd.detect_bounce(
            symbol="BTCUSDT", junior_tf="5m", junior_direction="LONG",
            junior_wt_zone="OS", junior_wt_cross=True,
            senior_tf="1h", senior_direction="LONG", senior_trend_strength=80,
        )
        assert result is None


# ---------------------------------------------------------------------------
# TestBounceFilters — фильтры входа
# ---------------------------------------------------------------------------

class TestBounceFilters:
    def test_wrong_zone_rejected(self):
        """LONG отскок но WT в OB (не в OS) → нет."""
        bd = _bounce_detector()
        result = bd.detect_bounce(
            symbol="BTCUSDT", junior_tf="5m", junior_direction="LONG",
            junior_wt_zone="OB", junior_wt_cross=True,
            senior_tf="1h", senior_direction="SHORT", senior_trend_strength=80,
        )
        assert result is None

    def test_neutral_zone_rejected(self):
        """LONG отскок в нейтральной зоне → нет."""
        bd = _bounce_detector()
        result = bd.detect_bounce(
            symbol="BTCUSDT", junior_tf="5m", junior_direction="LONG",
            junior_wt_zone="N", junior_wt_cross=True,
            senior_tf="1h", senior_direction="SHORT", senior_trend_strength=80,
        )
        assert result is None

    def test_no_wt_cross_rejected(self):
        """Зона правильная но нет WT кросса → нет."""
        bd = _bounce_detector()
        result = bd.detect_bounce(
            symbol="BTCUSDT", junior_tf="5m", junior_direction="LONG",
            junior_wt_zone="OS", junior_wt_cross=False,
            senior_tf="1h", senior_direction="SHORT", senior_trend_strength=80,
        )
        assert result is None

    def test_weak_trend_rejected(self):
        """Тренд слишком слабый (< min_strength) → нет."""
        bd = _bounce_detector(min_strength=60)
        result = bd.detect_bounce(
            symbol="BTCUSDT", junior_tf="5m", junior_direction="LONG",
            junior_wt_zone="OS", junior_wt_cross=True,
            senior_tf="1h", senior_direction="SHORT", senior_trend_strength=40,
        )
        assert result is None

    def test_fvg_bonus_increases_strength(self):
        """FVG даёт +15 к strength."""
        bd = _bounce_detector()
        without_fvg = bd.detect_bounce(
            symbol="BTCUSDT", junior_tf="5m", junior_direction="LONG",
            junior_wt_zone="OS", junior_wt_cross=True,
            senior_tf="1h", senior_direction="SHORT", senior_trend_strength=80,
        )
        bd2 = _bounce_detector()
        with_fvg = bd2.detect_bounce(
            symbol="ETHUSDT", junior_tf="5m", junior_direction="LONG",
            junior_wt_zone="OS", junior_wt_cross=True,
            senior_tf="1h", senior_direction="SHORT", senior_trend_strength=80,
            has_fvg=True,
        )
        assert with_fvg.strength > without_fvg.strength
        assert with_fvg.strength - without_fvg.strength == pytest.approx(15, abs=1)


# ---------------------------------------------------------------------------
# TestWaveCount — волновой счёт (макс 2 отскока за импульс)
# ---------------------------------------------------------------------------

class TestWaveCount:
    def test_two_bounces_allowed(self):
        """Два отскока в одном импульсе — ок (волны 2 и 4)."""
        bd = _bounce_detector(cooldown=0)
        b1 = bd.detect_bounce(
            symbol="BTCUSDT", junior_tf="5m", junior_direction="LONG",
            junior_wt_zone="OS", junior_wt_cross=True,
            senior_tf="1h", senior_direction="SHORT", senior_trend_strength=80,
        )
        assert b1 is not None
        assert b1.bounce_number == 1

        b2 = bd.detect_bounce(
            symbol="BTCUSDT", junior_tf="5m", junior_direction="LONG",
            junior_wt_zone="OS", junior_wt_cross=True,
            senior_tf="1h", senior_direction="SHORT", senior_trend_strength=80,
        )
        assert b2 is not None
        assert b2.bounce_number == 2

    def test_third_bounce_blocked(self):
        """Третий отскок блокируется (импульс исчерпал коррекции)."""
        bd = _bounce_detector(max_bounces=2, cooldown=0)
        bd.detect_bounce(
            symbol="BTCUSDT", junior_tf="5m", junior_direction="LONG",
            junior_wt_zone="OS", junior_wt_cross=True,
            senior_tf="1h", senior_direction="SHORT", senior_trend_strength=80,
        )
        bd.detect_bounce(
            symbol="BTCUSDT", junior_tf="5m", junior_direction="LONG",
            junior_wt_zone="OS", junior_wt_cross=True,
            senior_tf="1h", senior_direction="SHORT", senior_trend_strength=80,
        )
        b3 = bd.detect_bounce(
            symbol="BTCUSDT", junior_tf="5m", junior_direction="LONG",
            junior_wt_zone="OS", junior_wt_cross=True,
            senior_tf="1h", senior_direction="SHORT", senior_trend_strength=80,
        )
        assert b3 is None

    def test_trend_change_resets_count(self):
        """Смена тренда сбрасывает счётчик."""
        bd = _bounce_detector(max_bounces=2, cooldown=0)
        bd.detect_bounce(
            symbol="BTCUSDT", junior_tf="5m", junior_direction="LONG",
            junior_wt_zone="OS", junior_wt_cross=True,
            senior_tf="1h", senior_direction="SHORT", senior_trend_strength=80,
        )
        bd.detect_bounce(
            symbol="BTCUSDT", junior_tf="5m", junior_direction="LONG",
            junior_wt_zone="OS", junior_wt_cross=True,
            senior_tf="1h", senior_direction="SHORT", senior_trend_strength=80,
        )
        # Смена тренда на LONG
        bd.notify_trend_change("BTCUSDT", "LONG")
        # Теперь новый импульс — SHORT отскок от LONG тренда
        b = bd.detect_bounce(
            symbol="BTCUSDT", junior_tf="5m", junior_direction="SHORT",
            junior_wt_zone="OB", junior_wt_cross=True,
            senior_tf="1h", senior_direction="LONG", senior_trend_strength=75,
        )
        assert b is not None
        assert b.bounce_number == 1  # Сброшен

    def test_cooldown_blocks(self):
        """Cooldown между отскоками."""
        bd = _bounce_detector(cooldown=600)  # 10 мин
        bd.detect_bounce(
            symbol="BTCUSDT", junior_tf="5m", junior_direction="LONG",
            junior_wt_zone="OS", junior_wt_cross=True,
            senior_tf="1h", senior_direction="SHORT", senior_trend_strength=80,
        )
        # Второй сразу → cooldown
        b2 = bd.detect_bounce(
            symbol="BTCUSDT", junior_tf="5m", junior_direction="LONG",
            junior_wt_zone="OS", junior_wt_cross=True,
            senior_tf="1h", senior_direction="SHORT", senior_trend_strength=80,
        )
        assert b2 is None


# ---------------------------------------------------------------------------
# TestImpulseTracker
# ---------------------------------------------------------------------------

class TestImpulseTracker:
    def test_different_symbols_independent(self):
        bd = _bounce_detector(max_bounces=1, cooldown=0)
        b1 = bd.detect_bounce(
            symbol="BTCUSDT", junior_tf="5m", junior_direction="LONG",
            junior_wt_zone="OS", junior_wt_cross=True,
            senior_tf="1h", senior_direction="SHORT", senior_trend_strength=80,
        )
        # BTC исчерпал (max=1), но ETH — новый
        b_btc = bd.detect_bounce(
            symbol="BTCUSDT", junior_tf="5m", junior_direction="LONG",
            junior_wt_zone="OS", junior_wt_cross=True,
            senior_tf="1h", senior_direction="SHORT", senior_trend_strength=80,
        )
        b_eth = bd.detect_bounce(
            symbol="ETHUSDT", junior_tf="5m", junior_direction="LONG",
            junior_wt_zone="OS", junior_wt_cross=True,
            senior_tf="1h", senior_direction="SHORT", senior_trend_strength=80,
        )
        assert b_btc is None
        assert b_eth is not None

    def test_impulse_info(self):
        bd = _bounce_detector(cooldown=0)
        bd.detect_bounce(
            symbol="BTCUSDT", junior_tf="5m", junior_direction="LONG",
            junior_wt_zone="OS", junior_wt_cross=True,
            senior_tf="1h", senior_direction="SHORT", senior_trend_strength=80,
        )
        info = bd.get_impulse_info("BTCUSDT")
        assert info is not None
        assert info["direction"] == "SHORT"
        assert info["bounce_count"] == 1
        assert info["remaining_bounces"] == 1

    def test_stats(self):
        bd = _bounce_detector(cooldown=0)
        bd.detect_bounce(
            symbol="BTCUSDT", junior_tf="5m", junior_direction="LONG",
            junior_wt_zone="OS", junior_wt_cross=True,
            senior_tf="1h", senior_direction="SHORT", senior_trend_strength=80,
        )
        stats = bd.get_stats()
        assert stats["enabled"]
        assert stats["active_impulses"] == 1
        assert stats["total_bounces_tracked"] == 1


# ---------------------------------------------------------------------------
# TestResolverSplit — Resolver с bounce_detector
# ---------------------------------------------------------------------------

class TestResolverSplit:
    def test_split_with_bounce(self):
        """1h SHORT + 5m LONG(OS, cross) → SPLIT: тренд + отскок."""
        bd = _bounce_detector(cooldown=0)
        r = MultiTFResolver(bounce_detector=bd)

        senior = _sig(tf="1h", direction="SHORT", strength=75)
        junior = _sig_with_wt(tf="5m", direction="LONG", strength=65,
                              wt_zone="OS", wt_cross=True)
        r.add_signal(senior)
        r.add_signal(junior)
        d = r.resolve("BTCUSDT")

        assert d.action == "SPLIT"
        assert d.conflict_type == "bounce_split"
        assert d.chosen_signal.direction == "SHORT"   # тренд
        assert d.bounce_signal.direction == "LONG"     # отскок
        assert "SPLIT" in d.reason

    def test_no_bounce_without_detector(self):
        """Без BounceDetector → обычная логика (старший побеждает)."""
        r = MultiTFResolver()  # no bounce_detector
        r.add_signal(_sig(tf="1h", direction="SHORT", strength=75))
        r.add_signal(_sig_with_wt(tf="5m", direction="LONG", wt_zone="OS", wt_cross=True))
        d = r.resolve("BTCUSDT")
        assert d.action == "ACCEPT"
        assert d.chosen_signal.direction == "SHORT"
        assert d.bounce_signal is None

    def test_no_split_when_not_in_extreme(self):
        """5m LONG в нейтральной зоне → не отскок → обычная логика."""
        bd = _bounce_detector(cooldown=0)
        r = MultiTFResolver(bounce_detector=bd)
        r.add_signal(_sig(tf="1h", direction="SHORT", strength=75))
        r.add_signal(_sig_with_wt(tf="5m", direction="LONG", wt_zone="N", wt_cross=True))
        d = r.resolve("BTCUSDT")
        assert d.action == "ACCEPT"  # Обычная логика
        assert d.chosen_signal.direction == "SHORT"
        assert d.bounce_signal is None

    def test_no_split_without_cross(self):
        """5m LONG в OS но без кросса → не отскок."""
        bd = _bounce_detector(cooldown=0)
        r = MultiTFResolver(bounce_detector=bd)
        r.add_signal(_sig(tf="1h", direction="SHORT", strength=75))
        r.add_signal(_sig_with_wt(tf="5m", direction="LONG", wt_zone="OS", wt_cross=False))
        d = r.resolve("BTCUSDT")
        assert d.action == "ACCEPT"
        assert d.bounce_signal is None

    def test_split_respects_wave_limit(self):
        """После 2 bounce → SPLIT больше не срабатывает."""
        bd = _bounce_detector(max_bounces=2, cooldown=0)
        r = MultiTFResolver(bounce_detector=bd)

        for i in range(3):
            r.clear()
            r.add_signal(_sig(tf="1h", direction="SHORT", strength=75))
            r.add_signal(_sig_with_wt(tf="5m", direction="LONG", wt_zone="OS", wt_cross=True))
            d = r.resolve_and_clear("BTCUSDT")
            if i < 2:
                assert d.action == "SPLIT", f"Bounce #{i+1} should SPLIT"
            else:
                assert d.action == "ACCEPT", f"Bounce #{i+1} should fall back to ACCEPT (limit hit)"
                assert d.chosen_signal.direction == "SHORT"


# ---------------------------------------------------------------------------
# TestBounceStrength
# ---------------------------------------------------------------------------

class TestBounceStrength:
    def test_strong_trend_strong_bounce(self):
        bd = _bounce_detector()
        b = bd.detect_bounce(
            symbol="BTCUSDT", junior_tf="5m", junior_direction="LONG",
            junior_wt_zone="OS", junior_wt_cross=True,
            senior_tf="1h", senior_direction="SHORT", senior_trend_strength=100,
        )
        # 100×0.6=60 + 15(OS) + 10(cross) = 85
        assert b.strength == pytest.approx(85, abs=1)

    def test_min_trend_weaker_bounce(self):
        bd = _bounce_detector()
        b = bd.detect_bounce(
            symbol="BTCUSDT", junior_tf="5m", junior_direction="LONG",
            junior_wt_zone="OS", junior_wt_cross=True,
            senior_tf="1h", senior_direction="SHORT", senior_trend_strength=50,
        )
        # 50×0.6=30 + 15 + 10 = 55
        assert b.strength == pytest.approx(55, abs=1)

    def test_with_fvg_max_strength(self):
        bd = _bounce_detector()
        b = bd.detect_bounce(
            symbol="BTCUSDT", junior_tf="5m", junior_direction="LONG",
            junior_wt_zone="OS", junior_wt_cross=True,
            senior_tf="1h", senior_direction="SHORT", senior_trend_strength=100,
            has_fvg=True,
        )
        # 60 + 15 + 10 + 15 = 100
        assert b.strength == 100
