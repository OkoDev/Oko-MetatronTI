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
        # 🔴 13.08.2026: было f[0] = ts_left (ЛЕВЫЙ бар формации, i-2) → флаг ставился
        # за 2 бара ДО того, как формация становится известна. В бэктесте это давало
        # look-ahead (WR 96.3% вместо 43.8%, PF 52.55 вместо 0.72), в бою — слепоту:
        # на текущем баре флага не было. Берём f[4] = ts_i — бар ОБНАРУЖЕНИЯ гэпа.
        # Контракт кортежа detect_fvg: (ts_left, top, bottom, kind, ts_i, mitigated).
        bar_raw, l1, l2, direction = f[4], f[1], f[2], f[3]
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

    close = df["close"].values
    bull_idx, bear_idx = [], []
    bull_near, bear_near = [], []
    _ATR_OB = _atr_pct(df)      # масштаб ТФ для порогов «цена у блока» (фикс 10.09)

    # 🔴 ФИКС 04.09.2026. Здесь стоял `active_order_blocks(obs, n_bars=30, per_side=5)` —
    # функция ОТРИСОВКИ, а не истории: она отдаёт блоки, живые на ПОСЛЕДНЕМ баре ряда
    # (её `n_bars` вообще не используется в теле, мёртвый параметр), и берёт лишь по 5
    # штук с каждой стороны. Итог: на 19 851 баре помечалось 4–5 — признак в матрице
    # существовал, но был почти всегда False, что неотличимо от «эджа нет»
    # ([[law_no_finding_means_no_feature]]).
    #
    # Для матрицы нужна ИСТОРИЯ, а не текущая картинка: берём ВСЕ блоки. Причинность
    # сохранена — `break_idx` это бар слома, на котором блок и становится известен
    # (лаг детектора 0, `SMC_DETECTOR_CONTRACTS`).
    for ob in obs:
        idx = ob.break_idx
        if not (0 <= idx < n):
            continue
        # окно жизни блока: от формирования до митигации (или до конца данных).
        # 🔴 `mitigated_idx` смотрит вперёд по построению, поэтому используем его
        # ТОЛЬКО как границу «блок ещё жив», а не как самостоятельный признак.
        end = ob.mitigated_idx if ob.mitigated_idx >= 0 else n
        stop = min(idx + 10, end, n)
        # 🔴 ФИКС 10.09.2026: окно «цена у блока» было АБСОЛЮТНЫМ (−0.5%…+3%).
        # Диагностика по гиперкубу: bull_ob_near схлопывался 2.42% → 0.00% с ростом ТФ
        # (дрейф 0.000) — на старших окнах признак не срабатывал НИКОГДА.
        # Границы переведены в доли ATR(14) своего ТФ, множители откалиброваны по 15m:
        # ATR(15m) ≈ 0.62% ⇒ −0.5% = −0.81·ATR, +3% = +4.84·ATR.
        if ob.kind == "bull":
            bull_idx.append(idx)
            for j in range(idx, stop):
                a = _ATR_OB[j] if _ATR_OB is not None and not np.isnan(_ATR_OB[j]) else 0.62
                if -0.81 * a <= (close[j] - ob.top) / close[j] * 100 <= 4.84 * a:
                    bull_near.append(j)
        else:
            bear_idx.append(idx)
            for j in range(idx, stop):
                a = _ATR_OB[j] if _ATR_OB is not None and not np.isnan(_ATR_OB[j]) else 0.62
                if -0.81 * a <= (ob.bottom - close[j]) / close[j] * 100 <= 4.84 * a:
                    bear_near.append(j)

    # ARCH-128 Шаг 2: митигация OB (флаг на баре пробоя блока) — из ВСЕХ obs, не только active
    bull_mit = [ob.mitigated_idx for ob in obs if ob.kind == "bull" and ob.mitigated_idx >= 0]
    bear_mit = [ob.mitigated_idx for ob in obs if ob.kind == "bear" and ob.mitigated_idx >= 0]

    # 🧱 BREAKER BLOCK (20.08.2026): пробитый OB МЕНЯЕТ РОЛЬ. Флаг ставится на барах,
    # где цена ТЕСТИРУЕТ зону уже после пробоя — это и есть вход по схеме ICT.
    #   bear-OB пробит вверх  → бывшее сопротивление стало ПОДДЕРЖКОЙ (bull_breaker)
    #   bull-OB пробит вниз   → бывшая поддержка стала СОПРОТИВЛЕНИЕМ (bear_breaker)
    # Каузально: бары строго ПОСЛЕ mitigated_idx. Окно теста 30 баров.
    # Замер 20.08: breaker — лучший ОДИНОЧНЫЙ фактор конфлюэнции по OOS (1.80).
    bull_brk, bear_brk = [], []
    for ob in obs:
        m = ob.mitigated_idx
        if m < 0 or m >= n:
            continue
        lo, hi = min(ob.top, ob.bottom), max(ob.top, ob.bottom)
        for j in range(m + 1, min(m + 31, n)):
            if lo * 0.997 <= close[j] <= hi * 1.003:
                (bull_brk if ob.kind == "bear" else bear_brk).append(j)

    ret = {"bull_ob": _to_bool_array(n, bull_idx), "bear_ob": _to_bool_array(n, bear_idx),
            "bull_ob_near": _to_bool_array(n, bull_near), "bear_ob_near": _to_bool_array(n, bear_near),
            "bull_ob_mitigated": _to_bool_array(n, bull_mit), "bear_ob_mitigated": _to_bool_array(n, bear_mit),
            "bull_breaker": _to_bool_array(n, bull_brk), "bear_breaker": _to_bool_array(n, bear_brk)}
    _add_dir_meta(ret, "ob", "bull")
    return ret


