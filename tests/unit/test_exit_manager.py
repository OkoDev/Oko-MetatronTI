"""Unit-тесты для ExitManager.magnet_tp_locked (ARCH-122 ч.1b, 31.05.2026)."""
from core.trading.exit_manager import magnet_tp_locked


class _Rec:
    def __init__(self, tp_source):
        self.tp_source = tp_source


class _Cfg:
    def __init__(self, enabled):
        self._d = {"sl_tp_engine": {"tp_selector_enabled": enabled}}
    def get(self, k, default=None):
        return self._d.get(k, default)


class TestMagnetLocked:
    def test_locked_when_enabled_and_magnet(self):
        # магнит-метка содержит '@' + tp_selector включён → заблокировано
        assert magnet_tp_locked(_Rec("eql+fvg_15m@0.00497"), _Cfg(True)) is True

    def test_not_locked_when_disabled(self):
        # tp_selector выключен → магнит не фиксируется
        assert magnet_tp_locked(_Rec("eql+fvg_15m@0.00497"), _Cfg(False)) is False

    def test_not_locked_when_pivot_source(self):
        # pivot-метка без '@' → override разрешён
        assert magnet_tp_locked(_Rec("pivot_1D:R2"), _Cfg(True)) is False

    def test_not_locked_atr_fallback(self):
        assert magnet_tp_locked(_Rec("atr_rr_3.0"), _Cfg(True)) is False

    def test_not_locked_range_bounce(self):
        assert magnet_tp_locked(_Rec("range_bounce_pivot"), _Cfg(True)) is False

    def test_none_tp_source(self):
        assert magnet_tp_locked(_Rec(None), _Cfg(True)) is False

    def test_empty_tp_source(self):
        assert magnet_tp_locked(_Rec(""), _Cfg(True)) is False

    def test_capped_magnet_still_locked(self):
        # магнит с суффиксом cap всё ещё содержит '@'
        assert magnet_tp_locked(_Rec("fvg_1h@0.5|capped_rr_2.5"), _Cfg(True)) is True

    def test_bad_config_safe(self):
        # config без get → не падает, возвращает False
        assert magnet_tp_locked(_Rec("x@1"), object()) is False
