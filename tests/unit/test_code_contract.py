# -*- coding: utf-8 -*-
"""Ворота паспорта инструмента проверяют то, что обещают (docs/TOOL_CONTRACT.md, ARCH-148).

Golden-case: подаём кусок диффа с известным ответом. Повод — 13.10 ворота в первый же час дважды соврали:
(1) ключом был только файл, и один `except` маскировал другой в том же файле;
(2) сравнение шло с последним коммитом, поэтому свежая правка в рабочем дереве не учитывалась.
"""
from __future__ import annotations

import scripts.code_contract as cc

HEAD = "+++ b/core/some_module.py\n@@ -10,3 +10,9 @@\n"


def _diff(body: str) -> str:
    return HEAD + body


def test_silent_pass_is_a_violation(monkeypatch):
    monkeypatch.setattr(cc, "sh", lambda *a: _diff("+    try:\n+        risky()\n+    except Exception:\n+        pass\n"))
    out = cc.silent_excepts("base")
    assert len(out) == 1 and out[0].startswith("core/some_module.py:12:")


def test_silent_debug_is_a_violation(monkeypatch):
    monkeypatch.setattr(cc, "sh", lambda *a: _diff("+    except Exception as e:\n+        logger.debug('ой: %s', e)\n"))
    assert len(cc.silent_excepts("base")) == 1


def test_loud_except_is_fine(monkeypatch):
    monkeypatch.setattr(cc, "sh", lambda *a: _diff("+    except Exception as e:\n+        logger.warning('не вышло: %s', e)\n"))
    assert cc.silent_excepts("base") == []


def test_reraise_is_fine(monkeypatch):
    monkeypatch.setattr(cc, "sh", lambda *a: _diff("+    except ValueError:\n+        raise\n"))
    assert cc.silent_excepts("base") == []


def test_explicit_silence_is_allowed(monkeypatch):
    """Молчать можно, если сказано почему: «# молчим: …» в той же строке."""
    monkeypatch.setattr(cc, "sh", lambda *a: _diff("+    except Exception:  # молчим: настройка консоли\n+        pass\n"))
    assert cc.silent_excepts("base") == []


def test_two_violations_in_one_file_are_distinguished(monkeypatch):
    """Ошибка 13.10: без номера строки второй `except` терялся за первым в базовой линии."""
    diff = _diff("+    except Exception:\n+        pass\n") + "@@ -40,3 +40,4 @@\n+    except Exception:\n+        pass\n"
    monkeypatch.setattr(cc, "sh", lambda *a: diff)
    out = cc.silent_excepts("base")
    assert len(out) == 2 and out[0] != out[1], "две разные строки обязаны дать две разные записи"


def test_line_numbers_follow_hunk_header(monkeypatch):
    monkeypatch.setattr(cc, "sh", lambda *a: "+++ b/core/x.py\n@@ -1,2 +100,4 @@\n при\n+    except Exception:\n+        pass\n")
    assert cc.silent_excepts("base") == ["core/x.py:101: except Exception:"]


def test_untested_live_file_is_flagged(monkeypatch, tmp_path):
    monkeypatch.setattr(cc, "sh", lambda *a: "core/brand_new_thing.py\nscripts/some_lab.py\n")
    monkeypatch.setattr(cc, "tests_text", lambda: "ничего про новый модуль тут нет")
    out = cc.untested_live("base")
    assert out == ["core/brand_new_thing.py"], "замеры в scripts/ теста не требуют, боевой модуль — требует"


def test_init_and_stub_are_not_required_to_have_tests(monkeypatch):
    monkeypatch.setattr(cc, "sh", lambda *a: "core/pkg/__init__.py\ncore/smc/old_stub.py\n")
    monkeypatch.setattr(cc, "tests_text", lambda: "")
    assert cc.untested_live("base") == []


def test_mentioned_in_tests_passes(monkeypatch):
    monkeypatch.setattr(cc, "sh", lambda *a: "core/brand_new_thing.py\n")
    monkeypatch.setattr(cc, "tests_text", lambda: "from core.brand_new_thing import f")
    assert cc.untested_live("base") == []
