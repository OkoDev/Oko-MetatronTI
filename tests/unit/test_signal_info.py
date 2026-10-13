# -*- coding: utf-8 -*-
"""Стенд слоя сигнала (L1) меряет то, что обещает (ARCH-148.3 «в», паспорт инструмента — вид D).

`scripts/signal_info.py` отвечает на вопрос «несёт ли сигнал информацию о движении цены» для любого
источника. Через него пойдёт замер позиций Hyperliquid (ARCH-140.4), а внешний аудит назвал в нём
находку F11 — «событие в 10:05 использует close бара 10:00–10:15». Тестов не было ни одного.

🔑 Что показала проверка фактом (тест `test_entry_price_is_the_close_of_the_signal_bar`): заглядывания
в будущее НЕТ — старт берётся по цене, доступной ПОСЛЕ сигнала. Но момент входа зависит от того, где
внутри бара случился сигнал: три сигнала с разницей 14 минут дают один и тот же вход и один форвард.
Для источников, считающих на ЗАКРЫТИИ бара (детекторы бота), это точно; для внутрибарных (радар по OI,
ликвидации) вход задержан на 0–15 минут. Тесты закрепляют это как ИЗВЕСТНОЕ свойство, а не как норму.
"""
from __future__ import annotations

import random

import numpy as np
import pandas as pd
import pytest

import scripts.signal_info as si


def make_bars(n: int = 40, start: str = "2026-10-01 10:00", step: float = 1.0, first: float = 100.0):
    """Бары как их отдаёт `market_store.read_bars`: DatetimeIndex, метка = время ОТКРЫТИЯ бара."""
    idx = pd.date_range(start, periods=n, freq="15min")
    base = first + np.arange(n) * step
    return pd.DataFrame({"open": base, "high": base + 0.5, "low": base - 0.5, "close": base + 0.2}, index=idx)


# ── выбор бара и момента входа ───────────────────────────────────────────────

def test_at_finds_the_bar_that_contains_the_signal():
    d = make_bars()
    pos, atr = si.at(d, pd.Timestamp("2026-10-01 13:07"))
    assert d.index[pos] == pd.Timestamp("2026-10-01 13:00")
    assert atr is not None and atr > 0


def test_at_refuses_without_history_or_future():
    """Нужны PRE_BARS истории для волатильности и хотя бы один бар впереди — иначе честный отказ."""
    d = make_bars()
    assert si.at(d, d.index[si.PRE_BARS - 2]) == (None, None)
    assert si.at(d, d.index[-1]) == (None, None)
    assert si.at(None, pd.Timestamp("2026-10-01 13:00")) == (None, None)


def test_entry_price_is_the_close_of_the_signal_bar():
    """🔴 Находка F11, проверенная фактом. Вход — close бара сигнала: цена доступна через 0–15 минут ПОСЛЕ
    сигнала, значит заглядывания в будущее нет. Но момент входа не зависит от момента сигнала внутри бара."""
    d = make_bars()
    results = [si.forward(d, si.at(d, pd.Timestamp(t))[0], True)
               for t in ("2026-10-01 13:00:00", "2026-10-01 13:07:00", "2026-10-01 13:14:59")]
    assert results[0] == results[1] == results[2], "сигналы внутри одного бара дают один и тот же замер"
    pos, _ = si.at(d, pd.Timestamp("2026-10-01 13:07"))
    assert d.index[pos] == pd.Timestamp("2026-10-01 13:00"), "вход по close бара 13:00–13:15, то есть в 13:15"


def test_horizons_are_counted_from_the_entry_bar():
    """«15м» — один бар от входа, «1ч» — четыре, «24ч» — 96. Считается от точки входа, а не от сигнала."""
    d = make_bars(n=200, step=0.0)
    d = d.copy()
    d.loc[d.index[20], "close"] = 100.0
    for name, n in si.HORIZONS.items():
        d.loc[d.index[20 + n], "close"] = 110.0
        out = si.forward(d, 20, True)
        assert out[name] == pytest.approx(10.0), f"горизонт {name} обязан смотреть ровно на {n} баров вперёд"
        d.loc[d.index[20 + n], "close"] = 100.0


