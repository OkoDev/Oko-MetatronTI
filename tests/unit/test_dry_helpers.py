"""Unit-тесты для helper-модулей DRY-рефакторинга 27.05.2026:
   bingx_client.{to_bingx_symbol, from_bingx_symbol}
   trading_settings.{get_*, is_live, TradingSettings}
   signal_models.to_direction
   time_utils.{utc_now, utc_iso, parse_iso_utc, ensure_utc}
"""
from datetime import datetime, timezone, timedelta

from core.exchange.bingx_client import to_bingx_symbol, from_bingx_symbol
from core.infra.trading_settings import (
    get_deposit, get_risk_pct, get_leverage, get_execution_mode, is_live,
    TradingSettings,
    DEFAULT_DEPOSIT_USDT, DEFAULT_RISK_PCT, DEFAULT_LEVERAGE,
)
from core.infra.time_utils import utc_now, utc_iso, parse_iso_utc, ensure_utc
from core.signals.signal_models import to_direction, SignalDirection


# ── Symbol conversion ────────────────────────────────────────────────────
class TestSymbolFormat:
    def test_to_bingx_basic(self):
        assert to_bingx_symbol("BTC/USDT:USDT") == "BTC-USDT"
        assert to_bingx_symbol("ETH/USDT:USDT") == "ETH-USDT"

    def test_from_bingx_basic(self):
        assert from_bingx_symbol("BTC-USDT") == "BTC/USDT:USDT"

    def test_round_trip(self):
        for sym in ("BTC/USDT:USDT", "ETH/USDT:USDT", "FHE/USDT:USDT"):
            assert from_bingx_symbol(to_bingx_symbol(sym)) == sym

    def test_empty_safe(self):
        assert to_bingx_symbol("") == ""
        assert from_bingx_symbol("") == ""

    def test_none_safe(self):
        assert to_bingx_symbol(None) == ""
        assert from_bingx_symbol(None) == ""


# ── Trading settings ─────────────────────────────────────────────────────
class _FakeConfig:
    def __init__(self, data):
        self.data = data

    def get(self, key, default=None):
        # Поддержка точечной нотации как config_loader
        keys = key.split(".")
        v = self.data
        try:
            for k in keys:
                v = v[k]
            return v
        except (KeyError, TypeError):
            return default


class TestTradingSettings:
    def test_defaults_when_empty(self):
        cfg = _FakeConfig({})
        assert get_deposit(cfg) == DEFAULT_DEPOSIT_USDT
        assert get_risk_pct(cfg) == DEFAULT_RISK_PCT
        assert get_leverage(cfg) == DEFAULT_LEVERAGE
        assert get_execution_mode(cfg) == "sim_only"
        assert is_live(cfg) is False

    def test_live_modes(self):
        for mode in ("vst", "live"):
            cfg = _FakeConfig({"trading": {"execution_mode": mode}})
            assert is_live(cfg) is True

    def test_sim_only_not_live(self):
        cfg = _FakeConfig({"trading": {"execution_mode": "sim_only"}})
        assert is_live(cfg) is False

    def test_case_insensitive_mode(self):
        cfg = _FakeConfig({"trading": {"execution_mode": "VST"}})
        assert is_live(cfg) is True

    def test_dataclass_from_config(self):
        cfg = _FakeConfig({"trading": {
            "deposit_usdt": 5000.0, "risk_pct": 0.5, "leverage": 10,
            "execution_mode": "live"}})
        ts = TradingSettings.from_config(cfg)
        assert ts.deposit_usdt == 5000.0
        assert ts.risk_pct == 0.5
        assert ts.leverage == 10
        assert ts.is_live is True


# ── Direction normalization ──────────────────────────────────────────────
class TestToDirection:
    def test_enum(self):
        assert to_direction(SignalDirection.LONG) == "LONG"
        assert to_direction(SignalDirection.SHORT) == "SHORT"
        assert to_direction(SignalDirection.NEUTRAL) == "NEUTRAL"

    def test_strings(self):
        assert to_direction("LONG") == "LONG"
        assert to_direction("long") == "LONG"
        assert to_direction("Short") == "SHORT"

    def test_buy_sell(self):
        assert to_direction("BUY") == "LONG"
        assert to_direction("SELL") == "SHORT"

    def test_none(self):
        assert to_direction(None) == "NEUTRAL"

    def test_unknown_neutral(self):
        assert to_direction("XYZ") == "NEUTRAL"
        assert to_direction("") == "NEUTRAL"


# ── Time utils ───────────────────────────────────────────────────────────
class TestTimeUtils:
    def test_utc_now_is_aware(self):
        dt = utc_now()
        assert dt.tzinfo == timezone.utc

    def test_utc_iso_format(self):
        s = utc_iso()
        assert "T" in s
        assert "+00:00" in s

    def test_parse_iso_z_suffix(self):
        dt = parse_iso_utc("2026-05-27T01:30:00Z")
        assert dt.tzinfo == timezone.utc
        assert dt.hour == 1

    def test_parse_iso_plus_offset(self):
        dt = parse_iso_utc("2026-05-27T01:30:00+00:00")
        assert dt.tzinfo == timezone.utc

    def test_round_trip(self):
        s = utc_iso()
        dt = parse_iso_utc(s)
        # ISO → parse → должен быть тем же моментом
        assert (dt - utc_now()) < timedelta(seconds=1)

    def test_ensure_utc_promotes_naive(self):
        naive = datetime(2026, 5, 27, 1, 30)
        aware = ensure_utc(naive)
        assert aware.tzinfo == timezone.utc

    def test_ensure_utc_passes_through_aware(self):
        aware = datetime(2026, 5, 27, 1, 30, tzinfo=timezone.utc)
        assert ensure_utc(aware) is aware
