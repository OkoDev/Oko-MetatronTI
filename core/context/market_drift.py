# -*- coding: utf-8 -*-
"""ПРИЧИННЫЙ ДЕТЕКТОР РЕЖИМА: дрейф вселенной + ширина рынка (11.08.2026).

Зачем. Замер 11.08 показал, что клетка OTE — не шортовый эдж, а ЗЕРКАЛО РЕЖИМА:
в быка платит лонг (PF 2.41), в медведя шорт (1.71), в нейтрали обе мертвы
([[ote_short_cluster_full_candidate]] снят как «шортовый кандидат»).
Но метка режима там бралась по доходности за ВЕСЬ ГОД — то есть с заглядыванием в будущее.
Как диагноз механики годится, как торговый гейт — нет.

Здесь метка строится ТОЛЬКО по прошлым барам:
  · drift   — медианная по вселенной доходность за окно (по умолчанию 30 дней)
  · breadth — доля монет выше своей скользящей средней (ширина рынка)
  · порог   — РАСШИРЯЮЩИЙСЯ перцентиль (терцили) по прошлым значениям, без знания будущего
  · shift(1) на выходе — метка доступна только со следующего бара

Почему не доминация: `core/context/marketcap_engine` работает ТОЛЬКО вживую
(`live_dominance`, `rotation_now`) — supply-снапшот и текущие цены. Исторического ряда
доминации нет, значит на бэктесте честно её взять неоткуда. Дрейф и ширина считаются
из того же ценового кэша и на истории, и в бою → один калькулятор, различия параметрами
([[principle_reuse_not_duplication]]).

Использование:
    from core.context.market_drift import regime_series, regime_now
    reg = regime_series(panel)          # бэктест: panel = DataFrame(index=время_мс, cols=символы)
    lab = regime_now(panel_recent)      # бой: та же функция на свежем окне
"""
from __future__ import annotations

import numpy as np
import pandas as pd

BULL, BEAR, FLAT = "БЫК", "МЕДВЕДЬ", "НЕЙТРАЛЬ"


def drift_breadth(panel: pd.DataFrame, drift_bars: int, ma_bars: int):
    """Дрейф вселенной и ширина рынка. Обе величины — только по прошлым барам.

    panel: индекс — время (возрастающее), колонки — символы, значения — close.
    drift_bars: окно доходности в барах (30 дней на 4h = 180).
    ma_bars: окно скользящей для ширины (8 дней на 4h = 48).
    """
    # Заполнение пропусков ЯВНОЕ и намеренное: пропуск переносит последнюю цену, иначе монета
    # выпадает из медианы этого бара. Это сохраняет замеры 11-12.08, на которых принят
    # переключатель режима. 17.08: перешли с депрекейтнутого pct_change(fill_method='pad')
    # на .ffill().pct_change() — ЭКВИВАЛЕНТНОСТЬ ДОКАЗАНА на панели 10038×488 (55% пропусков):
    # drift и breadth совпали побитово, все 50 190 ячеек regime_series — 0 расхождений.
    # TODO: прогнать развёртку БЕЗ заполнения — честнее, но потребует пересчёта вердиктов.
    drift = panel.ffill().pct_change(drift_bars).median(axis=1)
    ma = panel.rolling(ma_bars, min_periods=max(5, ma_bars // 2)).mean()
    breadth = (panel > ma).sum(axis=1) / panel.notna().sum(axis=1).replace(0, np.nan)
    return drift, breadth


def _expanding_tercile_label(x: pd.Series, min_periods: int) -> pd.Series:
    """Терциль ПО ПРОШЛЫМ значениям: порог на баре t считается по x[:t], не по всему ряду.

    Именно здесь обычно протекает будущее: фиксированные пороги, подобранные на всей
    выборке, — это скрытый look-ahead. Расширяющееся окно его исключает.
    """
    lo = x.expanding(min_periods=min_periods).quantile(1 / 3)
    hi = x.expanding(min_periods=min_periods).quantile(2 / 3)
    out = pd.Series(FLAT, index=x.index, dtype=object)
    out[x >= hi] = BULL
    out[x <= lo] = BEAR
    out[x.isna() | lo.isna() | hi.isna()] = None
    return out


def _persist(label: pd.Series, min_hold: int) -> pd.Series:
    """ГИСТЕРЕЗИС: смена режима засчитывается только после `min_hold` подряд идущих баров
    нового состояния. До подтверждения держим прежний.

    Зачем: без этого значение, болтающееся у порога терциля, перебрасывает метку туда-обратно.
    Замер 11.08 на сырой метке: 04.05 БЫК→НЕЙТРАЛЬ в тот же день, 13.05 дважды за сутки.
    Режим, меняющийся дважды в день, — это шум, а не режим: как гейт он будет открывать
    и закрывать сторону на ровном месте. Причинность сохраняется — смотрим только назад.
    """
    if min_hold <= 1:
        return label
    out = []
    cur = None
    run_val, run_len = None, 0
    for v in label:
        v = None if (v is None or (isinstance(v, float) and np.isnan(v))) else v
        if v == run_val:
            run_len += 1
        else:
            run_val, run_len = v, 1
        if run_val is not None and run_len >= min_hold:
            cur = run_val
        out.append(cur)
    return pd.Series(out, index=label.index, dtype=object)


def regime_series(panel: pd.DataFrame, drift_bars: int = 180, ma_bars: int = 48,
                  min_periods: int = 500, combine: bool = True,
                  min_hold: int = 12) -> pd.DataFrame:
    """Причинный ряд режима. Возвращает DataFrame: drift, breadth, label.

    combine=True — метка ставится только когда дрейф и ширина СОГЛАСНЫ; при расхождении
    НЕЙТРАЛЬ. Согласие двух независимых измерителей — защита от одиночного выброса.
    min_hold — сколько баров новое состояние должно продержаться до смены (12 баров 4h = 2 суток).
    """
    panel = panel.sort_index()
    drift, breadth = drift_breadth(panel, drift_bars, ma_bars)
    lab_d = _expanding_tercile_label(drift, min_periods)
    lab_b = _expanding_tercile_label(breadth, min_periods)
    if combine:
        label = pd.Series(FLAT, index=panel.index, dtype=object)
        both_bull = (lab_d == BULL) & (lab_b == BULL)
        both_bear = (lab_d == BEAR) & (lab_b == BEAR)
        label[both_bull] = BULL
        label[both_bear] = BEAR
        label[lab_d.isna() | lab_b.isna()] = None
    else:
        label = lab_d
    label = _persist(label, min_hold)
    out = pd.DataFrame({"drift": drift, "breadth": breadth,
                        "label_drift": lab_d, "label_breadth": lab_b, "label": label})
    # ПРИЧИННОСТЬ: метка бара t доступна только со следующего бара
    return out.shift(1)


def regime_now(panel: pd.DataFrame, **kw) -> str | None:
    """Последняя доступная метка режима — та же функция, что и на истории."""
    s = regime_series(panel, **kw)
    if s.empty:
        return None
    v = s["label"].iloc[-1]
    return None if (v is None or (isinstance(v, float) and np.isnan(v))) else str(v)
