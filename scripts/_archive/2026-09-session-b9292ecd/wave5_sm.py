# -*- coding: utf-8 -*-
"""ВОЛНЫ НА ДВУХСЛОЙНОМ ЭТАЛОНЕ OKO-SM (13.09, Егор: «по картинкам видно — проблема в детекции волн;
у нас есть двойной слой для точного подсчёта; + пересечение WT-медианы как вес входа»).

Было: зигзаг по ATR (dev=3) → 6 точек по размеру отклонения → 3 запрещающих правила. Внутренняя
структура волн НЕ смотрелась. Результат на картинках: точки 1-2 на соседних барах, «5» = середина.

Здесь: свинги СТАРШЕГО слоя (`_swings(len=SW)`) = волны; точка 5 = provisional (текущий экстремум
после последнего подтверждённого свинга). События МЛАДШЕГО слоя (internal_len=5) внутри каждой волны =
фрактальная проверка по канону (obsidian/Concepts/Elliott-Wave-Labeling.md §10, §13):
  · волны 1/3/5 (импульсные): ≥ MIN_BOS младших BOS ПО направлению;
  · волны 2/4 (коррекции): младший CHoCH ПРОТИВ есть, старшего CHoCH — НЕТ (иначе разворот);
  · волна 3: больше младших BOS, чем 1 и 5 (характер «самая сильная»);
  · волна 5: дивергенция WT (флаг) + объём ниже волны 3 (характер «слабая»).
Каузальность: свинг известен с бара подтверждения (sw.conf_i), событие — с бара ev.i; на баре t
берём только conf_i ≤ t и ev.i ≤ t. Никакого префиксного зигзага — один прогон движка.

Вход — кросс wt1×wt2 на LTF после бара t; ВЕС: wt1 выше/ниже WT-медианы (EMA(wt1, MED_LEN)) на LTF
в момент кросса — «пересекли медиану — это плюс» (Егор). Всё флагами, не фильтрами.
Стоп за фактический экстремум к моменту кросса; цели w4/0.382/0.5/0.618; выходы 7/14 сут; контроль.

Запуск: python wave5_sm.py --htf 4h --ltf 15m --sw 20 [--pairs 60] [--z 45]
"""
from __future__ import annotations
import argparse, sys, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

from research_harness import load as _load_cache, universe  # noqa: E402

PARQ_1M = Path("C:/oko_history/1m")


def load(sym, tf):
    """1m — из паркетов (50 монет, 2025-01 → 2026-08); 3m — ресемпл тех же паркетов (в кэше 3m всего
    28 монет, с 1m пересекаются 5); остальное — кэш проекта."""
    if tf not in ("1m", "3m"):
        return _load_cache(sym, tf)
    p = PARQ_1M / f"{sym.replace('/', '')}.parquet"
    if not p.exists():
        return pd.DataFrame()
    d = pd.read_parquet(p)[["open", "high", "low", "close", "volume"]]
    if tf == "3m":
        d = d.resample("3min", label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["open"])
    return d
from core.smc.oko_sm_engine import run_structure, _swings   # noqa: E402
from core.indicators.indicators import calculate_wt, calculate_trend  # noqa: E402
from core.calculators.combinator_core import _wtx_divergences  # noqa: E402

WARMUP = 400
BUF = 0.0015
DIV_W = 12
ENTRY_W_HTF = 24
MAXHOLD_HTF = 240
MIN_IMP_PCT, MAX_IMP_PCT = 3.0, 100.0   # 🔴 потолок 40% (под зигзаг) резал 23 из 37 импульсов на sw=20
MIN_BOS = 1          # младших сломов по направлению внутри импульсной волны (после правки — CHoCH+BOS)
INTERNAL_LEN = 5     # 🔑 младший слой: на sw=30 при il=5 (6:1) fractal_ok ПЕРЕВЕРНУЛСЯ — пропорция слоёв решает
MIN_LAG_H = 0        # минимум часов от вершины w5 до входа (0 = первый кросс после закрытия HTF-бара)
MAXHOLD_H = 0        # потолок удержания в часах (0 = MAXHOLD_HTF в барах — старое поведение)
ENTRY_W_H = 0        # окно входа от вершины w5 в часах (0 = ENTRY_W_HTF в барах: 96 ч на 4h, 24 ч на 1h, 6 ч на 15m)
ENTRY_MODE = "cross" # cross = первый кросс wt1×wt2 на LTF · line24 = первое LTF-закрытие за линией 2-4
CTX_1D = False       # дневной контекст (ресемпл из HTF): структура, свинги, WT, supertrend
CTX_SW = 10          # масштаб дневных свингов (дней)
MED_LEN = 200        # WT-медиана = EMA(wt1, 200)
TGTS = ["w4", "f382", "f500", "f618"]
TF_MIN = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "1h": 60, "4h": 240}


