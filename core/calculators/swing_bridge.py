"""
DS-313/DS-314: Эталонные детекторы для combinator_v2 через smc_engine.
Конвертирует результаты smc_engine в boolean-массивы для compute_flags.
DS-314: унификация направлений — каждый признак получает dir_label (bull/bear) + dir (±1).
Правило: {long, up} → bull/+1, {short, down} → bear/−1.
"""
import numpy as np
import pandas as pd
from typing import List, Dict

# ── C-01 (11.06): CHoCH length из config ──────────────────────────
def _get_choch_length() -> int:
    """Читает arch104.choch_length из config.yaml. Дефолт 50 (текущее).
    Менять на 5 после ре-майнинга 69 паттернов + A/B бэктеста."""
    try:
        from core.infra.config_loader import config as _cfg
        return int(_cfg.get("arch104.choch_length", 50))
    except Exception:
        return 50

# ── Канон направлений (DS-314) — ТРОИЧНЫЙ ──────────────────────────
# dir ∈ {+1, 0, −1}   ·   dir_label ∈ {bull, range, bear}
CANON = {
    "bull": ("bull", +1), "bear": ("bear", -1),
    "long": ("bull", +1), "short": ("bear", -1),
    "up": ("bull", +1), "down": ("bear", -1),
    "range": ("range", 0), "neutral": ("range", 0), "eq": ("range", 0),
}


def _norm_dir(raw_dir: str):
    """Нормализовать направление → (dir_label, dir_val)."""
    if raw_dir in CANON:
        return CANON[raw_dir]
    return (raw_dir, 0)  # неизвестное


def _add_dir_meta(result: dict, prefix: str, raw_dir: str):
    """Добавить dir_label_{prefix} и dir_{prefix} в result."""
    label, val = _norm_dir(raw_dir)
    result[f"dir_label_{prefix}"] = label
    result[f"dir_{prefix}"] = val


def _to_bool_array(n: int, indices: List[int]) -> np.ndarray:
    arr = np.zeros(n, dtype=bool)
    for idx in indices:
        if 0 <= idx < n:
            arr[idx] = True
    return arr


def etl_fvg(df: pd.DataFrame) -> Dict[str, np.ndarray]:
    """ARCH-128: FVG через detect_fvg → bool массивы."""
    from core.smc.smc_engine import detect_fvg

    n = len(df)
    close = df["close"].values
    fvgs = detect_fvg(df)  # List[(bar, lvl1, lvl2, dir, extra1, extra2)]

    bull_idx, bear_idx = [], []
    bull_in = np.zeros(n, dtype=bool)
    bear_in = np.zeros(n, dtype=bool)

    for f in fvgs:
        bar_raw, l1, l2, direction = f[0], f[1], f[2], f[3]
        # bar может быть Timestamp или int
        bar = df.index.get_loc(bar_raw) if hasattr(bar_raw, 'timestamp') else int(bar_raw)
        bot, top = min(l1, l2), max(l1, l2)
        if direction == "bull":
            bull_idx.append(bar)
        else:
            bear_idx.append(bar)
        for j in range(bar, min(bar + 20, n)):
            if bot * 0.998 <= close[j] <= top * 1.002:
                if direction == "bull":
                    bull_in[j] = True
                else:
                    bear_in[j] = True

    ret = {"bull_fvg": _to_bool_array(n, bull_idx), "bear_fvg": _to_bool_array(n, bear_idx),
            "bull_fvg_in": bull_in, "bear_fvg_in": bear_in}
    _add_dir_meta(ret, "fvg", "bull")  # FVG всегда знает сторону
    return ret


