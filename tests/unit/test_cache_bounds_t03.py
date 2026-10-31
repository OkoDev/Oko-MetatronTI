# -*- coding: utf-8 -*-
"""T-03 (закрыто 31.10): потолки кэшей — `analysis_cache`, `recommendation_history`, `_last_signal`.

Задача роя 10.06 («TTL/maxsize для `_last_signal`/`analysis_cache` — растут без лимита»), 17.10 её
слили в BOT-MEM-LEAK как «зацепку». Замер 31.10: это мегабайты, а не причина рестартов (та — в PriceWS,
ARCH-154), но лимит должен быть явным и проверяемым. Здесь — что потолок есть и логика не изменилась.
"""
from datetime import datetime, timedelta

from bot import monitoring as mon
from core.trading_intelligence import TradingIntelligence


class _Rec:
    """Минимальная замена TradingRecommendation — для проверки потолков."""

    def __init__(self, n: int):
        self.n = n


class _Bot:
    """Заглушка бота: только то, что читает дедупликация сигналов."""

    def __init__(self, dedup_minutes: int = 30):
        self.config = {"signal_quality.dedup_minutes": dedup_minutes}
        self._last_signal = {}


def _ti() -> TradingIntelligence:
    """Объект без тяжёлой инициализации: нужны только проверяемые поля и методы."""
    ti = object.__new__(TradingIntelligence)
    ti.analysis_cache = {}
    ti.recommendation_history = {}
    ti._analysis_cache_max = 5
    ti._history_max = 3
    return ti


def test_analysis_cache_has_hard_limit():
    ti = _ti()
    for i in range(20):
        ti._cache_analysis(f"SYM{i}/USDT:USDT", _Rec(i))
    assert len(ti.analysis_cache) == 5
    assert "SYM19/USDT:USDT" in ti.analysis_cache              # свежее — на месте
    assert "SYM0/USDT:USDT" not in ti.analysis_cache           # старое вытеснено


def test_recommendation_history_keeps_only_tail():
    ti = _ti()
    for i in range(10):
        ti._remember_recommendation("BTC/USDT:USDT", _Rec(i))
    hist = ti.recommendation_history["BTC/USDT:USDT"]
    assert len(hist) == 3 and [r.n for r in hist] == [7, 8, 9]


def test_dedup_sweep_drops_old_marks_only():
    bot = _Bot()
    now = datetime.now()
    bot._last_signal[("BTC/USDT:USDT", "wt", "LONG")] = now - timedelta(hours=1)     # свежая
    bot._last_signal[("DEAD/USDT:USDT", "wt", "LONG")] = now - timedelta(hours=12)   # мёртвая
    removed = mon._sweep_last_signal(bot, now)
    assert removed == 1
    assert ("BTC/USDT:USDT", "wt", "LONG") in bot._last_signal
    assert ("DEAD/USDT:USDT", "wt", "LONG") not in bot._last_signal


def test_dedup_behaviour_unchanged_within_window():
    """Логика остаётся прежней: второй сигнал в окне — дубликат, после окна — нет."""
    bot = _Bot(dedup_minutes=30)
    assert mon._is_duplicate_signal(bot, "ETH/USDT:USDT", "wt", "LONG") is False
    assert mon._is_duplicate_signal(bot, "ETH/USDT:USDT", "wt", "LONG") is True
    # спустя окно тот же сигнал снова проходит
    key = ("ETH/USDT:USDT", "wt", "LONG")
    bot._last_signal[key] = datetime.now() - timedelta(minutes=31)
    assert mon._is_duplicate_signal(bot, "ETH/USDT:USDT", "wt", "LONG") is False


def test_dedup_sweep_runs_periodically_and_at_overflow():
    bot = _Bot()
    now = datetime.now()
    bot._last_signal[("OLD/USDT:USDT", "wt", "SHORT")] = now - timedelta(hours=10)
    bot._last_signal_calls = 499                       # следующий вызов — 500-й, идёт уборка
    mon._is_duplicate_signal(bot, "BTC/USDT:USDT", "wt", "SHORT")
    assert ("OLD/USDT:USDT", "wt", "SHORT") not in bot._last_signal