def etl_bos_choch(df: pd.DataFrame) -> Dict[str, np.ndarray]:
    """BOS/CHoCH из ДВУХСЛОЙНОГО эталона OKO-SM (ARCH-137.5, 02.09.2026).

    Было — ТРИ источника структуры в одних массивах: `detect_structure_breaks`
    на `choch_length` (=50) + примесь `find_setups_zz` (zigzag_atr). Замер 02.09
    по 4757 живым сделкам: BOS/CHoCH присутствовали лишь в **1.3%** снимков,
    против FVG 88% и pivot 100%. Следствие — из 75 флагов, набравших статистику
    в 200 паттернах arch104, структурных **ноль**: майнинг просто не видел слома.

    Стало — один эталон, оба слоя сразу (`run_structure(swing_len=50,
    internal_len=5)`):
      · старший слой (swing, len=50)   → `bull_bos` / `bear_bos` / `*_choch`
        — та же семантика, что раньше, сопоставимо со старыми замерами;
      · микроструктура (internal, len=5) → `*_i`-флаги, которых НЕ БЫЛО вовсе.

    Примесь zigzag убрана: разные движки, писавшие в одно поле, — это то самое
    дублирование, из-за которого один и тот же слом получал разную метку.
    Смена состава → `feature_snapshot.SCHEMA_VERSION` поднят до 5, старые снимки
    в обучение не смешиваются.
    """
    from core.smc.oko_sm_engine import run_structure

    n = len(df)
    st = run_structure(df, swing_len=_get_choch_length(), internal_len=5,
                       record_legs=False)

    idx: Dict[str, List[int]] = {k: [] for k in (
        "bull_bos", "bear_bos", "bull_choch", "bear_choch",
        "bull_bos_i", "bear_bos_i", "bull_choch_i", "bear_choch_i")}
    for e in st.events:
        key = f"{'bull' if e.bull else 'bear'}_{'bos' if e.kind == 'BOS' else 'choch'}"
        if e.internal:
            key += "_i"
        idx[key].append(e.i)

    ret = {k: _to_bool_array(n, v) for k, v in idx.items()}

    # ── ЭПИК B (04.09): СОГЛАСОВАНИЕ ДВУХ МАСШТАБОВ = ГЕОМЕТРИЯ ВХОДА ──────────
    # Метод Егора: старший масштаб задаёт СТОРОНУ, младший — МОМЕНТ. До этого
    # матрица знала, куда смотрит старшая структура, и не знала НИ ОДНОГО признака
    # того, КОГДА входить — искать триггер в наборе без триггеров невозможно.
    # Признаки названы ЗАРАНЕЕ (`sc_pullback`/`sc_resume`, `matrix_full.py:476`),
    # то есть защищены от подгонки под результат; здесь они собираются поверх
    # ЭТАЛОНА, а не копией research-кода — иначе получим третий движок структуры.
    #
    # Причинность: событие эталона известно на баре подтверждения (лаг 0 у
    # `run_structure`), но состояние «после события» читаем со сдвигом на бар —
    # `np.roll` + обнуление первого элемента, как `.shift(1)` в research-версии.
    maj_dir = np.zeros(n, dtype=np.int8)     # +1 бычий старший слом, −1 медвежий
    min_dir = np.zeros(n, dtype=np.int8)
    maj_is_bos = np.zeros(n, dtype=bool)     # старший идёт ПРОДОЛЖЕНИЕМ, не разворотом
    cur_maj = cur_min = 0
    cur_maj_bos = False
    ev_by_bar: Dict[int, list] = {}
    for e in st.events:
        ev_by_bar.setdefault(e.i, []).append(e)
    for i in range(n):
        for e in ev_by_bar.get(i, ()):
            if e.internal:
                cur_min = 1 if e.bull else -1
            else:
                cur_maj = 1 if e.bull else -1
                cur_maj_bos = (e.kind == "BOS")
        maj_dir[i] = cur_maj
        min_dir[i] = cur_min
        maj_is_bos[i] = cur_maj_bos

    def _lag1(a: np.ndarray) -> np.ndarray:
        out = np.roll(a, 1)
        if len(out):
            out[0] = 0 if out.dtype != bool else False
        return out

    maj_dir, min_dir, maj_is_bos = _lag1(maj_dir), _lag1(min_dir), _lag1(maj_is_bos)
    both = (maj_dir != 0) & (min_dir != 0)
    agree = both & (maj_dir == min_dir)
    against = both & (maj_dir != min_dir)

    # ОТКАТ ПО ТРЕНДУ: старший в продолжении (BOS), младший сломался ПРОТИВ него.
    # Это точка входа по тренду, а НЕ разворот — не путать с mean-reversion.
    ret["sc_pullback"] = against & maj_is_bos
    # ВОЗОБНОВЛЕНИЕ: младший вернулся на сторону старшего — откат закончен.
    ret["sc_resume"] = agree
    # Сторона согласования — чтобы отбор мог искать раздельно по long/short.
    ret["sc_pullback_bull"] = ret["sc_pullback"] & (maj_dir > 0)
    ret["sc_pullback_bear"] = ret["sc_pullback"] & (maj_dir < 0)
    ret["sc_resume_bull"] = agree & (maj_dir > 0)
    ret["sc_resume_bear"] = agree & (maj_dir < 0)

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
    from core.smc.smc_engine import confirmed_swings
    _LEN = 20
    _sw = sorted(confirmed_swings(df, _LEN), key=lambda x: x[0])   # [(idx, price, 'H'/'L')]
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
    # 🔴 FIX 13.08.2026 (Егор «проверить наборы ote_nested на правильность детекции импульса»):
    # было — ОДНА зона от find_choch_ote(breaks, df), то есть от ПОСЛЕДНЕГО CHoCH всей истории,
    # и она красила ВСЕ бары `for i in range(n)`. Пока CHoCH не случился, зоны нет; как только
    # случился — она ретроактивно подсвечивала прошлое. Замер видимости: ote_short лаг >20 баров
    # на 100% событий, ote_long — на 67%. Весь ote_nested стоял на этом.
    # Стало — rolling, как у premium/discount выше: зона действует ТОЛЬКО с бара своего CHoCH
    # до следующего. find_choch_ote переиспользуется на префиксе (вызовов = число CHoCH,
    # не число баров) — формула не дублируется, ARCH-118 «один калькулятор» соблюдён.
    _choch_pos = [j for j, b in enumerate(breaks) if b.kind == "CHoCH"]
    _OTE_SW_LEN = 20
    _sw_all = _sw if _sw else confirmed_swings(df, _OTE_SW_LEN)   # считаем ОДИН раз
    for _k, _j in enumerate(_choch_pos):
        _b = breaks[_j]
        _bi = getattr(_b, "idx", None)
        if _bi is None or not (0 <= _bi < n):
            continue
        # swings, ПОДТВЕРЖДЁННЫЕ к бару слома (swing на idx виден только через _OTE_SW_LEN баров)
        _sw_ok = [s for s in _sw_all if s[0] + _OTE_SW_LEN <= _bi]
        if len(_sw_ok) < 2:
            continue
        _co = find_choch_ote(breaks[:_j + 1], df, swing_len=_OTE_SW_LEN, swings=_sw_ok)
        if not _co:
            continue
        # build_ote возвращает зону под ключом 'ote', НЕ 'ote_zone' (FIX 12.07, Егор «копай глубже»):
        # get дефолтил (0,0) → 0<=c<=0 никогда → ote_long/ote_short был мёртв с ARCH-128.
        zone = _co.get("ote", _co.get("ote_zone", (0, 0)))
        direction = _co.get("direction", "")
        if not direction or zone[1] <= 0:
            continue
        _end = breaks[_choch_pos[_k + 1]].idx if _k + 1 < len(_choch_pos) else n
        _end = min(max(_end, _bi), n)
        for i in range(_bi, _end):
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

    classify_structure (опорные точки окна 50): HH/LH для вершин, LL/HL для доньев.
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
        # 🔴 13.08.2026: `held` — утверждение о барах ПОСЛЕ since (зона удержалась),
        # раньше ставилось на сам since → look-ahead. Теперь флаг held идёт на бар
        # held_ts = since + hold_bars, когда удержание реально известно.
        hbar = _bar_of(df, o.get("held_ts"), n) if o.get("held_ts") is not None else None
        if hbar is None:
            hbar = bar
        if o["direction"] == "up":
            bull_ov[bar] = True
            if o.get("held"): bull_ov_held[hbar] = True
        else:
            bear_ov[bar] = True
            if o.get("held"): bear_ov_held[hbar] = True
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


