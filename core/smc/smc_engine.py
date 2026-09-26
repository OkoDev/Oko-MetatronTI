"""ARCH-128 — SMC Engine: единый калькулятор SMC для бота, матрицы и терминала.

Слои: ZigZag · structure HH/HL/LH/LL · BOS/CHoCH (защищённые уровни) · Order Blocks
(+mitigation) · Premium/Discount · OTE (0.5-0.79) · EQH/EQL · FVG (+overlap) ·
Эллиотт (5-волн +extension, мульти-масштаб).

С 26.09.2026 опорные точки, сломы, блоки, равные уровни, разрывы и зоны диапазона считает
структурное ядро `core/structure` (docs/STRUCTURE_KERNEL_SPEC.md); функции ниже сохраняют
прежние сигнатуры и форматы. Базис значимости свингов:
1. опорные точки окна length: старший масштаб (major, len=50) и младший (minor, len=5).
2. ZigZag с ATR-deviation: разворот ≥ k×ATR% (dev=3, depth=11). Отсекает шум.

ЕДИНЫЙ КАЛЬКУЛЯТОР (ARCH-118): combinator/features_json/сферы Bus вызывают ЭТОТ модуль,
не дублируют формулы. Источник: memory/reference_oko_sm_indicator.md, docs/PRICE_PATTERNS_LIBRARY.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal, Optional

import numpy as np
import pandas as pd

from core.structure import (LevelBreak, confirmed_pivots, equal_levels, fair_value_gaps, label_swings,
                            level_breaks, order_blocks, range_zones, two_sided_pivots)
from core.structure.levels import column


@dataclass(frozen=True)
class Swing:
    idx: int          # позиция бара (iloc) подтверждённого свинга
    ts: object         # timestamp (index value)
    price: float
    kind: Literal["H", "L"]
    level: Literal["major", "minor"]


def confirmed_swings(df: pd.DataFrame, length: int) -> List[tuple]:
    """Опорные точки окна length (core.structure.confirmed_pivots). Возвращает [(idx, price, 'H'/'L')],
    idx — бар экстремума; точка известна на баре idx + length. Ряд короче 2·length+2 баров — пусто."""
    if len(df) < length * 2 + 2:
        return []
    return [(p.bar, p.price, "H" if p.is_high else "L")
            for p in confirmed_pivots(column(df, "high"), column(df, "low"), length)]


def detect_swings(
    df: pd.DataFrame,
    major_len: int = 50,
    minor_len: int = 5,
) -> List[Swing]:
    """Двухуровневые свинги. df: OHLC (DatetimeIndex желателен).

    major (len=50) — значимая структура (BOS/CHoCH, OTE-свинг слома).
    minor (len=5)  — внутренняя структура (точки входа).
    """
    d = df.copy()
    d.columns = [c.lower() for c in d.columns]
    res: List[Swing] = []
    for length, level in ((major_len, "major"), (minor_len, "minor")):
        for idx, price, kind in confirmed_swings(d, length):
            ts = d.index[idx] if idx < len(d.index) else idx
            res.append(Swing(idx=idx, ts=ts, price=price, kind=kind, level=level))  # type: ignore
    res.sort(key=lambda s: s.idx)
    return res


@dataclass(frozen=True)
class StructureBreak:
    ts: object            # бар пробоя
    idx: int              # бар пробоя (iloc)
    price: float          # пробитый уровень (swing)
    kind: Literal["BOS", "CHoCH"]
    direction: Literal["bull", "bear"]
    has_volume: bool      # объём на пробое выше среднего (критерий настоящего слома)
    from_idx: int = -1    # бар свинга-уровня (откуда тянуть линию до пробоя)


def detect_structure_breaks(
    df: pd.DataFrame,
    length: int = 50,
    vol_len: int = 20,
    vol_mult: float = 1.2,
) -> List[StructureBreak]:
    """BOS/CHoCH одного масштаба + критерий пользователя: пробой + ОБЪЁМ + закрепление.

    Слом — закрытие за последней опорной точкой окна length (core.structure.level_breaks):
      BOS   = пробой ПО тренду (продолжение)
      CHoCH = первый пробой ПРОТИВ тренда (смена характера)
    Закрепление = пробой по CLOSE (тело, не фитиль) + объём на баре пробоя выше среднего
    за vol_len баров × vol_mult (has_volume=True). from_idx — бар опорной точки уровня.
    """
    idx = df.index
    return [StructureBreak(idx[b.bar], b.bar, b.level, b.kind, "bull" if b.bullish else "bear",  # type: ignore
                           b.heavy_volume, b.level_bar)
            for b in level_breaks(df, window=length, vol_len=vol_len, vol_mult=vol_mult)]


@dataclass(frozen=True)
class OrderBlock:
    left_idx: int         # бар OB-свечи (левый край бокса)
    top: float
    bottom: float
    kind: Literal["bull", "bear"]
    break_idx: int        # бар слома, при котором OB сформирован
    mitigated_idx: int = -1   # бар пробоя OB (close за боксом) → невалиден; -1 = активен
    is_breaker: bool = False  # пробитый OB сменил роль (breaker block)


def detect_order_blocks(
    df: pd.DataFrame,
    breaks: List["StructureBreak"],
    atr_len: int = 200,
) -> List[OrderBlock]:
    """Order Blocks (core.structure.order_blocks): при сломе структуры — крайняя «спокойная»
    свеча (размах < 2×ATR Уайлдера) на отрезке [опорная точка..пробой].

    bull-слом → bullish OB = свеча с самым низким low (поддержка, институционал покупал).
    bear-слом → bearish OB = свеча с самым высоким high (сопротивление).
    OB-бокс = (high, low) той свечи; mitigated_idx — первое закрытие за дальней границей.

    🔴 ПРИЧИННОСТЬ ПОЛЕЙ (важно при использовании в признаках):
      · `left_idx`, `break_idx` — ПРИЧИННЫ (лаг 0): блок известен на баре слома;
      · `mitigated_idx`, `is_breaker` — СМОТРЯТ ВПЕРЁД по построению. Их можно
        использовать ТОЛЬКО как границу «блок жив до N», но НЕЛЬЗЯ как признак
        на баре ≤ N: на баре 100 мы не знаем, что блок пробьют на баре 300.
      · `active_order_blocks(obs, ...)` — функция ОТРИСОВКИ, а не истории: отдаёт
        блоки, живые на ПОСЛЕДНЕМ баре ряда, по `per_side` с каждой стороны
        (её `n_bars` в теле не используется). Для чарта верно, для признаков —
        нет: 04.09 выяснилось, что в конвейере матрицы она обрезала OB до 10 баров
        на всю историю (теряя 70% митигированных блоков), и признак был почти
        всегда False — неотличимо от «эджа нет».

    🧱 BREAKER BLOCK (20.08.2026): пробитый OB МЕНЯЕТ РОЛЬ — бывшая поддержка становится
    сопротивлением и наоборот, с бара mitigated_idx. Замер 20.08: breaker — лучший
    ОДИНОЧНЫЙ фактор конфлюэнции по OOS (1.80).
    """
    level = [LevelBreak(b.idx, b.direction == "bull", getattr(b, "kind", "BOS") == "CHoCH",
                        getattr(b, "price", float("nan")), b.from_idx, bool(getattr(b, "has_volume", False)))
             for b in breaks]
    return [OrderBlock(z.origin_bar, z.top, z.bottom, "bull" if z.bullish else "bear",  # type: ignore
                       z.break_bar, z.gone_bar, is_breaker=z.flipped)
            for z in order_blocks(df, level, atr_len=atr_len)]


def active_breakers(obs: List[OrderBlock], at_bar: int) -> List[OrderBlock]:
    """Breaker-блоки, активные НА БАРЕ at_bar (каузально).

    Breaker = OB, пробитый до этого бара. Его торговая сторона ОБРАТНА исходной:
    пробитый bull-OB (поддержка не удержала) работает как сопротивление, и наоборот.
    Возвращает те, что уже сломаны (mitigated_idx <= at_bar), в хронологии.
    """
    return sorted(
        [o for o in obs if o.mitigated_idx != -1 and o.mitigated_idx <= at_bar],
        key=lambda o: o.mitigated_idx,
    )


def breaker_side(ob: "OrderBlock") -> str:
    """Сторона, с которой breaker работает после смены роли: bull-OB → 'bear' и наоборот."""
    return "bear" if ob.kind == "bull" else "bull"


def active_order_blocks(obs: List[OrderBlock], n_bars: int, per_side: int = 5) -> List[OrderBlock]:
    """Только ВАЛИДНЫЕ OB к концу данных (непробитые), последние per_side каждого типа.

    Пробитый OB в отрисовку не попадает (mitigated_idx != -1 и < n_bars). Показываем
    активные (mitigated_idx == -1) — последние per_side bull + per_side bear.
    """
    active = [o for o in obs if o.mitigated_idx == -1]
    bull = [o for o in active if o.kind == "bull"][-per_side:]
    bear = [o for o in active if o.kind == "bear"][-per_side:]
    return sorted(bull + bear, key=lambda o: o.left_idx)


def classify_structure(df: pd.DataFrame, length: int = 50) -> List[tuple]:
    """Структура HH/HL/LH/LL по опорным точкам окна length (core.structure.label_swings).

    Классификация по предыдущей точке того же вида:
      вершина: HH если > пред. вершины, иначе LH
      впадина: LL если < пред. впадины, иначе HL
    Возвращает [(ts, price, label)] где label ∈ {HH,HL,LH,LL}. Отдельный слой
    от ZigZag (структурные точки, не волновая линия).
    """
    n = len(df.index)
    return [(df.index[idx] if idx < n else idx, float(price), label)
            for idx, price, label in label_swings(df, length)]


def premium_discount(top: float, btm: float) -> dict:
    """Premium/Discount/Equilibrium — полосы диапазона (core.structure.range_zones).

    top = верх ноги, btm = низ ноги. Связь с Фибо:
      equilibrium ≈ 0.5; discount = нижняя зона (где OTE-LONG 0.705-0.786);
      premium = верхняя (где OTE-SHORT). Грубая рамка «где торговать»:
      покупать в discount, продавать в premium.
    """
    z = range_zones(top, btm)
    return {"premium": z["upper"], "equilibrium": z["middle"], "discount": z["lower"], "eq_mid": z["mid"]}


def build_ote(swing_a: float, swing_b: float) -> dict:
    """OTE/Fib-сетка отката (как разметка пользователя на XLM). 🔴 КАНОН ПРОЕКТА (Егор 02.06, «все на канон!» 19.09).

    Ориентация — стандартный retracement: 0 = swing_a = КОНЕЦ импульса, 1 = swing_b = его НАЧАЛО; f = доля
    отката от конца к началу (0.5 — половина, 0.79 — глубокий). Вызовы в проекте: build_ote(high, low) → откат
    вниз восходящего импульса low→high → LONG в зоне у low; build_ote(low, high) → SHORT у high.
    (До 19.09 docstring называл swing_a «началом» — это путало: математика всегда была стандартной.)
    Пример пользователя (импульс low 0.21478 → high 0.22528, фибо от high вниз):
      0.382=0.22127, 0.5=0.22003, 0.618=0.21879, 0.705=0.21787, 0.786=0.21702.

    Зона входа = OTE_TOP–OTE_BOTTOM (0.5–0.79, core.smc.fibonacci) с уровнями 0.62/0.705 внутри.
    direction по знаку: swing_a>swing_b → LONG (OTE снизу), swing_a<swing_b → SHORT.
    Возвращает {'levels': {fib: price}, 'ote': (low, high), 'direction': 'long'/'short'}.
    """
    rng = swing_b - swing_a
    # Набор уровней пользователя (TradingView OTE): 0.5/0.62/0.705/0.79.
    # Отрицательные = фибо-РАСШИРЕНИЕ за конец импульса (measured move = цели волны 3/5):
    # -0.62/-1.0(100%)/-1.618(вола3 гайд)/-2.618 — лестница целей метода Егора (тот же расчёт).
    fibs = [-2.618, -1.618, -1.0, -0.62, 0.0, 0.382, 0.5, 0.62, 0.705, 0.79, 1.0]
    levels = {f: swing_a + f * rng for f in fibs}
    # Зона входа = 0.5-0.79 (уточнение пользователя 02.06: вход в диапазоне discount/premium,
    # не только глубокий 0.705-0.79; 0.705/0.79 — наиболее вероятные точки отскока внутри).
    # 19.09 «все на канон!»: границы берутся из core.smc.fibonacci (OTE_TOP/OTE_BOTTOM) — это ЭТАЛОН проекта.
    from core.smc.fibonacci import OTE_TOP, OTE_BOTTOM
    o1, o2 = levels[OTE_TOP], levels[OTE_BOTTOM]
    ote = (min(o1, o2), max(o1, o2))
    direction = "long" if swing_a > swing_b else "short"   # импульс вниз → ждём LONG из OTE
    return {"levels": levels, "ote": ote, "direction": direction}


def find_choch_ote(
    breaks: List["StructureBreak"],
    df_for_swings: Optional["pd.DataFrame"] = None,
    swing_len: int = 20,
    swings: Optional[List[tuple]] = None,
) -> Optional[dict]:
    """OTE на ЗНАЧИМОМ импульсе, что ВЫЗВАЛ последний CHoCH (механика пользователя).

    bull-CHoCH: импульс ВВЕРХ (последний swing low → swing high, что пробил структуру)
        → OTE near low → LONG (ждём откат вниз в OTE для покупки).
    bear-CHoCH: импульс ВНИЗ (swing high → swing low) → OTE near high → SHORT.
    Импульс = «первый левый от низа до верха» (значимая нога, не последняя мелкая).
    0=КОНЕЦ импульса, 1=НАЧАЛО. Торговля вероятностей — цена может НЕ зайти в OTE.

    `swings` — необязательный УЖЕ ПОСЧИТАННЫЙ список [(idx, price, 'H'/'L')].
    Нужен вызывающим, которые строят OTE для каждого CHoCH по очереди (rolling):
    без него пересчёт swings на каждом префиксе даёт O(k·n). Формула одна и та же —
    различие вынесено в параметр (ARCH-118 «один калькулятор», reuse ≠ дублирование).
    """
    chochs = [b for b in breaks if b.kind == "CHoCH"]
    if not chochs:
        return None
    b = chochs[-1]
    # ЗНАЧИМЫЙ импульс, что вызвал CHoCH: структурные swing-точки ДО слома.
    if swings is not None:
        sw = swings
    else:
        sw = confirmed_swings(df_for_swings, swing_len) if (df_for_swings is not None) else []
    pts = [(i, p, k) for i, p, k in sw if df_for_swings.index[i] <= b.ts]
    if len(pts) < 2:
        return None
    highs = [(i, p) for i, p, k in pts if k == "H"]
    lows = [(i, p) for i, p, k in pts if k == "L"]
    low_arr = df_for_swings["low"].values
    high_arr = df_for_swings["high"].values
    if b.direction == "bull":
        # bull-CHoCH: импульс = ПОСЛЕДНЯЯ восходящая волна (дно→вершина).
        # вершина = последний swing high перед сломом; дно = минимум low от предыдущей
        # вершины до этой (самый глубокий LL, с которого начался рост — «от низа до верха»).
        if not highs:
            return None
        hi, hp = highs[-1]
        prev_hi = highs[-2][0] if len(highs) >= 2 else 0
        seg_lows = low_arr[prev_hi:hi + 1]
        if len(seg_lows) == 0:
            return None
        rel = int(seg_lows.argmin()); li = prev_hi + rel; lp = float(low_arr[li])
        ote = build_ote(hp, lp)               # 0=high(конец), 1=low(начало) → long, OTE near low
        ote["from"], ote["to"] = (df_for_swings.index[li], lp), (df_for_swings.index[hi], hp)
    else:
        # bear-CHoCH: импульс = последняя нисходящая волна (вершина→дно).
        if not lows:
            return None
        li, lp = lows[-1]
        prev_lo = lows[-2][0] if len(lows) >= 2 else 0
        seg_highs = high_arr[prev_lo:li + 1]
        if len(seg_highs) == 0:
            return None
        rel = int(seg_highs.argmax()); hi = prev_lo + rel; hp = float(high_arr[hi])
        ote = build_ote(lp, hp)               # 0=low(конец), 1=high(начало) → short, OTE near high
        ote["from"], ote["to"] = (df_for_swings.index[hi], hp), (df_for_swings.index[li], lp)
    ote["choch"] = b
    return ote


def _pivots(df: "pd.DataFrame", length: int, is_high: bool) -> List[tuple]:
    """Pivot-точки (строгий left, нестрогий right — анти-дубль плато, как zigzag_atr).

    Кандидат на баре c — экстремум окна [c-length .. c+length]. Возвращает [(idx, price)].
    Используется для EQH/EQL (eq_len=3) и любой fixed-pivot разметки (core.structure.two_sided_pivots).
    """
    return two_sided_pivots(column(df, "high" if is_high else "low"), length, highs=is_high)


def detect_equal_levels(
    df: "pd.DataFrame",
    eq_len: int = 3,
    threshold: float = 0.1,
    atr_len: int = 200,
) -> List[tuple]:
    """EQH/EQL — равные хаи/лоу = зоны ликвидности (скопления стопов), core.structure.equal_levels.

    Две СОСЕДНИЕ опорные точки (окно eq_len с обеих сторон) одного вида «равны», если
    |Δцены| < threshold×ATR Уайлдера(atr_len) на второй точке.
    EQH = равные вершины (ликвидность сверху, цель для свипа вверх); EQL = равные донья.
    Возвращает [(ts1, p1, ts2, p2, 'EQH'/'EQL')] — пары уровней.
    """
    idx = df.index
    return [(idx[p.first_bar], p.first_price, idx[p.second_bar], p.second_price, "EQH" if p.highs else "EQL")
            for p in equal_levels(df, window=eq_len, tolerance=threshold, atr_len=atr_len)]


@dataclass(frozen=True)
class SponsoredCandle:
    ts: object               # бар SC
    idx: int                 # iloc
    top: float               # верх box (bull: max(o,c); bear: high-фитиль)
    bottom: float            # низ box (bull: low-фитиль; bear: min(o,c))
    direction: Literal["bull", "bear"]
    mt: float                # Mean Threshold = 0.5 box (крупный капитал тестит середину)
    open_level: float        # уровень открытия SC (первичная поддержка/сопротивление)
    swept: float             # пробитый экстремум (снятая ликвидность)
    broke_structure: bool    # критерий 2: импульс после = BOS (обновил экстремум)
    has_imbalance: bool      # критерий 3: FVG сразу после
    confirmed: bool          # ИСТИННЫЙ SC = свип+разворот + BOS + FVG (все 3 критерия)


def detect_sponsored_candle(
    df: "pd.DataFrame",
    lookback: int = 10,
    atr_len: int = 14,
    min_body_atr: float = 0.5,
    min_wick_frac: float = 0.3,
    confirm_bars: int = 5,
) -> List[SponsoredCandle]:
    """SC (Sponsored Candle) — свеча, СНИМАЮЩАЯ ликвидность + РАЗВОРОТ (эталон пользователя/ICT).

    Свеча-кандидат (2 условия):
      1. Снятие ликвидности: фитиль обновляет пред. экстремум (lookback), снимая стопы.
      2. Импульс-разворот: close против фитиля.
    ИСТИННЫЙ SC (confirmed) — + ещё 2 критерия (как у истинного OB):
      3. Ломает структуру: импульс после = CHoCH (для разворотной SC слом ПРОТИВ тренда =
         смена характера, НЕ BOS; пробивает противотрендовый защитный экстремум).
      4. Оставляет имбаланс: FVG сразу после свечи.

    Разметка box:
      • Bull SC (свип МИНИМУМА → вверх): top=max(o,c) [тело], bottom=low [фитиль].
      • Bear SC (свип МАКСИМУМА → вниз): top=high [фитиль], bottom=min(o,c) [тело].
    Уровни: MT (0.5 box), open_level. Поля broke_structure/has_imbalance/confirmed = критерии 3-4.
    """
    d = df.copy()
    d.columns = [c.lower() for c in d.columns]
    o, h, l, c = d["open"].values, d["high"].values, d["low"].values, d["close"].values
    n = len(d)
    tr = pd.concat([
        d["high"] - d["low"],
        (d["high"] - d["close"].shift()).abs(),
        (d["low"] - d["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / atr_len, adjust=False).mean().values

    def _confirm(i: int, bull: bool):
        """Критерии 3-4: CHoCH (слом ПРОТИВ тренда = смена характера) + FVG в окне после."""
        w_end = min(i + 1 + confirm_bars, n)
        if w_end <= i + 1:
            return False, False
        if bull:
            # bull SC свипнул МИНИМУМ (тренд был вниз) → пробой пред. HIGH вверх = CHoCH bull
            choch = h[i + 1:w_end].max() > h[i - lookback:i + 1].max()
        else:
            # bear SC свипнул МАКСИМУМ (тренд был вверх) → пробой пред. LOW вниз = CHoCH bear
            choch = l[i + 1:w_end].min() < l[i - lookback:i + 1].min()
        fvg = False                                                    # трёхсвечный имбаланс после
        for j in range(i + 1, min(i + confirm_bars, n - 1)):
            if bull and l[j + 1] > h[j - 1]:
                fvg = True; break
            if (not bull) and h[j + 1] < l[j - 1]:
                fvg = True; break
        return bool(choch), bool(fvg)

    out: List[SponsoredCandle] = []
    for i in range(lookback, n):
        if pd.isna(atr[i]) or atr[i] <= 0:
            continue
        body = abs(c[i] - o[i])
        if body < min_body_atr * atr[i]:
            continue
        prev_min = l[i - lookback:i].min()
        prev_max = h[i - lookback:i].max()
        lower_wick = min(o[i], c[i]) - l[i]
        upper_wick = h[i] - max(o[i], c[i])
        # Bull SC: фитиль снял МИНИМУМ + закрытие вверх
        if l[i] < prev_min and c[i] > o[i] and lower_wick > min_wick_frac * body:
            bos, fvg = _confirm(i, True)
            top = float(max(o[i], c[i])); bot = float(l[i])
            out.append(SponsoredCandle(d.index[i], i, top, bot, "bull",
                round((top + bot) / 2, 8), float(o[i]), float(prev_min), bos, fvg, bos and fvg))
        # Bear SC: фитиль снял МАКСИМУМ + закрытие вниз
        elif h[i] > prev_max and c[i] < o[i] and upper_wick > min_wick_frac * body:
            bos, fvg = _confirm(i, False)
            top = float(h[i]); bot = float(min(o[i], c[i]))
            out.append(SponsoredCandle(d.index[i], i, top, bot, "bear",
                round((top + bot) / 2, 8), float(o[i]), float(prev_max), bos, fvg, bos and fvg))
    return out


def detect_fvg(
    df: "pd.DataFrame",
    threshold: Optional[float] = None,
) -> List[tuple]:
    """FVG / Fair Value Gap — трёхсвечный имбаланс (незаполненный гэп), core.structure.fair_value_gaps.

    bull-FVG: low[i] > high[i-2] и close[i-1] > high[i-2] → гэп ВВЕРХ (бокс high[i-2]..low[i]).
    bear-FVG: high[i] < low[i-2] и close[i-1] < low[i-2] → гэп ВНИЗ (бокс high[i]..low[i-2]).
    Фильтр значимости: Δ% > threshold; threshold=None — причинный авто-порог: удвоенное
    расширяющееся среднее размера гэпа в % по барам ≤ i (гэп=0 где нет). Раньше (до 04.09)
    среднее бралось по ВСЕМУ ряду — look-ahead в бэктесте, менявший сам набор зон.
    mitigated = бар, где цена ЗАКРЫЛА гэп (close за дальней границей, не фитиль); None = активен.
    Возвращает [(ts_left, top, bottom, kind, ts_i, mitigated_ts_or_None)].
    Конфлюенция: FVG внутри OTE-зоны = усиление сигнала («+»).
    """
    idx = df.index
    return [(idx[g.left_bar], g.top, g.bottom, "bull" if g.bullish else "bear", idx[g.bar],
             idx[g.filled_bar] if g.filled_bar != -1 else None)
            for g in fair_value_gaps(df, threshold)]


def detect_fvg_overlap(
    df: "pd.DataFrame",
    threshold: Optional[float] = None,
    hold_bars: int = 5,
) -> List[dict]:
    """Перекрытие bull×bear FVG = ПОТЕНЦИАЛЬНЫЙ разворот (НЕ гарантия — наблюдать).

    bull-FVG перекрывает bear-FVG (bull сформирован ПОЗЖЕ, зоны пересекаются) → bull-импульс
    снял bear-сопротивление → возможный разворот ВВЕРХ. Bear часто уже mitigated (его и
    закрыл этот bull). Зеркально: bear перекрыл bull → разворот ВНИЗ.
    held = зона перекрытия удержалась (цена не закрылась за противоположной границей)
    на окне `hold_bars` баров после формирования — подтверждение, что разворот пока в силе.
    Правило пользователя 03.06: сигнал вероятностный, требует наблюдения за откатом,
    не вход «вслепую».

    🔴 `held` — утверждение о барах ПОСЛЕ `since`, поэтому оно становится известно только
    на баре `held_ts` = since + hold_bars. Потребитель обязан ставить флаг именно туда,
    иначе получает look-ahead на hold_bars. Возвращается в поле `held_ts`.

    Возвращает [dict(lo, hi, direction 'up'/'down', since, held, held_ts, bull, bear)].
    """
    fvgs = detect_fvg(df, threshold)
    close = df["close"].values
    n = len(df)
    pos = {ts: i for i, ts in enumerate(df.index)}
    def lohi(f):
        return min(f[1], f[2]), max(f[1], f[2])
    bulls = [f for f in fvgs if f[3] == "bull"]
    bears = [f for f in fvgs if f[3] == "bear"]
    out: List[dict] = []

    # 🔴 FIX 13.08.2026 (Егор «FVG чинить и приводить все к эталону») — ДВА look-ahead:
    #  (1) `for bu in bulls if f[5] is None` брал только FVG, НИ РАЗУ не митигированные
    #      за всю оставшуюся историю → survivorship: зона попадала в набор за то,
    #      что выживет в будущем.
    #  (2) `held = all(close[j] ... for j in range(i0+1, n))` проверял до КОНЦА данных →
    #      флаг на баре `since` утверждал, что цена НИКОГДА не уйдёт за границу зоны.
    # Цена ошибки: паттерны на `bull_fvg_overlap(_held)_15m` показывали WR 89–92%,
    # PF 49–71, +4.49%/сд — невозможные для рынка числа.
    # Стало: активность FVG проверяется НА МОМЕНТ бара обнаружения (митигация позже —
    # не наше знание), а `held` считается на КОНЕЧНОМ окне `hold_bars` и потому известен
    # на баре since+hold_bars (потребитель обязан ставить флаг именно туда).
    def _active_at(f, i_at: int) -> bool:
        """FVG не митигирован К БАРУ i_at (митигация в будущем — не наше знание)."""
        if f[5] is None:
            return True
        m = pos.get(f[5])
        return m is None or m > i_at

    for bu in bulls:
        bl, bh = lohi(bu)
        i0 = pos[bu[4]]
        if not _active_at(bu, i0):
            continue
        for be in bears:
            rl, rh = lohi(be)
            if bl <= rh and rl <= bh and bu[4] > be[4]:
                lo, hi = max(bl, rl), min(bh, rh)
                j1 = min(i0 + 1 + hold_bars, n)
                held = all(close[j] >= lo for j in range(i0 + 1, j1)) if i0 + 1 < j1 else True
                held_ts = df.index[min(i0 + hold_bars, n - 1)]
                out.append(dict(lo=lo, hi=hi, direction="up", since=bu[4], held=held,
                                held_ts=held_ts, bull=bu, bear=be))
    for be in bears:
        rl, rh = lohi(be)
        i0 = pos[be[4]]
        if not _active_at(be, i0):
            continue
        for bu in bulls:
            bl, bh = lohi(bu)
            if bl <= rh and rl <= bh and be[4] > bu[4]:
                lo, hi = max(bl, rl), min(bh, rh)
                j1 = min(i0 + 1 + hold_bars, n)
                held = all(close[j] <= hi for j in range(i0 + 1, j1)) if i0 + 1 < j1 else True
                held_ts = df.index[min(i0 + hold_bars, n - 1)]
                out.append(dict(lo=lo, hi=hi, direction="down", since=be[4], held=held,
                                held_ts=held_ts, bull=bu, bear=be))
    return out


def detect_elliott_impulse(zz: List[tuple]) -> List[dict]:
    """ARCH-128 — Эллиотт: 5-волновой импульс на ZigZag (1-3-5 импульсные, 2-4 коррекции).

    🔴🔴 ПЕРЕРИСОВКА — ОБЯЗАТЕЛЬНО К ПРОЧТЕНИЮ ПЕРЕД ЛЮБЫМ ЗАМЕРОМ.
    Функция работает поверх `zigzag_atr`, а зигзаг ПЕРЕРИСОВЫВАЕТ историю. Замер
    03.09.2026 (`scripts/impulse_decay_causal.py`, префиксный проход по 4 символам):
    из импульсов, ВИДИМЫХ в реальном времени, в финальной разметке остаётся лишь
    27–60% — HYPE теряет 40%, GRT 62%, SOL 73%, LINK 66%.

    Отсюда ДВЕ обязательные проверки причинности, не одна:
      1. ЛАГ ПОДТВЕРЖДЕНИЯ — префиксный аудит `детектор(df[:t])` против полного df.
         Замерен: ровно 6 баров, одинаково на всех символах (это ПАРАМЕТР детектора,
         не статистика — [[detector_lag_is_a_parameter_not_statistics]]).
      2. SURVIVORSHIP — торговать надо КАЖДЫЙ импульс в момент его первого появления,
         включая те, что позже исчезнут. Иначе замер идёт только по «выжившим», то
         есть по заведомо настоящим сигналам.

    Цена пропуска: тот же замер без обеих проверок дал PF **15.65**, с одной лагом —
    **5.47**, с обеими — **0.97**. Первые два числа были артефактом целиком.
    🔑 Практическое правило: PF > 5 на механике с базой ~0.8 — это сигнал ошибки
    теста, а не находка.

    Окно из 6 ZigZag-точек = 5 волн. Hard-правила Эллиотта (обязательные):
      R1. Волна 2 не откатывает ЗА начало волны 1.
      R2. Волна 3 НЕ самая короткая из (1,3,5).
      R3. Волна 4 не заходит в территорию волны 1 (не перекрывает её конец).
    bull-импульс (вверх): точки L,H,L,H,L,H; bear (вниз): H,L,H,L,H,L.
    Большая волновая фибо строится на всём импульсе (точка0 → точка5) → откат к OTE.
    Возвращает [dict(waves=[(ts,price)×6], direction, lens=(w1,w3,w5))]. Самый свежий — последний.
    """
    typed = _zz_typed(zz)
    out: List[dict] = []
    for i in range(len(typed) - 5):
        seg = typed[i:i + 6]
        kinds = [t for _, _, t in seg]
        ps = [p for _, p, _ in seg]
        ts = [t for t, _, _ in seg]
        p0, p1, p2, p3, p4, p5 = ps
        if kinds == ["L", "H", "L", "H", "L", "H"]:
            # bull: w2 выше старта (R1), w3 новый max + не перекрытие w1 (R3), w5 новый max
            if not (p1 > p0 and p2 > p0 and p3 > p1 and p4 > p1 and p5 > p3):
                continue
            l1, l3, l5 = p1 - p0, p3 - p2, p5 - p4
            direction = "up"
        elif kinds == ["H", "L", "H", "L", "H", "L"]:
            if not (p1 < p0 and p2 < p0 and p3 < p1 and p4 < p1 and p5 < p3):
                continue
            l1, l3, l5 = p0 - p1, p2 - p3, p4 - p5
            direction = "down"
        else:
            continue
        if l3 < l1 and l3 < l5:        # R2: волна 3 не самая короткая
            continue
        # EXTENSION волны 5: продлить до финального экстремума. Волна 5 часто расширяется
        # под-волнами (GRT 15m: 19:30 → откат 21:30 → новое дно 23:15). Тянем точку 5 до
        # последнего low(bear)/high(bull), пока цена не развернулась ЗА волну 4 (конец импульса).
        w5_ts, w5_p = ts[5], ps[5]
        k = i + 6
        while k < len(typed):
            kt, kp, kk = typed[k]
            if direction == "down":
                if kk == "H" and kp > p4:        # разворот вверх за волну 4 = импульс закончен
                    break
                if kk == "L" and kp < w5_p:       # новое дно — продлеваем волну 5
                    w5_ts, w5_p = kt, kp
            else:
                if kk == "L" and kp < p4:
                    break
                if kk == "H" and kp > w5_p:
                    w5_ts, w5_p = kt, kp
            k += 1
        l5 = abs(w5_p - p4)
        # Фибо-соотношения волн (docs/ENCYCLOPEDIA.md «Волновая теория Эллиотта»):
        #   w2 откат 0.618-0.786 волны 1 = классика (OTE SHORT/LONG); w4 откат ~0.382 волны 3;
        #   w3 расширение ≥1.618 волны 1 = сильный импульс. textbook = все три в норме.
        w2_retr = abs(p2 - p1) / l1 if l1 else 0.0
        w4_retr = abs(p4 - p3) / l3 if l3 else 0.0
        w3_ext = l3 / l1 if l1 else 0.0
        textbook = (0.5 <= w2_retr <= 0.886) and (0.236 <= w4_retr <= 0.618) and w3_ext >= 1.3
        waves = [(ts[k2], ps[k2]) for k2 in range(5)] + [(w5_ts, w5_p)]
        out.append(dict(waves=waves, direction=direction,
                        lens=(l1, l3, l5), w2_retr=round(w2_retr, 3), w4_retr=round(w4_retr, 3),
                        w3_ext=round(w3_ext, 3), textbook=textbook))
    return out


def detect_elliott_mtf(df: "pd.DataFrame", devs: tuple = (3.0, 5.0, 8.0)) -> List[dict]:
    """Эллиотт на НЕСКОЛЬКИХ масштабах ZigZag — волновой мульти-масштаб (фрактальность).

    Одно движение на мелком dev = под-волны (не проходит правила), на крупном = чистый
    импульс. Перебираем dev → собираем импульсы с пометкой scale. GRT 02.06: на 1m dev=3
    импульса нет (под-волны), на 15m — есть. Каждый импульс несёт 'scale'=dev (масштаб волны).
    Возвращает [dict(... + scale)], от мелкого масштаба к крупному.
    """
    res: List[dict] = []
    for dev in devs:
        zz = zigzag_atr(df, 11, float(dev))
        for imp in detect_elliott_impulse(zz):
            imp = dict(imp); imp["scale"] = dev
            res.append(imp)
    return res


def _zz_typed(zz: List[tuple]) -> List[tuple]:
    """ZigZag-точки с типом H/L (строгое чередование). [(ts, price, 'H'/'L')].

    ZigZag по построению чередует вершины/донья. Тип первой определяется сравнением
    со второй, дальше чередование. Нужен для структурного анализа (HH/HL/LH/LL, слом).
    """
    if not zz:
        return []
    if len(zz) == 1:
        return [(zz[0][0], zz[0][1], "H")]
    first_is_high = zz[0][1] > zz[1][1]
    out = []
    for k, (ts, p) in enumerate(zz):
        is_high = first_is_high == (k % 2 == 0)
        out.append((ts, p, "H" if is_high else "L"))
    return out


def find_setups_zz(zz: List[tuple], df: "pd.DataFrame") -> List[dict]:
    """ARCH-128 ЯДРО АВТОПОИСКА — сетапы на ZigZag-структуре (точные вершины опорные точки окна 50 пропускают).

    Перебирает ВСЕ значимые сломы (не «последний CHoCH»). Слом структуры на ZigZag:
      • новый zz-high > предыдущего zz-high → пробой хая вверх (bull).
          trend<0 (была нисходящая LL/LH) → CHoCH (смена характера); иначе BOS (продолжение).
      • новый zz-low < предыдущего zz-low → пробой лоу вниз (bear). Симметрично.
    ИМПУЛЬС СЛОМА (для фибо) = тот, что пробил структуру: от zz-экстремума-начала
    (low перед bull-сломом / high перед bear-сломом) до zz-вершины слома. На GRT 02.06:
    LL 19:33(0.02284) → H 19:53(0.02348) пробил LH 19:00(0.02342) = bull-CHoCH, OTE near low.

    Логика BOS/CHoCH/trend — общая SMC (защищённые уровни); источник свингов — ZigZag
    (точнее опорных точек окна 50).
    Возвращает [dict] (build_ote + from/to/kind/struct/choch_ts/broken_level), хронологически.
    """
    typed = _zz_typed(zz)
    if len(typed) < 3:
        return []
    setups: List[dict] = []
    trend = 0
    # ЗАЩИТНЫЕ структурные уровни (держатся, пока тренд жив — НЕ сосед):
    #   prot_high — пробой вверх = bull-слом; prot_low — пробой вниз = bear-слом.
    # cand_* — последний swing того же типа (кандидат: начало импульса слома + новый защитный).
    prot_high: Optional[tuple] = None   # (ts, price)
    prot_low: Optional[tuple] = None
    cand_high: Optional[tuple] = None
    cand_low: Optional[tuple] = None
    for ts, p, t in typed:
        if t == "H":
            if prot_high is not None and p > prot_high[1]:
                # пробой защитного high → bull-слом. CHoCH если был нисходящий тренд, иначе BOS.
                kind = "CHoCH" if trend < 0 else "BOS"
                if cand_low is not None:
                    lp, hp = cand_low[1], p
                    ote = build_ote(hp, lp)                 # 0=high(конец), 1=low(начало) → long, near low
                    ote["from"], ote["to"] = (cand_low[0], lp), (ts, hp)
                    ote.update(kind=kind, struct="bull", choch_ts=ts,
                               broken_level=prot_high[1], broken_ts=prot_high[0])
                    setups.append(ote)
                trend = 1
                prot_high = (ts, p)
                if cand_low is not None:
                    prot_low = cand_low      # защитный low поднят на HL подтверждённой структуры
            elif prot_high is None:
                prot_high = (ts, p)
            cand_high = (ts, p)
        else:
            if prot_low is not None and p < prot_low[1]:
                kind = "CHoCH" if trend > 0 else "BOS"
                if cand_high is not None:
                    hp, lp = cand_high[1], p
                    ote = build_ote(lp, hp)                 # 0=low(конец), 1=high(начало) → short, near high
                    ote["from"], ote["to"] = (cand_high[0], hp), (ts, lp)
                    ote.update(kind=kind, struct="bear", choch_ts=ts,
                               broken_level=prot_low[1], broken_ts=prot_low[0])
                    setups.append(ote)
                trend = -1
                prot_low = (ts, p)
                if cand_high is not None:
                    prot_high = cand_high
            elif prot_low is None:
                prot_low = (ts, p)
            cand_low = (ts, p)
    return setups


def adaptive_dev(df: "pd.DataFrame", depth: int = 11, target: int = 12) -> float:
    """Подбор dev_mult под ~target zz-точек (масштаб как ручная разметка Егора).
    Статичный dev не универсален (XLM=2, W=4) — адаптив даёт верный масштаб per-пара."""
    best_dev, best = 3.0, 10 ** 9
    for dv in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0):
        try:
            nn = len(zigzag_atr(df, depth, dv))
        except Exception:
            continue
        if abs(nn - target) < best:
            best, best_dev = abs(nn - target), dv
    return best_dev


def select_significant_impulse(df: "pd.DataFrame", zz: List[tuple],
                              current_price: Optional[float] = None,
                              prefer_recency: bool = False) -> Optional[dict]:
    """ЗНАЧИМЫЙ ЖИВОЙ импульс для OTE-контекста (ARCH-128, Егор 23.06) — заменяет наивный htf[-1].

    Метод (валидирован на стенде oko_context_locator, 6 пар + ТФ 1d→5m):
      1. EXTREME-нога: от значимого LOW к значимому HIGH (и наоборот) в ОКНЕ актуального
         тренда = от последнего ПРОТИВОПОЛОЖНОГО CHoCH-разворота. Берёт ПОЛНУЮ ногу тренда,
         а не дроблёный последний слом (find_setups_zz[-1] = корень провала OKO-OTE).
      2. ИНВАЛИДАЦИЯ: импульс МЁРТВ, если откат пробил 0.79 (= нарратив сменился).
      3. ВЫБОР: цена в OTE (готов) → цена в ноге отката (ждём) → крупнейший span.
    Возвращает setup dict (build_ote + from/to/direction/levels/kind) или None.

    prefer_recency (Егор 25.06): среди кандидатов выбирать САМЫЙ СВЕЖИЙ слом, не крупнейший
    span. Корень «мерцания зоны» (BTC 10.2025: span-приоритет брал старую апрель-майскую ногу
    вместо свежего октябрьского слома, когда цена выходила из OTE свежего). Свежий слом =
    триггер начала движения к магниту (инсайт Егора). default False = старое поведение (span)."""
    if df is None or len(df) < 10:
        return None
    setups = find_setups_zz(zz, df) or []
    pos = {ts: i for i, ts in enumerate(df.index)}
    cur = float(current_price if current_price is not None else df["close"].iloc[-1])
    hi = df["high"].values; lo = df["low"].values; n = len(df)
    # окно актуального тренда = от последнего ПРОТИВОПОЛОЖНОГО CHoCH-разворота (не фикс)
    chs = [(pos.get(s.get("choch_ts")), s["direction"]) for s in setups
           if s.get("kind") == "CHoCH" and pos.get(s.get("choch_ts")) is not None]
    if chs:
        li, ld = chs[-1]
        opp = [i for i, dd in chs if dd != ld and i < li]
        wmin = opp[-1] if opp else max(0, li - 400)
    else:
        wmin = max(0, n - 400)
    typed = _zz_typed(zz)
    P = [(pos.get(ts), p, k) for ts, p, k in typed
         if pos.get(ts) is not None and pos.get(ts) >= wmin]
    L = [(i, p) for i, p, k in P if k == "L"]; H = [(i, p) for i, p, k in P if k == "H"]

    def _mk(ai, ap, bi, bp):           # a=начало, b=конец ноги
        o = build_ote(bp, ap)          # 0=конец, 1=начало → long(bull)/short(bear) по знаку
        o["from"] = (df.index[ai], ap); o["to"] = (df.index[bi], bp)
        o["choch_ts"] = df.index[bi]; o["kind"] = "IMP"
        o["struct"] = "bull" if bp > ap else "bear"
        o["broken_level"] = None; o["broken_ts"] = None
        return o

    extras = []
    if L and H:
        ml = min(L, key=lambda x: x[1]); ha = [h for h in H if h[0] > ml[0]]
        if ha:
            mh = max(ha, key=lambda x: x[1]); extras.append(_mk(ml[0], ml[1], mh[0], mh[1]))
        mh2 = max(H, key=lambda x: x[1]); la = [l for l in L if l[0] > mh2[0]]
        if la:
            ml2 = min(la, key=lambda x: x[1]); extras.append(_mk(mh2[0], mh2[1], ml2[0], ml2[1]))

    now, leg = [], []
    for s in (extras + setups):
        lv = s["levels"]; olo, ohi = s["ote"]
        l079 = lv.get(0.79); ci = pos.get(s.get("choch_ts"))
        inv = False
        if l079 is not None and ci is not None:
            if s["direction"] == "short":
                seg = hi[ci + 1:]; inv = bool(len(seg)) and float(seg.max()) > l079
            else:
                seg = lo[ci + 1:]; inv = bool(len(seg)) and float(seg.min()) < l079
        if inv:
            continue
        l0 = lv.get(0.0); l1 = lv.get(1.0)
        span = abs(s["to"][1] - s["from"][1]) / s["from"][1] if s["from"][1] else 0.0
        # ключ выбора: prefer_recency → свежесть слома (pos choch) первична, span tie-break;
        # иначе старое поведение (span). ci уже = pos.get(choch_ts) выше.
        key = (ci if ci is not None else -1, span) if prefer_recency else (span,)
        if olo <= cur <= ohi:
            now.append((key, s))
        elif l0 is not None and l1 is not None and min(l0, l1) <= cur <= max(l0, l1):
            leg.append((key, s))
    if now:
        return max(now, key=lambda x: x[0])[1]
    if leg:
        return max(leg, key=lambda x: x[0])[1]
    return None


def append_provisional_leg(zz: List[tuple], df: "pd.DataFrame") -> tuple:
    """LIVE: дорисовывает ТЕКУЩУЮ формирующуюся ногу как НЕПОДТВЕРЖДЁННЫЙ pivot.

    Решает критичный лаг zigzag (zigzag_lag_live_critical): последняя нога подтверждается
    только через depth//2 баров (4h=20ч!), поэтому live-движок СЛЕП к свежему слому.
    Provisional = текущий rolling-экстремум после последней zz-точки = то, что трейдер
    рисует ГЛАЗОМ+рукой, не дожидаясь индикатора. Проверено XLM 1h: воспроизводит
    ручную SHORT-OTE пользователя до фибо (все 6 уровней совпали).

    Возвращает (zz_extended, provisional_ts | None). Если новой ноги нет — (zz, None).
    """
    if not zz:
        return zz, None
    typed = _zz_typed(zz)
    if not typed:
        return zz, None
    last_ts, last_p, last_t = typed[-1]
    pos = {ts: i for i, ts in enumerate(df.index)}
    li = pos.get(last_ts)
    if li is None or li >= len(df) - 1:
        return zz, None
    after = df.iloc[li + 1:]
    if last_t == "H":                                   # формируется LOW
        pi = li + 1 + int(after["low"].values.argmin()); pp = float(after["low"].min())
        if pp >= last_p:
            return zz, None                             # не ниже последней H → нет новой ноги
    else:                                               # формируется HIGH
        pi = li + 1 + int(after["high"].values.argmax()); pp = float(after["high"].max())
        if pp <= last_p:
            return zz, None
    prov_ts = df.index[pi]
    return list(zz) + [(prov_ts, pp)], prov_ts


def ote_retest_setups(
    df: "pd.DataFrame",
    *,
    dev_mult: float = 3.0,
    retest_bars: int = 60,
    only_choch: bool = True,
    depth: int = 11,
    provisional: bool = False,
) -> List[dict]:
    """ARCH-128 — OTE-Retest Engine (ядро): слом → импульс → OTE → РЕТЕСТ → вход+стоп+конфлюенция.

    Логика входа (метод пользователя):
      1. Значимый слом структуры (CHoCH) — `find_setups_zz`.
      2. Импульс слома → OTE-зона 0.5-0.79 (`build_ote`).
      3. РЕТЕСТ: первый бар ПОСЛЕ слома, где цена вернулась в OTE-зону (откат).
      4. КОНФЛЮЕНЦИЯ: OB/FVG той же стороны внутри OTE = усиление (+/++).
      5. ВХОД = середина OTE (0.645), СТОП за 1.0 (начало импульса) + буфер.
    direction: long (bull-CHoCH, OTE near low) / short (bear-CHoCH, near high).
    Возвращает [dict(choch_ts, entry_ts, entry, sl, risk, direction, ote, confluence, from, to)].
    TP не считается здесь — отдельный слой (магниты/фибо/пивоты).
    """
    zz = zigzag_atr(df, depth, dev_mult)
    prov_ts = None
    if provisional:
        zz, prov_ts = append_provisional_leg(zz, df)   # live: дорисовать текущую ногу
    setups = find_setups_zz(zz, df)
    breaks = detect_structure_breaks(df)
    obs = detect_order_blocks(df, breaks)
    fvgs = detect_fvg(df)
    pos = {ts: i for i, ts in enumerate(df.index)}
    low_a, high_a = df["low"].values, df["high"].values
    n = len(df)
    out: List[dict] = []

    for s in setups:
        if only_choch and s.get("kind") != "CHoCH":
            continue
        ote_lo, ote_hi = s["ote"]
        direction = s["direction"]            # long / short
        ci = pos.get(s["choch_ts"])
        if ci is None:
            continue
        # 3. РЕТЕСТ — первый бар после слома, коснувшийся OTE-зоны
        entry_i = None
        for j in range(ci + 1, min(ci + 1 + retest_bars, n)):
            if low_a[j] <= ote_hi and high_a[j] >= ote_lo:
                entry_i = j
                break
        if entry_i is None:
            continue
        entry = (ote_lo + ote_hi) / 2.0       # середина зоны (~0.645)
        # 4. КОНФЛЮЕНЦИЯ — OB/FVG той же стороны в OTE-зоне
        # 🔴 ФИКС ПРИЧИННОСТИ (19.08.2026): раньше конфлюэнция считалась по ВСЕЙ истории —
        # сетап на баре 100 получал усиление от FVG, образовавшегося на баре 500.
        # Это и был источник «35.4% сетапов не существуют причинно» (аудит лага флагов).
        # Теперь берём только то, что СУЩЕСТВОВАЛО на баре входа:
        #   OB  — сформирован (break_idx <= entry_i) и ещё не митигирован;
        #   FVG — обнаружен на баре f[4]=ts_i (контракт detect_fvg) не позже входа.
        want = "bull" if direction == "long" else "bear"
        confl = 0
        for ob in obs:
            if ob.kind != want or ob.break_idx > entry_i:
                continue
            if 0 <= ob.mitigated_idx <= entry_i:
                continue
            if min(ob.top, ob.bottom) <= ote_hi and max(ob.top, ob.bottom) >= ote_lo:
                confl += 1
        _entry_ts = df.index[entry_i]
        for fv in fvgs:
            if fv[3] != want:
                continue
            _seen = fv[4] if len(fv) > 4 else fv[0]     # ts_i — бар обнаружения гэпа
            if _seen is not None and _seen > _entry_ts:
                continue
            ftop, fbot = max(fv[1], fv[2]), min(fv[1], fv[2])
            if fbot <= ote_hi and ftop >= ote_lo:
                confl += 1
        # 5. СТОП за 1.0 (начало импульса = s['to'] для long(низ)? — точка 1.0 build_ote)
        one_level = s["levels"][1.0]          # 1.0 = начало импульса
        sl = one_level
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        out.append(dict(
            choch_ts=s["choch_ts"], entry_ts=df.index[entry_i], entry=round(entry, 8),
            sl=round(sl, 8), risk=round(risk, 8), direction=direction,
            ote=(ote_lo, ote_hi), confluence=confl, **{"from": s["from"], "to": s["to"]},
            unconfirmed=bool(prov_ts is not None and s["to"][0] == prov_ts),  # provisional нога
        ))
    return out


def last_swing_leg_ote(df: pd.DataFrame, length: int = 20) -> Optional[dict]:
    """OTE от последней ЗНАЧИМОЙ последовательной ноги структуры (привязка к swing H/L).

    Импульс = две последние СОСЕДНИЕ swing-точки (swings(length)) — реальная нога
    high→low или low→high, привязанная к экстремумам (не глобальный поиск, не мелкая
    ZigZag-нога). bull (нога вниз high→low) → OTE near low; bear (вверх) → near high.
    """
    sw = confirmed_swings(df, length)   # [(idx, price, 'H'/'L')] в порядке времени
    if len(sw) < 2:
        return None
    (ai, ap, ak), (ci, cp, ck) = sw[-2], sw[-1]   # последняя нога: ap=начало, cp=конец
    a_ts, c_ts = df.index[ai], df.index[ci]
    # Правило пользователя: 0 = КОНЕЦ импульса (cp), 1 = НАЧАЛО (ap). Откат к началу.
    #   нога low→high (импульс ВВЕРХ) → 0=high, 1=low → OTE near low → LONG (откат вниз)
    #   нога high→low (импульс ВНИЗ)  → 0=low, 1=high → OTE near high → SHORT (откат вверх)
    ote = build_ote(cp, ap)
    ote["from"], ote["to"] = (a_ts, ap), (c_ts, cp)   # наклонная: начало→конец (реальное направление)
    ote["leg"] = f"{ak}->{ck}"
    return ote


def last_impulse_ote(zz: List[tuple]) -> Optional[dict]:
    """Авто-OTE от последнего завершённого импульса ZigZag (нога high→low или low→high).

    zz = точки ZigZag [(ts, price)]. Берёт последнюю ногу (zz[-2]→zz[-1]) как импульс,
    строит OTE. direction='long' если нога вниз (откат вверх = LONG-сетап).
    Возвращает dict build_ote + {'from': (ts,price), 'to': (ts,price)} или None.
    """
    if not zz or len(zz) < 2:
        return None
    (a_ts, a), (b_ts, b) = zz[-2], zz[-1]
    res = build_ote(a, b)
    res["from"] = (a_ts, a)
    res["to"] = (b_ts, b)
    return res


def zigzag_atr(
    df: pd.DataFrame,
    depth: int = 11,
    dev_mult: float = 3.0,
    atr_len: int = 10,
) -> List[tuple]:
    """ZigZag «Waves» — порт OKO-SM Pine 1:1 (depth=11, dev=3 = настройки пользователя).

    Pine-точно:
      • pivot подтверждается ЧЕРЕЗ length=depth//2 баров (НЕ look-ahead): на баре i
        проверяется кандидат src[i-length] против окна [i-2length .. i] (только прошлое).
      • high-pivot имеет приоритет над low на одном баре (Pine: if iH else iL).
      • dev_thresh = atr(10)/close*100 × dev_mult (Wilder RMA, как ta.atr).
      • pivotFound: то же направление → продлить экстремум; разворот → новый свинг
        только если abs(calc_dev) > dev_thresh.
    Возвращает [(ts, price)] подтверждённых точек.
    """
    d = df.copy()
    d.columns = [c.lower() for c in d.columns]
    n = len(d)
    length = max(1, depth // 2)        # Pine: i_depth/2
    l2 = length * 2
    if n < l2 + atr_len + 2:
        return []
    high, low, close = d["high"].values, d["low"].values, d["close"].values
    # ATR Wilder RMA (как ta.atr): ewm alpha=1/period, adjust=False
    tr = pd.concat([
        d["high"] - d["low"],
        (d["high"] - d["close"].shift()).abs(),
        (d["low"] - d["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / atr_len, adjust=False).mean().values

    def pivot_at(i, hi):
        """Pine pivots(): кандидат = src[i-length], окно [i-l2 .. i] (прошлое). None если не pivot."""
        c_idx = i - length
        if c_idx < 0:
            return None
        c = high[c_idx] if hi else low[c_idx]
        for j in range(i - l2, i + 1):
            if j < 0 or j == c_idx:
                continue
            # Анти-дубль плато: слева СТРОГО (>=/<=  отменяет), справа нестрого (>/<).
            # На ровном плато проходит только ПЕРВЫЙ бар; если слева есть равный —
            # не пивот (убирает лишние zz-точки 18:06/18:36 GRT 02.06, сохраняя значимые).
            left = j < c_idx
            if hi:
                if left and high[j] >= c:
                    return None
                if not left and high[j] > c:
                    return None
            else:
                if left and low[j] <= c:
                    return None
                if not left and low[j] < c:
                    return None
        return c_idx, float(c)

    pts: List[tuple] = []
    last_is_high: Optional[bool] = None
    last_price = None

    for i in range(l2, n):
        thr = (atr[i] / close[i] * 100 * dev_mult) if (not pd.isna(atr[i]) and close[i]) else 1e9
        # high приоритет (Pine: if not na(iH) ... else if not na(iL))
        ph = pivot_at(i, True)
        pl = pivot_at(i, False) if ph is None else None
        cand = (True, ph) if ph is not None else ((False, pl) if pl is not None else None)
        if cand is None:
            continue
        hi, (c_idx, price) = cand
        if last_is_high is None:
            last_is_high, last_price = hi, price
            pts.append((d.index[c_idx], price))
            continue
        if hi == last_is_high:
            # продлить экстремум в том же направлении
            if (hi and price > last_price) or (not hi and price < last_price):
                last_price = price
                pts[-1] = (d.index[c_idx], price)
        else:
            dev = abs(100 * (price - last_price) / price) if price else 0
            if dev > thr:
                last_is_high, last_price = hi, price
                pts.append((d.index[c_idx], price))
    return pts
