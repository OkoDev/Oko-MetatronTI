# -*- coding: utf-8 -*-
"""Карточка вердикта судит верно (ARCH-148.3, паспорт инструмента — вид D «замер»).

Зачем. `scripts/research_verify.py` — измеритель, на котором стоят ВСЕ выводы проекта «работает / не
работает», и ровно эту услугу мы собираемся продавать. До 13.10.2026 у него не было ни одного теста:
если он врёт, врут все выводы разом, включая те, по которым что-то уже выключено.

Как проверяем. Golden-case: подаём данные с заранее известным ответом и смотрим на ВЕРДИКТ и на
список гейтов, а не на числа. Четыре случая, ради которых карточка и писалась:
  • эджа нет вовсе                     → не прошла, и провалился гейт нулевой модели;
  • эдж есть и устойчив                → прошла;
  • «эдж» держится на нескольких днях  → провалился гейт «без лучших дней»;
  • эдж есть, но на четверти монет     → провалился гейт охвата.

🔴 Во всех тестах `journal=False`: журнал гипотез живёт на G:/oko_lab и считает N между сессиями —
тестовые прогоны не имеют права его засорять.
"""
from __future__ import annotations

import numpy as np
import pytest

import scripts.research_verify as rv
from tests.factories import trades

FAST = {"n_null": 150}          # нулевая модель: 150 сдвигов вместо 1000 — хватает для вердикта, тест быстрый


def _card(df, **kw):
    D = rv.normalize(df)
    return rv.card(D, D.index.isin(df.index[df.cand]), name=kw.pop("name", "кандидат"),
                   study="тест", spec=FAST, journal=False, quiet=True, **kw)


# ── контракт данных ──────────────────────────────────────────────────────────

def test_normalize_renames_and_drops_broken_rows():
    df = trades(days=5, years=1).rename(columns={"pnl": "net_pct", "ts": "entry_time"})
    df.loc[0, "net_pct"] = np.nan
    df.loc[1, "entry_time"] = None
    D = rv.normalize(df, pnl="net_pct", ts="entry_time")
    assert {"pnl", "ts", "sym", "side", "year", "day"} <= set(D.columns)
    assert len(D) == len(df) - 2, "строки без исхода или без времени обязаны выпасть"
    assert D.ts.dt.tz is None and D.day.dt.hour.eq(0).all()


def test_fingerprint_is_stable_and_data_dependent():
    a, b = trades(days=6, years=1, seed=1), trades(days=6, years=1, seed=1)
    c = trades(days=6, years=1, seed=2)
    assert rv.fingerprint(rv.normalize(a)) == rv.fingerprint(rv.normalize(b))
    assert rv.fingerprint(rv.normalize(a)) != rv.fingerprint(rv.normalize(c))


# ── четыре главных случая ────────────────────────────────────────────────────

def test_no_edge_is_rejected():
    """Исходы случайны, кандидат размечен случайно. Карточка обязана отклонить и назвать нулевую модель."""
    out = _card(trades(edge=0.0, seed=11), name="пустышка")
    assert out["passed"] is False
    assert "лучше остальных (нулевая модель)" in out["failed"]


def test_real_edge_passes_all_gates():
    out = _card(trades(edge=1.2, noise=1.0, seed=3), name="настоящий эдж")
    assert out["passed"] is True, f"устойчивый эдж отклонён, провалились: {out['failed']}"
    assert out["delta"] > 0.5 and out["p"] < 0.05


def test_edge_made_of_a_few_days_fails_fragility():
    """Обычные дни в нуле, несколько дней дают всю прибыль. Деньги на месте, но держатся на днях."""
    out = _card(trades(edge=0.0, base=0.0, noise=0.8, per_day=8, spike_days=6, spike=4.0, seed=5),
                name="шесть дней")
    assert out["gates"]["деньги"] is True, "случай задуман так, что деньги в среднем есть"
    assert out["gates"]["без лучших дней"] is False
    assert out["passed"] is False


def test_edge_on_few_coins_fails_coverage():
    """Деньги в среднем есть, но делают их 4 монеты из 16 — карточка обязана это назвать."""
    out = _card(trades(edge=3.0, cand_coins=4, coins=16, noise=0.8, base=-0.3, seed=9), name="четыре монеты")
    assert out["gates"]["деньги"] is True
    assert out["gates"]["охват монет"] is False
    assert out["passed"] is False


def test_profit_from_rare_tails_fails_money_gate():
    """Среднее положительное, но всё держится на редких огромных выигрышах: без лучших 10% сделок — минус.
    Гейт «деньги» обязан смотреть на хрупкость, а не только на среднее."""
    out = _card(trades(edge=0.0, noise=0.8, per_day=8, spike_days=4, spike=5.0, seed=5), name="хвост")
    assert out["gates"]["деньги"] is False
    assert out["passed"] is False


def test_edge_only_in_one_year_fails_years_gate():
    """Эдж был в первом году и исчез во втором — по годам кандидат не устойчив."""
    out = _card(trades(noise=0.8, years=2, edge_by_year=(2.5, -1.0), seed=15), name="только первый год")
    assert out["gates"]["годы"] is False
    assert out["passed"] is False


