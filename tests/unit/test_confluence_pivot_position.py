"""09.10: машина конфлюэнции — поддержка/сопротивление по ПОЛОЖЕНИЮ уровня к цене (как find_near_pivot).

Сценарий NEAR 08.10 зеркально: лоу окна касались S1, потом цена его пробила вниз — S1 теперь НАД ценой,
это сопротивление, лонгу его засчитывать нельзя.
"""
import pandas as pd

from core.confluence.confluence_scanner import _check_near_resistance, _check_near_support

PIV = {"PP": 100.0, "S1": 95.0, "S2": 90.0, "R1": 105.0, "R2": 110.0}


def _win(lows, highs, closes):
    return pd.DataFrame({"low": lows, "high": highs, "close": closes})


def test_broken_s1_above_price_is_not_support():
    w = _win([95.05, 93.0, 92.0], [96.0, 95.0, 93.0], [95.5, 93.5, 92.5])
    hit, _ = _check_near_support(w, PIV, {}, "X", 0.15, ref_price=92.5)
    assert not hit
    # для шорта тот же S1 — сопротивление над ценой, хай касался
    w2 = _win([95.0, 93.0, 92.0], [95.1, 95.0, 93.0], [95.5, 93.5, 92.5])
    hit, desc = _check_near_resistance(w2, PIV, {}, "X", 0.15, ref_price=92.5)
    assert hit and desc.startswith("1D_S1")


def test_s1_below_price_still_support():
    w = _win([95.05, 96.0, 97.0], [96.0, 97.0, 98.0], [95.8, 96.8, 97.5])
    hit, desc = _check_near_support(w, PIV, {}, "X", 0.15, ref_price=97.5)
    assert hit and desc.startswith("1D_S1")


def test_broken_r1_below_price_is_support_not_resistance():
    w = _win([105.05, 106.0, 107.0], [105.5, 107.0, 108.0], [105.4, 106.8, 107.5])
    hit, desc = _check_near_support(w, PIV, {}, "X", 0.15, ref_price=107.5)
    assert hit and desc.startswith("1D_R1")
    hit, _ = _check_near_resistance(w, PIV, {}, "X", 0.15, ref_price=107.5)
    assert not hit


def test_ref_price_defaults_to_last_close():
    w = _win([95.05, 93.0, 92.0], [96.0, 95.0, 93.0], [95.5, 93.5, 92.5])
    assert not _check_near_support(w, PIV, {}, "X", 0.15)[0]