# ── ЛИКВИДНОСТЬ (04.09, ЭПИК B): кластеры свингов — семьи в матрице НЕ БЫЛО ──────
# `core/smc/liquidity.py:detect_liquidity` стоял в MATRIX_REGISTRY:325 как «❌ НЕТ».
# EQH/EQL (`etl_eql_eql`) — это ПАРА равных пивотов; здесь КЛАСТЕР из N свингов с силой
# (сколько стопов накоплено) и статусом снятия. Родственник ERL, но не он: ERL —
# граница 96-барового окна ([[erl_distance_gate_candidate]]), здесь — уровни скоплений.
#
# 🔴 ПОЧЕМУ НЕ ПЕРЕИСПОЛЬЗОВАНЫ `_cluster_swings` / `_track_sweeps` (закон reuse):
#   1. `_cluster_swings` кластеризует ВСЮ историю разом — для серии по барам его пришлось
#      бы звать на каждом баре заново (O(n·k log k), десятки секунд на 40k баров);
#   2. `_track_sweeps` стартует с `max(swing_indices) + 1` — с бара ПОСЛЕ свинга, тогда как
#      свинг подтверждается только через `length` баров. В live это безвредно (всё в прошлом),
#      в матрице дало бы look-ahead: зона «снята» раньше, чем мы могли о ней узнать.
# Поэтому зоны ведутся ОНЛАЙН — ровно так, как возникали бы в реальном времени.
# Причинность по построению: ни одного обращения к будущему.
_LIQ_SW_LEN = 20          # та же длина свингов, что у OTE-семьи (etl_ote_premium:_LEN)
_LIQ_TOL_PCT = 0.3        # допуск кластеризации — дефолт боевого detect_liquidity
# 🔴 ФИКС 10.09.2026. Здесь стоял АБСОЛЮТНЫЙ порог `_LIQ_NEAR_PCT = 0.5` (% от цены).
# Диагностика по гиперкубу: частота liq_near падала 16.26% → 0.10% с ростом ТФ
# (дрейф 0.006), то есть на старших окнах признак МЁРТВ по построению — расстояния
# до уровней растут с масштабом, а порог оставался фиксированным.
# Это ровно [[law_no_finding_means_no_feature]]: «находок нет» = нет признака.
# Порог переведён в доли ATR(14) своего ТФ. Множитель откалиброван так, чтобы на 15m
# порог остался прежним (ATR(14) на 15m ≈ 0.62% ⇒ 0.81·ATR ≈ 0.5%) — поведение на
# боевом ТФ не меняется, старшие окна оживают.
_LIQ_NEAR_ATR = 0.81      # «цена у зоны» = ближе 0.81·ATR(14)
_LIQ_NEAR_PCT_FALLBACK = 0.5   # если ATR не считается (короткий ряд)


