"""МАТРИЦА OTE (Егор 02.07) — живая таблица OTE-зон всех ТФ с состоянием.

Идея: система ВСЕГДА держит матрицу OTE-зон (4h/1h/15m/5m). Зоны появляются при сломе, инвалидируются
при пробое/устаревании. Старшая активная зона = ЦЕЛЬ+НАПРАВЛЕНИЕ; младшие зоны в том же направлении =
входы ПО ПУТИ к старшей цели. Пока цена не дошла до старшей OTE — новые младшие входы туда же.
Изолированная младшая нога вне контекста старшего = ШУМ (корень слива на 15m в зоне 4h).

Reuse: ote_retest_setups + build_ote (core.smc.smc_engine). Не дублирует детекторы.
[[ote_matrix_concept]] [[mtf_nested_zigzag_principle]]. Пока research-слой (визуал-валидация через TW-MCP).
"""
from __future__ import annotations

from core.smc.smc_engine import ote_retest_setups, build_ote, detect_structure_breaks, zigzag_atr, _zz_typed


def _atr(df, n: int = 14) -> float:
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    import pandas as _pd
    tr = _pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    v = tr.rolling(n).mean().iloc[-1]
    return float(v) if v == v else 0.0    # NaN-guard


def _lookback_for_tf(df, target_days: float = 12.0, floor: int = 150) -> int:
    """КАЛЕНДАРНО-адаптивный lookback (Егор 02.07 «15m и 1h слом одинаковый»): окно в БАРАХ
    рассчитывается так, чтобы каждый ТФ покрывал ~одинаковый КАЛЕНДАРНЫЙ период (target_days).
    Иначе младший ТФ с фикс-окном в барах видит слишком мало (15m@250бар=2.6дн НЕ достаёт до
    значимой ноги 7дн назад → ловит шум → ЛОЖНЫЙ переворот). ТФ определяется по шагу индекса."""
    try:
        step_min = (df.index[-1] - df.index[-2]).total_seconds() / 60.0
        if step_min <= 0:
            return max(floor, 250)
        bars = int(target_days * 1440.0 / step_min)
        return max(floor, min(bars, len(df)))
    except Exception:
        return max(floor, 250)


