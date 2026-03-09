"""
Тесты для ConfigLoader.save_* методов.
Используют временный config.yaml, чтобы не трогать продакшн-конфиг.
"""
import os
import yaml
import pytest
from core.config_loader import ConfigLoader


MINIMAL_YAML = {
    "telegram": {"token": "${TELEGRAM_TOKEN}", "admin_id": "${ADMIN_ID}"},
    "analysis": {
        "volume_multiplier": 5.0,
        "price_threshold": 7.0,
        "check_interval": 60,
        "history_size": 200,
        "indicators": {
            "wavetrend": {"n1": 10, "n2": 21, "ob_threshold": 58.0, "os_threshold": -58.0},
            "trend": {"atr_period": 43, "factor": 1.0},
        },
    },
    "trading": {"use_tsl": True, "tsl_activation_r": 1.0, "tsl_buffer_pct": 0.1},
    "signal_quality": {
        "sl_cooldown_hours": 4,
        "dedup_minutes": 30,
        "min_volume_usd": 1000000,
        "min_strength": 50,
        "min_strength_register": 40,
    },
}


@pytest.fixture
def cfg(tmp_path):
    """ConfigLoader, указывающий на временный yaml-файл."""
    path = str(tmp_path / "config.yaml")
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(MINIMAL_YAML, f, allow_unicode=True, default_flow_style=False)
    return ConfigLoader(config_path=path)


# ──────────────────────────────────────────────────────────────────────────────
# save_analysis
# ──────────────────────────────────────────────────────────────────────────────

class TestSaveAnalysis:
    def test_returns_true(self, cfg):
        assert cfg.save_analysis(6.0, 8.0, 120, 300) is True

    def test_values_persisted(self, cfg):
        cfg.save_analysis(6.5, 9.0, 90, 250)
        assert cfg.get("analysis.volume_multiplier") == 6.5
        assert cfg.get("analysis.price_threshold") == 9.0
        assert cfg.get("analysis.check_interval") == 90
        assert cfg.get("analysis.history_size") == 250

    def test_written_to_file(self, cfg):
        cfg.save_analysis(7.0, 10.0, 45, 150)
        with open(cfg.config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        assert raw["analysis"]["volume_multiplier"] == 7.0
        assert raw["analysis"]["check_interval"] == 45


# ──────────────────────────────────────────────────────────────────────────────
# save_indicators
# ──────────────────────────────────────────────────────────────────────────────

class TestSaveIndicators:
    def test_returns_true(self, cfg):
        assert cfg.save_indicators(12, 25, 60.0, -60.0, 50, 1.2) is True

    def test_wavetrend_values(self, cfg):
        cfg.save_indicators(12, 25, 65.0, -65.0, 50, 1.2)
        assert cfg.get("analysis.indicators.wavetrend.n1") == 12
        assert cfg.get("analysis.indicators.wavetrend.n2") == 25
        assert cfg.get("analysis.indicators.wavetrend.ob_threshold") == 65.0
        assert cfg.get("analysis.indicators.wavetrend.os_threshold") == -65.0

    def test_trend_values(self, cfg):
        cfg.save_indicators(10, 21, 58.0, -58.0, 30, 0.8)
        assert cfg.get("analysis.indicators.trend.atr_period") == 30
        assert abs(cfg.get("analysis.indicators.trend.factor") - 0.8) < 1e-6


# ──────────────────────────────────────────────────────────────────────────────
# save_trading
# ──────────────────────────────────────────────────────────────────────────────

class TestSaveTrading:
    def test_returns_true(self, cfg):
        assert cfg.save_trading(False, 1.5, 0.05) is True

    def test_use_tsl_false(self, cfg):
        cfg.save_trading(False, 1.5, 0.05)
        assert cfg.get("trading.use_tsl") is False

    def test_use_tsl_true(self, cfg):
        cfg.save_trading(True, 2.0, 0.15)
        assert cfg.get("trading.use_tsl") is True

    def test_activation_and_buffer(self, cfg):
        cfg.save_trading(True, 1.5, 0.075)
        assert cfg.get("trading.tsl_activation_r") == 1.5
        assert abs(cfg.get("trading.tsl_buffer_pct") - 0.075) < 1e-6


# ──────────────────────────────────────────────────────────────────────────────
# save_signal_quality
# ──────────────────────────────────────────────────────────────────────────────

class TestSaveSignalQuality:
    def test_returns_true(self, cfg):
        assert cfg.save_signal_quality(6, 45, 500000, 55, 45) is True

    def test_all_fields(self, cfg):
        cfg.save_signal_quality(8, 20, 2000000, 60, 50)
        assert cfg.get("signal_quality.sl_cooldown_hours") == 8
        assert cfg.get("signal_quality.dedup_minutes") == 20
        assert cfg.get("signal_quality.min_volume_usd") == 2000000
        assert cfg.get("signal_quality.min_strength") == 60
        assert cfg.get("signal_quality.min_strength_register") == 50

    def test_file_updated(self, cfg):
        cfg.save_signal_quality(3, 15, 750000, 45, 35)
        with open(cfg.config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        assert raw["signal_quality"]["min_strength"] == 45
        assert raw["signal_quality"]["min_strength_register"] == 35


# ──────────────────────────────────────────────────────────────────────────────
# get() — обход вложенных ключей
# ──────────────────────────────────────────────────────────────────────────────

class TestGetMethod:
    def test_nested_key(self, cfg):
        val = cfg.get("analysis.volume_multiplier")
        assert val == 5.0

    def test_missing_key_returns_default(self, cfg):
        val = cfg.get("nonexistent.key", "fallback")
        assert val == "fallback"

    def test_missing_key_returns_none(self, cfg):
        val = cfg.get("nonexistent.key")
        assert val is None
