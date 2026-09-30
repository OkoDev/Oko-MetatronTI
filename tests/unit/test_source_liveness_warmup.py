"""Прибор живости не должен хоронить источник на холодном логе.

Повод (30.09.2026): L12b работает селф-тестом В МОМЕНТ СТАРТА бота — текущий лог тогда почти
пуст, а вчерашние строки уехали в ротированный файл. Читая только текущий, прибор видел ноль
следов и печатал «ПУТЬ НЕ НАЙДЕН · ветка в коде недостижима?» про живой `waves_long`, который
стартовал штатно. Ровно так же он мог бы оболгать любой источник после каждого рестарта.
"""
from __future__ import annotations

import time

import pytest

from core.trading import source_liveness as SL


def _write(p, lines):
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(p)


def test_traces_include_rotated_logs(tmp_path):
    """Следы ищутся и в ротированных файлах — иначе рестарт обнуляет историю."""
    cur = _write(tmp_path / "bot-out.log", ["2026-09-30 13:00:00,000 - старт"])
    _write(tmp_path / "bot-out__2026-09-29_00-00-01.log",
           ["2026-09-29 10:00:00,000 - [WAVES_LONG] старт",
            "2026-09-29 11:00:00,000 - [WAVES_LONG] скан"])
    n, span = SL._count_traces("waves_long", cur)
    assert n == 2, "следы из ротированного лога потеряны"
    assert span > 0


def test_cold_log_gives_warmup_not_dead(tmp_path):
    """Свежий лог без следов = ПРОГРЕВ, а не приговор."""
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    cur = _write(tmp_path / "bot-out.log", [f"{now},000 - старт бота"])
    n, span = SL._count_traces("waves_long", cur)
    assert n == 0
    assert span < 1.0, "только что созданный лог не может покрывать час истории"


def test_old_log_without_traces_is_dead(tmp_path):
    """А вот сутки лога без единого следа — это уже настоящая тревога."""
    cur = _write(tmp_path / "bot-out.log",
                 ["2026-09-29 00:00:00,000 - старт", "2026-09-29 00:01:00,000 - [RADAR-ARMED] ок"])
    n, span = SL._count_traces("waves_long", cur)
    assert n == 0
    assert span > 1.0, "лог суточной давности обязан давать покрытие больше часа"


def test_missing_log_is_unknown_not_zero(tmp_path):
    """Нет лога — колонка не участвует в вердикте (-1), а не «следов ноль»."""
    n, span = SL._count_traces("waves_long", str(tmp_path / "нет-такого.log"))
    assert n == -1 and span == 0.0


@pytest.mark.parametrize("src", ["choch_wavec", "impulse_fib", "radar", "waves_long"])
def test_every_live_source_has_log_tag(src):
    """Источник без тега в LOG_TAGS невозможно отличить «молчит» от «недостижим»."""
    assert src in SL.LOG_TAGS and SL.LOG_TAGS[src]
