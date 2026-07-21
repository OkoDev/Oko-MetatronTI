# -*- coding: utf-8 -*-
"""Поведенческий контракт Сферы Фазы v0 (Decision Core, 21.07). Пороги калибруются
по shadow-сверке с глазом Егора — логика классификации заморожена этими кейсами."""
from core.context.phase_sphere import (
    diagnose_macro, diagnose_pair, phase_fit, MacroPhase, PairPhase,
)


class TestMacro:
    def test_squeeze_up_precursors(self):
        # шорты грузятся на дне (2/3 прекурсора) → готовим LONG-разворот
        m = diagnose_macro(pct_pdn_oiup=30, median_funding_pct=-0.01, btc_trend="short", usdtd_risk_off=True)
        assert m.phase == "REVERSAL_BREWING" and m.bias == "LONG" and m.veto == "SHORT"

    def test_markup_down(self):
        m = diagnose_macro(pct_pdn_oiup=5, median_funding_pct=0.01, btc_trend="short", usdtd_risk_off=True)
        assert m.phase == "TREND_DOWN" and m.bias == "SHORT" and m.veto == "LONG"

    def test_markup_up(self):
        m = diagnose_macro(pct_pdn_oiup=5, median_funding_pct=0.01, btc_trend="long", usdtd_risk_off=False)
        assert m.phase == "TREND_UP" and m.bias == "LONG"

    def test_neutral_when_unclear(self):
        m = diagnose_macro(pct_pdn_oiup=10, median_funding_pct=0.0, btc_trend=None, usdtd_risk_off=None)
        assert m.phase == "UNCLEAR" and m.bias is None

    def test_degrades_on_none(self):
        # None-входы не роняют — меньше уверенности
        m = diagnose_macro(None, None, None, None)
        assert m.phase == "UNCLEAR"


class TestPair:
    def _struct(self, trend, origin, extreme):
        return {"trend": trend, "impulse_origin": origin, "extreme": extreme}

    def test_reversal_at_extreme(self):
        # цена у дна short-ноги + переворот пошёл → LONG reversal (метод Егора)
        s = self._struct("short", origin=100.0, extreme=80.0)
        r = {"reversing": True, "progress": 2}
        p = diagnose_pair(s, r, quadrant="PUP+OIUP", funding=-0.01, px=81.0)  # pos≈0.95 у extreme
        assert p.phase == "REVERSAL" and p.side == "LONG" and p.strategy_class == "reversal"

    def test_continuation_midleg_with_flow(self):
        # середина short-ноги + поток вниз (PDN) → SHORT continuation
        s = self._struct("short", origin=100.0, extreme=80.0)
        r = {"reversing": False, "progress": 0}
        p = diagnose_pair(s, r, quadrant="PDN+OIUP", funding=0.01, px=90.0)  # pos=0.5
        assert p.phase == "CONTINUATION" and p.side == "SHORT" and p.concordance is True

    def test_chop_midleg_against_flow(self):
        # середина ноги, но поток ПРОТИВ тренда → стоять
        s = self._struct("short", origin=100.0, extreme=80.0)
        r = {"reversing": False, "progress": 0}
        p = diagnose_pair(s, r, quadrant="PUP+OIUP", funding=0.0, px=90.0)
        assert p.phase == "CHOP" and p.side is None

    def test_chop_no_leg(self):
        p = diagnose_pair({"trend": None}, {"reversing": False}, quadrant=None, funding=None, px=100.0)
        assert p.phase == "CHOP"


class TestPhaseFit:
    def test_fit_concordant(self):
        macro = MacroPhase("TREND_DOWN", "SHORT", "LONG", 0.8, "")
        pair = PairPhase("CONTINUATION", "SHORT", "trend", True, 0.7, "")
        fit, _ = phase_fit("SHORT", macro, pair)
        assert fit is True

    def test_conflict_against_pair_side(self):
        macro = MacroPhase("TREND_DOWN", "SHORT", "LONG", 0.8, "")
        pair = PairPhase("CONTINUATION", "SHORT", "trend", True, 0.7, "")
        fit, _ = phase_fit("LONG", macro, pair)
        assert fit is False

    def test_conflict_chop(self):
        macro = MacroPhase("UNCLEAR", None, None, 0.4, "")
        pair = PairPhase("CHOP", None, None, None, 0.3, "")
        fit, _ = phase_fit("SHORT", macro, pair)
        assert fit is False
