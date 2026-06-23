# -*- coding: utf-8 -*-
"""OKO-OTE — ЕДИНЫЙ УНИВЕРСАЛЬНЫЙ детектор метода Егора. КОМПОЗИЦИЯ ЭТАЛОНОВ, 0 своих формул.

🔴 ЗАКОН (Егор 22.06): никаких новых вычислений — только эталоны проекта, без дублей.
Один метод = один движок; режимы (продолжение/разворот) = НАРРАТИВ (направление), не разные коды.
См. memory/oko_ote_torn_from_context.md, principle_reuse_not_duplication.

МЕТОД (мультиструктура = вложенность волн, обе стороны):
  1. КОНТЕКСТ старшего ТФ (zone): zigzag_atr+find_setups_zz → последний ЗНАЧИМЫЙ импульс +
     его OTE-зона (build_ote). «Где цена в структуре» = зона отскока/разворота.
  2. СЛОМ младшего ТФ (break, find_setups_zz) — РАБОТАЕТ В ОБЕ СТОРОНЫ. Направление = слом.
     Нарратив переключается сам, когда ломается старший ТФ (его OTE-зона обновляется).
  3. ВЛОЖЕННОСТЬ: вход (OTE 0.62 младшего) ТОЛЬКО ВНУТРИ OTE-зоны старшего → отскок до зоны
     ИЛИ идеальная точка разворота. Слом вне зоны старшего = рябь внутри ноги → пропуск.
  4. ПОДТВЕРЖДЕНИЯ ≥3 из 6 (div/wt_cross/vol/liq_sweep/fvg_held/atr) — эталон combinator
     (ote_signal_generator._confirmations). Конфлюенция +1.23 vs solo +0.13 (ote_engine_full_map).
  5. ФИЛЬТР ГЛУБИНЫ 0.55-0.68 + WT-подтверждение (calculate_wt) + дивергенция (DivergenceDetector).
  6. SL = Strong Low (levels[1.0]) ± буфер. ЦЕЛЬ = лестница фибо-РАСШИРЕНИЙ
     −1/−1.618/−2.618 (build_ote, measured move волн 3/5) → дальше магнит TPSelector (ARCH-113).

Все вычисления — готовые эталоны проекта. Здесь только КОМПОЗИЦИЯ + КОНТЕКСТ + НАРРАТИВ.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List, Tuple

OB, OS = 60.0, 60.0       # |WT| порог (calculate_wt); OS = −60
BUF = 0.0015              # буфер SL
ENTRY_FIB = 0.62          # OTE 0.618 — вход (эталонный уровень build_ote)
DEPTH_MIN, DEPTH_MAX = 0.55, 0.68   # фильтр средней глубины коррекции (инсайт Егора)
RETEST_BARS = 60          # окно касания OTE после слома
MIN_CONFIRMATIONS = 3     # ≥3 из 6 (эталон ote_nested — весомы, конфлюенция +1.23)
EXT_FIBS = [-1.0, -1.618, -2.618]   # лестница целей-расширений (measured move, гайды IKIGAI)

# SHADOW-ядро связок (зона_тф, слом_тф): старшая зона = выше WR + ниже DD
SHADOW_LINKS: List[Tuple[str, str]] = [("4h", "1h"), ("4h", "15m"), ("1h", "15m")]

_GEN = None               # ленивый singleton OTESignalGenerator (эталон подтверждений)


def _get_gen():
    global _GEN
    if _GEN is None:
        from core.smc.ote_signal_generator import OTESignalGenerator
        _GEN = OTESignalGenerator()
    return _GEN


@dataclass
class OkoOteSignal:
    symbol: str
    direction: str          # 'long' | 'short' (= направление слома, обе стороны)
    zone_tf: str
    break_tf: str
    entry: float            # OTE 0.62 младшего импульса
    sl: float               # Strong Low (levels[1.0]) ± буфер
    tp: float               # первая цель лестницы (расширение −1)
    tp_source: str          # 'fib_ext_-1.0' | 'TPSelector:<label>'
    depth: float            # глубина коррекции (0.55-0.68 = валид)
    rr: float               # |tp-entry|/|entry-sl|
    zone_ts: str            # контекст: htf-нарратив + confs + div
    choch_ts: str           # время слома младшего
    targets: Optional[List[Tuple[float, str]]] = None   # лестница −1/−1.618/−2.618/магниты
    entry_ts: str = ""      # время бара входа (касание OTE) — для бэктеста/раннера


class _Ctx:
    """Лёгкий market_context для TPSelector (ему нужны .symbol + .smc_snap)."""
    def __init__(self, symbol: str, smc_snap):
        self.symbol = symbol
        self.smc_snap = smc_snap


def _far_magnet(symbol, snap, entry, is_long, beyond):
    """Магнит TPSelector ДАЛЬШЕ последней фибо-цели (ЭТАЛОН ARCH-113). snap = готовый
    build_smc_snapshot (строится 1 раз на пару, НЕ per сетап). None если нет/ближе."""
    if not snap:
        return None
    try:
        from core.smc.tp_selector import TPSelector
        _, tp2 = TPSelector().select(entry, "LONG" if is_long else "SHORT",
                                     abs(entry - beyond) / entry * 100.0, _Ctx(symbol, snap))
        if tp2 and ((tp2.price > beyond) if is_long else (tp2.price < beyond)):
            return float(tp2.price), f"TPSelector:{tp2.label}"
    except Exception:
        pass
    return None


def detect_oko_ote(symbol: str, df_zone, df_break, zone_tf: str, break_tf: str,
                   only_latest: bool = True, min_confs: Optional[int] = None, dfs_all=None):
    """OKO-OTE: КОНТЕКСТ старшего ТФ → вложенный вход младшего В OTE-зоне старшего (обе стороны)
    → подтверждения ≥3 → цель-лестница расширений. df_zone=старший, df_break=младший (вход).

    only_latest=True → Optional[OkoOteSignal] (live, первый свежий). False → List (бэктест).
    min_confs=None → MIN_CONFIRMATIONS (live ≥3). 0 в бэктесте = мерить геометрию/выход отдельно.
    dfs_all={tf:df} — ПОЛНЫЙ набор ТФ для подтверждений (как ote_nested: atr на 3m/15m,
      div/wt/vol/liq на ltf). БЕЗ него _confirmations видит только 2 ТФ → confs занижены → ≥3=0.
    """
    _min_confs = MIN_CONFIRMATIONS if min_confs is None else int(min_confs)
    from core.smc.smc_engine import (zigzag_atr, find_setups_zz,
                                     select_significant_impulse)
    from core.indicators.indicators import calculate_wt
    from core.indicators.divergence_detector import DivergenceDetector

    if df_zone is None or df_break is None or len(df_zone) < 100 or len(df_break) < 300:
        return None

    # 1) КОНТЕКСТ СТАРШЕГО ТФ — ЗНАЧИМЫЙ ЖИВОЙ импульс (extreme LOW→HIGH от CHoCH-окна +
    #    инвалидация 0.79 + цена в OTE/ноге), а НЕ наивный htf[-1] (корень провала OKO-OTE,
    #    Егор 23.06). Fallback на htf[-1] для совместимости. См. [[oko_ote_torn_from_context]].
    _zz_zone = zigzag_atr(df_zone)
    h = select_significant_impulse(df_zone, _zz_zone)
    if h is None:
        htf = find_setups_zz(_zz_zone, df_zone)
        if not htf:
            return None
        h = htf[-1]
    htf_dir = h["direction"]                    # нарратив старшего (инфо; НЕ жёсткий фильтр)
    htf_ote_lo, htf_ote_hi = h["ote"]           # зона старшего = «где должна быть цена» (вложенность)

    # 2) СЛОМЫ МЛАДШЕГО ТФ — обе стороны (тот же эталон)
    ltf = find_setups_zz(zigzag_atr(df_break), df_break)
    if not ltf:
        return None

    try:
        wt_l = calculate_wt(df_break.copy())["wt1"].values
    except Exception:
        wt_l = None
    df_div = df_break.copy()
    try:
        df_div["wt1"] = wt_l if wt_l is not None else 0.0
    except Exception:
        df_div = None
    _dd = DivergenceDetector()

    # подтверждения — эталон combinator. live: flast на ПОСЛЕДНЕМ баре (1 раз).
    # бэктест (only_latest=False): flags_df на ВСЕХ барах → строка на баре входа ei (live-точно).
    gen = _get_gen()
    # ПОЛНЫЙ dfs для подтверждений (atr на 3m/15m + div/wt/vol/liq) — как ote_nested.
    dfs = dict(dfs_all) if dfs_all else {}
    dfs.setdefault(zone_tf, df_zone); dfs.setdefault(break_tf, df_break)
    flast = None; flags_df = None
    if only_latest:
        try:
            flast = gen._ltf_flags(df_break, break_tf)
        except Exception:
            flast = None
    else:
        try:
            from core.smc.ote_signal_generator import _combinator
            flags_df = _combinator().compute_flags(df_break, break_tf)
        except Exception:
            flags_df = None
    # snapshot для far-магнитов TPSelector — ОДИН раз на пару (не per сетап = быстро + с магнитами)
    _snap = None
    try:
        from core.smc.smc_snapshot import build_smc_snapshot
        _snap = build_smc_snapshot(symbol, {zone_tf: df_zone, break_tf: df_break})
    except Exception:
        _snap = None

    posL = {ts: i for i, ts in enumerate(df_break.index)}
    lo = df_break["low"].values; hi = df_break["high"].values; cl = df_break["close"].values; n = len(df_break)

    out_all: List[OkoOteSignal] = []        # only_latest=False → ВСЕ сетапы (для бэктеста)
    order = list(reversed(ltf)) if only_latest else ltf
    for s in order:
        D = s["direction"]                      # НАПРАВЛЕНИЕ = слом младшего (обе стороны)
        is_long = D == "long"
        entry = s["levels"][ENTRY_FIB]
        # 🔑 ВЛОЖЕННОСТЬ: вход ТОЛЬКО ВНУТРИ OTE-зоны старшего (отскок/разворот в зоне).
        # Слом вне зоны старшего = рябь внутри ноги (корень шума) → пропуск.
        if not (htf_ote_lo <= entry <= htf_ote_hi):
            continue
        ci = posL.get(s["choch_ts"])
        if ci is None:
            continue
        ei = None
        for j in range(ci + 1, min(ci + 1 + RETEST_BARS, n)):
            if (lo[j] <= entry) if is_long else (hi[j] >= entry):
                ei = j
                break
        if ei is None:
            continue
        imp_from = s["from"][1]; imp_to = s["to"][1]; rng = abs(imp_to - imp_from)
        if rng <= 0:
            continue
        # глубина коррекции (фильтр средней 0.55-0.68)
        if is_long:
            mn = lo[ci:ei + 1].min() if ei > ci else lo[ei]; depth = (imp_to - mn) / rng
        else:
            mx = hi[ci:ei + 1].max() if ei > ci else hi[ei]; depth = (mx - imp_to) / rng
        if not (DEPTH_MIN <= depth < DEPTH_MAX):
            continue
        # WT-ПОДТВЕРЖДЕНИЕ: не входить против WT-экстремума
        if wt_l is not None and ei < len(wt_l):
            wv = float(wt_l[ei])
            if (is_long and wv >= OB) or (not is_long and wv <= -OS):
                continue
        # ПОДТВЕРЖДЕНИЯ ≥3 из 6 (эталон combinator) — весомый фильтр качества
        # ПОДТВЕРЖДЕНИЯ НАБИРАЮТСЯ (ARMED→FIRE как nested): confs пересчитываются на барах
        # ПОСЛЕ касания, пока цена в OTE-зоне. ≥3 на ОДНОМ баре не совпадают — нужно окно.
        # live: confs на текущем баре (накопление через повторные сканы observer каждые 5 мин).
        confs = []
        if only_latest:
            try:
                cf = gen._confirmations(D, dfs, break_tf, flast)
            except Exception:
                cf = []
            if len(cf) >= _min_confs:
                confs = cf
        else:
            _zlo = min(s["levels"][0.5], s["levels"][0.79])
            _zhi = max(s["levels"][0.5], s["levels"][0.79])
            for j in range(ei, min(ei + RETEST_BARS, n)):
                if not (_zlo <= cl[j] <= _zhi):     # цена вышла из OTE-зоны → ARMED истёк
                    break
                _fj = flags_df.iloc[j] if (flags_df is not None and j < len(flags_df)) else None
                try:
                    cf = gen._confirmations(D, dfs, break_tf, _fj)
                except Exception:
                    cf = []
                if len(cf) >= _min_confs:
                    confs = cf; break           # FIRE — подтверждения набрались в зоне
        if len(confs) < _min_confs:
            continue
        # дивергенция разворота (эталон) — в zone_ts (инфо)
        div_rev = False
        if df_div is not None and ei > 35:
            try:
                seg = df_div.iloc[:ei + 1]
                dv = (_dd.detect_regular_bullish(seg, "wt1") if is_long
                      else _dd.detect_regular_bearish(seg, "wt1"))
                div_rev = dv is not None
            except Exception:
                pass

        slv = s["levels"][1.0] * (1 - BUF) if is_long else s["levels"][1.0] * (1 + BUF)
        risk = abs(entry - slv)
        if risk <= 0:
            continue
        # ЦЕЛИ-ЛЕСТНИЦА: фибо-расширения −1/−1.618/−2.618 (эталон build_ote) → дальше магнит
        targets: List[Tuple[float, str]] = []
        for f in EXT_FIBS:
            lv = s["levels"].get(f)
            if lv and ((lv > entry) if is_long else (lv < entry)):
                targets.append((round(float(lv), 8), f"fib_ext_{f}"))
        if not targets:
            continue
        far = _far_magnet(symbol, _snap, entry, is_long, targets[-1][0])   # snap готов (1 раз/пара)
        if far:
            targets.append((round(far[0], 8), far[1]))
        tp, tp_source = targets[0]              # первая цель = −1 (консервативно, RR ~4.2)
        rr = abs(tp - entry) / risk
        sig = OkoOteSignal(
            symbol=symbol, direction=D, zone_tf=zone_tf, break_tf=break_tf,
            entry=round(entry, 8), sl=round(slv, 8), tp=round(tp, 8),
            tp_source=tp_source, depth=round(depth, 3), rr=round(rr, 2),
            zone_ts=f"htf={htf_dir} in_ote=1 confs={'+'.join(confs)} div={int(div_rev)}",
            choch_ts=str(s["choch_ts"]), targets=targets, entry_ts=str(df_break.index[ei]),
        )
        if only_latest:
            return sig                          # live: первый свежий сетап
        out_all.append(sig)                     # бэктест: собираем все
    return out_all if not only_latest else None