def test_edge_in_both_years_passes_years_gate():
    out = _card(trades(edge=1.6, noise=0.8, years=2, seed=15), name="оба года")
    assert out["gates"]["годы"] is True


# ── границы и честность отчёта ───────────────────────────────────────────────

def test_tiny_candidate_builds_no_card():
    df = trades(days=4, years=1, per_day=2, seed=4)
    df["cand"] = False
    df.loc[df.index[:3], "cand"] = True
    out = _card(df, name="три сделки")
    assert out["passed"] is False and out["gates"] == {}
    assert "карточка не строится" in out["text"]


def test_small_sample_fails_sample_gate():
    """Монет и дней мало — карточка строится, но прямо говорит, что выборки не хватает."""
    out = _card(trades(coins=4, days=12, per_day=6, years=1, edge=1.5, seed=6), name="мало данных")
    assert out["gates"], "карточка обязана построиться: сделок хватает, мало именно монет и дней"
    assert out["gates"]["выборка (дни, монеты)"] is False
    assert out["passed"] is False


def test_missing_checks_are_declared_not_hidden():
    """Чего посчитать нельзя — обязано попасть в «НЕ проверено», а не промолчать."""
    out = _card(trades(edge=1.2, seed=3))
    for expect in ("контроль", "ликвидность", "перекрытие", "геометри"):
        assert any(expect in m for m in out["missing"]), f"не объявлено: {expect}"
    assert "ярус 2" in out["text"] and "суррогат IAAFT" in out["text"]


def _with_control(df, cand_adv: float, rest_adv: float):
    """Контроль: случайный вход той же геометрии. `cand_adv` — насколько кандидат его обыгрывает, `rest_adv` — остальные."""
    df = df.copy()
    df["ctrl"] = df.pnl - np.where(df.cand, cand_adv, rest_adv)
    D = rv.normalize(df, ctrl="ctrl")
    return rv.card(D, D.index.isin(df.index[df.cand]), name="с контролем", study="тест",
                   spec=FAST, journal=False, quiet=True)


def test_control_gate_looks_at_the_candidate_not_at_the_rest():
    """Кандидат обыгрывает случайный вход, остальные ему проигрывают — гейт обязан судить по КАНДИДАТУ.
    Тест специально асимметричный: при подмене «кандидат → остальные» он падает (проверено мутацией)."""
    out = _with_control(trades(edge=1.2, seed=3), cand_adv=1.0, rest_adv=-1.0)
    assert out["gates"]["лучше случайного входа той же геометрии"] is True
    assert not any("контроль" in m for m in out["missing"]), "колонка есть — проверка обязана включиться"


def test_control_gate_fails_when_candidate_loses_to_random_entry():
    out = _with_control(trades(edge=1.2, seed=3), cand_adv=-1.0, rest_adv=1.0)
    assert out["gates"]["лучше случайного входа той же геометрии"] is False
    assert out["passed"] is False


def test_journal_off_writes_nothing(monkeypatch, tmp_path):
    j = tmp_path / "journal.jsonl"
    monkeypatch.setattr(rv, "JOURNAL", j)
    _card(trades(days=6, years=1, seed=8), name="без журнала")
    assert not j.exists(), "journal=False обязан молчать: тесты не засоряют журнал гипотез"


def test_same_data_gives_same_verdict():
    """Вердикт не имеет права плавать от прогона к прогону: нулевая модель идёт от зафиксированного seed."""
    a = _card(trades(edge=1.2, seed=3), name="повтор")
    b = _card(trades(edge=1.2, seed=3), name="повтор")
    assert (a["passed"], round(a["p"], 6), round(a["delta"], 6)) == (b["passed"], round(b["p"], 6), round(b["delta"], 6))


# ── ярус 2: нулевая модель всего поиска ──────────────────────────────────────

def test_search_null_catches_a_search_that_finds_noise():
    """Поиск перебирает 60 случайных масок и берёт лучшую — такой «победитель» находится и на мусоре."""
    D = rv.normalize(trades(edge=0.0, seed=12))
    rng = np.random.default_rng(0)
    masks = [rng.random(len(D)) < 0.3 for _ in range(60)]

    def search(pnl):
        best = max(range(len(masks)), key=lambda i: pnl[masks[i]].mean() - pnl[~masks[i]].mean())
        return f"маска {best}", pnl[masks[best]].mean() - pnl[~masks[best]].mean()

    out = rv.search_null(D, search, name="перебор масок", study="тест", n=60, journal=False)
    assert out["passed"] is False, "перебор на шуме обязан провалить ярус 2"


def test_search_null_passes_a_real_signal():
    df = trades(edge=2.0, seed=13)
    D = rv.normalize(df)
    m = D.index.isin(df.index[df.cand])

    def search(pnl):
        return "настоящая метка", pnl[m].mean() - pnl[~m].mean()

    out = rv.search_null(D, search, name="настоящий сигнал", study="тест", n=60, journal=False)
    assert out["passed"] is True and out["p"] < 0.05