def structure_trend(df, k: int = 2, lookback: int | None = None, atr_mult: float = 0.5,
                    min_move_floor: float = 0.0):
    """ПРАВИЛО ЕГОРА (02.07, визуал GRT/TW-MCP) + КАЛЕНДАРНО-адаптивный lookback. Валидировано на
    GRT 4h: воспроизводит разметку Егора (break=0.01872 = последний ХАЙ перед LL 0.01709, SHORT).

    Механика: даунтренд = делаем более низкие лои (LL); слом = ПОСЛЕДНИЙ хай ПЕРЕД новым LL (не
    последний хай вообще — отскок ПОСЛЕ лоя не слом). Higher Low после LL = консолидация, слом НЕ
    трогаем (держим до пробоя). Пробой слома вверх close>break = CHoCH в лонг. Симметрично аптренд.

    Адаптивность к ТФ (Егор): (1) значимость свинга = ATR-порог atr_mult*ATR (ATR масштабируется под
    ТФ); (2) lookback=КАЛЕНДАРНЫЙ (target_days) — каждый ТФ видит ~одинаковый период, младшие достают
    до значимой ноги (иначе фикс-бары → 15m шумит → ложный переворот, Егор поймал 02.07).
    ⚠️ ТОЧНЫЙ общий слом младший=старший (15m=1h=0.01872) = модель ВЛОЖЕННОСТИ (младший наследует
    значимый слом старшего) — НЕ решается изолированным per-ТФ фракталом, см. [[mtf_nested_zigzag_principle]].

    Возвращает {trend: 'long'/'short'/None, break_level, extreme, broken, break_ts, extreme_ts,
    impulse_origin, origin_ts}. break_level = СКОЛЬЗЯЩИЙ CHoCH-уровень (последний H/L перед
    последним LL/HH — дрейфует, для детекта флипа). impulse_origin = Strong High/Low: экстремум,
    чей пробой дал флип; НЕ дрейфует. НОГА для OTE-целей = origin→extreme (НЕ break→extreme —
    Егор 07.07, ETH: нога 2464→1504, а не 2157→1504).
    """
    try:
        if lookback is None:
            lookback = _lookback_for_tf(df)
        a = _atr(df)
        # СВЯЗНОСТЬ (Егор 02.07): порог значимости = max(свой ATR, floor от старшего). Младший видит
        # структурные точки НЕ мельче значимости старшего → боковик младшего не плодит ложных сломов.
        minmove = max(atr_mult * a, min_move_floor)
        h = df["high"].values; l = df["low"].values; idx = df.index
        n = len(df); lo = max(k, n - lookback)
    except Exception:
        return {"trend": None, "break_level": None, "broken": False}
    if n < 2 * k + 5:
        return {"trend": None, "break_level": None, "broken": False}
    # фрактальные пивоты (локальные пики/впадины, окно ±k)
    piv = []
    for i in range(lo, n - k):
        wh = h[i - k:i + k + 1]; wl = l[i - k:i + k + 1]
        if h[i] == wh.max() and list(wh).count(h[i]) == 1:
            piv.append((idx[i], float(h[i]), "H"))
        elif l[i] == wl.min() and list(wl).count(l[i]) == 1:
            piv.append((idx[i], float(l[i]), "L"))
    # collapse одинаковых подряд (держим экстремум) + ATR-значимость (мелкий противосвинг = шум)
    col = []
    for p in piv:
        if col and col[-1][2] == p[2]:
            if (p[2] == "H" and p[1] > col[-1][1]) or (p[2] == "L" and p[1] < col[-1][1]):
                col[-1] = p
        elif col and abs(p[1] - col[-1][1]) < minmove:
            continue
        else:
            col.append(p)
    # СТРУКТУРА (правило Егора = market-structure BOS/CHoCH на ЗАЩИЩЁННЫХ уровнях, без залипания и
    # без ложного флипа на отскок). Идём по значимым пивотам в хронологии:
    #  • short: слом = последний H перед LL (защищённый хай). Флип в LONG ТОЛЬКО когда пивот-хай
    #    ПРОБИВАЕТ этот защищённый хай (CHoCH up), а не любой предыдущий хай (отскок в даунтренде).
    #  • long: слом = последний L перед HH (защищённый лой). Флип в SHORT когда пивот-лой пробивает его.
    # Так GRT остаётся short (отскоки 0.01855 < защищённого 0.01872), а XLM флипает long (0.18755
    # пробил защищённый 0.17934 → CHoCH up → слом=последний лой 0.17373).
    # СТРУКТУРНЫЕ экстремумы ноги (НЕ последний пивот!): слом обновляется только при пробое
    # структурного min/max. Higher Low в даунтренде = консолидация, слом НЕ дрейфует (был баг:
    # сравнивал с пред. пивотом → откат-лои дрейфовали слом 0.01872→0.01811).
    def _last(kind_want, upto):        # последний пивот нужного типа ДО индекса upto → (t, p)
        for tt, pp, kk in reversed(col[:upto]):
            if kk == kind_want:
                return (tt, pp)
        return None
    # break_pt/extreme_pt = (time, price) для точной отрисовки ноги на РОДНОМ ТФ (не по цене!)
    # impulse_origin (07.07, Егор «нога ОТЕ = вершина ВСЕГО импульса», ETH-кейс 2464 vs 2157):
    # Strong High/Low — экстремум, чей пробой дал ФЛИП (CHoCH). Фиксируется в момент флипа
    # и НЕ дрейфует при новых LL/HH (break_level дрейфует — он CHoCH-уровень инвалидации,
    # а origin = начало ноги для OTE-целей). ETH 1d: origin=2464 (17.04), break=2157 (21.05).
    trend = None; break_level = None; break_ts = None
    origin = None; origin_ts = None
    struct_low = None; struct_high = None; ext_ts = None
    for i, (t, p, kind) in enumerate(col):
        if kind == "L":
            if trend == "long":
                if break_level is not None and p < break_level:        # пробой защищённого лоя = CHoCH down
                    trend = "short"
                    hb = _last("H", i)
                    if hb: break_ts, break_level = hb
                    if hb: origin_ts, origin = hb                      # вершина импульса (Strong High)
                    struct_low = p; ext_ts = t; struct_high = None
            elif trend == "short":
                if struct_low is None or p < struct_low:               # новый СТРУКТУРНЫЙ LL
                    hb = _last("H", i)
                    if hb: break_ts, break_level = hb                  # слом дрейфует; origin — НЕТ
                    struct_low = p; ext_ts = t
            else:                                                       # инициализация short
                if struct_low is not None and p < struct_low:
                    hb = _last("H", i)
                    if hb: trend = "short"; break_ts, break_level = hb; ext_ts = t
                    if hb: origin_ts, origin = hb
                if struct_low is None or p < struct_low:
                    struct_low = p; ext_ts = t if trend == "short" else ext_ts
        else:
            if trend == "short":
                if break_level is not None and p > break_level:        # пробой защищённого хая = CHoCH up
                    trend = "long"
                    lb = _last("L", i)
                    if lb: break_ts, break_level = lb
                    if lb: origin_ts, origin = lb                      # дно импульса (Strong Low)
                    struct_high = p; ext_ts = t; struct_low = None
            elif trend == "long":
                if struct_high is None or p > struct_high:             # новый СТРУКТУРНЫЙ HH
                    lb = _last("L", i)
                    if lb: break_ts, break_level = lb
                    struct_high = p; ext_ts = t
            else:                                                       # инициализация long
                if struct_high is not None and p > struct_high:
                    lb = _last("L", i)
                    if lb: trend = "long"; break_ts, break_level = lb; ext_ts = t
                    if lb: origin_ts, origin = lb
                if struct_high is None or p > struct_high:
                    struct_high = p; ext_ts = t if trend == "long" else ext_ts
    close = float(df["close"].values[-1])
    broken = ((trend == "short" and break_level and close > break_level) or
              (trend == "long" and break_level and close < break_level))
    # экстремум ноги = второй конец импульса (для OTE): short→LL, long→HH.
    extreme = struct_low if trend == "short" else (struct_high if trend == "long" else None)
    return {"trend": trend, "break_level": break_level, "extreme": extreme, "broken": broken,
            "break_ts": break_ts, "extreme_ts": ext_ts,
            "impulse_origin": origin, "origin_ts": origin_ts}

