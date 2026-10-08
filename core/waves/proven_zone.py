# -*- coding: utf-8 -*-
"""ДОКАЗАННАЯ ЗОНА ВХОДА waves — одно правило для боя, канала Oko-WAVES и карточки аналитика (08.10).

Раньше правило жило только в `bot/loops/waves_long_loop.py`, и канал его не знал: Егор 08.10 («мы точно видим то что
нужно?!») — канал публиковал недоказанный поток (USELESS: 7 бумажных стопов за полтора дня на одиночной монете) без
пометки, а карточка аналитика горела зелёным при стопе 1.4%. Функции перенесены сюда без изменения смысла; бой
импортирует их отсюда же, поэтому канал не может разойтись с боем.

Правило (config.yaml → trading.waves_long): ЛОНГ доказан, если структурный стоп ≥ proven_stop_pct % цены ИЛИ ширина
стопа в долях импульса в коридоре [stop_rel_min; stop_rel_max). У ШОРТА доказанной зоны нет (замер 07.10).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

COST_RT = 0.35          # линейка коста проекта, % на круг ([[cost_is_amplifier_not_cause]])


def _stop_rel(entry, stop, imp_pct):
    """Ширина стопа в долях импульса: |вход−стоп|/вход, делённое на размер импульса в %.

    Считаем из цен сигнала, а не из `wv_risk_pct` тени: поле может отсутствовать у старых
    записей очереди, а цены есть всегда. None — если импульс неизвестен или нулевой
    (тогда решение принимает вызывающий, а не молчаливый ноль)."""
    try:
        e, s, i = float(entry), float(stop), float(imp_pct)
    except (TypeError, ValueError):
        return None
    if e <= 0 or i <= 0:
        return None
    return abs(e - s) / e * 100 / i


def _in_corridor(rel, lo, hi) -> bool:
    """Попадает ли ширина стопа в измеренный коридор [lo; hi).

    Верхняя граница ИСКЛЮЧЕНА — корзина 30-50% в замере считалась как [0.3; 0.5).
    Неизвестная ширина (нет `wv_imp_pct`) — это НЕ «в коридоре»: метка должна отличать
    «вне» от «не знаем», поэтому False, а признак `wv_stop_rel` в сделку просто не попадёт."""
    if rel is None:
        return False
    if lo is not None and rel < float(lo):
        return False
    if hi is not None and rel >= float(hi):
        return False
    return True


def _long_proven(entry, stop, in_corridor: bool, proven_stop_pct) -> bool:
    """ДОКАЗАННАЯ ЗОНА ЛОНГА: структурный стоп ≥ `proven_stop_pct` % цены ИЛИ коридор 30-50% импульса.

    07.10 (Егор: «заставить работать то, что уже доказано»). Замер боевым кодом
    (`scripts/wave_entry_delay_lab.py`, 198 монет, кост 0.35): лонг после завершённой пятёрки
    вниз со стопом ≥6% цены — плюс В КАЖДОМ году: 2023 PF 3.50 · 2024 1.43 · 2025 4.36 ·
    **2026 5.39 (183 сделки, 79% прибыльных, +7.59% в среднем)**. Коридор 30-50% импульса
    (метка с 03.10) тоже живой (n=126, PF 3.50) — он остаётся, зона его не заменяет, а
    расширяет. Стоп у доказанных сделок: медиана 9%, квартили 6.9–12.2%.
    """
    if in_corridor:
        return True
    if proven_stop_pct is None:
        return False
    try:
        e, s = float(entry), float(stop)
        if e <= 0:
            return False
        return abs(e - s) / e * 100.0 >= float(proven_stop_pct)
    except (TypeError, ValueError):
        return False


def _cfg_get() -> Callable[[str, Any], Any]:
    from core.infra.config_loader import config
    return config.get


def zone(side: str, entry, stop, imp_pct=None, get: Optional[Callable[[str, Any], Any]] = None) -> Dict[str, Any]:
    """Зона входа так, как её решает бой (`waves_long_loop`): proven, ширина стопа, доля импульса и строка для канала.
    `get` — чтение конфига `get(ключ, дефолт)`; по умолчанию config.yaml через config_loader."""
    g = get or _cfg_get()
    short = str(side).upper() == "SHORT"
    try:
        stop_pct = abs(float(entry) - float(stop)) / float(entry) * 100.0
    except (TypeError, ValueError, ZeroDivisionError):
        stop_pct = None
    rel = _stop_rel(entry, stop, imp_pct)
    in_cor = _in_corridor(rel, g("trading.waves_long.stop_rel_min", None), g("trading.waves_long.stop_rel_max", None))
    thr = g("trading.waves_long.proven_stop_pct", None)
    proven = False if short else _long_proven(entry, stop, in_cor, thr)
    shadow = bool(g("trading.waves_long.unproven_to_shadow", False))
    on = bool(g("trading.waves_long.enabled", False)) and (not short or bool(g("trading.waves_long.short_enabled", False)))
    sp = "—" if stop_pct is None else f"{stop_pct:.1f}%"
    rl = "" if rel is None else f" · {rel:.2f} импульса"
    if not on:
        route = "бой выключен"
    elif proven:
        route = "в бой"
    else:
        route = "тень, на биржу не идёт" if shadow else "на биржу пониженным риском"
    if proven:
        why = f"стоп {sp} ≥ {thr}%" if (stop_pct is not None and thr is not None and stop_pct >= float(thr)) else f"коридор{rl}"
        label = f"🔑 ДОКАЗАННАЯ ЗОНА: {why} → {route}"
    elif short:
        label = f"🌒 шорт: доказанной зоны нет (стоп {sp}) → {route}"
    else:
        label = f"🌒 вне доказанной зоны: стоп {sp} < {thr}%{rl} → {route}"
    return {"proven": proven, "stop_pct": stop_pct, "rel": rel, "in_corridor": in_cor, "route": route, "label": label,
            "thr": thr}