def etl_order_blocks(df: pd.DataFrame) -> Dict[str, np.ndarray]:
    """ARCH-128: структурные OB с ATR(200) + mitigation."""
    from core.smc.smc_engine import detect_structure_breaks, detect_order_blocks, active_order_blocks

    n = len(df)
    breaks = detect_structure_breaks(df, length=_get_choch_length())  # C-01: config-флаг choch_length
    obs = detect_order_blocks(df, breaks)       # List[OrderBlock]
    active = active_order_blocks(obs, n_bars=30, per_side=5)

    close = df["close"].values
    bull_idx, bear_idx = [], []
    bull_near, bear_near = [], []

    for ob in active:
        idx = ob.break_idx
        if not (0 <= idx < n):
            continue
        if ob.kind == "bull":
            bull_idx.append(idx)
            for j in range(idx, min(idx + 10, n)):
                if -0.5 <= (close[j] - ob.top) / close[j] * 100 <= 3:
                    bull_near.append(j)
        else:
            bear_idx.append(idx)
            for j in range(idx, min(idx + 10, n)):
                if -0.5 <= (ob.bottom - close[j]) / close[j] * 100 <= 3:
                    bear_near.append(j)

    # ARCH-128 Шаг 2: митигация OB (флаг на баре пробоя блока) — из ВСЕХ obs, не только active
    bull_mit = [ob.mitigated_idx for ob in obs if ob.kind == "bull" and ob.mitigated_idx >= 0]
    bear_mit = [ob.mitigated_idx for ob in obs if ob.kind == "bear" and ob.mitigated_idx >= 0]

    ret = {"bull_ob": _to_bool_array(n, bull_idx), "bear_ob": _to_bool_array(n, bear_idx),
            "bull_ob_near": _to_bool_array(n, bull_near), "bear_ob_near": _to_bool_array(n, bear_near),
            "bull_ob_mitigated": _to_bool_array(n, bull_mit), "bear_ob_mitigated": _to_bool_array(n, bear_mit)}
    _add_dir_meta(ret, "ob", "bull")
    return ret


def etl_bos_choch(df: pd.DataFrame) -> Dict[str, np.ndarray]:
    """ARCH-128: BOS/CHoCH через detect_structure_breaks."""
    from core.smc.smc_engine import detect_structure_breaks, zigzag_atr, find_setups_zz

    n = len(df)
    breaks = detect_structure_breaks(df, length=_get_choch_length())  # C-01

    # Из StructureBreak объектов
    bull_bos_idx = [b.idx for b in breaks if b.kind == "BOS" and b.direction == "bull"]
    bear_bos_idx = [b.idx for b in breaks if b.kind == "BOS" and b.direction == "bear"]
    bull_choch_idx = [b.idx for b in breaks if b.kind == "CHoCH" and b.direction == "bull"]
    bear_choch_idx = [b.idx for b in breaks if b.kind == "CHoCH" and b.direction == "bear"]

    # Дополнительно: ZigZag-based сетапы (find_setups_zz)
    zz = zigzag_atr(df)
    setups = find_setups_zz(zz, df)
    for s in setups:
        bar = s.get("bar", 0)
        if s.get("kind") == "BOS" and s.get("dir") == "bull":
            if bar not in bull_bos_idx: bull_bos_idx.append(bar)
        elif s.get("kind") == "BOS" and s.get("dir") == "bear":
            if bar not in bear_bos_idx: bear_bos_idx.append(bar)
        elif s.get("kind") == "CHoCH" and s.get("dir") == "bull":
            if bar not in bull_choch_idx: bull_choch_idx.append(bar)
        elif s.get("kind") == "CHoCH" and s.get("dir") == "bear":
            if bar not in bear_choch_idx: bear_choch_idx.append(bar)

    ret = {"bull_bos": _to_bool_array(n, bull_bos_idx), "bear_bos": _to_bool_array(n, bear_bos_idx),
            "bull_choch": _to_bool_array(n, bull_choch_idx), "bear_choch": _to_bool_array(n, bear_choch_idx)}
    _add_dir_meta(ret, "bos_choch", "bull")
    return ret


