"""09.10: пульс обязан выходить из СЛИВ/ВЫНОС в НОРМУ после HOLD_OFF спокойных минут подряд.

Было: счётчик спокойных минут обнулялся каждую минуту (по `new` = перенесённому состоянию) → 08.10 пульс застрял
в СЛИВ, потом в ВЫНОС на часы.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import market_pulse as MP  # noqa: E402


def _m(dn2=0.0, up2=0.0, med15=0.0, dn15=0.0, up15=0.0, med1=0.0):
    return {"15m": {"dn": dn15, "up": up15, "med": med15}, "1h": {"med": med1},
            "2h": {"dn": dn2, "up": up2, "med": 0.0}}


def test_dump_then_calm_returns_to_norm():
    prev = {"state": "НОРМА"}
    st, _ = MP.classify(_m(dn2=0.8), prev)
    assert st == "СЛИВ"
    prev["state"] = st
    seen = []
    for _ in range(MP.HOLD_OFF):
        st, _ = MP.classify(_m(dn2=0.1, med15=0.0), prev)
        prev["state"] = st
        seen.append(st)
    assert seen[:-1] == ["СЛИВ"] * (MP.HOLD_OFF - 1)
    assert seen[-1] == "НОРМА"


def test_pump_then_calm_returns_to_norm():
    prev = {"state": "НОРМА"}
    st, _ = MP.classify(_m(up2=0.6), prev)
    assert st == "ВЫНОС"
    prev["state"] = st
    for _ in range(MP.HOLD_OFF):
        st, _ = MP.classify(_m(up2=0.03, med15=0.001), prev)
        prev["state"] = st
    assert st == "НОРМА"


def test_relapse_resets_counter():
    prev = {"state": "СЛИВ"}
    MP.classify(_m(dn2=0.1), prev)                      # 1 спокойная минута
    st, _ = MP.classify(_m(dn2=0.8), prev)              # снова слив — счётчик в ноль
    assert st == "СЛИВ" and prev["below"] == 0
    for _ in range(MP.HOLD_OFF - 1):
        st, _ = MP.classify(_m(dn2=0.1), prev)
    assert st == "СЛИВ"                                  # HOLD_OFF−1 спокойных минут мало
