# -*- coding: utf-8 -*-
"""Время филла в схеме (05.10.2026) — без него кост у LIMIT-источников неизмерим.

Повод: замер 04.10 сравнивал цену филла с минутной свечой момента `created_at` и дал по лимиткам
«82-100% филлов вне реального диапазона цен», тогда как у рыночных входов вышло 33%. Разница не
рыночная: у LIMIT заявка стоит часами, `created_at` — это момент ПОСТАНОВКИ, а не исполнения.
Цена филла в БД была (`actual_entry_price`), времени — нет.

Колонка заполняется в двух местах, и точность у них РАЗНАЯ:
  · `core/exchange/exec_ws_integration.py` — WS приносит событие исполнения → время точное;
  · `core/exchange/position_sync.py` — backfill узнаёт о филле при синке → ВЕРХНЯЯ граница,
    фактический филл был раньше. В замерах эту разницу надо называть.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_column_is_declared_in_migrations():
    src = (ROOT / "core" / "db" / "subscription_manager.py").read_text(encoding="utf-8")
    assert '("filled_at", "TIMESTAMP")' in src, "колонка filled_at не заведена в миграциях"


def test_created_table_gets_column(tmp_path):
    """Новая база обязана получить колонку — иначе на чистой установке кост снова неизмерим."""
    from core.db.subscription_manager import SubscriptionManager
    db = tmp_path / "t.db"
    SubscriptionManager(str(db))
    with sqlite3.connect(db) as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(simulated_trades)")]
    assert "filled_at" in cols
    assert "actual_entry_price" in cols, "время филла бессмысленно без цены филла"


def test_both_writers_fill_the_column():
    """Оба пути записи фактического филла обязаны проставлять и время."""
    ws = (ROOT / "core" / "exchange" / "exec_ws_integration.py").read_text(encoding="utf-8")
    sync = (ROOT / "core" / "exchange" / "position_sync.py").read_text(encoding="utf-8")
    assert "actual_entry_price=?, filled_at=?" in ws, "WS-путь пишет цену филла без времени"
    assert "filled_at=COALESCE(filled_at, ?)" in sync, "backfill пишет цену филла без времени"


def test_backfill_does_not_overwrite_precise_time():
    """COALESCE: если точное время уже пришло по WS, backfill его НЕ затирает своей верхней границей."""
    sync = (ROOT / "core" / "exchange" / "position_sync.py").read_text(encoding="utf-8")
    assert "COALESCE(filled_at, ?)" in sync
    assert "filled_at=?" not in sync.replace("filled_at=COALESCE(filled_at, ?)", ""), (
        "в backfill есть безусловная запись filled_at — она затрёт точное время от WS")


def test_column_accepts_iso_and_reads_back(tmp_path):
    from core.db.subscription_manager import SubscriptionManager
    db = tmp_path / "t2.db"
    SubscriptionManager(str(db))
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO simulated_trades (symbol, direction, entry_price, status, filled_at) "
                  "VALUES (?,?,?,?,?)",
                  ("BTC/USDT:USDT", "LONG", 100.0, "OPEN", "2026-10-05T00:30:00+00:00"))
        got = c.execute("SELECT filled_at FROM simulated_trades").fetchone()[0]
    assert got.startswith("2026-10-05T00:30")


def test_cost_measure_can_use_it():
    """Измеритель коста должен знать про новое поле — иначе колонка останется мёртвой."""
    src = (ROOT / "scripts" / "cost_measure.py").read_text(encoding="utf-8")
    assert "filled_at" in src, (
        "scripts/cost_measure.py не использует filled_at: для LIMIT-источников он по-прежнему "
        "будет сравнивать филл с минутой постановки заявки")
