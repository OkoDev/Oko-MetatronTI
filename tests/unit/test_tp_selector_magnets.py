"""Unit-тесты для TPSelector магнитов из Bus snap (ARCH-122, 30.05.2026)."""
from core.smc.tp_selector import TPSelector, _Magnet


def _snap():
    """Богатый snap (как из SMC Sub-куба) — entry будем ставить = 100."""
    return {
        "bear_fvg_active": [
            {"tf": "1h", "top": 106.0, "bottom": 104.0},
            {"tf": "4h", "top": 110.0, "bottom": 108.0},
        ],
        "bull_fvg_active": [
            {"tf": "1h", "top": 95.0, "bottom": 93.0},
        ],
        "nearest_bear_ob": {"top": 112.0, "bottom": 110.0},
        "nearest_bull_ob": {"top": 90.0, "bottom": 88.0},
        "eqh_level": 115.0,
        "eql_level": 85.0,
        "fib_levels": {"1.272": 120.0, "0.618": 96.2, "1.618": 130.0},
    }


class TestMagnetsFromSnap:
    def test_long_collects_above_entry(self):
        sel = TPSelector()
        magnets = []
        sel._magnets_from_snap(_snap(), entry=100.0, is_long=True, magnets=magnets)
        sources = {m.source for m in magnets}
        # LONG: bear FVG, bear OB, EQH, fib_ext выше entry
        assert "fvg_1h" in sources
        assert "fvg_4h" in sources       # multi-TF лейбл работает
        assert "ob" in sources
        assert "eqh" in sources
        assert "fib_ext" in sources
        assert all(m.price > 100.0 for m in magnets)  # все выше entry

    def test_short_collects_below_entry(self):
        sel = TPSelector()
        magnets = []
        sel._magnets_from_snap(_snap(), entry=100.0, is_long=False, magnets=magnets)
        sources = {m.source for m in magnets}
        # SHORT: bull FVG, bull OB, EQL ниже entry
        assert "fvg_1h" in sources
        assert "ob" in sources
        assert "eql" in sources
        assert all(m.price < 100.0 for m in magnets)  # все ниже entry

    def test_long_excludes_eql_short_excludes_eqh(self):
        sel = TPSelector()
        m_long = []
        sel._magnets_from_snap(_snap(), 100.0, True, m_long)
        assert "eql" not in {m.source for m in m_long}  # EQL только для SHORT
        m_short = []
        sel._magnets_from_snap(_snap(), 100.0, False, m_short)
        assert "eqh" not in {m.source for m in m_short}  # EQH только для LONG

    def test_empty_snap_no_crash(self):
        sel = TPSelector()
        magnets = []
        sel._magnets_from_snap({}, 100.0, True, magnets)
        assert magnets == []

    def test_collect_magnets_prefers_snap_over_smc_context(self):
        """Если ctx.smc_snap есть — используется он (богатый), не smc_context.fvg."""
        class Ctx:
            symbol = "TEST"
            smc_snap = _snap()
            smc_context = None
            swing_high = None
            swing_low = None
            pivot_cache_1d_1w = {}
        sel = TPSelector()
        magnets = sel._collect_magnets(100.0, "LONG", Ctx())
        # OB и EQH есть только в snap-пути
        sources = {m.source for m in magnets}
        assert "ob" in sources or "eqh" in sources