# порядок старший→младший (вес контекста убывает)
TF_ORDER = ["1d", "4h", "1h", "15m", "5m"]


def _zone_state(s, df, price, max_age_bars):
    """Состояние зоны: valid (не устарела/не пробита), active (цена в зоне)."""
    ct = s.get("choch_ts")
    valid = True
    if ct is not None and ct in df.index:
        after = df[df.index > ct]
        # 1. устарела (старше max_age баров от слома)
        if len(after) > max_age_bars:
            valid = False
        # 2. цена пробила SL зоны ДО входа = импульс отменён
        slv = s.get("sl")
        if valid and slv and len(after):
            if s["direction"] == "long" and float(after["low"].min()) < slv:
                valid = False
            elif s["direction"] == "short" and float(after["high"].max()) > slv:
                valid = False
    olo, ohi = s["ote"]
    active = olo <= price <= ohi
    return valid, active


def _target_062(s):
    """Цель зоны = fib -0.62 extension (метод Егора) от импульса зоны."""
    lv = build_ote(s["to"][1], s["from"][1]).get("levels", {})
    return lv.get(-0.62)


def build_ote_matrix(dfs_by_tf: dict, max_age_bars: int = 60) -> dict:
    """Строит матрицу OTE-зон по всем ТФ. dfs_by_tf = {tf: df(DatetimeIndex OHLC)}.

    Возвращает {tf: [zone,...]} где zone = dict(tf, direction, ote_lo, ote_hi, sl, entry,
    target_062, valid, active, from, to, choch_ts). Порядок ТФ: старший→младший.
    """
    matrix = {}
    for tf in TF_ORDER:
        df = dfs_by_tf.get(tf)
        if df is None or len(df) < 100:
            continue
        price = float(df["close"].values[-1])
        try:
            setups = ote_retest_setups(df, only_choch=False, provisional=True)
        except Exception:
            setups = []
        zones = []
        for s in setups:
            valid, active = _zone_state(s, df, price, max_age_bars)
            olo, ohi = s["ote"]
            zones.append({
                "tf": tf, "direction": s["direction"],
                "ote_lo": olo, "ote_hi": ohi, "sl": s.get("sl"),
                "entry": (olo + ohi) / 2, "target_062": _target_062(s),
                "valid": valid, "active": active,
                "from": s["from"][1], "to": s["to"][1], "choch_ts": s.get("choch_ts"),
            })
        matrix[tf] = zones
    return matrix


