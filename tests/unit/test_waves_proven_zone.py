# -*- coding: utf-8 -*-
"""08.10 «мы точно видим то что нужно?!» (Егор, USELESS): одно правило зоны для боя, канала и карточки,
светофор карточки по нему, массовость дня и пометка битых записей журнала тени."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

CFG = {"trading.waves_long.enabled": True, "trading.waves_long.short_enabled": True,
       "trading.waves_long.proven_stop_pct": 6.0, "trading.waves_long.stop_rel_min": 0.30,
       "trading.waves_long.stop_rel_max": 0.50, "trading.waves_long.unproven_to_shadow": True}


def get(k, d=None):
    return CFG.get(k, d)


def test_battle_imports_same_rule():
    """Бой берёт правило из core — канал не может разойтись с боем."""
    import bot.loops.waves_long_loop as L
    import core.waves.proven_zone as Z
    assert L._long_proven is Z._long_proven and L._stop_rel is Z._stop_rel and L._in_corridor is Z._in_corridor


@pytest.mark.parametrize("side,entry,stop,imp,proven,word", [
    ("LONG", 100.0, 91.0, 100.0, True, "стоп 9.0%"),        # стоп ≥ 6%
    ("LONG", 100.0, 97.0, 8.0, True, "коридор"),            # 3% / 8% импульса = 0.375 → коридор
    ("LONG", 100.0, 97.2, 40.0, False, "вне доказанной"),   # USELESS-подобный: 2.8%, 0.07 импульса
    ("SHORT", 100.0, 110.0, 30.0, False, "шорт"),           # у шорта зоны нет
])
def test_zone(side, entry, stop, imp, proven, word):
    from core.waves.proven_zone import zone
    z = zone(side, entry, stop, imp, get=get)
    assert z["proven"] is proven and word in z["label"]
    assert ("→ в бой" in z["label"]) is proven
    if not proven:
        assert "тень" in z["label"]


def _rep(stop, up=False):
    return {"sym": "T/USDT", "price": 0.2040, "ltf": "3m", "structure": {"up": up, "kind": "impulse"},
            "ltf_state": {"choch_int": {"t": 0}, "a_done": True, "A": 0.01, "a_top": 0.21, "retr_now": 0.6,
                          "zone": {0.5: 0.2050, 0.618: 0.2038, 0.705: 0.2030}, "stop_886": stop},
            "scenarios": [{"name": "A", "targets": [("t1", 0.25)], "invalid": "ниже 0.19"}], "leg": {}}


def test_card_green_only_when_proven(monkeypatch):
    import core.waves.proven_zone as Z
    monkeypatch.setattr(Z, "_cfg_get", lambda: get)
    from core.waves.wave_analyst import decision_card
    tight = decision_card(_rep(0.2013))                     # стоп 1.3% — как USELESS 08.10
    assert tight["light"] == "wait" and tight["status"].startswith("ВХОД НЕ ДОКАЗАН")
    assert "ЦЕНА В ЗОНЕ ВХОДА" in tight["status_sub"]
    assert tight["targets"][0][3] is None and "RR не показан" in tight["rr_note"]
    wide = decision_card(_rep(0.1872))                      # стоп 8%
    assert wide["light"] == "go" and wide["targets"][0][3] is not None
    short = decision_card(_rep(0.2200, up=True))
    assert short["light"] == "wait" and "шорт" in short["status"]


def test_caption_carries_sub_status_and_extra():
    from core.waves.wave_tg import caption_card
    cap = caption_card({"sym": "T", "price": 1.0, "light": "wait", "status": "ВХОД НЕ ДОКАЗАН: x",
                        "status_sub": "ЦЕНА В ЗОНЕ", "side": "LONG"}, "", "🌒 зона\n👥 массовость")
    assert "ЦЕНА В ЗОНЕ" in cap and "🌒 зона" in cap and "👥 массовость" in cap


def test_day_mass_is_causal_by_entries():
    """Определение замера wave_day_mass_lab: ДРУГИЕ монеты той же стороны, уже вошедшие сегодня до ts."""
    import wave5_shadow as W
    st = {"A|1|2": {"sym": "A", "side": "LONG", "entered_at": "2026-09-16 04:15"},
          "B|1|2": {"sym": "B", "side": "LONG", "entered_at": "2026-09-16 12:15"},
          "C|1|2": {"sym": "C", "side": "SHORT", "entered_at": "2026-09-16 04:15"},
          "D|1|2": {"sym": "D", "side": "LONG", "entered_at": "2026-09-15 20:15"},
          "E|1|2": {"sym": "E", "side": "LONG", "entered_at": None}}
    assert W.day_mass(st, "LONG", "2026-09-16 08:15") == 1                 # B позже, D вчера, C шорт, E не вошёл
    assert W.day_mass(st, "LONG", "2026-09-16 23:00") == 2
    assert W.day_mass(st, "LONG", "2026-09-16 23:00", sym="A") == 1        # себя не считает
    line = W._mass_line({**st, "X": {"sym": "X", "side": "LONG", "universe_n": 594}},
                        {"sym": "X", "side": "LONG", "universe_n": 594}, "2026-09-16 23:00")
    assert "немассовый" in line and "0.7 на 198" in line                     # 2 из 594 → 0.7 на 198 замера


def test_mark_bad_target_behind_and_dup_reentry():
    import wave5_shadow as W
    st = {"SYN|1|2": {"sym": "SYN", "side": "LONG", "detected_at": "2026-09-16 04:05", "entry_price": 0.1685, "p4_target": 0.0956},
          "U|1|2|7": {"sym": "U", "side": "LONG", "detected_at": "2026-10-07 16:10", "re_entry_at": "2026-10-08 05:18"},
          "U|1|2|8": {"sym": "U", "side": "LONG", "detected_at": "2026-10-07 20:05", "re_entry_at": "2026-10-08 05:18"},
          "V|9|9": {"sym": "V", "side": "LONG", "detected_at": "2026-10-07 20:05", "re_entry_at": "2026-10-08 05:18"}}
    assert W.mark_bad(st) == 2
    assert "за входом" in st["SYN|1|2"]["bad"]
    assert st["U|1|2|8"]["re_outcome"] == "dup" and st["U|1|2|8"]["re_dup_of"] == "U|1|2|7"
    assert st["U|1|2|7"].get("re_outcome") != "dup" and st["V|9|9"].get("re_outcome") != "dup"   # другой импульс — не дубль
    assert W.mark_bad(st) == 0                                                                       # идемпотентно
