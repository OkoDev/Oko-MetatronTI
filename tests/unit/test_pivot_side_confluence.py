# -*- coding: utf-8 -*-
"""08.10 (Егор, NEAR): ARCH-23 давал «confluence» +20 WT-лонгу в 0.44% ПОД недельным R1 — уровень против стороны.
Уровень опорный только с правильной стороны: LONG — на цене или ниже, SHORT — на цене или выше."""
from core.pivots.pivot_calculator_fixed import PivotCalculatorFixed


class _Fake:
    def __init__(self, cache):
        self.pivot_cache = cache


NEAR = {"NEAR/USDT:USDT_1W": {"PP": 4.9933, "R1": 5.4267, "R2": 5.97, "S1": 4.4796, "S2": 4.0163, "S3": 3.4876}}


def find(price, side=None, cache=NEAR):
    return PivotCalculatorFixed.find_near_pivot(_Fake(cache), price, "NEAR/USDT:USDT", side=side)


def test_near_case_long_under_r1_is_not_confluence():
    price = 5.4267 / 1.0044                                   # 0.44% под R1 — как 08.10 05:12 UTC
    assert find(price) == (5.4267, "1W:R1")                  # старое поведение: любой уровень
    assert find(price, side="LONG") is None                  # лонг под сопротивлением — не конфлюэнция
    assert find(price, side="SHORT") == (5.4267, "1W:R1")    # шорт под сопротивлением — конфлюэнция


def test_long_above_support_and_broken_resistance():
    assert find(4.50, side="LONG") == (4.4796, "1W:S1")      # над S1 — поддержка
    assert find(5.45, side="LONG") == (5.4267, "1W:R1")      # R1 пробит вверх — теперь поддержка


def test_short_below_broken_support():
    assert find(4.46, side="SHORT") == (4.4796, "1W:S1")     # S1 пробит вниз — сопротивление
    assert find(4.46, side="LONG") is None
