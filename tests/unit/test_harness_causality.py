# -*- coding: utf-8 -*-
"""Харнесс не заглядывает в будущее и не отбирает шум (ARCH-148.3 «в», паспорт инструмента — вид D).

Это ядро замеров: на `scripts/research_harness.py` стоят все выводы матрицы признаков. Заглядывание в будущее
(look-ahead) — главный враг бэктеста (README), и защищают от него три места:
  • `noncausal` — чёрный список признаков, которые ставятся задним числом (экстремумы HH/HL/LH/LL, Эллиотт);
  • `mtf_flags` — старший ТФ берётся только с ЗАКРЫТОГО бара (`shift(1)`): младший бар 10:15 не смеет знать
    часовой бар 10:00–11:00 до его закрытия;
  • `blind_select` — слепой отбор: признак, хороший на IS, но мусорный на OOS, не проходит; монеты IS и OOS
    не пересекаются.

Проверяем каждое golden-case: причинность — тем, что старший ТФ сдвинут ровно на один бар; отбор — тем, что
честный признак проходит, а подогнанный под IS отсеивается на OOS.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import scripts.research_harness as h


# ── чёрный список look-ahead ─────────────────────────────────────────────────

@pytest.mark.parametrize("col", [
    "hh_4h", "hl_15m", "lh_1h", "ll_1d",                      # экстремумы задним числом (префиксы)
    "elliott_bull_impulse", "elliott_textbook",              # разметка Эллиотта
    "inducement_bull", "bear_fvg_overlap_held",              # inducement, held-флаг
])
def test_noncausal_flags_are_rejected(col):
    assert h.noncausal(col) is True, f"look-ahead признак {col} обязан быть отсеян"


@pytest.mark.parametrize("col", [
    "wt_cross_up", "pivot_nearest_dist_r1", "atr_trend_up", "bos_up", "choch_down", "leg_up_depth",
])
def test_causal_flags_pass(col):
    assert h.noncausal(col) is False, f"нормальный признак {col} не должен попасть в чёрный список"


def test_blacklist_prefix_does_not_overmatch():
    """`ll_` сидит внутри каждого `bull_…` — чёрный список по префиксам, а не по подстроке, иначе вырежет живое."""
    assert h.noncausal("bull_ob") is False
    assert h.noncausal("full_leg") is False
    assert h.noncausal("ll_swing") is True


# ── причинность старшего ТФ (shift(1)) ───────────────────────────────────────

def _price(n: int, start="2026-01-01"):
    idx = pd.date_range(start, periods=n, freq="15min")
    base = 100 + np.arange(n) * 0.01
    return pd.DataFrame({"open": base, "high": base + 0.1, "low": base - 0.1,
                         "close": base, "volume": 1.0}, index=idx)


def _fake_compute_flags(df, label, include_pivots=False):
    """Вместо тяжёлого детектора — один признак `tick` = порядковый номер бара ЭТОГО ТФ.
    Так видно, какой именно бар старшего ТФ попал в младший."""
    return pd.DataFrame({"tick": np.arange(len(df), dtype=float)}, index=df.index)


def test_senior_timeframe_is_shifted_by_one_closed_bar(monkeypatch):
    monkeypatch.setattr("core.calculators.combinator_core.compute_flags", _fake_compute_flags)
    df = _price(4 * 400)                                       # 400 часов по 4 бара 15m (senior нужно >300)
    out = h.mtf_flags(df, "15m", senior=["1h"])
    col = "tick__from_1h"
    assert col in out.columns, "признак старшего ТФ обязан иметь суффикс __from_1h"
    # бар 15m в 03:00 лежит в часе 03:00–04:00 (tick часа = 3); с shift(1) он видит ЗАКРЫТЫЙ час 02:00 → tick 2
    v = out.loc[pd.Timestamp("2026-01-01 03:00"), col]
    assert v == 2.0, f"ожидали закрытый предыдущий час (tick 2), получили {v} — это заглядывание в будущее"
    # первый час закрытого старшего бара ещё нет → NaN
    assert pd.isna(out.loc[pd.Timestamp("2026-01-01 00:15"), col])


def test_senior_value_is_constant_within_its_bar(monkeypatch):
    """Внутри одного часа все четыре младших бара видят ОДНО значение старшего — ffill по закрытому бару."""
    monkeypatch.setattr("core.calculators.combinator_core.compute_flags", _fake_compute_flags)
    df = _price(4 * 400)
    out = h.mtf_flags(df, "15m", senior=["1h"])
    hour5 = out.loc["2026-01-01 05:00":"2026-01-01 05:45", "tick__from_1h"]
    assert hour5.nunique() == 1 and hour5.iloc[0] == 4.0, "четыре бара часа 05:00 видят закрытый час 04:00 (tick 4)"


def test_noncausal_columns_dropped_from_matrix(monkeypatch):
    def with_lookahead(df, label, include_pivots=False):
        return pd.DataFrame({"wt_cross_up": 1.0, "hh_swing": 1.0, "elliott_textbook": 1.0}, index=df.index)
    monkeypatch.setattr("core.calculators.combinator_core.compute_flags", with_lookahead)
    out = h.mtf_flags(_price(4 * 400), "15m", senior=[])
    assert "wt_cross_up" in out.columns
    assert "hh_swing" not in out.columns and "elliott_textbook" not in out.columns


# ── слепой отбор IS→OOS ──────────────────────────────────────────────────────

def _panel(seed=0):
    """Синтетическая база сделок: 40 монет, годы 2023–2026, поле pnl и два признака.
    `good` несёт настоящий эдж во ВСЕ годы; `is_only` — только на монетах IS в ранние годы (подгонка)."""
    rng = np.random.default_rng(seed)
    rows = []
    for coin in range(40):
        for y in range(2023, 2027):
            for _ in range(25):
                pnl = rng.normal(-0.1, 1.2)                   # шумная база чуть в минусе
                good = rng.random() < 0.4
                if good:
                    pnl += 0.8                                # умеренный честный эдж во ВСЕ годы
                is_mon = coin % 2 == 0
                is_only = int(is_mon and y <= 2024 and rng.random() < 0.3)
                if is_only:
                    pnl += 0.9                                # «эдж» только на монетах IS и ранних годах
                rows.append((f"C{coin:02d}", y, coin % 2 == 1, float(pnl), int(good), is_only))
    R = pd.DataFrame(rows, columns=["sym", "year", "oos", "pnl", "good", "is_only"])
    return R


def test_blind_select_keeps_a_genuine_edge(capsys):
    out = h.blind_select(_panel(1), is_years=(0, 2024), oos_years=(2025, 9999), min_keep_pct=10)
    assert "good" in out, "признак с настоящим эджем во все годы обязан пройти IS и OOS"


def test_blind_select_drops_is_only_overfit(capsys):
    """Признак, подогнанный под монеты и годы IS, на OOS (другие монеты, поздние годы) обязан провалиться."""
    out = h.blind_select(_panel(1), is_years=(0, 2024), oos_years=(2025, 9999), min_keep_pct=10)
    assert "is_only" not in out, "подгонка под IS не должна переживать слепой OOS"


def test_blind_select_is_and_oos_coins_do_not_overlap():
    R = _panel(2)
    IS = R[(~R.oos) & (R.year <= 2024)]
    OOS = R[R.oos & (R.year >= 2025)]
    assert set(IS.sym) and set(OOS.sym)
    assert set(IS.sym) & set(OOS.sym) == set(), "монеты IS и OOS обязаны не пересекаться"


def test_blind_select_rejects_a_flag_that_covers_everything(capsys):
    """Признак, срабатывающий почти на всей выборке, «фильтрует воздух» и не проходит отбор.
    Два барьера режут его: порог потока (>80%) и порог PF относительно базы — широкий признак размыт к базе,
    поэтому PF*1.15 не бьёт. Проверяем факт отсева, не настаивая на конкретном барьере."""
    rng = np.random.default_rng(3)
    R = _panel(3)
    R["wide"] = ((R["good"] == 1) | (rng.random(len(R)) < 0.85)).astype(int)
    assert R["wide"].mean() > 0.85
    out = h.blind_select(R, is_years=(0, 2024), oos_years=(2025, 9999), min_keep_pct=10)
    assert "wide" not in out


def test_feature_cols_skips_meta_and_nonnumeric():
    R = _panel(0)
    R["entry_ts"] = pd.Timestamp("2026-01-01")               # служебное поле времени не должно уехать в отбор
    cols = h.feature_cols(R)
    assert "good" in cols and "is_only" in cols
    assert not ({"sym", "oos", "year", "pnl", "entry_ts"} & set(cols))