def etl_ote_premium(df: pd.DataFrame) -> Dict[str, np.ndarray]:
    """ARCH-128: OTE + Premium/Discount."""
    from core.smc.smc_engine import premium_discount, build_ote, find_choch_ote, detect_structure_breaks

    n = len(df)
    close, high, low = df["close"].values, df["high"].values, df["low"].values

    ote_long = np.zeros(n, dtype=bool)
    ote_short = np.zeros(n, dtype=bool)
    premium = np.zeros(n, dtype=bool)
    discount = np.zeros(n, dtype=bool)

    # Premium/Discount от ROLLING dealing range (последний ПОДТВЕРЖДЁННЫЙ swing H/L до бара).
    # ARCH-118 (05.06): глобальный high.max/low.min был НЕСТАБИЛЕН (зависел от глубины истории
    # → 8/10 parity-расхождений: full=давний ATH vs deep=недавний) И семантически неверен +
    # lookahead (весь df включая будущее). SMC меряет от dealing range ТЕКУЩЕЙ структуры.
    # Rolling per bar (swing подтверждён через length баров) → lookahead-safe + parity
    # (last bar = последний confirmed leg, одинаков на любой глубине истории).
    from core.smc.smc_engine import _swings_luxalgo
    _LEN = 20
    _sw = sorted(_swings_luxalgo(df, _LEN), key=lambda x: x[0])   # [(idx, price, 'H'/'L')]
    _last_h = _last_l = None
    _si = 0
    for i in range(n):
        while _si < len(_sw) and _sw[_si][0] + _LEN <= i:         # swing подтверждён к бару i
            _idx, _price, _kind = _sw[_si]
            if _kind == "H": _last_h = _price
            else:            _last_l = _price
            _si += 1
        if _last_h is None or _last_l is None:
            continue                                              # структура не определена
        _z = premium_discount(max(_last_h, _last_l), min(_last_h, _last_l))
        c = close[i]
        prem_lo, prem_hi = _z["premium"]; disc_lo, disc_hi = _z["discount"]
        if prem_lo <= c <= prem_hi:
            premium[i] = True
        elif disc_lo <= c <= disc_hi:
            discount[i] = True

    # OTE от CHoCH
    breaks = detect_structure_breaks(df, length=_get_choch_length())  # C-01
    choch_ote = find_choch_ote(breaks, df)
    if choch_ote:
        # 🔴 FIX 12.07 (Егор «копай глубже»): build_ote возвращает зону под ключом 'ote',
        # НЕ 'ote_zone' → get дефолтил (0,0) → 0<=c<=0 никогда → ote_long/ote_short мёртв
        # с ARCH-128 (0/25000 баров). Тот же класс, что eqh/eql свип.
        zone = choch_ote.get("ote", choch_ote.get("ote_zone", (0, 0)))
        direction = choch_ote.get("direction", "")
        for i in range(n):
            c = close[i]
            if zone[0] <= c <= zone[1]:
                if direction == "long":
                    ote_long[i] = True
                elif direction == "short":
                    ote_short[i] = True

    ret = {"ote_long": ote_long, "ote_short": ote_short,
            "premium": premium, "discount": discount}
    _add_dir_meta(ret, "ote", "long")  # long → bull/+1
    return ret


def etl_eql_eql(df: pd.DataFrame) -> Dict[str, np.ndarray]:
    """ARCH-128: EQH/EQL sweep через detect_equal_levels.

    🔴 FIX 12.07 (Егор «копни»): свип = ПОСЛЕ формирования равного уровня цена пробивает его
    (снятие ликвидности), НЕ на баре пивота. Старый код проверял high[bar_пивота] > level*1.003,
    но на баре пивота high==level по определению равного хая → флаг НИКОГДА не горел (0/2000
    баров). Теперь сканируем бары ПОСЛЕ 2-го пивота до первого пробоя = момент свипа.
    detect_equal_levels → List[(ts1, p1, ts2, p2, kind)] — пара равных пивотов."""
    from core.smc.smc_engine import detect_equal_levels

    n = len(df)
    high, low = df["high"].values, df["low"].values
    levels = detect_equal_levels(df)
    eqh = np.zeros(n, dtype=bool)
    eql = np.zeros(n, dtype=bool)

    for lvl in levels:
        ts2, kind = lvl[2], lvl[4]                    # 2-й пивот = конец формирования уровня
        i2 = df.index.get_loc(ts2) if hasattr(ts2, "timestamp") else int(ts2)
        # уровень ликвидности: EQH берём выше из пары (пробить надо его), EQL — ниже
        lvl_price = max(lvl[1], lvl[3]) if kind == "EQH" else min(lvl[1], lvl[3])
        for b in range(i2 + 1, n):                    # первый бар ПОСЛЕ, что снимает уровень
            if kind == "EQH" and high[b] > lvl_price * 1.003:
                eqh[b] = True
                break
            if kind == "EQL" and low[b] < lvl_price * 0.997:
                eql[b] = True
                break

    return {"eqh_sweep": eqh, "eql_sweep": eql}


