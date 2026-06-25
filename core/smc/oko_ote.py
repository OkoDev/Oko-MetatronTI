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
  5. ФИЛЬТР ГЛУБИНЫ 0.5-0.705 + WT-подтверждение (calculate_wt) + дивергенция (DivergenceDetector).
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
DEPTH_MIN, DEPTH_MAX = 0.382, 0.79   # фильтр глубины коррекции = OTE-зона входа (эталон IKIGAI:
                                     # зона коррекции 0.382-0.786, волна4=0.382, волна2/глубокая
                                     # =0.618/0.786, доминанта 0.618). 0.786≈0.79 (Егор, используем
                                     # существующий уровень build_ote 0.79). Узкая 0.5-0.705 резала
                                     # валидные касания (BTC окт). zone_lo/hi = levels[0.382/0.79].
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
    depth: float            # глубина коррекции (0.5-0.705 = валид)
    rr: float               # |tp-entry|/|entry-sl|
    zone_ts: str            # контекст: htf-нарратив + confs + div
    choch_ts: str           # время слома младшего
    targets: Optional[List[Tuple[float, str]]] = None   # лестница −1/−1.618/−2.618/магниты
    entry_ts: str = ""      # время бара входа (касание OTE) — для бэктеста/раннера
    # 25.06 (Вариант А, гейт свежести): границы OTE-зоны (levels[DEPTH_MIN]/levels[DEPTH_MAX])
    # — наблюдателю нужны ОБЕ границы, не только entry, чтобы не резать сетап если цена ушла
    # от точного entry_fib, но осталась внутри зоны (метод OTE = вся зона валидна для входа).
    zone_lo: float = 0.0
    zone_hi: float = 0.0


class _Ctx:
    """Лёгкий market_context для TPSelector (ему нужны .symbol + .smc_snap)."""
    def __init__(self, symbol: str, smc_snap):
        self.symbol = symbol
        self.smc_snap = smc_snap


def _precompute_wt(dfl):
    """wt1/wt2 ОДИН раз на пару (формула _raw_wt_cross, эталон combinator.wavetrend).
    Бэктест: без этого окно подтверждений пересчитывает wavetrend на КАЖДОМ баре каждого
    сетапа (O(сетапы×окно×n)) — корень тормозов confs≥3 на 15m (минуты на пару)."""
    try:
        from core.smc.ote_signal_generator import _combinator
        import pandas as pd
        wt1 = _combinator().wavetrend(dfl).values
        wt2 = pd.Series(wt1).rolling(4, min_periods=1).mean().values
        return wt1, wt2
    except Exception:
        return None, None


def _wt_cross_at(wt1, wt2, j, up, look=3):
    """Точечная (на баре j) _raw_wt_cross — та же формула combinator, без пересчёта/lookahead."""
    if wt1 is None or j is None:
        return False
    for i in range(max(1, j - look + 1), j + 1):
        if up and wt1[i - 1] <= wt2[i - 1] and wt1[i] > wt2[i]:
            return True
        if not up and wt1[i - 1] >= wt2[i - 1] and wt1[i] < wt2[i]:
            return True
    return False


def _precompute_atr_dir(dfs, df_break):
    """ATRTrend-направление (combinator.atr_supertrend) на 3m/15m, ОДИН раз, выровнено
    asof/ffill по индексу df_break — точка-в-моменте (без lookahead), без пересчёта в окне."""
    import pandas as pd
    from core.smc.ote_signal_generator import _combinator
    out = {}
    for atf in ("3m", "15m"):
        d = dfs.get(atf)
        if d is None or len(d) <= 30:
            continue
        try:
            tr = _combinator().atr_supertrend(d)
            s = pd.Series(tr, index=d.index)
            out[atf] = s.reindex(df_break.index, method="ffill").values
        except Exception:
            continue
    return out