def trend_direction(df, length: int = 5) -> str | None:
    """Направление структурного тренда = ПРАВИЛО ЕГОРА (structure_trend), НЕ сырой CHoCH.
    Раньше брал последний CHoCH → пила в боковике (визуал GRT 02.07: ложный переворот).
    Теперь: LH давший LL = short-структура, HL давший HH = long. Стабильно, без пилы."""
    return structure_trend(df)["trend"]


def effective_trend(df, min_move_floor: float = 0.0) -> str | None:
    """ФАКТИЧЕСКОЕ направление с учётом пробоя слома: структура short + close>break = уже
    развернулась ВВЕРХ (эффективно long) и наоборот. Именно это ловит переворот младший→старший:
    15m/5m структурно short, но их слом ПРОБИТ вверх → фактически long (разворот идёт снизу)."""
    r = structure_trend(df, min_move_floor=min_move_floor)
    if r["trend"] and r["broken"]:
        return "long" if r["trend"] == "short" else "short"
    return r["trend"]


# СВЯЗНОСТЬ МАТРИЦЫ (Егор 02.07): якорь значимости + доля его ATR как floor для младших
COHERENCE_ANCHOR = "4h"       # значимый масштаб-якорь (крупная нога)
COHERENCE_BETA = 0.5          # floor младших = 0.5*ATR(anchor) — валидировано GRT (убрал ложный флип 5m)


def _coherence_floor(dfs_by_tf: dict) -> tuple:
    """floor значимости для младших ТФ = COHERENCE_BETA * ATR(anchor). Возвращает (floor, anchor_idx)."""
    anchor_df = dfs_by_tf.get(COHERENCE_ANCHOR)
    anchor_idx = TF_ORDER.index(COHERENCE_ANCHOR) if COHERENCE_ANCHOR in TF_ORDER else 1
    if anchor_df is None:                       # fallback: самый старший доступный
        for i, tf in enumerate(TF_ORDER):
            if tf in dfs_by_tf:
                anchor_df, anchor_idx = dfs_by_tf[tf], i; break
    return (COHERENCE_BETA * _atr(anchor_df) if anchor_df is not None else 0.0, anchor_idx)


def coherent_structure(dfs_by_tf: dict) -> dict:
    """СВЯЗНАЯ матрица структуры (Егор: «младшие ТФ ВИДЯТ структурные точки старших, иначе любой
    боковик сломает матрицу»; «15m и 1h слом ОДИНАКОВЫЙ»). Два уровня связности:
      1. floor значимости от anchor (боковик младшего не плодит мелких сломов);
      2. НАСЛЕДОВАНИЕ УРОВНЯ: младшие (< anchor) БЕРУТ направление+слом старшего (общий слом),
         а свой broken считают по ОБЩЕМУ слому и своей (более свежей) цене → младший ПЕРВЫМ
         реагирует на пробой общего слома = переворот младший→старший на СВЯЗНОМ уровне.
    Собственная (тонкая) структура младшего сохраняется в ['own'] для entry-timing (СЛОЙ-2).
    Возвращает {tf: {trend, break_level, broken, [own]}}."""
    floor, anchor_idx = _coherence_floor(dfs_by_tf)
    out = {}
    parent_dir = parent_break = parent_extreme = None      # нога старшего для наследования
    for i, tf in enumerate(TF_ORDER):
        if tf not in dfs_by_tf:
            continue
        df = dfs_by_tf[tf]
        own = structure_trend(df, min_move_floor=(floor if i > anchor_idx else 0.0))
        if i > anchor_idx and parent_dir and parent_break is not None:
            # наследуем НОГУ старшего (направление+слом+экстремум); broken = своя цена пробила общий слом
            close = float(df["close"].values[-1])
            broken = ((parent_dir == "short" and close > parent_break) or
                      (parent_dir == "long" and close < parent_break))
            out[tf] = {"trend": parent_dir, "break_level": parent_break,
                       "extreme": parent_extreme, "broken": broken, "own": own}
        else:
            out[tf] = own
            if own["trend"] and own["break_level"] is not None and i <= anchor_idx:
                parent_dir, parent_break, parent_extreme = own["trend"], own["break_level"], own.get("extreme")
    return out


