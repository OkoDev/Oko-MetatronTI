# -*- coding: utf-8 -*-
"""Отбор waves_long по ширине стопа в долях импульса (03.10.2026).

Повод: замер 02.10 на 1427 LONG-сделках показал, что настоящая форма закона размера стопа —
доля ИМПУЛЬСА, а не процент цены:
  0-10% импульса → ср +0.52 (WR 16%, безтоп10% −908) · 10-20% → +2.89 · 20-30% → +2.22 ·
  **30-50% → +5.01 (WR 80%, Δr +10.76, Δt +1.63, безтоп +295)**
А бой стоял на медиане 0.129 — то есть в худших корзинах: 0 из 14 сделок попадали в коридор.

🔴 Отбор ОТМЕНЯЕТ прежнее правило «не отбирать заранее, резать результат потом» (17.09),
поэтому пороги живут в config (`trading.waves_long.stop_rel_min/max`) и снимаются одной правкой.
Тест фиксирует: арифметику доли, границы коридора (включая/исключая), поведение без порогов
и отказ считать при неизвестном импульсе — молчаливого нуля быть не должно.
"""
from __future__ import annotations

import pytest

from bot.loops.waves_long_loop import _in_corridor, _risk_mult, _stop_rel


def test_arithmetic_matches_measurement_units():
    """Стоп 12% цены при импульсе 40% = 0.30 импульса — нижняя граница коридора."""
    assert _stop_rel(100.0, 88.0, 40.0) == pytest.approx(0.30)
    # Медианный бой до правки: стоп 4.5% цены при импульсе 37.2% → 0.121 импульса.
    # (Поэлементная медиана по 14 сделкам БД — 0.129; отношение медиан ей не равно, это разные
    #  величины — здесь проверяется именно арифметика одной сделки.)
    assert _stop_rel(100.0, 95.5, 37.2) == pytest.approx(0.1210, abs=1e-4)


def test_direction_does_not_matter_for_width():
    """Берём модуль: ширина стопа не зависит от того, выше или ниже он входа."""
    assert _stop_rel(100.0, 90.0, 50.0) == _stop_rel(100.0, 110.0, 50.0)


@pytest.mark.parametrize("imp", [None, 0, 0.0, "", "нет"])
def test_unknown_impulse_returns_none_not_zero(imp):
    """Без импульса величина НЕИЗВЕСТНА. Ноль здесь означал бы «вне коридора» и тихо
    отбрасывал бы сигналы по несуществующей причине."""
    assert _stop_rel(100.0, 94.0, imp) is None


@pytest.mark.parametrize("entry", [0, -1, None, "abc"])
def test_bad_entry_returns_none(entry):
    assert _stop_rel(entry, 94.0, 40.0) is None


def _passes(rel, lo, hi):
    """Та же проверка границ, что в цикле: [lo; hi)."""
    if lo is None and hi is None:
        return True
    if rel is None:
        return False
    return not ((lo is not None and rel < float(lo)) or (hi is not None and rel >= float(hi)))


@pytest.mark.parametrize("rel,expect", [
    (0.129, False),   # медиана боя до правки — отсекается
    (0.299, False),
    (0.30, True),     # нижняя граница ВКЛЮЧЕНА
    (0.42, True),
    (0.499, True),
    (0.50, False),    # верхняя ИСКЛЮЧЕНА: корзина 30-50% мерилась как [0.3; 0.5)
    (0.80, False),
])
def test_corridor_boundaries(rel, expect):
    assert _passes(rel, 0.30, 0.50) is expect


def test_no_thresholds_means_no_gate():
    """Удалить ключи из конфига = вернуть прежний поток, включая узкие стопы."""
    assert _passes(0.05, None, None) is True
    assert _passes(None, None, None) is True


def test_config_keeps_both_tracks_in_play():
    """🔴 03.10 КОРИДОР = МЕТКА, А НЕ ОТБОР (Егор: «механику с гейтом можно оставить, но она не
    должна быть единственной! такой подход лишает нас потока данных ИСПОЛНЕНИЯ! можем оставлять
    их в работе, но параллельно друг другу»).

    Жёсткий отбор оставлял 6% потока (3 из 48 записей живой очереди) — данные исполнения
    (филлы, проскальзывание, косты) по остальным 94% не набирались бы вовсе. Тест закрепляет:
    границы коридора ЗАДАНЫ (иначе метка бессмысленна), а гейт ВЫКЛЮЧЕН (иначе второй трек
    исчезает). Вернуть отбор — осознанная правка конфига вместе с этим тестом.
    """
    from core.infra.config_loader import ConfigLoader
    cfg = ConfigLoader("config.yaml")
    lo = cfg.get("trading.waves_long.stop_rel_min", None)
    hi = cfg.get("trading.waves_long.stop_rel_max", None)
    gate = cfg.get("trading.waves_long.stop_rel_gate", False)
    assert lo is not None and hi is not None, "границы коридора не заданы — метка wv_in_corridor пуста"
    assert bool(gate) is False, (
        "stop_rel_gate=true оставляет в бою ТОЛЬКО коридор (~5 сделок/мес) и лишает данных "
        "исполнения по второму треку; если это намеренно — поправь тест вместе с конфигом")


def test_label_separates_tracks_but_blocks_nobody():
    """Оба трека идут в бой, но различимы: метка считается по тем же границам, что и отбор."""
    assert _in_corridor(0.42, 0.30, 0.50) is True
    assert _in_corridor(0.129, 0.30, 0.50) is False     # медианный бой — второй трек, но торгуется
    assert _in_corridor(None, 0.30, 0.50) is False      # ширина неизвестна ≠ «в коридоре»


