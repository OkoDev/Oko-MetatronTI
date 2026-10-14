# -*- coding: utf-8 -*-
"""Селфтест Куба отчитывается в сферу 12 (ARCH-148.5 «б», паспорт инструмента — правило 4).

Егор: «путь должен лежать через 12-ю сферу и в отчёт». До 14.10 113 проверок селфтеста Куба печатались в
консоль по запросу — на вопрос «что сейчас красное в Кубе» ответа в одном месте не было, а событие
`sphere_health` в каталоге шины было заведено и никем не публиковалось. Теперь сводка селфтеста уходит фактом
в хаб, и реестр проверок читает её без повторного прогона.
"""
from __future__ import annotations

import core.selftest_cube as sc
from core.selftest_cube import ACTIVE, MISSING, SHADOW, CubeCheckResult, health_summary


def _r(code, status):
    return CubeCheckResult("L13_sphere", code, code, status)


def test_summary_counts_by_status():
    results = [_r("DC", ACTIVE), _r("WT", ACTIVE), _r("P", SHADOW), _r("XM", MISSING)]
    h = health_summary(results)
    assert h["total"] == 4 and h["active"] == 2 and h["shadow"] == 1 and h["missing"] == 1


def test_summary_lists_what_is_missing():
    """Красное = MISSING: компонент заявлен в карте Куба, но не отвечает. Список обязан называть их поимённо."""
    results = [_r("DC", ACTIVE), _r("XM", MISSING), _r("ML", MISSING)]
    h = health_summary(results)
    assert h["missing"] == 2
    assert "XM:XM" in h["missing_list"] and "ML:ML" in h["missing_list"]


def test_summary_all_active_has_empty_missing():
    h = health_summary([_r("DC", ACTIVE), _r("WT", ACTIVE)])
    assert h["missing"] == 0 and h["missing_list"] == []


def test_summary_has_timestamp():
    h = health_summary([_r("DC", ACTIVE)])
    assert h["ts"].endswith("+00:00") and "T" in h["ts"], "время расчёта — ISO UTC с зоной (правило 2 данных)"


def test_missing_list_is_capped():
    """Сводка — не дамп: длинный список MISSING обрезается, весь — в самом селфтесте."""
    results = [_r(f"M{i}", MISSING) for i in range(60)]
    assert len(health_summary(results)["missing_list"]) == 40


def test_publish_health_sends_sphere_health_event(monkeypatch):
    """Публикуется именно `sphere_health` для «пары» *CUBE* через cube_client; сводка — в data."""
    sent = {}

    def fake_publish(event, symbol, data, producer="satellite"):
        sent.update(event=event, symbol=symbol, data=data, producer=producer)
        return True

    import core.context.cube_client as cc
    monkeypatch.setattr(cc, "publish", fake_publish)
    ok = sc.publish_health([_r("DC", ACTIVE), _r("XM", MISSING)])
    assert ok is True
    assert sent["event"] == "sphere_health" and sent["symbol"] == "*CUBE*"
    assert sent["data"]["missing"] == 1 and sent["producer"] == "selftest-cube"


def test_publish_health_never_raises(monkeypatch):
    """Диагностика не роняет старт бота: если хаб недоступен — False, не исключение."""
    import core.context.cube_client as cc

    def boom(*a, **k):
        raise ConnectionError("хаб недоступен")

    monkeypatch.setattr(cc, "publish", boom)
    assert sc.publish_health([_r("DC", ACTIVE)]) is False