# ── направление и края ───────────────────────────────────────────────────────

def test_forward_flips_sign_for_short():
    d = make_bars()
    long_, short_ = si.forward(d, 20, True), si.forward(d, 20, False)
    assert long_["15м"] > 0 and short_["15м"] == pytest.approx(-long_["15м"])


def test_forward_returns_none_beyond_data():
    """За краем данных — None, а не ноль: ноль означал бы «движения не было» и врал бы в медиане."""
    d = make_bars(n=30)
    out = si.forward(d, 28, True)
    assert out["15м"] is not None and out["24ч"] is None


def test_forward_measures_from_close_not_open():
    d = make_bars(n=40, step=0.0)
    d = d.copy()
    d.loc[d.index[10], ["open", "close"]] = [50.0, 100.0]      # внутри бара цена выросла вдвое
    d.loc[d.index[11], "close"] = 110.0
    assert si.forward(d, 10, True)["15м"] == pytest.approx(10.0), "старт — close (100), а не open (50)"


# ── устойчивая статистика ────────────────────────────────────────────────────

def test_boot_returns_zero_without_data():
    assert si.boot([], [1.0, 2.0], random.Random(1)) == (0.0, 0.0, 0.0)


def test_boot_difference_and_interval():
    rnd = random.Random(23)
    a, b = [1.0] * 200, [0.0] * 200
    diff, lo, hi = si.boot(a, b, rnd, n=200)
    assert diff == pytest.approx(1.0) and lo <= diff <= hi


def test_boot_interval_covers_zero_for_identical_samples():
    """Две одинаковые выборки: интервал обязан накрывать ноль — иначе стенд объявит преимущество на ровном месте."""
    rnd = random.Random(23)
    xs = [float(i % 7) - 3 for i in range(300)]
    diff, lo, hi = si.boot(xs, list(xs), rnd, n=300)
    assert lo <= 0 <= hi


def test_boot_interval_has_real_width_on_noisy_data():
    """Интервал — это разброс, а не точка: на шумных данных он обязан быть шире нуля.
    Иначе вывод «разница +0.3 п.п.» подаётся без меры неопределённости (проверено мутацией)."""
    rnd = random.Random(23)
    a = [float((i * 37) % 23) - 11 for i in range(400)]
    b = [float((i * 17) % 19) - 9 for i in range(400)]
    diff, lo, hi = si.boot(a, b, rnd, n=400)
    assert hi > lo, "границы интервала совпали — это не интервал"
    assert lo < diff + 1e-9 and diff - 1e-9 < hi

    share = si.boot(a, b, rnd, stat="share", n=400)
    assert share[2] > share[1], "у доли>0 интервал тоже обязан иметь ширину"


def test_boot_statistic_is_chosen_by_argument():
    """`stat` обязан переключать СУТЬ величины: медиана — проценты движения, share — доля>0 в процентах.
    Если стенд всегда считает медиану, подпись «доля>0» в отчёте врёт (проверено мутацией)."""
    rnd = random.Random(23)
    a, b = [1.5] * 200, [-1.5] * 200
    assert si.boot(a, b, rnd, stat="median", n=100)[0] == pytest.approx(3.0)
    assert si.boot(a, b, rnd, stat="share", n=100)[0] == pytest.approx(100.0)


def test_boot_is_reproducible_with_same_seed():
    xs, ys = [float(i % 5) for i in range(200)], [float(i % 3) for i in range(200)]
    assert si.boot(xs, ys, random.Random(23), n=200) == si.boot(xs, ys, random.Random(23), n=200)


def test_summary_reports_median_share_and_mean():
    out = si.summary([-2.0, -1.0, 1.0, 2.0, 3.0])
    assert "n=     5" in out and "мед=+1.000%" in out and "доля>0=60.0%" in out
    assert si.summary([]) == "—"