@pytest.mark.parametrize("rel,expect", [
    (0.299, False), (0.30, True), (0.499, True), (0.50, False),
])
def test_label_boundaries_match_measured_basket(rel, expect):
    """Границы метки = границы корзины замера [0.3; 0.5): иначе метка и замер разойдутся."""
    assert _in_corridor(rel, 0.30, 0.50) is expect


class TestRiskWeightInsteadOfCutting:
    """🌊 04.10 РИСК-ВЕС ТРЕКА (Егор «да»): деньги защищаем размером, а не отсечением.

    Эдж мерится в % хода и от размера позиции НЕ зависит — значит поток резать не нужно,
    достаточно развести риск. Границы итога — те же [0.25; cap], что в `trade_router`:
    если ослабление выйдет за них, оно срежется там и правка станет декоративной.
    """

    CAP = 1.5

    def test_corridor_keeps_coin_weight_untouched(self):
        assert _risk_mult(1.2, True, 0.5, self.CAP) == pytest.approx(1.2)
        assert _risk_mult(0.8, True, 0.5, self.CAP) == pytest.approx(0.8)

    def test_outside_corridor_is_halved(self):
        assert _risk_mult(1.0, False, 0.5, self.CAP) == pytest.approx(0.5)
        assert _risk_mult(1.5, False, 0.5, self.CAP) == pytest.approx(0.75)

    def test_outside_without_coin_weight_still_weakened(self):
        """Веса монеты нет — ослабление всё равно должно примениться к базовой единице."""
        assert _risk_mult(None, False, 0.5, self.CAP) == pytest.approx(0.5)

    def test_nothing_to_apply_returns_none(self):
        """Ни веса, ни ослабления → ключ в сделку не пишется, риск базовый (как до правки)."""
        assert _risk_mult(None, True, None, self.CAP) is None
        assert _risk_mult(None, True, 0.5, self.CAP) is None

    def test_result_stays_inside_router_bounds(self):
        """Нижний пол 0.25 и потолок cap — иначе значение срежет роутер."""
        assert _risk_mult(0.5, False, 0.1, self.CAP) == pytest.approx(0.25)   # 0.05 → пол
        assert _risk_mult(1.5, True, 0.5, 1.2) == pytest.approx(1.2)          # 1.5 → потолок

    def test_disabled_multiplier_equalizes_tracks(self):
        """null или 1.0 → риск у обоих треков одинаковый."""
        assert _risk_mult(1.1, False, None, self.CAP) == _risk_mult(1.1, True, None, self.CAP)
        assert _risk_mult(1.1, False, 1.0, self.CAP) == pytest.approx(1.1)

    @pytest.mark.parametrize("bad", ["", "нет", object()])
    def test_bad_values_do_not_break_sizing(self, bad):
        """Мусор в весе или множителе не должен обнулять риск или ронять луп."""
        assert _risk_mult(bad, True, 0.5, self.CAP) is None
        assert _risk_mult(1.0, False, bad, self.CAP) == pytest.approx(1.0)

    def test_config_has_risk_weight_wired(self):
        from core.infra.config_loader import ConfigLoader
        cfg = ConfigLoader("config.yaml")
        rm = cfg.get("trading.waves_long.stop_rel_risk_mult", None)
        assert rm is not None and 0 < float(rm) < 1, (
            f"риск-вес трека не настроен (stop_rel_risk_mult={rm}) — вне коридора ставка "
            "должна быть МЕНЬШЕ, иначе защита денег не работает")


def test_one_sided_threshold_works():
    """Только нижний порог — коридор без верхней границы (вариант «стоп≥30% импульса»:
    n=54, ср +5.41, WR 83%)."""
    assert _passes(0.95, 0.30, None) is True
    assert _passes(0.20, 0.30, None) is False


# ── 06.10 ШОРТ: своя клетка, не коридор импульса ──────────────────────────────
# Егор «шорт-ядра +». Шорт отсекался наглухо с 16.09; замер 29.09 подтвердил это
# на общей базе (Δt −0.09, при боевом косте вся сторона −0.22), но нашёл ОДНО живое
# место — «полное ядро ∧ стоп ≥6% цены» (n=36, Δt +4.41, перестановка p=0.002).
class TestShortCell:
    def test_both_conditions_required(self):
        from bot.loops.waves_long_loop import _short_cell
        # ядро есть, стоп 10% → клетка
        assert _short_cell(100.0, 110.0, True) is True
        # ядро есть, стоп 3% → НЕ клетка (стоп узкий)
        assert _short_cell(100.0, 103.0, True) is False
        # стоп широкий, ядра нет → НЕ клетка: «стоп≥6% без ядра» мёртв (Δt −0.69)
        assert _short_cell(100.0, 110.0, False) is False
        # ни того, ни другого
        assert _short_cell(100.0, 102.0, False) is False

    def test_boundary_is_six_percent(self):
        from bot.loops.waves_long_loop import _short_cell
        assert _short_cell(100.0, 106.0, True) is True      # ровно 6% — внутри
        assert _short_cell(100.0, 105.99, True) is False    # чуть меньше — вне

    @pytest.mark.parametrize("entry,stop", [(None, 110.0), (100.0, None),
                                            ("x", 110.0), (0.0, 110.0)])
    def test_garbage_does_not_raise(self, entry, stop):
        from bot.loops.waves_long_loop import _short_cell
        assert _short_cell(entry, stop, True) is False

    def test_config_has_short_wired(self):
        """Флаги должны читаться ЧЕРЕЗ config_loader, а не из сырого YAML."""
        from core.infra.config_loader import ConfigLoader
        cfg = ConfigLoader("config.yaml")
        assert cfg.get("trading.waves_long.short_enabled", None) is True
        assert float(cfg.get("trading.waves_long.short_cell_risk_mult", 0)) == 0.5
