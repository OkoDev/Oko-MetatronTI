# -*- coding: utf-8 -*-
"""Паспорт данных, правила 2 и 5 (docs/DATA_CONTRACT.md, ARCH-147).

Правило 5: запись мимо каталога шины — громкое предупреждение, один раз на имя. До 13.10.2026 неизвестное поле
уходило в debug и терялось молча, неизвестный тип события не оставлял следа вовсе.
Правило 2: время не сравнивают как текст. В базе рядом живут строки ISO с «T» и строки SQLite с пробелом.
"""
from __future__ import annotations

import logging
import sqlite3

from core.context.pair_context import PairContextBus, SphereEvent

SYM = "BTC/USDT:USDT"


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING and "мимо каталога шины" in r.getMessage()]


def test_unknown_field_is_loud_once(caplog):
    bus = PairContextBus()
    with caplog.at_level(logging.WARNING):
        bus.update(SYM, no_such_field=1)
        bus.update(SYM, no_such_field=2)
        bus.update("ETH/USDT:USDT", no_such_field=3)
    msgs = _warnings(caplog)
    assert len(msgs) == 1 and "no_such_field" in msgs[0], "предупреждение одно на имя, а не на каждую пару и вызов"
    assert not hasattr(bus.get(SYM), "no_such_field")


def test_known_field_is_silent(caplog):
    bus = PairContextBus()
    with caplog.at_level(logging.WARNING):
        bus.update(SYM, regime="RANGE")
    assert _warnings(caplog) == [] and bus.get(SYM).regime == "RANGE"


def test_unknown_event_type_is_loud_once(caplog):
    bus = PairContextBus()
    with caplog.at_level(logging.WARNING):
        bus.publish(SYM, "made_up_event", {"x": 1})
        bus.publish(SYM, "made_up_event", {"x": 2})
    msgs = _warnings(caplog)
    assert len(msgs) == 1 and "made_up_event" in msgs[0]


def test_catalog_events_are_silent(caplog):
    bus = PairContextBus()
    with caplog.at_level(logging.WARNING):
        bus.publish(SYM, SphereEvent.WT_SNAP_UPDATED, {"15m": {"zone": "OB"}})
    assert _warnings(caplog) == []


def test_time_must_not_be_compared_as_text():
    """Сделка создана 3 часа назад и записана ISO-строкой. Текстовое сравнение с отметкой SQLite её НЕ находит
    («T» больше пробела), сравнение через datetime() — находит. Так чинилась ручка закрытия старых сделок."""
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE t (created_at TEXT)")
    c.execute("INSERT INTO t VALUES ('2026-10-13T10:00:00.123456+00:00')")      # так пишет бот
    border = "2026-10-13 12:00:00"                                             # так отдаёт datetime('now', …)
    as_text = c.execute("SELECT COUNT(*) FROM t WHERE created_at < ?", (border,)).fetchone()[0]
    as_time = c.execute("SELECT COUNT(*) FROM t WHERE datetime(created_at) < datetime(?)", (border,)).fetchone()[0]
    assert as_time == 1, "datetime() обязан понимать ISO-строку с зоной"
    assert as_text == 0, "если текстовое сравнение вдруг заработало — тест устарел, а не правило"