def _atr_pct(df: pd.DataFrame, period: int = 14) -> np.ndarray:
    """ATR(period) в ПРОЦЕНТАХ цены — общая мера масштаба для порогов «цена у зоны».
    True Range с учётом гэпов; на первых барах — расширяющееся окно."""
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    prev = np.concatenate(([c[0]], c[:-1]))
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev), np.abs(l - prev)))
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.where(c > 0, tr / c * 100.0, np.nan)
    s = pd.Series(rel).rolling(period, min_periods=max(2, period // 3)).mean()
    return s.to_numpy(dtype=float)


def etl_liquidity(df: pd.DataFrame) -> Dict[str, np.ndarray]:
    """Зоны ликвидности как СЕРИЯ: дистанция до ближайшей, сила, момент снятия.

    BUY-side — кластеры swing-highs (стопы шортистов, выше цены);
    SELL-side — кластеры swing-lows (стопы лонгистов, ниже цены).
    Свинг на баре `idx` подтверждается через `_LIQ_SW_LEN` баров ⇒ зона рождается
    на `idx + _LIQ_SW_LEN`, раньше её не существует.
    """
    from core.smc.smc_engine import confirmed_swings

    n = len(df)
    nan = float("nan")
    up_d = np.full(n, nan); dn_d = np.full(n, nan)
    up_n = np.full(n, nan); dn_n = np.full(n, nan)
    sw_up = np.zeros(n, dtype=bool); sw_dn = np.zeros(n, dtype=bool)

    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)

    # свинг → бар, с которого он ИЗВЕСТЕН
    born: Dict[int, List[tuple]] = {}
    for idx, price, kind in confirmed_swings(df, _LIQ_SW_LEN):
        b = int(idx) + _LIQ_SW_LEN
        if b < n:
            born.setdefault(b, []).append((float(price), kind))

    # активные зоны: [level, count, side] — side 'H' (buy-side) / 'L' (sell-side)
    zones: List[list] = []

    for b in range(n):
        for price, kind in born.get(b, ()):                # 1) родившиеся зоны
            for z in zones:
                if z[2] == kind and z[0] > 0 and abs(price - z[0]) / z[0] * 100 <= _LIQ_TOL_PCT:
                    z[0] = (z[0] * z[1] + price) / (z[1] + 1)   # средний уровень кластера
                    z[1] += 1
                    break
            else:
                zones.append([price, 1, kind])

        alive = []                                          # 2) снятие на ЭТОМ баре
        for z in zones:
            tol = z[0] * _LIQ_TOL_PCT / 100.0
            if z[2] == "H" and high[b] > z[0] + tol:
                sw_up[b] = True                             # сняли buy-side (стопы шортов)
            elif z[2] == "L" and low[b] < z[0] - tol:
                sw_dn[b] = True
            else:
                alive.append(z)
        zones = alive

        c = close[b]                                        # 3) ближайшие активные
        if c <= 0:
            continue
        up = [z for z in zones if z[2] == "H" and z[0] > c]
        dn = [z for z in zones if z[2] == "L" and z[0] < c]
        if up:
            z = min(up, key=lambda z: z[0])
            up_d[b] = (z[0] - c) / c * 100.0
            up_n[b] = z[1]
        if dn:
            z = max(dn, key=lambda z: z[0])
            dn_d[b] = (c - z[0]) / c * 100.0
            dn_n[b] = z[1]

    # порог «цена у зоны» — в долях ATR своего ТФ, а не фиксированные 0.5% (фикс 10.09)
    thr = _LIQ_NEAR_ATR * _atr_pct(df)
    thr = np.where(np.isnan(thr), _LIQ_NEAR_PCT_FALLBACK, thr)
    with np.errstate(invalid="ignore"):
        near_up = np.nan_to_num(up_d, nan=1e9) < thr
        near_dn = np.nan_to_num(dn_d, nan=1e9) < thr

    return {"liq_up_dist_pct": up_d, "liq_dn_dist_pct": dn_d,
            "liq_up_strength": up_n, "liq_dn_strength": dn_n,
            "liq_sweep_up": sw_up, "liq_sweep_dn": sw_dn,
            "liq_near_up": near_up, "liq_near_dn": near_dn}


def etl_smc_ext(df: pd.DataFrame) -> Dict[str, np.ndarray]:
    """SMC-extensions в матрицу (04.09, ЭПИК B): inducement + liquidity void.

    Оба числились в MATRIX_REGISTRY:324 как «❌ НЕТ В МАТРИЦЕ».
      · inducement — ложный пробой равных уровней с возвратом (stop hunt);
      · liquidity void — широкий импульсный бар, к середине которого цена не вернулась
        (магнит: рынок склонен возвращаться в пустоту).

    🔴 `detect_breaker_block` СЮДА НЕ ВНЕСЁН НАМЕРЕННО: детектор существует, но его эдж
    уже мерился и НЕ подтвердился ([[breaker_detector_real_vs_claimed]]). Вносить признак
    с известным отсутствием эджа = растить множественность без шанса на находку.

    🔴 `detect_inducement` содержал look-ahead (флаг на баре свипа зависел от закрытий
    i+1/i+2) — починен 04.09 в источнике: флаг встаёт на бар ПОДТВЕРЖДЁННОГО возврата.
    Оба прошли префиксный тест: 0 расхождений на t=1500/2500/3400.
    """
    from core.smc.smc_extensions import detect_inducement, detect_liquidity_void

    bull_ind, bear_ind = detect_inducement(df)
    bull_void, bear_void = detect_liquidity_void(df)
    return {"inducement_bull": bull_ind, "inducement_bear": bear_ind,
            "liq_void_bull": bull_void, "liq_void_bear": bear_void}


# etl_regime УДАЛЁН (03.06, решение ARCH): regime-классификатор не нужен — торгуем ДВИЖЕНИЯ,
# не боковик. Любой regime врёт/дёргается (ARCH-124 уже доказал). Направление = ATR-trend + HH/HL
# (прямые признаки). Стратегия = волна(Эллиотт) + зона входа(OTE/FVG/OB) + TP-цели, а не режим.
# Изучали Range Filter (=ATR-trend) + Range Detector (боковик) + debounce — рабочий honest-regime
# получился, НО боковик стратегически не нужен → не внедрён. Прототипы: tmp_charts/regime_*.png.
