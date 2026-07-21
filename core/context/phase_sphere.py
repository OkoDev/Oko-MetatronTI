# -*- coding: utf-8 -*-
"""core.context.phase_sphere — СФЕРА ФАЗЫ / Decision Core (Сфера 13, 21.07).

Егор: «Куб = аналитика, не решает в какой ФАЗЕ рынок и что торговать». Эта сфера собирает
ДОКАЗАННЫЕ разделители в ВЕРДИКТ фазы → шина становится «мозгом» (Сфера 9 гейтит по фазе).

Консилиум (bot-arch + рой 6, DISCUSSION 21.07): НЕ Вайкофф с нуля (навязывает теорию,
ADX-режим доказанно крудо), а КОМПОЗИТ проверенных сепараторов + метод Егора. Ноль новых
детекторов — reuse: structure_trend/reversal_state (ote_matrix, метод Егора), квадрант-поток
(radar_state, ЕДИНСТВЕННЫЙ чистый Δ1.13%), USDT.D risk, funding-толпа.

🔴 ЭТАП SHADOW: диагностирует и ЛОГИРУЕТ (не гейтит). Пороги СТАРТОВЫЕ — калибруются сверкой
с ГЛАЗОМ Егора 2-3 недели (TG «согласен/нет»). Чистые функции без IO — вход подаёт вызывающий.

Два уровня: МАКРО (весь рынок → разрешение+veto стороны) · ПЕР-ПАРА (сторона+класс+фит).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# ── Пороги (СТАРТОВЫЕ, tune по shadow-сверке) ──────────────────────────────────
_PRECURSOR_PDN_OIUP = 25.0     # % пар PDN+OIUP → шорты грузятся на дне (reversal_watch)
_PRECURSOR_FUNDING = -0.005    # медиана funding % → шорты платят = топливо сквиза вверх
_EDGE_NEAR_EXTREME = 0.70      # pos≥edge = цена у экстремума большой ноги (зона разворота)
_MIDDLE_LO, _MIDDLE_HI = 0.30, 0.70   # pos в середине ноги = зона продолжения


@dataclass(frozen=True)
class MacroPhase:
    phase: str                 # MARKUP_UP | MARKUP_DOWN | SQUEEZE_UP | NEUTRAL
    bias: Optional[str]        # LONG | SHORT | None — разрешённая сторона входов
    veto: Optional[str]        # какую сторону continuation ВЕТИРУЕМ (против фазы)
    confidence: float          # 0..1 (доля согласных сигналов)
    detail: str


@dataclass(frozen=True)
class PairPhase:
    phase: str                 # REVERSAL | CONTINUATION | CHOP
    side: Optional[str]        # LONG | SHORT | None
    strategy_class: Optional[str]   # reversal (method_egor/ote) | trend (atr_s2/cont) | None
    concordance: Optional[bool]     # квадрант по потоку стороны? None=нет данных (деградация)
    confidence: float
    detail: str


def diagnose_macro(pct_pdn_oiup: Optional[float], median_funding_pct: Optional[float],
                   btc_trend: Optional[str], usdtd_risk_off: Optional[bool]) -> MacroPhase:
    """МАКРО-фаза из market-wide агрегатов (reuse _reversal_watch-сигналы + USDT.D).

    Задаёт РАЗРЕШЕНИЕ стороны + veto continuation. Деградирует gracefully (None-входы = меньше
    уверенности, не падение). Логика консилиума:
      прекурсоры накопления ≥2/3 → SQUEEZE_UP (готовим LONG-разворот, SHORT-cont вето)
      risk_off & BTC↓            → MARKUP_DOWN (SHORT ок, LONG-cont вето)
      risk_on & BTC↑             → MARKUP_UP   (LONG ок, SHORT-cont вето)
      иначе                      → NEUTRAL     (стоять/сокращать)
    """
    # прекурсоры бычьего разворота (reversal_watch, 2 из 3)
    prec = [
        pct_pdn_oiup is not None and pct_pdn_oiup >= _PRECURSOR_PDN_OIUP,
        median_funding_pct is not None and median_funding_pct <= _PRECURSOR_FUNDING,
        btc_trend == "long",
    ]
    n_prec = sum(prec)
    if n_prec >= 2:
        return MacroPhase("SQUEEZE_UP", "LONG", "SHORT", min(1.0, n_prec / 3 + 0.2),
                          f"прекурсоры накопления {n_prec}/3 → готовим LONG-разворот")
    if usdtd_risk_off is True and btc_trend == "short":
        return MacroPhase("MARKUP_DOWN", "SHORT", "LONG", 0.8,
                          "risk_off + BTC↓ → разгрузка, SHORT по тренду")
    if usdtd_risk_off is False and btc_trend == "long":
        return MacroPhase("MARKUP_UP", "LONG", "SHORT", 0.8,
                          "risk_on + BTC↑ → разметка, LONG по тренду")
    return MacroPhase("NEUTRAL", None, None, 0.4,
                      f"нет чистой фазы (risk_off={usdtd_risk_off}, BTC={btc_trend}, прек={n_prec}/3) → стоять")


def _pos_in_leg(px: float, origin: Optional[float], extreme: Optional[float]) -> Optional[float]:
    """Позиция цены в большой ноге origin→extreme (0=у origin, 1=у extreme). Метод Егора:
    'где цена в БОЛЬШОМ движении'. None если ноги нет."""
    if not (origin and extreme) or origin == extreme or px <= 0:
        return None
    p = (px - origin) / (extreme - origin)
    return max(0.0, min(1.0, p))


def _quadrant_concordant(quadrant: Optional[str], side: str) -> Optional[bool]:
    """Квадрант по потоку стороны? SHORT конкордантен PDN (цена вниз), LONG — PUP.
    PFL (флэт цены) или нет данных → None (деградация, НЕ блок)."""
    if not quadrant or quadrant.startswith("PFL"):
        return None
    pq = quadrant.split("+")[0]
    if pq == "PUP":
        return side == "LONG"
    if pq == "PDN":
        return side == "SHORT"
    return None


def diagnose_pair(struct: dict, rev: dict, quadrant: Optional[str], funding: Optional[float],
                  px: float) -> PairPhase:
    """ПЕР-ПАРА фаза из structure_trend (метод Егора: позиция в большой ноге) + reversal_state
    (переворот младший→старший) + квадрант (поток) + funding (толпа).

    REVERSAL: цена у экстремума большой ноги (pos≥edge) + переворот начался (reversing) →
              сторона ПРОТИВ HTF-тренда, класс method_egor/ote (разворот у экстремума).
    CONTINUATION: цена в середине ноги + квадрант конкордантен тренду → сторона ПО тренду,
              класс trend/atr_s2.
    CHOP: нет тренда / конфликт / квадрант флэт → стоять.
    """
    trend = struct.get("trend")           # 'long'/'short'/None — направление большой ноги
    origin = struct.get("impulse_origin")
    extreme = struct.get("extreme")
    pos = _pos_in_leg(px, origin, extreme)
    reversing = bool(rev.get("reversing"))
    progress = int(rev.get("progress") or 0)

    if trend is None or pos is None:
        return PairPhase("CHOP", None, None, None, 0.3, "нет чистой большой ноги (структура боковик)")

    htf_side = "SHORT" if trend == "short" else "LONG"
    against = "LONG" if htf_side == "SHORT" else "SHORT"

    # REVERSAL: у экстремума + переворот пошёл (метод Егора — разворот у вершины/дна большой ноги)
    if pos >= _EDGE_NEAR_EXTREME and reversing and progress >= 1:
        conc = _quadrant_concordant(quadrant, against)
        conf = min(1.0, 0.4 + 0.15 * progress + (0.2 if conc else 0))
        return PairPhase("REVERSAL", against, "reversal", conc, conf,
                         f"pos={pos:.2f} у экстремума {trend}-ноги + переворот прогресс={progress} → {against}")

    # CONTINUATION: середина ноги + поток по тренду
    if _MIDDLE_LO <= pos <= _MIDDLE_HI:
        conc = _quadrant_concordant(quadrant, htf_side)
        if conc:   # только ЕСЛИ квадрант подтверждает поток по тренду (доказанный рычаг)
            return PairPhase("CONTINUATION", htf_side, "trend", True,
                             min(1.0, 0.5 + 0.2), f"pos={pos:.2f} середина {trend}-ноги + поток по тренду → {htf_side}")
        return PairPhase("CHOP", None, None, conc, 0.35,
                         f"pos={pos:.2f} середина ноги, но поток НЕ по тренду ({quadrant}) → стоять")

    # прочее (у origin / поздняя нога без переворота) — неясно
    return PairPhase("CHOP", None, None, _quadrant_concordant(quadrant, htf_side), 0.35,
                     f"pos={pos:.2f} {trend}-нога, нет чёткого REVERSAL/CONT → стоять")


def phase_fit(signal_direction: str, macro: MacroPhase, pair: PairPhase) -> tuple[bool, str]:
    """ГЕЙТ-СУДЬЯ (SHADOW): вписывается ли сигнал в фазу. Возвращает (fit, причина).
    НЕ блокирует пока (features_json snapshot) — форвард сверит fit vs conflict net%.
      fit = сторона сигнала == сторона пары И не под макро-veto И (концорданс не False).
    """
    sd = (signal_direction or "").upper()
    if pair.phase == "CHOP":
        return False, "пара в CHOP (стоять)"
    if pair.side and sd != pair.side:
        return False, f"сторона {sd} против фазы пары {pair.side}"
    if macro.veto and sd == macro.veto and pair.phase == "CONTINUATION":
        return False, f"continuation {sd} под макро-veto ({macro.phase})"
    if pair.concordance is False:
        return False, "против потока квадранта"
    return True, f"fit: {sd} в {pair.phase}/{macro.phase}"