def ote_matrix(dfs_by_tf: dict) -> dict:
    """OTE-МАТРИЦА ОТ СВЯЗНОЙ СТРУКТУРЫ (Егор 02.07: «раз сломы и матрицу сделали — теперь OTE по
    матрице»). Для каждого ТФ берём НОГУ из coherent_structure (экстремум→слом) и строим OTE-зону
    (фибо-откат 0.5-0.79) + цели (расширение −0.62/−1.0/−1.618). Младшие наследуют ногу старшего
    (связность) → OTE младших ВЛОЖЕНЫ в OTE старшего, а не изолированы (корень слива был в изоляции).

    Возвращает {tf: {direction, ote_lo, ote_hi, entry, sl, target_062, target_1, targets, active,
    in_leg, broken, from, to}} где from=экстремум ноги, to=слом (начало/конец импульса для build_ote).
    active = цена сейчас В OTE-зоне (готов вход). in_leg = цена между сломом и целью (по пути)."""
    struct = coherent_structure(dfs_by_tf)
    out = {}
    for tf in TF_ORDER:
        if tf not in struct or tf not in dfs_by_tf:
            continue
        r = struct[tf]
        trend, brk, ext = r.get("trend"), r.get("break_level"), r.get("extreme")
        if not trend or brk is None or ext is None:
            out[tf] = None
            continue
        # OTE от ноги: swing_a=экстремум, swing_b=слом → build_ote даёт direction=trend, зону отката,
        # отрицательные фибо = цели-расширение за экстремум (метод Егора −0.62).
        ob = build_ote(ext, brk)
        lo, hi = ob["ote"]
        lv = ob["levels"]
        price = float(dfs_by_tf[tf]["close"].values[-1])
        out[tf] = {
            "direction": trend, "ote_lo": lo, "ote_hi": hi,
            "entry": (lo + hi) / 2, "sl": brk,               # SL за слом (защищённый уровень)
            "target_062": lv.get(-0.62), "target_1": lv.get(-1.0),
            "targets": [lv.get(-0.62), lv.get(-1.0), lv.get(-1.618)],
            "active": lo <= price <= hi,                     # цена В зоне = готов вход
            "broken": r.get("broken", False),
            "from": ext, "to": brk,
        }
    return out


def reversal_state(dfs_by_tf: dict) -> dict:
    """Прогресс ПЕРЕВОРОТА матрицы МЛАДШИЙ→СТАРШИЙ (Егор 02.07): разворот начинается снизу.
    Старший тренд = базовое направление (по старшему ТФ с CHoCH). Считаем, сколько младших ТФ
    ПОДРЯД снизу уже сломились ПРОТИВ старшего тренда = ранний сигнал разворота.

    Возвращает {base_dir, base_tf, flipped_tfs, progress, reversing}:
      base_dir — направление старшего тренда; flipped_tfs — младшие ТФ, сломившиеся против (снизу вверх);
      progress — сколько подряд снизу перевернулось; reversing — идёт ли переворот (progress>0).
    """
    # СВЯЗНАЯ структура (Егор): младшие видят точки старших через floor → боковик не даёт ложный флип.
    # ФАКТИЧЕСКОЕ направление (с учётом пробоя слома) — иначе структура short у всех, переворот не виден.
    struct = coherent_structure(dfs_by_tf)
    def _eff(r):
        if r["trend"] and r["broken"]:
            return "long" if r["trend"] == "short" else "short"
        return r["trend"]
    dirs = {tf: _eff(struct[tf]) for tf in TF_ORDER if tf in struct}
    # базовое направление = САМЫЙ СТАРШИЙ ТФ с определённым трендом
    base_dir = base_tf = None
    for tf in TF_ORDER:
        if dirs.get(tf):
            base_dir, base_tf = dirs[tf], tf; break
    if not base_dir:
        return {"base_dir": None, "base_tf": None, "flipped_tfs": [], "progress": 0, "reversing": False}
    # снизу вверх: сколько младших ПОДРЯД против base_dir (начало переворота)
    younger = [tf for tf in TF_ORDER if tf in dfs_by_tf][::-1]   # 5m→...→старший
    flipped = []
    for tf in younger:
        if tf == base_tf:
            break
        if dirs.get(tf) and dirs[tf] != base_dir:
            flipped.append(tf)
        else:
            break                             # каскад прервался (не подряд снизу)
    return {"base_dir": base_dir, "base_tf": base_tf, "flipped_tfs": flipped,
            "progress": len(flipped), "reversing": len(flipped) > 0}