def wt_pack(df, med=False):
    d = calculate_wt(df.copy())
    wt1, wt2 = d["wt1"].values.astype(float), d["wt2"].values.astype(float)
    b_reg, s_reg, b_hid, s_hid = _wtx_divergences(
        wt1, df.low.values.astype(float), df.high.values.astype(float))
    up = np.zeros(len(wt1), bool); dn = np.zeros(len(wt1), bool)
    up[1:] = (wt1[1:] > wt2[1:]) & (wt1[:-1] <= wt2[:-1])
    dn[1:] = (wt1[1:] < wt2[1:]) & (wt1[:-1] >= wt2[:-1])
    median = pd.Series(wt1).ewm(span=MED_LEN, adjust=False).mean().values if med else None
    return wt1, up, dn, b_reg, s_reg, b_hid, s_hid, median


def impulses_on_bar(swings, t, high, low):
    """Кандидаты 5-волновых импульсов, видимые на баре t: 5 подтверждённых свингов старшего слоя
    + provisional точка 5 = текущий экстремум после последнего свинга. → list[dict]."""
    conf = [s for s in swings if s[0] <= t]          # (conf_i, sw_i, price, is_top)
    if len(conf) < 5:
        return []
    last5 = conf[-5:]
    kinds = [s[3] for s in last5]
    if any(kinds[i] == kinds[i + 1] for i in range(4)):
        return []
    idx = [s[1] for s in last5]; px = [s[2] for s in last5]
    li = idx[-1]
    if li >= t:
        return []
    seg_h, seg_l = high[li + 1:t + 1], low[li + 1:t + 1]
    if last5[-1][3]:                                   # последний = top → импульс ВНИЗ, точка 5 = low
        p5i = li + 1 + int(seg_l.argmin()); p5 = float(seg_l.min())
        if p5 >= px[-1] or kinds != [True, False, True, False, True]:
            return []
        p0, p1, p2, p3, p4 = px
        if not (p1 < p0 and p2 < p0 and p3 < p1 and p4 < p1 and p5 < p3):
            return []
        l1, l3, l5 = p0 - p1, p2 - p3, p4 - p5
        direction = "down"
    else:                                              # последний = btm → импульс ВВЕРХ, точка 5 = high
        p5i = li + 1 + int(seg_h.argmax()); p5 = float(seg_h.max())
        if p5 <= px[-1] or kinds != [False, True, False, True, False]:
            return []
        p0, p1, p2, p3, p4 = px
        if not (p1 > p0 and p2 > p0 and p3 > p1 and p4 > p1 and p5 > p3):
            return []
        l1, l3, l5 = p1 - p0, p3 - p2, p5 - p4
        direction = "up"
    if l3 < l1 and l3 < l5:                            # R2
        return []
    w_idx = idx + [p5i]; w_px = px + [p5]
    return [dict(waves=list(zip(w_idx, w_px)), direction=direction, lens=(l1, l3, l5),
                 w2_retr=abs(p2 - p1) / l1 if l1 else 0, w4_retr=abs(p4 - p3) / l3 if l3 else 0,
                 w3_ext=l3 / l1 if l1 else 0)]


def fractal_check(events, w_idx, up_imp, t):
    """Младшие события внутри каждой волны (только ev.i ≤ t). → dict флагов и счётчиков."""
    ev = [e for e in events if e.i <= t and w_idx[0] <= e.i <= w_idx[5]]
    def seg(k):
        a, b = w_idx[k], w_idx[k + 1]
        return [e for e in ev if a < e.i <= b]
    # 🔴 Воронка 13.09: внутри волны ПЕРВЫЙ младший слом по направлению движок метит как CHoCH
    # (смена itrend), и только следующие — BOS. Считать надо ВСЕ младшие сломы по направлению
    # (CHoCH+BOS), иначе у волны 1 медиана = 0. То же для коррекций — все сломы ПРОТИВ.
    def n_bos_dir(es, along):          # все младшие сломы по направлению импульса (along) или против
        want_bull = (up_imp if along else (not up_imp))
        return sum(1 for e in es if e.internal and e.bull == want_bull)
    def n_choch_against(es):
        return sum(1 for e in es if e.internal and e.bull == (not up_imp))
    def swing_choch_against(es):
        return any((not e.internal) and e.kind == "CHoCH" and e.bull == (not up_imp) for e in es)
    b1, b3, b5 = n_bos_dir(seg(0), True), n_bos_dir(seg(2), True), n_bos_dir(seg(4), True)
    c2, c4 = n_choch_against(seg(1)), n_choch_against(seg(3))
    sc2, sc4 = swing_choch_against(seg(1)), swing_choch_against(seg(3))
    # 🔴 РЕВЬЮ 13.09 (D2/D3): волна 5 provisional → её младшие сломы не успевают подтвердиться,
    # b5 занижен по построению; сравнивать b3 с b5 и требовать b5≥1 — смещение. corr_ok почти
    # всегда True (старший CHoCH против уже исключён правилами Эллиотта) — не несёт смысла.
    # Честная фрактальная проверка = только ЗАВЕРШЁННЫЕ волны 1 и 3.
    imp_ok = b1 >= MIN_BOS and b3 >= MIN_BOS
    corr_ok = (not sc2) and (not sc4)
    w3_strong = b3 >= b1
    return dict(bos1=b1, bos3=b3, bos5=b5, choch2=c2, choch4=c4, sw_choch24=int(sc2 or sc4),
                frac_imp=imp_ok, frac_corr=corr_ok, frac_w3=w3_strong,
                fractal_ok=imp_ok and w3_strong,          # без b5 и без corr_ok
                fractal_old=imp_ok and (b5 >= 1) and corr_ok and (b3 >= max(b1, b5)))


