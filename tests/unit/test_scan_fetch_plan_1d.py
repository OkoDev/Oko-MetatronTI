# -*- coding: utf-8 -*-
"""1d едет в общем gather, а не отдельным запросом (05.10.2026, «адрес 1»).

Повод — замер `[SCAN-PERF]`: блок `fetch_extra` съедал 1672 мс на пару (50% «детекторов и
прочего») на загруженном цикле и **0 мс** на свободном. То есть платили не за загрузку данных,
а за стояние лишнего запроса в очереди: `3m` давно был в общем плане, а `1d` грузился отдельным
await сразу после `asyncio.gather`, который и так тянул шесть таймфреймов.

Тест держит инвариант: 1d объявлен в плане загрузки и читается из его результата, а одиночный
запрос остаётся только запасным путём.
"""
from __future__ import annotations

from pathlib import Path

SRC = (Path(__file__).resolve().parents[2] / "bot" / "loops" / "scan_loop.py").read_text(encoding="utf-8")


def test_1d_is_in_fetch_plan():
    assert '_add_fetch("1d", 60)' in SRC, "1d не добавлен в общий план загрузки"


def test_1d_is_read_from_gather_result():
    assert 'df_1d = _fetched_map.get(("1d", 60))' in SRC, (
        "1d не читается из результата общего gather — значит он снова грузится отдельно")


def test_single_request_is_only_a_fallback():
    """Одиночный запрос допустим, но лишь когда плана не хватило."""
    i_read = SRC.index('df_1d = _fetched_map.get(("1d", 60))')
    i_fallback = SRC.index('get_ohlcv(sym, "1d", limit=60)', i_read)
    between = SRC[i_read:i_fallback]
    assert "if df_1d is None:" in between, (
        "одиночная загрузка 1d не прикрыта проверкой — она выполнится всегда")


def test_3m_stays_in_plan():
    """3m был в плане и должен там остаться — иначе вернём ту же потерю."""
    assert '_add_fetch("3m", 100)' in SRC
    assert 'df_3m = _fetched_map.get(("3m", 100))' in SRC


def test_perf_instrumentation_survives():
    """Замер должен остаться: без него мы не увидим, вернулась ли потеря."""
    assert "[SCAN-PERF]" in SRC
    assert '_perf2["' in SRC or '_tm("' in SRC
