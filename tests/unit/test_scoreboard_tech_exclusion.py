"""09.10: форвард-табло терминала не смешивает технические закрытия с результатом механики."""
from web.structure_terminal import _sb_tech


def _r(**kw):
    base = {"mode": "vst", "symbol": "PONS/USDT:USDT", "fakeR_quarantine": 0,
            "actual_entry_price": 0.4192, "entry_price": 0.4136}
    base.update(kw)
    return base


def test_normal_trade_counts():
    assert not _sb_tech(_r())                                     # обычная VST-сделка, вход +1.35% — не сбой


def test_bare_symbol_vst_is_orphan_bug():
    assert _sb_tech(_r(symbol="EVAA/USDT"))                       # баг формата 01–18.09: сирота
    assert not _sb_tech(_r(symbol="EVAA/USDT", mode="sim"))       # в SIM детектора сирот нет


def test_quarantine_and_entry_glitch():
    assert _sb_tech(_r(fakeR_quarantine=1))
    assert _sb_tech(_r(entry_price=0.04125, actual_entry_price=0.05351))   # STAR #59784: +29.7%
    assert not _sb_tech(_r(actual_entry_price=None))