def dominant_context(matrix: dict, price: float, dfs_by_tf: dict | None = None) -> dict | None:
    """Активный старший контекст = НАПРАВЛЕНИЕ ТРЕНДА старшего + цель. Двунаправленный:
    матрица активна в СТОРОНУ ТРЕНДА (GRT падает → SHORT торгует обновление минимумов; LONG спит).
    Переворот при противоположном CHoCH старшего.

    Направление = trend_direction старшего ТФ с валидными зонами (последний CHoCH). Цель = target
    valid-зоны того направления (ближайшая по пути). Возвращает {htf, direction, target, trend}
    или None (нет структуры/сломов вообще = совсем мёртвый).
    """
    # ПРИОРИТЕТ 1: активная VALID зона (цена В OTE-откате = мы в зоне разворота старшего).
    # Старший первым. XLM: цена в 1d LONG-зоне → LONG (мы в откате к развороту вверх).
    for tf in TF_ORDER:
        act = [z for z in matrix.get(tf, []) if z["valid"] and z["active"]]
        if act:
            z = act[-1]
            return {"htf": tf, "direction": z["direction"], "target": z["target_062"],
                    "mode": "in_zone", "has_valid_zone": True}
    # ПРИОРИТЕТ 2: нет активной зоны → НАПРАВЛЕНИЕ ТРЕНДА старшего (GRT падает → SHORT торгует
    # обновление минимумов, LONG спит). Переворот при противоположном CHoCH.
    for tf in TF_ORDER:
        if dfs_by_tf and tf in dfs_by_tf:
            tr = trend_direction(dfs_by_tf[tf])
            if tr:
                dir_zones = [z for z in matrix.get(tf, []) if z["valid"] and z["direction"] == tr and z["target_062"]]
                target = dir_zones[-1]["target_062"] if dir_zones else None
                return {"htf": tf, "direction": tr, "target": target,
                        "mode": "trend", "has_valid_zone": bool(dir_zones)}
    return None


def ltf_entries_in_context(matrix: dict, ctx: dict) -> list:
    """Младшие входы ПО ПУТИ к старшей цели: valid зоны младше htf, direction==контекст,
    и «по пути» (между текущей ценой и старшей целью). Против направления = ШУМ, отброшено."""
    if not ctx:
        return []
    htf_i = TF_ORDER.index(ctx["htf"])
    out = []
    for tf in TF_ORDER[htf_i + 1:]:            # только младше старшего
        for z in matrix.get(tf, []):
            if z["valid"] and z["direction"] == ctx["direction"]:
                out.append(z)
    return out


def _ote_touched_since(df, lo, hi, since_ts) -> bool:
    """Заходила ли цена в OTE-зону [lo,hi] ПОСЛЕ формирования ноги (since_ts=время экстремума)."""
    import pandas as _pd
    try:
        after = df[df.index > _pd.Timestamp(since_ts)] if since_ts is not None else df.tail(60)
    except Exception:
        after = df.tail(60)
    if len(after) == 0:
        return False
    return bool((after["low"] <= hi).any() and (after["high"] >= lo).any())