def _confirmations_bt(is_long, _fj, ltf, wt1, wt2, j, atr_dirs) -> list:
    """Бэктест-версия OTESignalGenerator._confirmations: ТЕ ЖЕ 6 признаков, но wt_cross/atr
    читаются из ПРЕДВЫЧИСЛЕННЫХ (1 раз/пара) массивов по индексу j — без пересчёта на баре
    и без lookahead (раньше _raw_wt_cross/_atr_trend_up всегда смотрели на конец df_break,
    игнорируя j). div/fvg_held/vol/liq_sweep — как в эталоне, через flags_df.iloc[j] (_fj)."""
    want = "bull" if is_long else "bear"
    conf = []
    if _fj is not None:
        g = lambda k: bool(_fj.get(k, False))
        if g(f"rsi_div_{want}_regular_{ltf}") or g(f"rsi_div_{want}_hidden_{ltf}"):
            conf.append("div")
        if g(f"{want}_fvg_overlap_held_{ltf}"):
            conf.append("fvg_held")
        if g(f"vol_spike_{ltf}"):
            conf.append("vol")
        if g(f"{'eql' if is_long else 'eqh'}_sweep_{ltf}"):
            conf.append("liq_sweep")
    if _wt_cross_at(wt1, wt2, j, is_long):
        conf.append("wt_cross")
    for atf, arr in atr_dirs.items():
        if j < len(arr):
            v = arr[j]
            if v == v and ((v == 1) == is_long):   # v==v: не NaN (нет истории до j)
                conf.append("atr"); break
    return conf


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


def _zone_asof(df_zone, dp, dev, as_of_ts, cache, prefer_recency=False):
    """PIT-зона старшего ТФ на МОМЕНТ as_of_ts (срез df_zone до этого времени) — честный
    point-in-time выбор (как видел бы живой бот), БЕЗ хиндсайта конца датасета.
    Кэш по индексу последнего бара среза: LTF-сломы внутри одного HTF-бара дают один ключ
    → пересчёт раз на HTF-бар, не на каждый слом (иначе O(сломы × zigzag) = неподъёмно).
    dev переиспользуется с полного df (масштаб-параметр пары стабилен во времени — аппроксимация
    ради скорости; точный adaptive_dev на каждом срезе удвоил бы и без того дорогой пересчёт).
    Возвращает (ote_lo, ote_hi, direction) или None. Эталоны: zigzag_atr/select_significant_impulse."""
    from core.smc.smc_engine import zigzag_atr, select_significant_impulse, find_setups_zz
    pos = int(df_zone.index.searchsorted(as_of_ts, side="right"))  # баров с временем <= as_of_ts
    if pos < 50:
        return None
    cached = cache.get(pos, "MISS")
    if cached != "MISS":
        return cached
    d_cut = df_zone.iloc[:pos]
    try:
        zz = zigzag_atr(d_cut, depth=dp, dev_mult=dev)
        h = select_significant_impulse(d_cut, zz, prefer_recency=prefer_recency)
        if h is None:
            hs = find_setups_zz(zz, d_cut)
            h = hs[-1] if hs else None
    except Exception:
        h = None
    res = (h["ote"][0], h["ote"][1], h["direction"]) if h else None
    cache[pos] = res
    return res