def walk(h, l, c, j0, e, sl, up_imp, tgt, end):
    sgn = -1 if up_imp else 1
    res, hit, pend, stop_i = {}, {}, set(tgt), None
    for k in range(j0, end + 1):
        if (h[k] >= sl) if up_imp else (l[k] <= sl):
            stop_i = k; break
        for kk in list(pend):
            px = tgt[kk]
            if (l[k] <= px) if up_imp else (h[k] >= px):
                res[kk] = (px - e) / e * 100 * sgn; hit[kk] = k; pend.discard(kk)
        if not pend:
            break
    sl_pnl = (sl - e) / e * 100 * sgn
    tail = (float(c[stop_i if stop_i is not None else end]) - e) / e * 100 * sgn
    return res, hit, stop_i, sl_pnl, tail


def hold_pnl(h, l, c, j0, e, sl, up_imp, end):
    sgn = -1 if up_imp else 1
    for k in range(j0, end + 1):
        if (h[k] >= sl) if up_imp else (l[k] <= sl):
            return (sl - e) / e * 100 * sgn, True
    return (float(c[end]) - e) / e * 100 * sgn, False


def run_symbol(sym, htf, ltf, sw, z, cost, rs):
    dh = load(sym, htf); dl = load(sym, ltf)
    if len(dh) < 1500 or len(dl) < 3000:
        return []
    ratio = TF_MIN[htf] // TF_MIN[ltf]
    idx_h, idx_l = dh.index, dl.index
    dh = dh.reset_index(drop=True); dl = dl.reset_index(drop=True)
    hh, lh, vh = dh.high.values.astype(float), dh.low.values.astype(float), dh.volume.values.astype(float)
    o_l, h_l, l_l, c_l = (dl.open.values.astype(float), dl.high.values.astype(float),
                          dl.low.values.astype(float), dl.close.values.astype(float))
    n_h, n_l = len(dh), len(dl)
    # 🔑 КОНТЕКСТ 1D (Егор 13.09: «если детектору добавить контекст с ТФ 1D?») — степень 4h-пятёрки
    # определяется дневной структурой. 1D строим ресемплом из HTF (в кэше 1d всего 19 монет), дни UTC.
    # Каузально: только дневные бары, ЗАКРЫТЫЕ до момента решения (close_1d = open + 1 день).
    ctx = None
    if CTX_1D:
        dd = pd.DataFrame({"open": dh.open.values, "high": hh, "low": lh, "close": dh.close.values}, index=idx_h) \
            .resample("1D", label="left", closed="left").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        d_st = run_structure(dd, swing_len=CTX_SW, internal_len=max(2, CTX_SW // 3))
        d_sw = _swings(dd["high"], dd["low"], CTX_SW)
        d_wt = calculate_wt(dd.copy())["wt1"].values.astype(float)
        d_tr = calculate_trend(dd.copy(), atr_period=43, factor=1.25)["trend"].values
        d_close = dd.index.values.astype("datetime64[ns]") + np.timedelta64(1, "D")
        d_ev = [e for e in d_st.events if not e.internal]     # старшие дневные сломы
        ctx = (dd, d_sw, d_wt, d_tr, d_close, d_ev)
    st = run_structure(dh[["open", "high", "low", "close"]], swing_len=sw, internal_len=INTERNAL_LEN)
    swings = _swings(dh["high"], dh["low"], sw)
    swings_i = _swings(dh["high"], dh["low"], INTERNAL_LEN)     # младший слой свингов — для степени
    # 🔑 СТАРШИЙ СЛОЙ НА ТОМ ЖЕ ТФ (Егор 13.09, ETC: «детектор часть не видит») — свинги ×3: точка 0
    # нашего импульса должна быть ВЕРШИНОЙ старшего масштаба, иначе наши волны — подволны старшей ноги.
    swings_b = _swings(dh["high"], dh["low"], sw * 3)
    wt1_h, _, _, b_reg, s_reg, b_hid, s_hid, _ = wt_pack(dh)
    wt1_l, cup_l, cdn_l, _, _, _, _, med_l = wt_pack(dl, med=True)
    if ENTRY_MODE == "atr":
        # 🔑 Егор 13.09: «вместо кросса — ATRCHANGE на LTF». Боевой детектор = смена supertrend
        # (calculate_trend, config.yaml: atr_period 43, factor 1.25) на ЗАКРЫТОЙ свече.
        tr = calculate_trend(dl[["open", "high", "low", "close"]].copy(), atr_period=43, factor=1.25)["trend"].values
        atr_up = np.zeros(n_l, bool); atr_dn = np.zeros(n_l, bool)
        atr_up[1:] = (tr[1:] == 1) & (tr[:-1] == -1); atr_dn[1:] = (tr[1:] == -1) & (tr[:-1] == 1)
        cup_l, cdn_l = atr_up, atr_dn                       # те же роли, что кросс WT вверх/вниз
    lt = idx_l.values.astype("datetime64[ns]")
    bars_day_l = 1440 // TF_MIN[ltf]

    seen, rows = set(), []
    for t in range(WARMUP, n_h):
        for imp in impulses_on_bar(swings, t, hh, lh):
            w = imp["waves"]
            w_idx = [int(x[0]) for x in w]; w_px = [float(x[1]) for x in w]
            a, b = w_idx[0], w_idx[5]
            key = (a, w_idx[4])
            if key in seen:
                continue
            p0, p4, p5 = w_px[0], w_px[4], w_px[5]
            rng = abs(p5 - p0)
            if rng <= 0 or p0 <= 0:
                continue
            imp_pct = rng / p0 * 100
            if not (MIN_IMP_PCT <= imp_pct <= MAX_IMP_PCT):
                continue
            up_imp = imp["direction"] == "up"
            if not np.isfinite(wt1_h[b]) or not ((wt1_h[b] > z) if up_imp else (wt1_h[b] < -z)):
                continue
            seen.add(key)
            fr = fractal_check(st.events, w_idx, up_imp, t)
            lo_d, hi_d = max(0, b - DIV_W), min(t, b + DIV_W)
            reg = bool((s_reg if up_imp else b_reg)[lo_d:hi_d + 1].any())
            hid = bool((s_hid if up_imp else b_hid)[lo_d:hi_d + 1].any())
            v3 = vh[w_idx[2] + 1:w_idx[3] + 1].mean() if w_idx[3] > w_idx[2] else np.nan
            v5 = vh[w_idx[4] + 1:b + 1].mean() if b > w_idx[4] else np.nan
            vol_w5_weak = bool(np.isfinite(v3) and np.isfinite(v5) and v5 < v3)
            # вход на LTF после закрытия HTF-бара t
            t_close = np.datetime64(idx_h[t].to_datetime64()) + np.timedelta64(TF_MIN[htf], "m")
            # 🔑 MIN_LAG_H (13.09, перенос на 1h): на 1h вход через 3 ч после вершины — «снайпер»
            # (тугой стоп, RR 8-15), на 4h через 8 ч — «позиционщик». Фрактал окупается только при
            # подтверждённом развороте → не входить раньше MIN_LAG_H часов от вершины w5.
            if MIN_LAG_H > 0:
                t_min = np.datetime64(idx_h[b].to_datetime64()) + np.timedelta64(int(MIN_LAG_H * 60), "m")
                t_close = max(t_close, t_min)
            j0 = int(np.searchsorted(lt, t_close))
            entry_w_min = ENTRY_W_HTF * TF_MIN[htf] if ENTRY_W_H <= 0 else int(ENTRY_W_H * 60)   # окно входа в минутах
            j1 = min(n_l - 2, int(np.searchsorted(lt, np.datetime64(idx_h[b].to_datetime64())
                                                   + np.timedelta64(entry_w_min, "m"))))
            if j1 <= j0:
                continue
            # линия 2-4 (канон: закрытие за ней = импульс завершён); нужна и для флага, и для режима входа
            x2, x4 = float(w_idx[2]), float(w_idx[4]); y2, y4 = w_px[2], w_px[4]
            slope = (y4 - y2) / (x4 - x2) if x4 > x2 else 0.0          # цена за 1 HTF-бар
            t_x4 = np.datetime64(idx_h[int(x4)].to_datetime64())
            def line_at(m_):
                pos_h = x4 + (lt[m_] - t_x4) / np.timedelta64(TF_MIN[htf], "m")
                return y4 + slope * (pos_h - x4)
            def beyond(m_):                                              # импульс вниз → пробой ВВЕРХ
                return (c_l[m_] > line_at(m_)) if (not up_imp) else (c_l[m_] < line_at(m_))
            if ENTRY_MODE == "line24":
                # 🔑 ДОСТРАИВАНИЕ (Егор 13.09: «детектор не достраивает импульсы»): вход не по кроссу WT,
                # а по первому LTF-закрытию ЗА линией 2-4 после закрытия HTF-бара обнаружения.
                js = [m_ for m_ in range(j0, j1 + 1) if beyond(m_)]
                if not js:
                    continue
                j = int(js[0])
            else:
                cross = cdn_l if up_imp else cup_l
                js = np.nonzero(cross[j0:j1 + 1])[0]
                if not len(js):
                    continue
                j = j0 + int(js[0])
            e = float(o_l[j + 1])
            if e <= 0:
                continue
            med_ok = bool(np.isfinite(med_l[j]) and ((wt1_l[j] < med_l[j]) if up_imp else (wt1_l[j] > med_l[j])))
            # 🔑 ДОТЯЖКА ДЕТЕКТОРА (13.09, по картинке DOGE — усечённая пятая, цена продолжила после
            # стопа): канон — конец волны 5 подтверждается МЛАДШИМ CHoCH против импульса на HTF.
            # Каузально: только 4h-бары, ЗАКРЫТЫЕ до времени кросса j (tj = последний закрытый).
            # 🔑 КАНОН (Егор 13.09, эталон ARKM/DOGE — ошибка СТЕПЕНИ): завершение импульса
            # подтверждается ПРОБОЕМ ЛИНИИ 2-4 (трендлиния через точки 2 и 4). Каузально: линия по
            # HTF-точкам, пробой ищем на 15m-барах между вершиной w5 и кроссом j — закрытие за линией.
            jb_ = int(np.searchsorted(lt, np.datetime64(idx_h[b].to_datetime64())))
            line_break = any(beyond(m_) for m_ in range(max(jb_, 0), j + 1))
            # 🔑 СТЕПЕНЬ ПО ВЛОЖЕННОСТИ (Егор 13.09, ARKM/DOGE/ZK — подволны приняты за волны): настоящая
            # волна степени N содержит несколько СВИНГОВ степени N−1. Считаем младшие свинги (len=INTERNAL_LEN),
            # подтверждённые к бару t, внутри каждой волны. Подволна степени N−1 сама таких почти не содержит.
            ns = [sum(1 for s in swings_i if s[0] <= t and w_idx[k] < s[1] <= w_idx[k + 1]) for k in range(5)]
            # контекст точки 0: начало импульса = экстремум за окно длины импульса до него (иначе — середина ноги)
            win0 = max(1, b - a); lo0 = max(0, a - win0)
            p0_ctx = bool((hh[lo0:a].max() <= p0) if (not up_imp) else (lh[lo0:a].min() >= p0)) if a > lo0 else False
            # старший слой ×3 (каузально: подтверждён к бару t): последний старший свинг ПЕРЕД/НА точке 0
            sb = [s for s in swings_b if s[0] <= t and s[1] <= a]
            big_top = [s for s in sb if s[3]]; big_btm = [s for s in sb if not s[3]]
            last_big = sb[-1] if sb else None
            # точка 0 = вершина старшего масштаба (для импульса вниз): последний старший свинг до точки 0 — ТОП, и он
            # не выше p0 более чем на 1% (наш импульс стартует с вершины старшего), иначе — мы внутри старшей ноги
            if last_big is not None:
                want_top = (not up_imp)
                big_p0 = bool(last_big[3] == want_top and (abs(last_big[2] - p0) / p0 <= 0.01 or last_big[1] == a))
                # «внутри старшей ноги»: последний старший свинг ПРОТИВ (для лонга — дно), т.е. старший масштаб
                # ещё в движении вниз с непод­тверждённым продолжением
                inside_big_leg = bool(last_big[3] != want_top)
                # глубина: насколько p0 ниже последней старшей вершины (импульс вниз) — 0 = сама вершина
                ref = (big_top[-1][2] if big_top else np.nan) if (not up_imp) else (big_btm[-1][2] if big_btm else np.nan)
                p0_vs_big = float((ref - p0) / p0 * 100) if np.isfinite(ref) else np.nan
                if up_imp and np.isfinite(ref): p0_vs_big = float((p0 - ref) / p0 * 100)
                big_age = int(a - last_big[1])
            else:
                big_p0, inside_big_leg, p0_vs_big, big_age = None, None, np.nan, -1
            # 🔑 АЛЬТЕРНАТИВНЫЙ СЧЁТ (Егор, ETC): детектор берёт ПОСЛЕДНИЕ 5 свингов и никогда не рассматривает
            # счёт со сдвигом на 2 свинга назад: 0'=s[-7], 1'=s[-6], 2'=наш 0, 3'=наш 1, 4'=наш 2 → наши 3-4-5
            # = подволны незавершённой 5'. Каузально: свинги s[-7], s[-6] подтверждены раньше наших.
            prev = [s for s in swings if s[0] <= t and s[1] < a]
            alt = {}
            if len(prev) >= 2:
                s7, s6 = prev[-2], prev[-1]          # 0', 1'
                want0 = (not up_imp)                  # импульс вниз: 0' — top, 1' — btm
                if s7[3] == want0 and s6[3] != want0:
                    p0p, p1p = float(s7[2]), float(s6[2])
                    # допустимость сдвинутого счёта: 2'(=наш 0) не за 0' (волна 2 не заходит за начало 1); 3'(=наш 1) за 1'
                    ok_r1 = (p0 <= p0p) if (not up_imp) else (p0 >= p0p)
                    ok_r3 = (w_px[1] < p1p) if (not up_imp) else (w_px[1] > p1p)
                    l1p = abs(p0p - p1p); l3p = abs(p0 - w_px[1]); l5p = abs(w_px[2] - p5)   # 5' до текущего экстремума
                    alt = {"alt_exists": bool(ok_r1 and ok_r3), "alt_w1": l1p / p0p * 100, "alt_w3_w1": (l3p / l1p if l1p else np.nan),
                           "alt_w5_w1": (l5p / l1p if l1p else np.nan), "alt_w2_retr": abs(p0 - p1p) / l1p if l1p else np.nan,
                           # «сдвинутый счёт правильнее»: у него третья — самая длинная, а у нашего — нет
                           "alt_better": bool(ok_r1 and ok_r3 and l3p >= l1p and l3p >= l5p and not (imp["lens"][1] >= imp["lens"][0] and imp["lens"][1] >= imp["lens"][2]))}
            if not alt:
                alt = {"alt_exists": False, "alt_w1": np.nan, "alt_w3_w1": np.nan, "alt_w5_w1": np.nan, "alt_w2_retr": np.nan, "alt_better": False}
            # 🔴 РЕВЬЮ 13.09 (D1, look-ahead вид 6): searchsorted по времени ОТКРЫТИЯ давал бар,
            # внутри которого стоит вход — он ещё НЕ закрыт (у 87% сделок). Момент решения =
            # открытие LTF-бара j+1; последний закрытый HTF-бар — тот, чьё ЗАКРЫТИЕ ≤ этому моменту.
            close_h = idx_h.values.astype("datetime64[ns]") + np.timedelta64(TF_MIN[htf], "m")
            t_dec = np.datetime64(idx_l[j + 1].to_datetime64())
            tj = int(np.searchsorted(close_h, t_dec, side="right")) - 1
            w5_ichoch = any(e.internal and e.bull == (not up_imp) and b < e.i <= min(tj, n_h - 1)
                            for e in st.events)
            # и старший CHoCH против после точки 5 (= разворот уже структурный; сильнее, но позже)
            w5_schoch = any((not e.internal) and e.bull == (not up_imp) and b < e.i <= min(tj, n_h - 1)
                            for e in st.events)
            d_flags = {}
            if ctx is not None:
                dd, d_sw, d_wt, d_tr, d_close, d_ev = ctx
                td = int(np.searchsorted(d_close, t_dec, side="right")) - 1       # последний ЗАКРЫТЫЙ дневной бар
                if td >= CTX_SW * 3:
                    ev_ok = [e for e in d_ev if e.i <= td]
                    last_ev = ev_ok[-1] if ev_ok else None
                    sw_ok = [s for s in d_sw if s[0] <= td]                        # подтверждённые дневные свинги
                    lows = [s for s in sw_ok if not s[3]]; highs = [s for s in sw_ok if s[3]]
                    last_low = lows[-1][2] if lows else np.nan; last_high = highs[-1][2] if highs else np.nan
                    p_ext = p5   # экстремум 4h-пятёрки
                    d_flags = {"d_bull": (bool(last_ev.bull) if last_ev is not None else None),
                               "d_last_kind": (last_ev.kind if last_ev is not None else None),
                               "d_wt": float(d_wt[td]) if np.isfinite(d_wt[td]) else np.nan,
                               "d_st": int(d_tr[td]) if not pd.isna(d_tr[td]) else 0,
                               # пятёрка вниз пробила последний дневной swing-low (= дневной слом вниз, продолжение)
                               "d_broke": bool((p_ext < last_low) if (not up_imp) else (p_ext > last_high)) if np.isfinite(last_low if not up_imp else last_high) else None,
                               # начало 4h-импульса выше последнего дневного swing-high (импульс из вершины дневной структуры)
                               "d_from_top": bool((p0 >= last_high) if (not up_imp) else (p0 <= last_low)) if np.isfinite(last_high if not up_imp else last_low) else None,
                               "d_bars_since_ev": (td - last_ev.i) if last_ev is not None else np.nan}
            jb = int(np.searchsorted(lt, np.datetime64(idx_h[b].to_datetime64())))
            ext = (float(h_l[jb:j + 1].max()) if up_imp else float(l_l[jb:j + 1].min())) if j >= jb else p5
            p5e = max(p5, ext) if up_imp else min(p5, ext)
            sl = p5e * (1 + BUF) if up_imp else p5e * (1 - BUF)
            if (up_imp and sl <= e) or (not up_imp and sl >= e):
                continue
            rng = abs(p5e - p0)
            tgt = {"w4": p4,
                   "f382": p5e - 0.382 * rng if up_imp else p5e + 0.382 * rng,
                   "f500": p5e - 0.500 * rng if up_imp else p5e + 0.500 * rng,
                   "f618": p5e - 0.618 * rng if up_imp else p5e + 0.618 * rng}
            tgt = {k: v for k, v in tgt.items() if ((v < e) if up_imp else (v > e))}
            if not tgt:
                continue
            # 🔴 MAXHOLD в барах переносился между ТФ молча: 240 баров = 960 ч на 4h, 240 ч на 1h, 60 ч на 15m.
            # --maxhold_h задаёт потолок в ЧАСАХ (0 = старое поведение в барах).
            cap_bars = MAXHOLD_HTF if MAXHOLD_H <= 0 else int(MAXHOLD_H * 60 / TF_MIN[htf])
            hold_l = min(cap_bars, max(20, 2 * (b - a))) * ratio
            end = min(j + 1 + hold_l, n_l - 1)
            res, hit, stop_i, sl_pnl, tail = walk(h_l, l_l, c_l, j + 1, e, sl, up_imp, tgt, end)
            row = {"sym": sym, "htf": htf, "ltf": ltf, "sw": sw, "z": z, "dir": imp["direction"],
                   "reg": reg, "hid": hid, "med_ok": med_ok, "vol_w5_weak": vol_w5_weak,
                   "w5_ichoch": bool(w5_ichoch), "w5_schoch": bool(w5_schoch), "line24_break": bool(line_break),
                   "ns1": ns[0], "ns2": ns[1], "ns3": ns[2], "ns4": ns[3], "ns5": ns[4], "p0_ctx": p0_ctx,
                   "big_p0": big_p0, "inside_big_leg": inside_big_leg, "p0_vs_big": p0_vs_big, "big_age": big_age, **alt,
                   "entry_mode": ENTRY_MODE, **d_flags,
                   "w3_ge_w1": bool(imp["w3_ext"] >= 1.0),
                   "ts": idx_l[j + 1], "year": int(pd.Timestamp(idx_l[j + 1]).year),
                   "entry": e, "sl": sl, "p0": p0, "p4": p4, "p5": p5e,
                   "wave_idx": w_idx, "wave_px": w_px[:5] + [p5e],
                   "w2_retr": imp["w2_retr"], "w4_retr": imp["w4_retr"], "w3_ext": imp["w3_ext"],
                   "a": a, "b": b, "t": t, "j": j, "provisional": True,
                   "lag_htf_bars": (idx_l[j + 1] - idx_h[b]).total_seconds() / 60 / TF_MIN[htf],
                   "wt_at_p5": float(wt1_h[b]), "sl_pct": abs(e - sl) / e * 100,
                   "gone": abs(e - p5e) / rng, "imp_pct": imp_pct, "stopped": stop_i is not None,
                   "hold": hold_l, **fr}
            for k4 in TGTS:
                if k4 in tgt:
                    row[f"hit_{k4}"] = k4 in hit
                    row[f"pnl_{k4}"] = (res[k4] if k4 in hit else (sl_pnl if stop_i is not None else tail)) - cost
                    row[f"rr_{k4}"] = abs(tgt[k4] - e) / abs(e - sl)
                    row[f"tgt_{k4}"] = tgt[k4]
                else:
                    for pre in ("hit_", "pnl_", "rr_", "tgt_"):
                        row[pre + k4] = np.nan
            for dd in (7, 14):
                pnl_h, st_h = hold_pnl(h_l, l_l, c_l, j + 1, e, sl, up_imp, min(j + 1 + bars_day_l * dd, n_l - 1))
                row[f"pnl_h{dd}d"] = pnl_h - cost; row[f"stopped_h{dd}d"] = st_h
            span = 30 * bars_day_l
            lo_i, hi_i = max(WARMUP * ratio, j - span), min(n_l - hold_l - 2, j + span)
            if hi_i > lo_i + 10:
                jj = rs.randint(lo_i, hi_i); ce = float(o_l[jj])
                csl = ce * (1 + row["sl_pct"] / 100) if up_imp else ce * (1 - row["sl_pct"] / 100)
                ctgt = {k5: (ce * (1 - row[f"rr_{k5}"] * row["sl_pct"] / 100) if up_imp
                             else ce * (1 + row[f"rr_{k5}"] * row["sl_pct"] / 100))
                        for k5 in TGTS if np.isfinite(row.get(f"rr_{k5}", np.nan))}
                cres, chit, cst, cslp, ctail = walk(h_l, l_l, c_l, jj, ce, csl, up_imp, ctgt, min(jj + hold_l, n_l - 1))
                for k5 in TGTS:
                    if k5 in ctgt:
                        row[f"ctl_{k5}"] = (cres[k5] if k5 in chit else (cslp if cst is not None else ctail)) - cost
                        row[f"ctlhit_{k5}"] = k5 in chit
                    else:
                        row[f"ctl_{k5}"] = np.nan; row[f"ctlhit_{k5}"] = np.nan
                for dd in (7, 14):
                    cp, _ = hold_pnl(h_l, l_l, c_l, jj, ce, csl, up_imp, min(jj + bars_day_l * dd, n_l - 1))
                    row[f"ctl_h{dd}d"] = cp - cost
            rows.append(row)
    return rows


def block(g, k):
    PN, CT = f"pnl_{k}", f"ctl_{k}"
    g = g[g[PN].notna() & g[CT].notna()]
    if len(g) < 20:
        return None
    dif = g[PN] - g[CT]
    epd = g.assign(_d=dif).groupby(g.sym + "_" + g.ts.dt.strftime("%Y%m"))._d.mean()
    rs2 = np.random.RandomState(7)
    bsd = [epd.sample(len(epd), replace=True, random_state=rs2.randint(1e6)).mean() for _ in range(1500)]
    keep = g[PN].sort_values(ascending=False).iloc[int(len(g) * 0.1):]
    return {"n": len(g), "эп": epd.size,
            "дошли%": g[f"hit_{k}"].mean() * 100 if f"hit_{k}" in g else np.nan,
            "на сделку%": g[PN].mean(), "медиана%": g[PN].median(), "WR%": (g[PN] > 0).mean() * 100,
            "контроль%": g[CT].mean(), "перевес": dif.mean(),
            "ДИ": f"[{np.percentile(bsd,2.5):+.2f},{np.percentile(bsd,97.5):+.2f}]",
            "✅": "ДА" if np.percentile(bsd, 2.5) > 0 else "нет",
            "безтоп10": keep.mean(), "монет+%": (g.groupby("sym")[PN].sum() > 0).mean() * 100}


def report(d, htf, ltf, sw, z, cost):
    print(f"\n{'='*100}\nВОЛНЫ НА OKO-SM (swing_len={sw}, internal=5) · HTF {htf} → вход {ltf} · зона |WT|>{z} · "
          f"сделок {len(d)} · монет {d.sym.nunique()} · {d.ts.min():%Y-%m-%d} → {d.ts.max():%Y-%m-%d} · кост {cost}%")
    print(f"стоп {d.sl_pct.median():.2f}% · стоп-аут {d.stopped.mean()*100:.0f}% · вход через {d.lag_htf_bars.median():.1f} HTF-баров · "
          f"опоздание {d.gone.median()*100:.0f}% · импульс {d.imp_pct.median():.1f}% · "
          f"fractal_ok {d.fractal_ok.mean()*100:.0f}% · med_ok {d.med_ok.mean()*100:.0f}% · vol_w5_weak {d.vol_w5_weak.mean()*100:.0f}%")
    rows = []
    for k in TGTS + ["h7d", "h14d"]:
        r = block(d, k)
        if r:
            rows.append({"выход": k, **r})
    print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:7.3f}"))
    for col in ("fractal_ok", "fractal_old", "w3_ge_w1", "line24_break", "w5_ichoch", "med_ok", "reg", "vol_w5_weak", "dir", "year"):
        if col not in d or d[col].nunique() < 2:
            continue
        t2 = d[d.pnl_w4.notna()].groupby(col).agg(
            n=("pnl_w4", "size"), дошли=("hit_w4", lambda x: x.mean() * 100), на_сделку=("pnl_w4", "mean"),
            медиана=("pnl_w4", "median"), контроль=("ctl_w4", "mean"), h14=("pnl_h14d", "mean"))
        print(f"\n--- {col} (цель w4):"); print(t2.to_string(float_format=lambda x: f"{x:8.3f}"))
    # связка канона целиком
    full = d[d.fractal_ok & d.reg & d.med_ok]
    if len(full) >= 15:
        r = block(full, "w4")
        print(f"\n=== КАНОН ЦЕЛИКОМ (fractal_ok + дивергенция + медиана): n={len(full)}")
        print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--htf", default="4h"); ap.add_argument("--ltf", default="15m")
    ap.add_argument("--sw", type=int, default=20); ap.add_argument("--pairs", type=int, default=60)
    ap.add_argument("--z", type=float, default=45); ap.add_argument("--cost", type=float, default=0.10)
    ap.add_argument("--il", type=int, default=5, help="младший слой (internal_len); держать пропорцию ~4:1 к --sw")
    ap.add_argument("--minlag", type=float, default=0, help="минимум часов от вершины w5 до входа")
    ap.add_argument("--maxhold_h", type=float, default=0, help="потолок удержания в часах (0 = 240 HTF-баров)")
    ap.add_argument("--entry_w_h", type=float, default=0, help="окно входа от вершины в часах (0 = 24 HTF-бара)")
    ap.add_argument("--entry", default="cross", choices=["cross", "line24", "atr"], help="триггер входа на LTF")
    ap.add_argument("--ctx1d", type=int, default=0, help="дневной контекст: масштаб дневных свингов (0 = выкл)")
    a = ap.parse_args()
    global INTERNAL_LEN, MIN_LAG_H, MAXHOLD_H, ENTRY_W_H, ENTRY_MODE, CTX_1D, CTX_SW
    CTX_1D = a.ctx1d > 0; CTX_SW = a.ctx1d if a.ctx1d > 0 else 10
    INTERNAL_LEN = a.il
    MIN_LAG_H = a.minlag
    MAXHOLD_H = a.maxhold_h
    ENTRY_W_H = a.entry_w_h
    ENTRY_MODE = a.entry
    syms = universe(a.htf, n=a.pairs)
    if a.ltf == "1m" or a.htf in ("1m", "3m"):   # паркеты — только монеты, у которых есть 1m
        have = {p.stem for p in PARQ_1M.glob("*.parquet")}
        syms = [s for s in universe("15m", n=500) if s.replace("/", "") in have]
    print(f"OKO-SM волны · HTF {a.htf} sw={a.sw} → LTF {a.ltf} · монет {len(syms)} · зона |WT|>{a.z}", flush=True)
    rs = np.random.RandomState(20260912); rows = []
    for i, s in enumerate(syms, 1):
        try:
            rows += run_symbol(s, a.htf, a.ltf, a.sw, a.z, a.cost, rs)
        except Exception as ex:
            print(f"  [skip] {s}: {type(ex).__name__} {ex}", flush=True)
        if i % 10 == 0:
            print(f"  {i}/{len(syms)} · строк {len(rows)}", flush=True)
    if not rows:
        print("НЕТ СДЕЛОК"); return
    d = pd.DataFrame(rows)
    _il = ("" if a.il == 5 else f"_il{a.il}") + ("" if a.minlag == 0 else f"_lag{a.minlag:g}") + \
          ("" if a.maxhold_h == 0 else f"_hold{a.maxhold_h:g}") + ("" if a.entry_w_h == 0 else f"_ew{a.entry_w_h:g}") + \
          ("" if a.entry == "cross" else f"_{a.entry}") + ("" if a.ctx1d == 0 else f"_ctx{a.ctx1d}")
    d.to_pickle(Path(__file__).parent / f"wave5sm_{a.htf}_{a.ltf}_sw{a.sw}{_il}_z{int(a.z)}.pkl")
    report(d, a.htf, a.ltf, a.sw, a.z, a.cost)


if __name__ == "__main__":
    main()