def matrix_playbook(dfs_by_tf: dict, anchor: str = COHERENCE_ANCHOR) -> dict | None:
    """ОПЕРАЦИОННЫЙ РАЗБОР МАТРИЦЫ — «это должен понимать БОТ» (Егор 02.07). Собирает то, что мы
    выводили вручную в визуал-сессии, в машинный + человекочитаемый план:
      • bias = направление значимого якоря (4h);
      • ЗНАЧИМАЯ старшая OTE и ТРОНУТА ли она (untouched = МАГНИТ, куда цена пойдёт);
      • где цена относительно зоны;
      • ПЛАН: что ждём / скальп-к-зоне (шорт младшего leg до зоны в лонге, или лонг до зоны в шорте) /
        прайм-вход когда цена В зоне / инвалидация.
    КЛЮЧЕВОЙ УРОК XLM (Егор): цена отскочила от МЕЛКОЙ 1h OTE, а значимая 4h OTE НЕ тронута →
    прайм-вход = НЕ здесь, а в старшей untouched-зоне; путь туда торгуем младшим контр-leg.
    Reuse: ote_matrix + structure_trend (extreme_ts). Ничего не дублирует.
    """
    om = ote_matrix(dfs_by_tf)
    tf_small = next((t for t in reversed(TF_ORDER) if t in dfs_by_tf), None)
    if tf_small is None:
        return None
    price = float(dfs_by_tf[tf_small]["close"].values[-1])
    az = om.get(anchor)
    if not az:
        return None
    bias = az["direction"]
    st = structure_trend(dfs_by_tf[anchor])
    touched = _ote_touched_since(dfs_by_tf[anchor], az["ote_lo"], az["ote_hi"], st.get("extreme_ts"))
    sig_high_low = az["from"]                        # ЭКСТРЕМУМ ноги старшего (long→значимый ХАЙ, short→значимый ЛОЙ)
    plan = {}
    if bias == "long":
        if price > az["ote_hi"] and not touched:
            plan = {
                "state": f"старшая {anchor} OTE НЕ тронута — МАГНИТ внизу",
                "wait": f"откат ВНИЗ в {anchor} OTE [{az['ote_lo']:.5f}–{az['ote_hi']:.5f}]",
                "scalp": f"SHORT младшего leg ДО зоны: вход в младший sell-OTE, SL за значимый хай {sig_high_low:.5f}, TP=верх {anchor} OTE {az['ote_hi']:.5f}",
                "then": f"ФЛИП в LONG от {anchor} OTE → цель {az['target_062']:.5f}",
                "invalidation": f"реклейм выше {sig_high_low:.5f} = лонг пошёл без захода в зону, скальп-шорт отменить",
            }
        elif az["ote_lo"] <= price <= az["ote_hi"]:
            plan = {"state": f"цена В старшей {anchor} OTE = ПРАЙМ-ЛОНГ",
                    "wait": "младший бычий CHoCH = триггер входа",
                    "entry": "LONG", "sl": az["sl"], "tp": az["target_062"]}
        else:
            plan = {"state": f"цена НИЖЕ {anchor} OTE", "wait": "проверить не сломан ли лонг (пробой SL старшего)"}
    else:  # short bias
        if price < az["ote_lo"] and not touched:
            plan = {
                "state": f"старшая {anchor} OTE НЕ тронута — МАГНИТ вверху",
                "wait": f"отскок ВВЕРХ в {anchor} OTE [{az['ote_lo']:.5f}–{az['ote_hi']:.5f}]",
                "scalp": f"LONG младшего leg ДО зоны, SL за значимый лой {sig_high_low:.5f}, TP=низ {anchor} OTE {az['ote_lo']:.5f}",
                "then": f"ФЛИП в SHORT от {anchor} OTE → цель {az['target_062']:.5f}",
                "invalidation": f"пробой ниже {sig_high_low:.5f} = шорт пошёл без захода в зону",
            }
        elif az["ote_lo"] <= price <= az["ote_hi"]:
            plan = {"state": f"цена В старшей {anchor} OTE = ПРАЙМ-ШОРТ",
                    "wait": "младший медвежий CHoCH = триггер",
                    "entry": "SHORT", "sl": az["sl"], "tp": az["target_062"]}
        else:
            plan = {"state": f"цена ВЫШЕ {anchor} OTE", "wait": "проверить не сломан ли шорт"}
    return {
        "anchor": anchor, "bias": bias, "price": round(price, 6),
        "anchor_ote": [round(az["ote_lo"], 6), round(az["ote_hi"], 6)],
        "anchor_touched": touched, "anchor_target": az.get("target_062"),
        "reversal": reversal_state(dfs_by_tf), "plan": plan,
    }