def detect_oko_ote(symbol: str, df_zone, df_break, zone_tf: str, break_tf: str,
                   only_latest: bool = True, min_confs: Optional[int] = None, dfs_all=None,
                   mid_tf: Optional[str] = None, df_mid=None, entry_fib: float = ENTRY_FIB,
                   pit_zone: bool = False, recency: bool = False, confs_tf: Optional[str] = None):
    """OKO-OTE: КОНТЕКСТ старшего ТФ → вложенный вход младшего В OTE-зоне старшего (обе стороны)
    → подтверждения ≥3 → цель-лестница расширений. df_zone=старший, df_break=младший (вход).

    only_latest=True → Optional[OkoOteSignal] (live, первый свежий). False → List (бэктест).
    min_confs=None → MIN_CONFIRMATIONS (live ≥3). 0 в бэктесте = мерить геометрию/выход отдельно.
    dfs_all={tf:df} — ПОЛНЫЙ набор ТФ для подтверждений (как ote_nested: atr на 3m/15m,
      div/wt/vol/liq на ltf). БЕЗ него _confirmations видит только 2 ТФ → confs занижены → ≥3=0.
    mid_tf/df_mid — опц. ТРЕТИЙ (средний) ТФ для ТРОЙНОЙ вложенности (4h⊃1h⊃15m/5m): своя
      OTE-зона mid_tf ВНУТРИ zone_tf-зоны → финальный слом break_tf ВНУТРИ mid_tf-зоны.
      None (default) = текущее 2-уровневое поведение, БЕЗ изменений (живой путь не трогает).
    entry_fib — фибо-уровень входа (default ENTRY_FIB=0.62); для sweep 0.5/0.62/0.705.
    pit_zone — БЭКТЕСТ-ОНЛИ (only_latest=False, mid_tf=None): зона старшего выбирается
      point-in-time на момент каждого слома (честно), а не один раз на полном df_zone
      (хиндсайт конца датасета = 67% сделок-артефактов, PIT-CHECK 25.06). Live игнорирует.
    """
    _min_confs = MIN_CONFIRMATIONS if min_confs is None else int(min_confs)
    from core.smc.smc_engine import (zigzag_atr, find_setups_zz,
                                     select_significant_impulse, adaptive_dev)
    from core.indicators.indicators import calculate_wt
    from core.indicators.divergence_detector import DivergenceDetector

    if df_zone is None or df_break is None or len(df_zone) < 100 or len(df_break) < 300:
        return None
    if mid_tf is not None and (df_mid is None or len(df_mid) < 100):
        return None

    # 1) КОНТЕКСТ СТАРШЕГО ТФ — ЗНАЧИМЫЙ ЖИВОЙ импульс (extreme LOW→HIGH от CHoCH-окна +
    #    инвалидация 0.79 + цена в OTE/ноге), а НЕ наивный htf[-1] (корень провала OKO-OTE,
    #    Егор 23.06). Fallback на htf[-1] для совместимости. См. [[oko_ote_torn_from_context]].
    # АДАПТИВНЫЙ dev (масштаб как ручная разметка): depth из config, dev под ~12 свингов.
    try:
        from core.smc.smc_snapshot import _zz_params
        _dp, _ = _zz_params(zone_tf)
    except Exception:
        _dp = 11
    _dev_zone = adaptive_dev(df_zone, _dp)
    _zz_zone = zigzag_atr(df_zone, depth=_dp, dev_mult=_dev_zone)
    h = select_significant_impulse(df_zone, _zz_zone, prefer_recency=recency)
    if h is None:
        htf = find_setups_zz(_zz_zone, df_zone)
        if not htf:
            return None
        h = htf[-1]
    htf_dir = h["direction"]                    # нарратив старшего (инфо; НЕ жёсткий фильтр)
    htf_ote_lo, htf_ote_hi = h["ote"]           # зона старшего = «где должна быть цена» (вложенность)

    # 1.5) СРЕДНИЙ ТФ (опц., тройная вложенность) — своя OTE-зона ВНУТРИ зоны старшего.
    # Тот же containment-приём, что и ниже для break_tf (НЕ новая формула) — на один уровень
    # глубже. find_setups_zz даёт ВСЕ сломы mid_tf (не один значимый), чтобы поймать МНОГО
    # вложенных под-импульсов внутри тренда старшего, а не только лучший.
    if mid_tf is not None:
        mid_setups = find_setups_zz(zigzag_atr(df_mid), df_mid)
        containers = [m["ote"] for m in mid_setups
                      if htf_ote_lo <= m["levels"].get(entry_fib, float("nan")) <= htf_ote_hi]
        if not containers:
            return [] if not only_latest else None
    else:
        containers = [(htf_ote_lo, htf_ote_hi)]

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
    if mid_tf is not None:
        dfs.setdefault(mid_tf, df_mid)
    # confs_tf (Егор 25.06): подтверждения на МАКСИМАЛЬНО МЛАДШЕМ ТФ (5m), а слом/вход на break_tf
    # (15m/1h). «Сетап на старшем, заходим+подтверждаемся на младшем». BTC окт: слом виден на 15m
    # (на 5m дробится), но confs≥3 на 15m не набрать (мало сигналов) → нужен слом 15m + confs 5m.
    # None → confs на break_tf (старое поведение). df_confs из dfs (5m). Бар входа ei(break_tf)
    # мапится по времени на confs_df бар (_confirmations_bt на нём).
    _confs_name = confs_tf if (confs_tf and confs_tf in dfs) else break_tf
    df_confs = dfs.get(_confs_name, df_break)
    _confs_idx = df_confs.index
    flast = None; flags_df = None
    if only_latest:
        try:
            flast = gen._ltf_flags(df_confs, _confs_name)
        except Exception:
            flast = None
    else:
        try:
            from core.smc.ote_signal_generator import _combinator
            flags_df = _combinator().compute_flags(df_confs, _confs_name)
        except Exception:
            flags_df = None
    # бэктест: wt/atr ПРЕДВЫЧИСЛЕНЫ 1 раз/пара (не на каждый бар окна, см. _confirmations_bt) — на confs-ТФ
    _bt_wt1, _bt_wt2, _bt_atr_dirs = None, None, {}
    if not only_latest:
        _bt_wt1, _bt_wt2 = _precompute_wt(df_confs)
        _bt_atr_dirs = _precompute_atr_dir(dfs, df_confs)
    # snapshot для far-магнитов TPSelector — ЛЕНИВО (1 раз, только если дойдёт ХОТЯ БЫ один
    # сетап до far_magnet). build_smc_snapshot (structure/fvg/order_blocks mitigation) — O(n)
    # с тяжёлыми .iloc-сканами; на 15m (24k+ баров) это ~7 минут ВСЕГДА, даже если confs≥3
    # не наберётся ни на одном сетапе (как чаще всего и бывает) — корень тормозов бэктеста.
    _snap_box = {}

    def _get_snap():
        if "v" not in _snap_box:
            try:
                from core.smc.smc_snapshot import build_smc_snapshot
                # tail(5000) — тот же приём, что в эталоне ote_signal_generator.py __main__
                # (для far-магнита нужна НЕДАВНЯЯ структура, не вся история; иначе на 15m
                # build_smc_snapshot гоняет .iloc-сканы по 20k+ барам — минуты на пару).
                _snap_box["v"] = build_smc_snapshot(
                    symbol, {zone_tf: df_zone.tail(5000), break_tf: df_break.tail(5000)})
            except Exception:
                _snap_box["v"] = None
        return _snap_box["v"]

    posL = {ts: i for i, ts in enumerate(df_break.index)}
    lo = df_break["low"].values; hi = df_break["high"].values; cl = df_break["close"].values; n = len(df_break)
    # PIT-зона (приоритет 1, 25.06): в бэктесте зона старшего пересчитывается point-in-time
    # на момент КАЖДОГО слома (честно), не один раз на полном df (хиндсайт = 67% сделок-артефактов,
    # PIT-CHECK). Только 2-уровневый (mid_tf=None); тройную с PIT перепроверять отдельно. Кэш по HTF-бару.
    _pit = bool(pit_zone) and not only_latest and mid_tf is None
    _zone_cache: dict = {}
    import pandas as _pd

    out_all: List[OkoOteSignal] = []        # only_latest=False → ВСЕ сетапы (для бэктеста)
    order = list(reversed(ltf)) if only_latest else ltf
    # containers=[(lo,hi)] — 1 элемент без mid_tf (== прежнее поведение 1:1), N при тройной
    # вложенности. Плоский список пар (container,s) вместо вложенных for — НЕ меняет отступы
    # остального тела цикла ниже (риск регрессии при правке живого детектора).
    _pairs = [(clo, chi, s) for (clo, chi) in containers for s in order]
    seen_choch: set = set()                 # дедуп: один и тот же слом не считать 2x по containers
    for container_lo, container_hi, s in _pairs:
        D = s["direction"]                      # НАПРАВЛЕНИЕ = слом младшего (обе стороны)
        is_long = D == "long"
        entry = s["levels"][entry_fib]
        # PIT: зону старшего пересчитываем на МОМЕНТ слома (честно, без хиндсайта конца датасета)
        if _pit:
            _z = _zone_asof(df_zone, _dp, _dev_zone, _pd.Timestamp(s["choch_ts"]), _zone_cache, recency)
            if _z is None:
                continue
            container_lo, container_hi, htf_dir = _z[0], _z[1], _z[2]
        # 🔑 ВЛОЖЕННОСТЬ: вход ТОЛЬКО ВНУТРИ OTE-зоны контейнера (старшего, либо среднего при
        # тройной вложенности). Слом вне зоны = рябь внутри ноги (корень шума) → пропуск.
        if not (container_lo <= entry <= container_hi):
            continue
        if s["choch_ts"] in seen_choch:
            continue
        seen_choch.add(s["choch_ts"])
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
                cf = gen._confirmations(D, dfs, _confs_name, flast)
            except Exception:
                cf = []
            if len(cf) >= _min_confs:
                confs = cf
        else:
            _zlo = min(s["levels"][0.5], s["levels"][0.79])
            _zhi = max(s["levels"][0.5], s["levels"][0.79])
            _same_confs = (_confs_name == break_tf)   # confs на том же ТФ → j5==j (без маппинга)
            for j in range(ei, min(ei + RETEST_BARS, n)):
                if not (_zlo <= cl[j] <= _zhi):     # цена вышла из OTE-зоны → ARMED истёк
                    break
                # confs на confs_df (5m): мапим время бара j(break_tf) → бар confs_df
                if _same_confs:
                    j5 = j
                else:
                    j5 = int(_confs_idx.searchsorted(df_break.index[j], side="right")) - 1
                    if j5 < 0:
                        continue
                _fj = flags_df.iloc[j5] if (flags_df is not None and 0 <= j5 < len(flags_df)) else None
                try:
                    cf = _confirmations_bt(is_long, _fj, _confs_name, _bt_wt1, _bt_wt2, j5, _bt_atr_dirs)
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
        far = _far_magnet(symbol, _get_snap(), entry, is_long, targets[-1][0])   # ленивый snap (1 раз, по нужде)
        if far:
            targets.append((round(far[0], 8), far[1]))
        tp, tp_source = targets[0]              # первая цель = −1 (консервативно, RR ~4.2)
        rr = abs(tp - entry) / risk
        _zlv1, _zlv2 = s["levels"][DEPTH_MIN], s["levels"][DEPTH_MAX]
        zone_lo, zone_hi = min(_zlv1, _zlv2), max(_zlv1, _zlv2)
        sig = OkoOteSignal(
            symbol=symbol, direction=D, zone_tf=zone_tf, break_tf=break_tf,
            entry=round(entry, 8), sl=round(slv, 8), tp=round(tp, 8),
            tp_source=tp_source, depth=round(depth, 3), rr=round(rr, 2),
            zone_ts=f"htf={htf_dir} in_ote=1 confs={'+'.join(confs)} div={int(div_rev)}",
            choch_ts=str(s["choch_ts"]), targets=targets, entry_ts=str(df_break.index[ei]),
            zone_lo=round(zone_lo, 8), zone_hi=round(zone_hi, 8),
        )
        if only_latest:
            return sig                          # live: первый свежий сетап
        out_all.append(sig)                     # бэктест: собираем все
    return out_all if not only_latest else None
