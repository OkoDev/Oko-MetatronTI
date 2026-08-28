# -*- coding: utf-8 -*-
"""ИМПУЛЬС → ЛИМИТ НА ОТКАТЕ 0.382 — единственный калькулятор механики (20.08.2026).

Главный результат сессии 19.08 ([[impulse_fib_three_gates_oos]]): OOS-монеты × OOS-время
n=201, WR 56.2%, PF 1.53, все 5 лет в плюсе (1.65/3.74/1.80/1.42/1.62).

    1. импульс ПО ОПРЕДЕЛЕНИЮ: ход ≥3 ATR, контр-откат ≤35% хода, длина ≤60 баров (1h);
    2. вход  = лимит на откате 0.382 от экстремума (лучший из пяти уровней);
    3. стоп  = 2.5·ATR от входа — НЕ за начало импульса ([[resurrect_dead_strategies_by_stop_size]]:
       стоп за origin даёт 8.5% и при плече 10 стоит ЗА ликвидацией — 123 ликвидации из 503;
       2.5·ATR даёт ~4.4% и двойной запас: 12 ликвидаций, PF 1.63 против 1.56);
    4. цель ОДНА для обеих сторон: −1.272 по фибо-шкале от экстремума. Прежнее правило
       «по стороне» снято по возражению Егора 20.08 и перемеру: цель — НЕ рычаг, кривая
       PF по сетке −0.5…−2.618 плоская везде, а сторона по годам переворачивается
       (2023: long 1.94 / short 0.68 против 2022: short 2.73 / long 0.79);
    5. три гейта: объём импульса 1.0–1.5× · по тренду EMA200 · ATR/SMA100 > 1.1.

🔴 ВЫХОД ТОЛЬКО ФИКСИРОВАННЫЙ. БУ, трейлинг и частичная фиксация проверены — каждый
забирает от 7 до 25% дохода: WR растёт, деньги падают ([[backlog_impulse_session_19_08]]).

🔴 ПИВОТНЫЙ ФИЛЬТР (LONG pivot_bounce_down_R1_1D · SHORT pivot_above_S1_1D) в бой НЕ взят:
поднимает PF, но режет частоту — портфельно +6.3%/мес против +8.4% без него.

Один калькулятор на скрипт и на луп ([[principle_reuse_not_duplication]]):
различия задаются параметрами, формулы не дублируются.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.smc.choch_wavec import is_junk  # noqa: F401  (реэкспорт: фильтр синтетики общий)

# Параметры механики. Значения получены измерением, не подбором «на глаз».
MIN_ATR = 3.0        # ход импульса в ATR — определение импульса
# 🔴 28.08.2026: 0.35 → 0.32 ВМЕСТЕ со сменой `amp_mode` на "extremes".
# Эти две константы ПАРНЫЕ и врозь не меняются. `max_retr` сравнивает контр-откат
# (он всегда считается по H/L) с ХОДОМ. Пока ход мерился по close, 0.35 означало
# одну строгость; ход по экстремумам больше медианно в 1.18× → то же число стало
# СЛАБЕЕ, впустив рваные движения. Замер 1h: смена режима без перекалибровки дала
# PF 2.90 → 1.67 и хрупкость +117 → −180. С 0.32 поток совпадает с прежним (1.12×)
# и PF возвращается к 2.17 при хрупкости +2.
# 🔑 Класс ошибки тот же, что `choch_length` между ТФ: константа сохранена,
# а означает уже другое, потому что изменился знаменатель.
MAX_RETR = 0.32      # максимальный контр-откат внутри хода (доля от хода)
MAX_BARS = 60        # длина импульса в барах
ENTRY_FIB = 0.382    # глубина отката для лимита
STOP_ATR_K = 2.5     # стоп = k·ATR от входа
WAIT_BARS = 12       # столько баров лимит остаётся актуальным
HOLD_BARS = 96       # горизонт удержания позиции после фила
MIN_BARS = 300       # ATR(43) и EMA200 требуют истории

# 🔴 ЦЕЛЬ ОДНА ДЛЯ ОБЕИХ СТОРОН — фибо-шкала: 0 = экстремум, <0 = расширение за него.
# Было `{"long": -1.0, "short": -1.618}`. Возражение Егора 20.08: «мы поедем на хардкоде,
# картина лонга может измениться». Замер (200 монет, 22 399 входов, сетка −0.5…−2.618)
# показал, что прав он, но по более сильной причине — ЦЕЛЬ ВООБЩЕ НЕ РЫЧАГ:
#   · кривая PF по сетке ПЛОСКАЯ в каждом разрезе (long 0.95-1.01 · short 1.02-1.10 ·
#     по режиму 1.09-1.13 · против режима 0.75-0.86);
#   · на одних сделках: по стороне 1.56 · по режиму 1.51 · фикс −1.618 1.56 ·
#     фикс −1.272 1.55 · фикс −1.0 1.53 — всё в пределах шума.
# А вот СТОРОНА по годам переворачивается: 2022 short 2.73/long 0.79 → 2023 (бычий)
# long 1.94/short 0.68 → 2025 short 1.05/long 0.75. Числа «для шорта», выведенные на
# окне 2022-2026, в бычий год поедут в стену — ровно то, о чём говорил Егор.
# Привязка к режиму тоже отклонена: на OOS×OOS согласие с режимом даёт 0.73 против
# 0.67 у «против режима», а лучше всех нейтраль (1.06) — правило не заслужило места.
# Внутри боевой клетки (три гейта + стоп 1.5-3.2%) кривая уже НЕ плоская, а растёт к
# дальним целям и на всём окне, и на свежем: −0.5 → 2.23/1.63 · −1.0 → 2.55/1.71 ·
# −1.618 → 2.77/1.94 · −2.0 → 2.85/1.90 (второе число = 2025-26). Берём −1.618: соседи
# с обеих сторон дают близкое, то есть это плато, а не пик.
TARGET_FIB = -1.618

# Пороги трёх гейтов.
VOL_LO, VOL_HI = 1.0, 1.5    # объём импульса к средней: и ниже, и ВЫШЕ коридора хуже
REGIME_MIN = 1.1             # ATR/SMA100 — механика живёт на расширении волатильности


def _atr(d: pd.DataFrame) -> pd.Series:
    """ATR боевой калибровки: ewm alpha=1/43 ([[calib_atrtrend_factor]])."""
    tr = pd.concat([d.high - d.low, (d.high - d.close.shift()).abs(),
                    (d.low - d.close.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / 43, adjust=False).mean()


def find_impulses(H, L, C, atr, n, *, min_atr: float = MIN_ATR,
                  max_retr: float = MAX_RETR, max_bars: int = MAX_BARS,
                  start: int = 60, seen: set | None = None,
                  origin_mode: str = "longest",
                  amp_mode: str = "extremes",
                  floor_i: np.ndarray | None = None) -> list[tuple[int, int, bool]]:
    """Импульсы (a, b, up) по определению. Для b берётся САМЫЙ ДЛИННЫЙ подходящий ход.

    Причинно: бар b использует только бары [a..b], будущее не читается.

    🔴 ДЕДУП ПО НАЧАЛУ ИМПУЛЬСА, а не решёткой сканирования. Раньше после находки
    детектор прыгал `b += 5` — и набор сетапов зависел от того, с какого бара начался
    скан: замер идёт с 60-го бара, бой стартует с окна ожидания, решётки разъезжаются.
    Регрессия эквивалентности поймала это на 1 сетапе из 48 (GRASS). Правило
    «один импульс = один сетап» одинаково работает в обе стороны: в замере дедуп
    держит `seen`, в бою ту же роль играет UNIQUE(symbol, origin_ts) в журнале.
    """
    out, b = [], start
    if seen is None:
        seen = set()
    while b < n:
        best, best_purity = None, None
        # 🔑 ГРАНИЦА ПО СТРУКТУРЕ (20.08): начало импульса не может уйти за экстремум
        # последней ПОДТВЕРЖДЁННОЙ структурной ноги. Это чинит захват чужого хвоста
        # (KAIA: origin встал на сутки раньше дна), НЕ трогая тех, кто и так внутри —
        # в отличие от полной замены детектора, которая сдвинула бы amp у ВСЕХ сетапов
        # и обрушила выборку (замер: 2.82 → 0.75). См. [[detector_form_is_the_root]].
        lo_bound = int(floor_i[b]) if floor_i is not None and floor_i[b] >= 0 else 1
        for back in range(5, max_bars + 1):
            a = b - back
            if a < 1 or a < lo_bound:
                break
            # 🔴 28.08 amp_mode (Егор: «импульс не захватывает экстремумы»).
            # `close` — историческое поведение: ход меряется по ЦЕНАМ ЗАКРЫТИЯ,
            # то есть тени в ход не входят. Замер на 32 803 импульсах: настоящий
            # ход по экстремумам БОЛЬШЕ медианно в 1.18×, а в 82% случаев занижен
            # более чем на 10%. Начало мимо экстремума на 0.53% цены, конец на 0.39%.
            # `extremes` — ход от экстремума к экстремуму, как его видит глаз.
            # Дефолт пока `close`: смена сдвигает амплитуду у ВСЕХ сетапов, а значит
            # вход по фибо, стоп и цель. Полная замена детектора однажды уже обрушила
            # выборку (2.82 → 0.75) — поэтому сначала замер, потом дефолт.
            if amp_mode == "extremes":
                p_a = float(L[a]) if C[b] > C[a] else float(H[a])
                p_b = float(H[b]) if C[b] > C[a] else float(L[b])
                move = abs(p_b - p_a)
            else:
                move = abs(C[b] - C[a])
            if atr[b] <= 0 or move / atr[b] < min_atr:
                continue
            sh, sl_ = H[a:b + 1], L[a:b + 1]
            dd = (float(np.max(np.maximum.accumulate(sh) - sl_)) if C[b] > C[a]
                  else float(np.max(sh - np.minimum.accumulate(sl_))))
            if dd / move > max_retr:
                continue
            up_ = C[b] > C[a]
            if origin_mode == "extreme":
                # origin ОБЯЗАН быть экстремумом окна: для хода вверх — минимум [a..b].
                # Иначе в «импульс» попадает хвост предыдущего снижения (KAIA 20.08:
                # origin встал на сутки раньше дна, «откат внутри 35%» оказался куском
                # чужого падения). Критерий «откат ≤35%» такой захват НЕ ловит — он лишь
                # ограничивает его размер.
                ok = (L[a] == float(np.min(L[a:b + 1])) if up_
                      else H[a] == float(np.max(H[a:b + 1])))
                if not ok:
                    continue
                best = (a, up_)          # среди экстремумов берём самый дальний
            elif origin_mode == "purest":
                p = dd / move            # чем меньше контр-откат, тем чище ход
                if best_purity is None or p < best_purity:
                    best, best_purity = (a, up_), p
            else:                        # "longest" — историческое поведение
                best = (a, up_)
        if best is not None and best not in seen:
            seen.add(best)
            out.append((best[0], b, best[1]))
        b += 1
    return out


def find_setup(df: pd.DataFrame, *, symbol: str = "", entry_fib: float = ENTRY_FIB,
               target_fib: float = TARGET_FIB, stop_atr_k: float = STOP_ATR_K,
               wait_bars: int = WAIT_BARS, drop_last: bool = True) -> dict:
    """Ищет живой сетап на 1h. Возвращает dict; ключ `reason` — только когда сетапа нет.

    drop_last=True отбрасывает незакрытый бар — без этого вход считается по цене,
    которой ещё нет ([[oko_suite_trend_wt_validated]], класс-1 look-ahead).

    🔑 Стоп берётся от ATR на баре КОНЦА ИМПУЛЬСА, а не на баре фила: лимит и стоп
    выставляются одновременно, ATR будущего бара в этот момент неизвестен.
    """
    if df is None or len(df) < MIN_BARS:
        return {"symbol": symbol, "reason": "мало данных"}
    d = df.copy()
    d.columns = [c.lower() for c in d.columns]
    if drop_last:
        d = d.iloc[:-1]
    dd = d.reset_index(drop=True)
    n = len(dd)
    H, L, C, V = dd.high.values, dd.low.values, dd.close.values, dd.volume.values

    aa = _atr(dd)
    atr = aa.values
    regime = (aa / aa.rolling(100).mean()).values
    ema200 = dd.close.ewm(span=200, adjust=False).mean().values
    volma = pd.Series(V).rolling(120).mean().values

    # Живым может быть только импульс, закончившийся не раньше wait_bars назад.
    imps = find_impulses(H, L, C, atr, n, start=max(60, n - 1 - wait_bars))
    if not imps:
        return {"symbol": symbol, "reason": "импульса нет"}
    a, b, up = imps[-1]

    side = "long" if up else "short"
    origin, extreme = float(C[a]), float(C[b])
    amp = abs(extreme - origin)
    if amp <= 0:
        return {"symbol": symbol, "reason": "нулевой ход"}

    sign = -1.0 if up else 1.0
    entry = extreme + sign * entry_fib * amp
    sl = entry - stop_atr_k * atr[b] if up else entry + stop_atr_k * atr[b]
    tp = extreme + sign * target_fib * amp
    if (up and sl >= entry) or (not up and sl <= entry):
        return {"symbol": symbol, "reason": "стоп с той же стороны, что вход"}

    stop_pct = abs(entry - sl) / entry * 100
    if stop_pct <= 0 or stop_pct > 30:
        return {"symbol": symbol, "reason": f"стоп {stop_pct:.1f}% вне диапазона"}

    # Лимит уже отработан / стоп уже пробит на прошедших барах → сетап не наш.
    post = slice(b + 1, n)
    filled = bool((L[post] <= entry).any() if up else (H[post] >= entry).any())
    invalid = bool((L[post] <= sl).any() if up else (H[post] >= sl).any())

    vol_sum = float(V[a:b + 1].sum())
    vratio = float(vol_sum / (b - a + 1) / volma[b]) if volma[b] > 0 else 0.0
    reg = float(regime[b]) if not np.isnan(regime[b]) else 1.0

    return {
        "symbol": symbol, "side": side, "price": float(C[-1]),
        "a": a, "b": b, "age": n - 1 - b,
        "origin": origin, "extreme": extreme, "amp": amp,
        "entry": entry, "sl": sl, "tp": tp, "stop_pct": stop_pct,
        "rr": abs(tp - entry) / abs(entry - sl),
        "filled": filled, "invalid": invalid,
        "vratio": vratio, "regime": reg,
        "with_trend": bool((C[b] > ema200[b]) == up),
        "atr_pct": float(atr[b] / C[b] * 100),
        "impulse_ts": str(d.index[b])[:16],
        # 🔑 ключ дедупа — НАЧАЛО импульса: один импульс даёт один сетап, даже если
        # детектор увидит его на нескольких соседних барах (см. find_impulses).
        "origin_ts": str(d.index[a])[:16],
        "live": bool(not invalid and not filled and (n - 1 - b) <= wait_bars),
    }


def gates(s: dict) -> dict:
    """Три гейта из OOS-сборки. `passed` — все три вместе (так и мерилось)."""
    g = {
        "vol_band": VOL_LO <= s["vratio"] < VOL_HI,   # коридор, НЕ «чем больше тем лучше»
        "with_trend": bool(s["with_trend"]),
        "high_regime": s["regime"] >= REGIME_MIN,
    }
    g["passed"] = all(g.values())
    return g


def score(s: dict) -> float:
    """Непрерывный скор — ТОЛЬКО как наблюдаемая метрика в журнале.

    🔴 ДЛЯ РАЗМЕРА ПОЗИЦИИ НЕ ПРИМЕНЯТЬ. Заявленная монотонность по квинтилям
    (0.95/0.89/0.92/1.04/1.25) при перемере на 250 монетах не подтвердилась:
    0.89 / 0.96 / 1.32 / 1.31 — верхние две ступени неразличимы, а самая массовая
    корзина (14 474 сделки, скор 1.0–1.7) убыточна. Пишем в журнал, чтобы набрать
    боевую статистику и перепроверить на своих данных.
    """
    v = s["vratio"]
    vol_part = 1.0 - min(abs(v - (VOL_LO + VOL_HI) / 2) / ((VOL_HI - VOL_LO) / 2), 1.0)
    return (vol_part
            + (1.0 if s["with_trend"] else 0.0)
            + min(max((s["regime"] - 1.0) / 0.5, 0.0), 1.0))


def size_mult(sc: float) -> float:
    """Ступени размера по скору: 0.5x / 1x / 1.5x / 2x. 🔴 См. предупреждение в score():
    ступени НЕ подтверждены перемером, значение пишется в журнал и не меняет риск."""
    if sc < 1.0:
        return 0.5
    if sc < 1.7:
        return 1.0
    if sc < 2.3:
        return 1.5
    return 2.0


def impulse_points(H, L, C, a: int, b: int, up: bool,
                   amp_mode: str = "close") -> tuple[float, float, float]:
    """
    Концы хода и его амплитуда — ЕДИНЫЙ источник для механики и отрисовки.

    Раньше каждый потребитель брал `C[a]`/`C[b]` сам, и «где начался импульс»
    определялось в трёх местах независимо. Отсюда же расхождение картинки с
    данными: линия шла по закрытиям и не доставала до экстремумов хода.

    amp_mode="close"    — исторически: от close к close (тени не в ходе);
    amp_mode="extremes" — от экстремума к экстремуму, как видит глаз.
    """
    if amp_mode == "extremes":
        p_a = float(L[a]) if up else float(H[a])
        p_b = float(H[b]) if up else float(L[b])
    else:
        p_a, p_b = float(C[a]), float(C[b])
    return p_a, p_b, abs(p_b - p_a)
