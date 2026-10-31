# -*- coding: utf-8 -*-
"""ARCH-154 (31.10): ловец эпизодов PriceWS — пороги, срез, запись среза в JSONL.

Зачем ловец: рестарты бота даёт эпизод роста памяти (очередь таймеров цикла уходит с единиц до
десятков миллионов; замеры 31.10: 29,0/37,3 млн, память 9,1/11,4 ГБ за 16 мин, до 20 ГБ в 05:54).
Перепись `mem_census` пишет срез раз в 15 минут — начало разгона в неё не попадает, поэтому нужен
свой замер раз в 10 секунд и улики (переподписки, таймауты, «пустой» приём) на момент старта.
"""
import asyncio
import json
import time

from core.infra import price_ws as pw


def test_episode_severity_thresholds():
    assert pw.episode_severity(0) == "ok"
    assert pw.episode_severity(16) == "ok"                      # обычный хвост в бою: 1–16
    assert pw.episode_severity(pw._CATCH_HEAP_WARN - 1) == "ok"
    assert pw.episode_severity(pw._CATCH_HEAP_WARN) == "warn"
    assert pw.episode_severity(pw._CATCH_HEAP_EPISODE) == "episode"
    assert pw.episode_severity(61_370_210) == "episode"         # худший замер 28.10


def test_catch_severity_sees_memory_as_well_as_timers():
    """31.10 06:44: бота убили на 20 ГБ при очереди таймеров 25 — значит память нужен свой признак."""
    assert pw.catch_severity(2, 1500.0) == "ok"
    assert pw.catch_severity(2, None) == "ok"                    # память неизвестна — не падаем
    assert pw.catch_severity(2, 5000.0) == "warn"                # только память
    assert pw.catch_severity(2, 7000.0) == "episode"             # только память
    assert pw.catch_severity(900_000, 1500.0) == "episode"       # только таймеры
    assert pw.catch_severity(60_000, 4500.0) == "warn"           # оба «warn»


def test_snapshot_reports_process_memory_field():
    async def _run():
        feed = pw.PriceWS(["BTC/USDT:USDT"], fast_channel="")
        feed._started_at = time.time()
        return feed._catch_snapshot()

    snap = asyncio.run(_run())
    assert "rss_mb" in snap and (snap["rss_mb"] is None or snap["rss_mb"] > 0)
    assert snap["severity"] in ("ok", "warn", "episode")


def test_snapshot_counts_own_loop_timers_and_counters():
    async def _run():
        loop = asyncio.get_running_loop()
        feed = pw.PriceWS(["BTC/USDT:USDT"], fast_channel="")
        feed._started_at = time.time()
        feed.anom["recv"] = 5
        feed._fast_state.update({"want": 3, "subscribed": 2})
        h = loop.call_later(30, lambda: None)                  # ровно один таймер в очереди
        snap = feed._catch_snapshot()
        h.cancel()
        return snap

    snap = asyncio.run(_run())
    assert snap["heap"] >= 1 and snap["severity"] == "ok"
    assert snap["recv"] == 5 and snap["want"] == 3 and snap["subscribed"] == 2
    for key in ("ts", "uptime_sec", "timers_cancelled", "ready", "updates", "conns",
                "pairs", "events"):
        assert key in snap, key


def test_note_keeps_only_last_ring_and_survives():
    feed = pw.PriceWS(["BTC/USDT:USDT"], fast_channel="")
    for i in range(60):
        feed._note("fast_reconn", f"#{i}")
    assert len(feed._events) == feed._events.maxlen
    assert feed._events[-1][2] == "#59"


def test_catch_log_appends_jsonl(tmp_path, monkeypatch):
    log = tmp_path / "catch.jsonl"
    monkeypatch.setattr(pw, "_CATCH_LOG", log)
    pw._append_catch_log({"ts": "2026-10-31T02:00:00+00:00", "heap": 7, "severity": "ok"})
    pw._append_catch_log({"ts": "2026-10-31T02:00:10+00:00", "heap": 900_000, "severity": "episode"})
    rows = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2 and rows[1]["severity"] == "episode"


def test_anom_counters_start_empty():
    feed = pw.PriceWS(["BTC/USDT:USDT"], fast_channel="")
    assert set(feed.anom) == {"recv", "timeout", "nonmsg", "spin", "err", "reconn", "sub", "unsub"}
    assert sum(feed.anom.values()) == 0