def etl_swing_structure(df: pd.DataFrame) -> Dict[str, np.ndarray]:
    """ARCH-128 Шаг 2: явные HH/HL/LH/LL флаги — тип swing-точки (состояние структуры).

    classify_structure (LuxAlgo Swings=50): HH/LH для вершин, LL/HL для доньев.
    Отличается от BOS/CHoCH (слом) и regime (грубый режим) — это ДЕТАЛЬНЫЙ тип точки.
    Майнинг: «вход на HL в восходящей», «LH перед сломом» и т.п.
    """
    from core.smc.smc_engine import classify_structure

    n = len(df)
    hh = np.zeros(n, dtype=bool); hl = np.zeros(n, dtype=bool)
    lh = np.zeros(n, dtype=bool); ll = np.zeros(n, dtype=bool)
    for ts, _price, label in classify_structure(df):
        bar = _bar_of(df, ts, n)
        if bar is None:
            continue
        if label == "HH": hh[bar] = True
        elif label == "HL": hl[bar] = True
        elif label == "LH": lh[bar] = True
        elif label == "LL": ll[bar] = True
    return {"hh": hh, "hl": hl, "lh": lh, "ll": ll}


# ── ARCH-128 Шаг 2 (Claude): fvg_overlap / elliott / regime троичный ──────────
def _bar_of(df, ts_or_idx, n):
    """Timestamp|int → позиция бара (или None если вне диапазона)."""
    bar = df.index.get_loc(ts_or_idx) if hasattr(ts_or_idx, "timestamp") else int(ts_or_idx)
    return bar if 0 <= bar < n else None


def etl_fvg_overlap(df: pd.DataFrame) -> Dict[str, np.ndarray]:
    """ARCH-128 Шаг 2: перекрытие bull×bear FVG = зона разворота (вероятностная).

    detect_fvg_overlap → [dict(lo, hi, direction up/down, since, held, ...)].
    up→bull-разворот, down→bear. held = зона удержалась на откате (подтверждение).
    """
    from core.smc.smc_engine import detect_fvg_overlap

    n = len(df)
    bull_ov = np.zeros(n, dtype=bool); bear_ov = np.zeros(n, dtype=bool)
    bull_ov_held = np.zeros(n, dtype=bool); bear_ov_held = np.zeros(n, dtype=bool)
    for o in detect_fvg_overlap(df):
        bar = _bar_of(df, o["since"], n)
        if bar is None:
            continue
        if o["direction"] == "up":
            bull_ov[bar] = True
            if o.get("held"): bull_ov_held[bar] = True
        else:
            bear_ov[bar] = True
            if o.get("held"): bear_ov_held[bar] = True
    ret = {"bull_fvg_overlap": bull_ov, "bear_fvg_overlap": bear_ov,
           "bull_fvg_overlap_held": bull_ov_held, "bear_fvg_overlap_held": bear_ov_held}
    _add_dir_meta(ret, "fvg_overlap", "up")  # up → bull/+1
    return ret


def etl_elliott(df: pd.DataFrame) -> Dict[str, np.ndarray]:
    """ARCH-128 Шаг 2: Эллиотт 5-волновой импульс (направление + textbook).

    Флаг ставится на баре волны 5 (конец импульса) — там завершается структура.
    elliott_textbook = фибо-соотношения волн в норме (сильная разметка).
    """
    from core.smc.smc_engine import zigzag_atr, detect_elliott_impulse

    n = len(df)
    bull_imp = np.zeros(n, dtype=bool); bear_imp = np.zeros(n, dtype=bool)
    textbook = np.zeros(n, dtype=bool)
    for imp in detect_elliott_impulse(zigzag_atr(df)):
        bar = _bar_of(df, imp["waves"][5][0], n)
        if bar is None:
            continue
        if imp["direction"] == "up":
            bull_imp[bar] = True
        else:
            bear_imp[bar] = True
        if imp.get("textbook"):
            textbook[bar] = True
    return {"elliott_bull_impulse": bull_imp, "elliott_bear_impulse": bear_imp,
            "elliott_textbook": textbook}


# etl_regime УДАЛЁН (03.06, решение ARCH): regime-классификатор не нужен — торгуем ДВИЖЕНИЯ,
# не боковик. Любой regime врёт/дёргается (ARCH-124 уже доказал). Направление = ATR-trend + HH/HL
# (прямые признаки). Стратегия = волна(Эллиотт) + зона входа(OTE/FVG/OB) + TP-цели, а не режим.
# Изучали Range Filter (=ATR-trend) + Range Detector (боковик) + debounce — рабочий honest-regime
# получился, НО боковик стратегически не нужен → не внедрён. Прототипы: tmp_charts/regime_*.png.
