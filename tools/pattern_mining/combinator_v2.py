"""
SMC + ALL INDICATORS Pattern Mining v2.

Добавлены:
- MTF Pivots (1D/1W) — 7 уровней (R3..S3), флаги: near/above/below + bounce
- RSI (на каждом TF) — OS/OB зоны + cross
- Bullish/Bearish divergence (RSI и WT)
- Trend regime (TREND_UP / TREND_DOWN / RANGE по ATR + EMA slope)
- BTC correlation context (опционально)

Pattern Mining через greedy hill-climbing:
- 1f: все
- 2f: все
- 3f: top-40 1f
- 4f: top-30 3f + 1 фактор
- 5f: top-20 4f + 1 фактор

Запуск: python e:/tmp/smc_combinator_v2.py
"""
import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from pathlib import Path
# ARCH-128 (DS-313): bridge импортирует core.smc.smc_engine + tools.pattern_mining (абсолютные) →
# нужен КОРЕНЬ проекта в sys.path, иначе CLI-скрипты pattern_mining падают «No module named tools/core».
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from itertools import combinations
import pandas as pd
import numpy as np

HISTORY_DIR = Path("E:/MTF BOT/CURSOR/crypto_volume_bot/data/history/1h")
TP_R        = 2.0
FUTURE_BARS = 12
ATR_PERIOD  = 43
ATR_FACTOR  = 1.25
WT_OS       = -60
WT_OB       =  60
RSI_OS      = 30
RSI_OB      = 70
MIN_N       = 50

TOP_1F = 40
TOP_3F = 30
TOP_4F = 20


# ───────── Indicators ─────────
def wavetrend(df, n1=10, n2=21):
    hlc3 = (df["high"]+df["low"]+df["close"])/3
    esa  = hlc3.ewm(span=n1, adjust=False).mean()
    d    = (hlc3-esa).abs().ewm(span=n1, adjust=False).mean()
    ci   = (hlc3-esa)/(0.015*d.replace(0, np.nan))
    return ci.ewm(span=n2, adjust=False).mean()


def rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    s = pd.Series(close)
    delta = s.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100/(1+rs)).values


def atr_supertrend(df, period=ATR_PERIOD, factor=ATR_FACTOR):
    hl2 = (df["high"]+df["low"])/2
    tr  = pd.concat([df["high"]-df["low"], (df["high"]-df["close"].shift()).abs(), (df["low"]-df["close"].shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()
    upper = (hl2 + factor*atr).values
    lower = (hl2 - factor*atr).values
    closes = df["close"].values
    trend  = np.ones(len(df))
    for i in range(1, len(df)):
        c, cp = closes[i], closes[i-1]
        if not (upper[i] < upper[i-1] or cp > upper[i-1]): upper[i] = upper[i-1]
        if not (lower[i] > lower[i-1] or cp < lower[i-1]): lower[i] = lower[i-1]
        t = trend[i-1]
        trend[i] = 1 if (t==1 and c>lower[i]) or (t==-1 and c>upper[i]) else -1
    return trend


# ───────── Pivots ─────────
def calc_pivots(prev_h, prev_l, prev_c):
    PP = (prev_h + prev_l + prev_c) / 3
    R1 = 2*PP - prev_l
    R2 = PP + (prev_h - prev_l)
    R3 = prev_h + 2*(PP - prev_l)
    S1 = 2*PP - prev_h
    S2 = PP - (prev_h - prev_l)
    S3 = prev_l - 2*(prev_h - PP)
    return {"PP":PP, "R1":R1, "R2":R2, "R3":R3, "S1":S1, "S2":S2, "S3":S3}


def add_pivot_flags(df_1h: pd.DataFrame, out: dict, label: str = "1D"):
    """Считает 1D или 1W пивоты + флаги на сетке 1h."""
    rule = "1D" if label == "1D" else "1W"
    agg = df_1h.resample(rule).agg({"open":"first","high":"max","low":"min","close":"last"}).dropna()
    if len(agg) < 2:
        return

    # Для каждого следующего периода — пивоты из предыдущего
    pivots_map = {}
    keys = list(agg.index)
    for i in range(1, len(keys)):
        prev = agg.iloc[i-1]
        piv = calc_pivots(prev["high"], prev["low"], prev["close"])
        # Действуют от начала текущего периода до конца
        start = keys[i]
        end = keys[i+1] if i+1 < len(keys) else df_1h.index[-1] + pd.Timedelta(hours=1)
        pivots_map[start] = (piv, end)

    n = len(df_1h)
    close = df_1h["close"].values
    high  = df_1h["high"].values
    low   = df_1h["low"].values
    idx   = df_1h.index

    # Для каждого бара 1h определяем активные пивоты
    pp_arr = {k: np.full(n, np.nan) for k in ["PP","R1","R2","R3","S1","S2","S3"]}
    for start, (piv, end) in pivots_map.items():
        mask = (idx >= start) & (idx < end)
        for k, v in piv.items():
            pp_arr[k][mask] = v

    TOL = 0.005   # 0.5%
    for k, vals in pp_arr.items():
        near = (np.abs(close - vals) / vals < TOL) & ~np.isnan(vals)
        above = (close > vals) & ~np.isnan(vals)
        below = (close < vals) & ~np.isnan(vals)
        out[f"pivot_near_{k}_{label}"] = near
        out[f"pivot_above_{k}_{label}"] = above
        out[f"pivot_below_{k}_{label}"] = below

    # Bounce: коснулись за последние 3 бара и сейчас вернулись.
    # D-034 (2026-05-22): persistent flag — TRUE ещё 10 баров после event,
    # чтобы live observer (last-bar scan каждые 10 мин) мог поймать setup
    # после первоначального касания. Без этого bounce — узкое событие на
    # 1-2 барах, almost never TRUE при `iloc[-1]` lookup.
    BOUNCE_PERSIST = 10
    for k, vals in pp_arr.items():
        bounce_up   = np.zeros(n, dtype=bool)
        bounce_down = np.zeros(n, dtype=bool)
        for i in range(3, n):
            if np.isnan(vals[i]): continue
            for j in range(max(0, i-3), i):
                if np.isnan(vals[j]): continue
                if low[j] <= vals[j] * (1 + TOL) and low[j] >= vals[j] * (1 - 0.003) and close[i] > vals[i]:
                    bounce_up[i] = True
                if high[j] >= vals[j] * (1 - TOL) and high[j] <= vals[j] * (1 + 0.003) and close[i] < vals[i]:
                    bounce_down[i] = True
        # Forward-fill: flag остаётся TRUE BOUNCE_PERSIST баров после события
        bounce_up_p   = pd.Series(bounce_up).rolling(window=BOUNCE_PERSIST, min_periods=1).max().fillna(0).astype(bool).values
        bounce_down_p = pd.Series(bounce_down).rolling(window=BOUNCE_PERSIST, min_periods=1).max().fillna(0).astype(bool).values
        out[f"pivot_bounce_up_{k}_{label}"]   = bounce_up_p
        out[f"pivot_bounce_down_{k}_{label}"] = bounce_down_p

    # ── Числовые pivot-фичи (ARCH-118 Шаг 5, вариант B — рой team-ask 6/7) ──
    # ТОТ ЖЕ калькулятор (pp_arr), что и булевы → инвариант «один калькулятор».
    # Свёртка 70 булевых → 3 числовых (nearest/dist/relation) ПАРАЛЛЕЛЬНО булевым
    # (булевы остаются для 187 паттернов, числовые — для ML feature importance).
    level_names = ["PP", "R1", "R2", "R3", "S1", "S2", "S3"]
    mat = np.vstack([pp_arr[k] for k in level_names])          # (7, n) значения уровней
    with np.errstate(invalid="ignore", divide="ignore"):
        signed_pct = (close[None, :] - mat) / mat * 100.0      # (7, n) знаковое % до уровня
    abs_pct = np.abs(signed_pct)
    all_nan = np.all(np.isnan(abs_pct), axis=0)                # бары без активных пивотов
    safe = np.where(np.isnan(abs_pct), np.inf, abs_pct)
    nearest_li = np.argmin(safe, axis=0)                       # индекс ближайшего уровня
    cols = np.arange(n)
    nearest_dist = signed_pct[nearest_li, cols]                # знаковое % до ближайшего
    nearest_name = np.array(level_names, dtype=object)[nearest_li]
    relation = np.where(np.abs(nearest_dist) < TOL * 100, "near",
                        np.where(nearest_dist > 0, "above", "below")).astype(object)
    nearest_name[all_nan] = None
    nearest_dist[all_nan] = np.nan
    relation[all_nan] = None
    out[f"pivot_nearest_{label}"] = nearest_name               # категория: PP/R1../S3
    out[f"pivot_dist_pct_{label}"] = nearest_dist              # float: знаковое % (+ выше, - ниже)
    out[f"pivot_relation_{label}"] = relation                  # above/below/near


# ───────── Дивергенции (DEV-233): порт Pine "Divergence for Many Indicators v4") ─────────
# Эталон: memory/reference_pine_divergence.md. source="Close" (по выбору ARCH 29.05).
# Все сравнения и trendline — по CLOSE (не low/high): пивоты по close, точки сравнения close,
# обе линии валидации (цена + осциллятор) по close. Реальные пивоты pivothigh/low(prd,prd)
# вместо argmin скользящего окна. Trendline non-intersection. Без persistent rolling.
DIV_PIVOT_PRD = 5      # prd: баров подтверждения с каждой стороны (Pine default)
DIV_MAX_PP    = 10     # maxpp: сколько пивотов назад проверять
DIV_MAX_BARS  = 100    # maxbars: макс. расстояние между пивотами


def _wtx_divergences(wt: np.ndarray, low: np.ndarray, high: np.ndarray):
    """Дивергенции по WT — порт индикатора WT_X (Oscilador WaveTrend).

    ОТЛИЧАЕТСЯ от LonesomeTheBlue (RSI): пивот = williams-фрактал на САМОМ WT
    (центр = wt[i-2], 2 бара слева + 2 справа), цена сравнивается по LOW/HIGH (тени),
    БЕЗ trendline. Сравнение с ПРЕДЫДУЩИМ WT-фракталом того же типа.
    Pine offset=-2: фрактал подтверждается через 2 бара.

      bull regular: WT-фрактал-low + low[fr] < low[prev_fr] + wt[fr] > wt[prev_fr]
      bull hidden:  WT-фрактал-low + low[fr] > low[prev_fr] + wt[fr] < wt[prev_fr]
      bear regular: WT-фрактал-high + high[fr] > high[prev_fr] + wt[fr] < wt[prev_fr]
      bear hidden:  WT-фрактал-high + high[fr] < high[prev_fr] + wt[fr] > wt[prev_fr]

    Флаг ставится на баре подтверждения фрактала (i, центр i-2). Возвращает
    (bull_reg, bear_reg, bull_hid, bear_hid) длины n.
    """
    n = len(wt)
    bull_reg = np.zeros(n, dtype=bool)
    bear_reg = np.zeros(n, dtype=bool)
    bull_hid = np.zeros(n, dtype=bool)
    bear_hid = np.zeros(n, dtype=bool)

    prev_top_wt = prev_top_price = None   # предыдущий WT-фрактал-high
    prev_bot_wt = prev_bot_price = None   # предыдущий WT-фрактал-low

    for i in range(4, n):
        s = wt
        # f_top_fractal: s[i-4]<s[i-2] and s[i-3]<s[i-2] and s[i-2]>s[i-1] and s[i-2]>s[i]
        c = s[i-2]
        if np.isnan(c) or np.isnan(s[i-4]) or np.isnan(s[i-1]) or np.isnan(s[i]) or np.isnan(s[i-3]):
            continue
        is_top = s[i-4] < c and s[i-3] < c and c > s[i-1] and c > s[i]
        is_bot = s[i-4] > c and s[i-3] > c and c < s[i-1] and c < s[i]
        if is_top:
            hp = high[i-2]
            if prev_top_wt is not None:
                # bear regular: price HH + wt LH
                if hp > prev_top_price and c < prev_top_wt:
                    bear_reg[i] = True
                # bear hidden: price LH + wt HH
                if hp < prev_top_price and c > prev_top_wt:
                    bear_hid[i] = True
            prev_top_wt, prev_top_price = c, hp
        if is_bot:
            lp = low[i-2]
            if prev_bot_wt is not None:
                # bull regular: price LL + wt HL
                if lp < prev_bot_price and c > prev_bot_wt:
                    bull_reg[i] = True
                # bull hidden: price HL + wt LL
                if lp > prev_bot_price and c < prev_bot_wt:
                    bull_hid[i] = True
            prev_bot_wt, prev_bot_price = c, lp

    return bull_reg, bear_reg, bull_hid, bear_hid


def _pivot_indices(arr: np.ndarray, prd: int, is_high: bool) -> list:
    """Реальные пивоты (аналог ta.pivothigh/pivotlow): бар i — пивот, если он строго
    экстремальнее prd баров слева И prd баров справа. Возвращает список (idx, value),
    отсортированный по idx по возрастанию. Подтверждение запаздывает на prd баров."""
    n = len(arr)
    pivots = []
    for i in range(prd, n - prd):
        v = arr[i]
        if np.isnan(v):
            continue
        left = arr[i-prd:i]
        right = arr[i+1:i+prd+1]
        if is_high:
            if v > left.max() and v >= right.max():
                pivots.append((i, v))
        else:
            if v < left.min() and v <= right.min():
                pivots.append((i, v))
    return pivots


def _calc_divergence(close: np.ndarray, osc: np.ndarray, prd: int,
                     maxpp: int, maxbars: int, persist: int = 3):
    """Порт Pine "Divergence for Many Indicators v4", source="Close".

    Сравнение ПИВОТ-К-ПИВОТУ (как Pine): когда подтверждается новый пивот (idx+prd),
    сравниваем его с предыдущими maxpp пивотами того же типа. Дивергенция = расхождение
    цены и осциллятора между двумя пивотами + trendline non-intersection между ними.
    Флаг ставится на баре подтверждения правого пивота (cur_idx + prd) — это реальный
    момент когда дивергенцию видно (lookahead-safe). persist держит флаг N баров
    (anchor-логике ARCH-104 нужен живой флаг на момент LTF-входа; Pine рисует линию,
    у нас флаг).

    Возвращает 4 bool-массива длины n: (bull_reg, bear_reg, bull_hid, bear_hid).
    """
    n = len(close)
    bull_reg = np.zeros(n, dtype=bool)
    bear_reg = np.zeros(n, dtype=bool)
    bull_hid = np.zeros(n, dtype=bool)
    bear_hid = np.zeros(n, dtype=bool)

    pl = _pivot_indices(close, prd, is_high=False)  # пивоты-low (по close)
    ph = _pivot_indices(close, prd, is_high=True)   # пивоты-high (по close)

    def _trendline_ok(i_a, i_b, series, line_lo: bool):
        """Прямая между точками series[i_a]→series[i_b]. line_lo=True: ни один бар между
        ними не НИЖЕ прямой (bull). line_lo=False: не ВЫШЕ прямой (bear)."""
        span = i_b - i_a
        if span <= 1:
            return True
        va, vb = series[i_a], series[i_b]
        if np.isnan(va) or np.isnan(vb):
            return True
        slope = (vb - va) / span
        for k in range(1, span):
            vline = va + slope * k
            y = series[i_a + k]
            if np.isnan(y):
                continue
            if line_lo and y < vline:
                return False
            if (not line_lo) and y > vline:
                return False
        return True

    # ── Bull side: для каждого пивота-low сравниваем с предыдущими ──
    for j in range(1, len(pl)):
        i2, c2 = pl[j]           # текущий (правый) пивот-low
        o2 = osc[i2]
        if np.isnan(o2):
            continue
        confirm_bar = i2 + prd   # бар, на котором пивот подтверждён
        if confirm_bar >= n:
            continue
        # ищем назад до maxpp предыдущих пивотов
        for k in range(j - 1, max(-1, j - 1 - maxpp), -1):
            i1, c1 = pl[k]
            length = i2 - i1
            if length <= 5:
                continue
            if length > maxbars:
                break
            o1 = osc[i1]
            if np.isnan(o1):
                continue
            # Bull regular: price LL (c2<c1) + osc HL (o2>o1)
            if c2 < c1 and o2 > o1:
                if _trendline_ok(i1, i2, close, True) and _trendline_ok(i1, i2, osc, True):
                    bull_reg[confirm_bar] = True
                    break
            # Bull hidden: price HL (c2>c1) + osc LL (o2<o1)
            if c2 > c1 and o2 < o1:
                if _trendline_ok(i1, i2, close, True) and _trendline_ok(i1, i2, osc, True):
                    bull_hid[confirm_bar] = True
                    break

    # ── Bear side: для каждого пивота-high ──
    for j in range(1, len(ph)):
        i2, c2 = ph[j]
        o2 = osc[i2]
        if np.isnan(o2):
            continue
        confirm_bar = i2 + prd
        if confirm_bar >= n:
            continue
        for k in range(j - 1, max(-1, j - 1 - maxpp), -1):
            i1, c1 = ph[k]
            length = i2 - i1
            if length <= 5:
                continue
            if length > maxbars:
                break
            o1 = osc[i1]
            if np.isnan(o1):
                continue
            # Bear regular: price HH (c2>c1) + osc LH (o2<o1)
            if c2 > c1 and o2 < o1:
                if _trendline_ok(i1, i2, close, False) and _trendline_ok(i1, i2, osc, False):
                    bear_reg[confirm_bar] = True
                    break
            # Bear hidden: price LH (c2<c1) + osc HH (o2>o1)
            if c2 < c1 and o2 > o1:
                if _trendline_ok(i1, i2, close, False) and _trendline_ok(i1, i2, osc, False):
                    bear_hid[confirm_bar] = True
                    break

    # ── LIVE-ветка (Pine dontconfirm=true): на КАЖДОМ баре сравниваем текущий бар
    # с последним подтверждённым пивотом (правый конец = живой бар, не ждём пока он
    # станет пивотом). Так маркер появляется в тот же момент, что на TradingView.
    # Левый конец остаётся подтверждённым пивотом. Фильтр входа: osc/price разворот.
    def _last_confirmed_pivot(pivs, i):
        """Последний пивот, чей правый край подтверждён к бару i (idx+prd <= i)."""
        best = None
        for (pidx, pval) in pivs:
            if pidx + prd <= i:
                best = (pidx, pval)
            else:
                break
        return best

    for i in range(prd + 6, n):
        if np.isnan(osc[i]) or np.isnan(osc[i-1]):
            continue
        # Bull: вход если осц растёт ИЛИ цена растёт (начало отскока вверх).
        # Правый конец дивергенции = самый низкий close ПОСЛЕ левого пивота (running-min),
        # а не текущий бар — Pine рисует линию к фактическому экстремуму. Текущий бар лишь
        # триггер «отскок начался».
        if osc[i] > osc[i-1] or close[i] > close[i-1]:
            piv = _last_confirmed_pivot(pl, i)
            if piv is not None:
                i1, c1 = piv
                if 5 < (i - i1) <= maxbars and not np.isnan(osc[i1]):
                    seg = close[i1+1:i+1]
                    i2 = i1 + 1 + int(np.argmin(seg))   # фактический low после пивота
                    c2, o2, o1 = close[i2], osc[i2], osc[i1]
                    if not np.isnan(o2) and (i2 - i1) > 1:
                        # Bull regular: price LL + osc HL
                        if c2 < c1 and o2 > o1:
                            if _trendline_ok(i1, i2, close, True) and _trendline_ok(i1, i2, osc, True):
                                bull_reg[i] = True
                        # Bull hidden: price HL + osc LL
                        elif c2 > c1 and o2 < o1:
                            if _trendline_ok(i1, i2, close, True) and _trendline_ok(i1, i2, osc, True):
                                bull_hid[i] = True
        # Bear: вход если осц падает ИЛИ цена падает (начало отката вниз).
        # Правый конец = самый высокий close после левого пивота (running-max).
        if osc[i] < osc[i-1] or close[i] < close[i-1]:
            piv = _last_confirmed_pivot(ph, i)
            if piv is not None:
                i1, c1 = piv
                if 5 < (i - i1) <= maxbars and not np.isnan(osc[i1]):
                    seg = close[i1+1:i+1]
                    i2 = i1 + 1 + int(np.argmax(seg))   # фактический high после пивота
                    c2, o2, o1 = close[i2], osc[i2], osc[i1]
                    if not np.isnan(o2) and (i2 - i1) > 1:
                        # Bear regular: price HH + osc LH
                        if c2 > c1 and o2 < o1:
                            if _trendline_ok(i1, i2, close, False) and _trendline_ok(i1, i2, osc, False):
                                bear_reg[i] = True
                        # Bear hidden: price LH + osc HH
                        elif c2 < c1 and o2 > o1:
                            if _trendline_ok(i1, i2, close, False) and _trendline_ok(i1, i2, osc, False):
                                bear_hid[i] = True

    # persist: держим флаг N баров (для anchor-матчинга на момент LTF-входа)
    if persist > 1:
        for arr in (bull_reg, bear_reg, bull_hid, bear_hid):
            src = arr.copy()
            for i in range(n):
                if src[i]:
                    arr[i:min(n, i + persist)] = True
    return bull_reg, bear_reg, bull_hid, bear_hid


# ───────── SMC + indicators флаги ─────────
def compute_flags(df: pd.DataFrame, label: str, include_pivots: bool = False) -> pd.DataFrame:
    n = len(df)
    high  = df["high"].values
    low   = df["low"].values
    close = df["close"].values
    open_ = df["open"].values
    volume= df["volume"].values if "volume" in df else np.zeros(n)

    out = {}

    # ── ARCH-128 эталон через smc_engine bridge ──────────────────────────
    from tools.pattern_mining.swing_service_bridge import (
        etl_fvg, etl_order_blocks, etl_bos_choch, etl_ote_premium, etl_eql_eql,
        etl_fvg_overlap, etl_elliott, etl_regime,   # ARCH-128 Шаг 2 (Claude)
        etl_swing_structure,                         # HH/HL/LH/LL
    )

    # ─ FVG (ARCH-128: структурный, порог значимости) ─────────────────────
    fvg_etl = etl_fvg(df)
    bull_fvg = fvg_etl["bull_fvg"]; bull_fvg_in = fvg_etl["bull_fvg_in"]
    bear_fvg = fvg_etl["bear_fvg"]; bear_fvg_in = fvg_etl["bear_fvg_in"]
    out[f"bull_fvg_{label}"]    = bull_fvg
    out[f"bull_fvg_in_{label}"] = bull_fvg_in
    out[f"bear_fvg_{label}"]    = bear_fvg
    out[f"bear_fvg_in_{label}"] = bear_fvg_in

    # ─ OB (ARCH-128: структурный слом + ATR(200) + mitigation) ───────────
    ob_etl = etl_order_blocks(df)
    bull_ob = ob_etl["bull_ob"]; bull_ob_near = ob_etl["bull_ob_near"]
    bear_ob = ob_etl["bear_ob"]; bear_ob_near = ob_etl["bear_ob_near"]
    out[f"bull_ob_{label}"]      = bull_ob
    out[f"bull_ob_near_{label}"] = bull_ob_near
    out[f"bear_ob_{label}"]      = bear_ob
    out[f"bear_ob_near_{label}"] = bear_ob_near
    out[f"bull_ob_mitigated_{label}"] = ob_etl["bull_ob_mitigated"]   # ARCH-128 Шаг 2
    out[f"bear_ob_mitigated_{label}"] = ob_etl["bear_ob_mitigated"]

    # ─ BOS/CHoCH (ARCH-128: LuxAlgo + объём + закрепление) ───────────────
    bos_etl = etl_bos_choch(df)
    bull_bos = bos_etl["bull_bos"]; bear_bos = bos_etl["bear_bos"]
    bull_choch = bos_etl["bull_choch"]; bear_choch = bos_etl["bear_choch"]
    out[f"bull_bos_{label}"]    = bull_bos
    out[f"bear_bos_{label}"]    = bear_bos
    out[f"bull_choch_{label}"]  = bull_choch
    out[f"bear_choch_{label}"]  = bear_choch

    # ─ OTE & Premium/Discount (ARCH-128: build_ote + find_choch_ote) ─────
    ote_etl = etl_ote_premium(df)
    ote_long = ote_etl["ote_long"]; ote_short = ote_etl["ote_short"]
    premium = ote_etl["premium"]; discount = ote_etl["discount"]
    out[f"ote_long_{label}"]  = ote_long
    out[f"ote_short_{label}"] = ote_short
    out[f"premium_{label}"]   = premium
    out[f"discount_{label}"]  = discount

    # ─ ATR Supertrend (оставлен как есть — не SMC) ──────────────────────
    atr = atr_supertrend(df)
    out[f"atr_up_{label}"]   = atr == 1
    out[f"atr_down_{label}"] = atr == -1
    atr_cu = np.zeros(n, dtype=bool); atr_cd = np.zeros(n, dtype=bool)
    for i in range(1, n):
        for j in range(max(1, i-2), i+1):
            if atr[j-1] == -1 and atr[j] == 1: atr_cu[i] = True
            if atr[j-1] ==  1 and atr[j] == -1: atr_cd[i] = True
    out[f"atr_cross_up_{label}"]   = atr_cu
    out[f"atr_cross_down_{label}"] = atr_cd

    # ─ WaveTrend ──────────────────────────────────────────────────────────
    wt = wavetrend(df).values            # wt1 (EMA21)
    wt2 = pd.Series(wt).rolling(window=4, min_periods=1).mean().values  # сигнальная SMA4
    out[f"wt_os_{label}"] = wt < WT_OS
    out[f"wt_ob_{label}"] = wt > WT_OB
    # DEV-234: wt_cross = кросс wt1×wt2 В ЗОНЕ OS/OB (как confluence_scanner / mtf_checker /
    # WT_X), НЕ кросс нуля. До 29.05 combinator считал кросс нуля → ARCH-104 паттерны с
    # wt_cross_up/down якорями (вкл. D-051 gate) матчились на неверном событии. Выровнено
    # с каноничной логикой основного бота (confluence_scanner.py:172-178).
    wt_cu = np.zeros(n, dtype=bool); wt_cd = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if np.isnan(wt[i]) or np.isnan(wt[i-1]) or np.isnan(wt2[i]) or np.isnan(wt2[i-1]):
            continue
        # cross up из зоны OS: wt1 пересекает wt2 снизу вверх, был в OS
        if wt[i-1] <= wt2[i-1] and wt[i] > wt2[i] and wt[i-1] < WT_OS:
            wt_cu[i] = True
        # cross down из зоны OB: wt1 пересекает wt2 сверху вниз, был в OB
        if wt[i-1] >= wt2[i-1] and wt[i] < wt2[i] and wt[i-1] > WT_OB:
            wt_cd[i] = True
    out[f"wt_cross_up_{label}"]   = wt_cu
    out[f"wt_cross_down_{label}"] = wt_cd

    # ─ WT Divergences (DEV-233): порт WT_X (фрактал на WT + low/high) ─
    # WT_X ≠ LonesomeTheBlue: пивот = williams-фрактал на самом WT, цена по low/high,
    # без trendline, сравнение с предыдущим WT-фракталом. RSI ниже — другой алгоритм (close).
    wt_div_bull_reg, wt_div_bear_reg, wt_div_bull_hid, wt_div_bear_hid = _wtx_divergences(
        wt, low, high)
    out[f"wt_div_bull_regular_{label}"] = wt_div_bull_reg  # ARCH-118 naming: reg→regular
    out[f"wt_div_bear_regular_{label}"] = wt_div_bear_reg
    out[f"wt_div_bull_hidden_{label}"] = wt_div_bull_hid
    out[f"wt_div_bear_hidden_{label}"] = wt_div_bear_hid

    # ─ RSI ────────────────────────────────────────────────────────────────
    r = rsi(close, 14)
    out[f"rsi_os_{label}"] = r < RSI_OS
    out[f"rsi_ob_{label}"] = r > RSI_OB
    # RSI cross 50
    rsi_x_up = np.zeros(n, dtype=bool); rsi_x_dn = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not np.isnan(r[i]) and not np.isnan(r[i-1]):
            if r[i-1] < 50 and r[i] >= 50: rsi_x_up[i] = True
            if r[i-1] >= 50 and r[i] < 50: rsi_x_dn[i] = True
    out[f"rsi_cross50_up_{label}"]   = rsi_x_up
    out[f"rsi_cross50_down_{label}"] = rsi_x_dn

    # ─ RSI Divergences (DEV-233): pivot-based порт Pine, source="Close" ─
    # Единый алгоритм с WT (тот же _calc_divergence). bull_div/bear_div = regular,
    # rsi_div_*_hidden = hidden. Заменил argmin-окно (regular + D-040 hidden).
    rsi_bull_reg, rsi_bear_reg, rsi_bull_hid, rsi_bear_hid = _calc_divergence(
        close, r, DIV_PIVOT_PRD, DIV_MAX_PP, DIV_MAX_BARS)
    out[f"rsi_div_bull_regular_{label}"] = rsi_bull_reg  # ARCH-118 naming: bull_div→rsi_div_bull_regular
    out[f"rsi_div_bear_regular_{label}"] = rsi_bear_reg
    out[f"rsi_div_bull_hidden_{label}"] = rsi_bull_hid
    out[f"rsi_div_bear_hidden_{label}"] = rsi_bear_hid

    # ─ EQH/EQL (ARCH-128: структурные уровни) ────────────────────────────
    eql_etl = etl_eql_eql(df)
    eqh_sw = eql_etl["eqh_sweep"]; eql_sw = eql_etl["eql_sweep"]
    out[f"eqh_sweep_{label}"] = eqh_sw
    out[f"eql_sweep_{label}"] = eql_sw

    # ─ FVG overlap / Эллиотт / Regime троичный (ARCH-128 Шаг 2, Claude) ───
    ovr = etl_fvg_overlap(df)
    out[f"bull_fvg_overlap_{label}"]      = ovr["bull_fvg_overlap"]
    out[f"bear_fvg_overlap_{label}"]      = ovr["bear_fvg_overlap"]
    out[f"bull_fvg_overlap_held_{label}"] = ovr["bull_fvg_overlap_held"]
    out[f"bear_fvg_overlap_held_{label}"] = ovr["bear_fvg_overlap_held"]
    ell = etl_elliott(df)
    out[f"elliott_bull_impulse_{label}"] = ell["elliott_bull_impulse"]
    out[f"elliott_bear_impulse_{label}"] = ell["elliott_bear_impulse"]
    out[f"elliott_textbook_{label}"]     = ell["elliott_textbook"]
    reg = etl_regime(df)
    out[f"regime_bull_{label}"]  = reg["regime_bull"]
    out[f"regime_range_{label}"] = reg["regime_range"]
    out[f"regime_bear_{label}"]  = reg["regime_bear"]
    out[f"regime_dir_{label}"]   = reg["regime_dir"]   # числовой троичный (+1/0/−1)
    sw = etl_swing_structure(df)                        # HH/HL/LH/LL — тип swing-точки
    out[f"hh_{label}"] = sw["hh"]; out[f"hl_{label}"] = sw["hl"]
    out[f"lh_{label}"] = sw["lh"]; out[f"ll_{label}"] = sw["ll"]

    # ─ Volume spike ───────────────────────────────────────────────────────
    if "volume" in df.columns:
        vol_sma = pd.Series(volume).rolling(20, min_periods=5).mean().values
        out[f"vol_spike_{label}"] = (volume > 1.5 * vol_sma) & (vol_sma > 0)

    # ─ Momentum ───────────────────────────────────────────────────────────
    bull_mom = np.zeros(n, dtype=bool); bear_mom = np.zeros(n, dtype=bool)
    for i in range(3, n):
        if close[i] > close[i-1] > close[i-2] > close[i-3]: bull_mom[i] = True
        if close[i] < close[i-1] < close[i-2] < close[i-3]: bear_mom[i] = True
    out[f"bull_mom_{label}"] = bull_mom
    out[f"bear_mom_{label}"] = bear_mom

    # ─ EMA50 / EMA200 ─────────────────────────────────────────────────────
    ema50  = pd.Series(close).ewm(span=50, adjust=False).mean().values
    ema200 = pd.Series(close).ewm(span=200, adjust=False).mean().values
    out[f"above_ema50_{label}"]  = close > ema50
    out[f"below_ema50_{label}"]  = close < ema50
    out[f"above_ema200_{label}"] = close > ema200
    out[f"below_ema200_{label}"] = close < ema200
    out[f"ema50_above_ema200_{label}"] = ema50 > ema200    # бычий tend
    out[f"ema50_below_ema200_{label}"] = ema50 < ema200    # медвежий

    # ─ CMA Lines (Фибо-SMA 21/55/89/144/233 — MA-магниты, OKO-SM пользователя) ──
    # Нестандартные Фибо-периоды (не 50/100/200) — уровни-магниты, не дублируют EMA.
    cma_periods = [21, 55, 89, 144, 233]
    cmas = {p: pd.Series(close).rolling(p, min_periods=1).mean().values for p in cma_periods}
    for p in cma_periods:
        out[f"cma{p}_above_{label}"] = close > cmas[p]   # позиция относительно Фибо-MA
    cma_near = np.zeros(n, dtype=bool)                    # магнит: цена ≤0.3% к любой CMA
    for p in cma_periods:
        cma_near |= np.abs(close - cmas[p]) / np.where(close != 0, close, 1) <= 0.003
    out[f"cma_near_{label}"] = cma_near
    cma_stack = np.vstack([cmas[p] for p in cma_periods])  # кластер: все 5 CMA ≤0.5% спред = сильный уровень
    out[f"cma_cluster_{label}"] = (cma_stack.max(0) - cma_stack.min(0)) / np.where(close != 0, close, 1) <= 0.005

    # ─ Dynamic Channel (linreg slope + 2σ канал, OKO-SM) — ВЕКТОРНО (sliding_window) ──
    # slope → тренд (дублирует regime/ATR), границы → зоны разворота (уникально).
    dc_len = 100
    dc_su = np.zeros(n, dtype=bool); dc_sd = np.zeros(n, dtype=bool)
    dc_up = np.zeros(n, dtype=bool); dc_lo = np.zeros(n, dtype=bool)
    if n > dc_len:
        from numpy.lib.stride_tricks import sliding_window_view
        W = sliding_window_view(close, dc_len)            # (n-dc_len+1, dc_len)
        k = np.arange(dc_len); km = k.mean(); kvar = ((k - km) ** 2).sum()
        ym = W.mean(axis=1)
        slope = ((W - ym[:, None]) * (k - km)).sum(axis=1) / kvar
        intercept = ym - slope * km
        reg = slope * (dc_len - 1) + intercept            # линия на последнем баре окна
        dev = (W - (slope[:, None] * k + intercept[:, None])).std(axis=1) * 2
        ii = np.arange(dc_len, n)                          # бар i → окно close[i-dc_len:i] = W[i-dc_len]
        sl = slope[:len(ii)]; rg = reg[:len(ii)]; dv = dev[:len(ii)]; ci = close[ii]
        dc_su[ii] = sl > 0
        dc_sd[ii] = sl < 0
        dc_up[ii] = ci >= rg + dv
        dc_lo[ii] = ci <= rg - dv
    out[f"dc_slope_up_{label}"]   = dc_su
    out[f"dc_slope_down_{label}"] = dc_sd
    out[f"dc_at_upper_{label}"]   = dc_up
    out[f"dc_at_lower_{label}"]   = dc_lo

    # ─ Pivots (только для исходного 1h TF) ────────────────────────────────
    if include_pivots:
        add_pivot_flags(df, out, "1D")
        add_pivot_flags(df, out, "1W")

    return pd.DataFrame(out, index=df.index)


def aggregate_tf(df_1h: pd.DataFrame, target: str) -> pd.DataFrame:
    rule = {"4h":"4h", "1d":"1D"}[target]
    return df_1h.resample(rule).agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()


def simulate(df: pd.DataFrame, tp_r: float = TP_R, future: int = FUTURE_BARS):
    n = len(df)
    high = df["high"].values; low = df["low"].values; close = df["close"].values
    r_long  = np.full(n, np.nan)
    r_short = np.full(n, np.nan)
    for i in range(20, n - future - 1):
        price = close[i]
        sl_l = low[i-10:i+1].min() * 0.999
        sld = price - sl_l
        if sld > 0 and sld/price < 0.06:
            tp = price + sld*tp_r
            fh = high[i+1:i+1+future]; fl = low[i+1:i+1+future]
            ht = (fh >= tp); hs = (fl <= sl_l)
            if ht.any() and hs.any():
                r_long[i] = tp_r if np.argmax(ht) <= np.argmax(hs) else -1.0
            elif ht.any(): r_long[i] = tp_r
            elif hs.any(): r_long[i] = -1.0
            else:          r_long[i] = (close[i+future]-price)/sld
        sl_s = high[i-10:i+1].max() * 1.001
        sld_s = sl_s - price
        if sld_s > 0 and sld_s/price < 0.06:
            tp = price - sld_s*tp_r
            fh = high[i+1:i+1+future]; fl = low[i+1:i+1+future]
            ht = (fl <= tp); hs = (fh >= sl_s)
            if ht.any() and hs.any():
                r_short[i] = tp_r if np.argmax(ht) <= np.argmax(hs) else -1.0
            elif ht.any(): r_short[i] = tp_r
            elif hs.any(): r_short[i] = -1.0
            else:          r_short[i] = (price-close[i+future])/sld_s
    return r_long, r_short


def process_symbol(path: Path):
    try:
        df_1h = pd.read_parquet(path)
        df_1h.columns = [c.lower() for c in df_1h.columns]
        if "ts" in df_1h.columns:
            try:
                df_1h["ts"] = pd.to_datetime(df_1h["ts"], unit="ms", utc=True)
            except Exception:
                df_1h["ts"] = pd.to_datetime(df_1h["ts"], utc=True, errors="coerce")
            df_1h = df_1h.set_index("ts")
        df_1h = df_1h[["open","high","low","close","volume"]].dropna().sort_index()
        if len(df_1h) < 200: return None
        df_4h = aggregate_tf(df_1h, "4h")
        df_1d = aggregate_tf(df_1h, "1d")
        if len(df_4h) < 50 or len(df_1d) < 30: return None
        f_1h = compute_flags(df_1h, "1h", include_pivots=True)
        # Lookahead fix: HTF индекс на конец периода (только после close)
        f_4h_raw = compute_flags(df_4h, "4h")
        f_4h_raw.index = f_4h_raw.index + pd.Timedelta(hours=4)
        f_4h = f_4h_raw.reindex(df_1h.index, method="ffill").fillna(False)
        f_1d_raw = compute_flags(df_1d, "1d")
        f_1d_raw.index = f_1d_raw.index + pd.Timedelta(days=1)
        f_1d = f_1d_raw.reindex(df_1h.index, method="ffill").fillna(False)
        all_flags = pd.concat([f_1h, f_4h, f_1d], axis=1).astype(bool)
        r_long, r_short = simulate(df_1h)
        return all_flags, r_long, r_short
    except Exception as e:
        print(f"  ERR {path.stem}: {e}")
        return None


# ───────── Combinator engine ─────────
def evaluate(flags_dict, factors: tuple, direction: str):
    all_rs = []
    for _, (flags, r_long, r_short) in flags_dict.items():
        mask = np.ones(len(flags), dtype=bool)
        for f in factors:
            if f not in flags.columns: return None
            mask &= flags[f].values
        if not mask.any(): continue
        rs = r_long if direction == "LONG" else r_short
        rs_valid = rs[mask & ~np.isnan(rs)]
        if len(rs_valid):
            all_rs.extend(rs_valid)
    if len(all_rs) < MIN_N: return None
    arr = np.array(all_rs)
    return {"n": len(arr), "avgR": float(arr.mean()), "sumR": float(arr.sum()),
            "WR": float((arr > 0).mean()*100), "stdR": float(arr.std())}


def score_fn(stats):
    return stats["avgR"] * (stats["WR"]/100) * np.log(stats["n"]) if stats else -999


# ───────── Main ─────────
def main():
    files = sorted(HISTORY_DIR.glob("*.parquet"))
    print(f"Найдено parquet: {len(files)}")
    if not files: return

    print(f"\n[1] Загрузка {len(files)} пар + SMC + Pivots + RSI...")
    t0 = time.time()
    flags_dict = {}
    for path in files:
        res = process_symbol(path)
        if res is None: continue
        flags_dict[path.stem] = res
        if len(flags_dict) % 5 == 0:
            print(f"  ...{len(flags_dict)}/{len(files)} ({time.time()-t0:.0f}с)")
    print(f"  Готово за {time.time()-t0:.0f}с. Пар: {len(flags_dict)}")
    if not flags_dict: return

    first = next(iter(flags_dict.values()))[0]
    ALL = list(first.columns)
    print(f"  Всего флагов: {len(ALL)}")

    LONG_F = [f for f in ALL if any(s in f for s in [
        "bull_","ote_long","discount","wt_os","atr_cross_up","atr_up",
        "eql_sweep","wt_cross_up","above_ema","vol_spike","rsi_os","rsi_cross50_up",
        "ema50_above_ema200","pivot_bounce_up","pivot_near_S","pivot_above_PP"
    ])]
    SHORT_F = [f for f in ALL if any(s in f for s in [
        "bear_","ote_short","premium","wt_ob","atr_cross_down","atr_down",
        "eqh_sweep","wt_cross_down","below_ema","vol_spike","rsi_ob","rsi_cross50_down",
        "ema50_below_ema200","pivot_bounce_down","pivot_near_R","pivot_below_PP"
    ])]
    print(f"  LONG: {len(LONG_F)}, SHORT: {len(SHORT_F)}")

    results = []

    print(f"\n[2] 1-факторные...")
    t1 = time.time()
    for direction, factors in [("LONG", LONG_F), ("SHORT", SHORT_F)]:
        for f in factors:
            s = evaluate(flags_dict, (f,), direction)
            if s:
                s.update({"pattern": f, "direction": direction, "k": 1, "score": score_fn(s)})
                results.append(s)
    print(f"  → {sum(1 for r in results if r['k']==1)} ({time.time()-t1:.0f}с)")

    print(f"\n[3] 2-факторные...")
    t1 = time.time()
    for direction, factors in [("LONG", LONG_F), ("SHORT", SHORT_F)]:
        for f1, f2 in combinations(factors, 2):
            s = evaluate(flags_dict, (f1, f2), direction)
            if s:
                s.update({"pattern": " + ".join([f1,f2]), "direction": direction, "k": 2,
                         "score": score_fn(s), "_factors": (f1, f2)})
                results.append(s)
    print(f"  → {sum(1 for r in results if r['k']==2)} ({time.time()-t1:.0f}с)")

    print(f"\n[4] 3-факторные (топ-{TOP_1F} 1f)...")
    t1 = time.time()
    for direction in ["LONG", "SHORT"]:
        top1 = sorted([r for r in results if r["k"]==1 and r["direction"]==direction and r["avgR"] > 0], key=lambda r: -r["avgR"])[:TOP_1F]
        pool = [r["pattern"] for r in top1]
        for f1, f2, f3 in combinations(pool, 3):
            s = evaluate(flags_dict, (f1, f2, f3), direction)
            if s:
                s.update({"pattern": " + ".join([f1,f2,f3]), "direction": direction, "k": 3,
                         "score": score_fn(s), "_factors": (f1, f2, f3)})
                results.append(s)
    print(f"  → {sum(1 for r in results if r['k']==3)} ({time.time()-t1:.0f}с)")

    print(f"\n[5] 4-факторные (топ-{TOP_3F} 3f + 1 фактор)...")
    t1 = time.time()
    for direction, factors in [("LONG", LONG_F), ("SHORT", SHORT_F)]:
        top3 = sorted([r for r in results if r["k"]==3 and r["direction"]==direction and r["avgR"] > 0], key=lambda r: -r["score"])[:TOP_3F]
        seen = set()
        for r3 in top3:
            base = r3["_factors"]
            for fnew in factors:
                if fnew in base: continue
                pat = tuple(sorted(list(base) + [fnew]))
                if pat in seen: continue
                seen.add(pat)
                s = evaluate(flags_dict, pat, direction)
                if s:
                    s.update({"pattern": " + ".join(pat), "direction": direction, "k": 4,
                             "score": score_fn(s), "_factors": pat})
                    results.append(s)
    print(f"  → {sum(1 for r in results if r['k']==4)} ({time.time()-t1:.0f}с)")

    print(f"\n[6] 5-факторные (топ-{TOP_4F} 4f + 1 фактор)...")
    t1 = time.time()
    for direction, factors in [("LONG", LONG_F), ("SHORT", SHORT_F)]:
        top4 = sorted([r for r in results if r["k"]==4 and r["direction"]==direction and r["avgR"] > 0], key=lambda r: -r["score"])[:TOP_4F]
        seen = set()
        for r4 in top4:
            base = r4["_factors"]
            for fnew in factors:
                if fnew in base: continue
                pat = tuple(sorted(list(base) + [fnew]))
                if pat in seen: continue
                seen.add(pat)
                s = evaluate(flags_dict, pat, direction)
                if s:
                    s.update({"pattern": " + ".join(pat), "direction": direction, "k": 5,
                             "score": score_fn(s), "_factors": pat})
                    results.append(s)
    print(f"  → {sum(1 for r in results if r['k']==5)} ({time.time()-t1:.0f}с)")

    print(f"\n{'='*110}")
    print(f"ВСЕГО ПАТТЕРНОВ: {len(results)}  |  пар: {len(flags_dict)}  |  TP={TP_R}R  |  fut: {FUTURE_BARS}h  |  min n={MIN_N}")
    print(f"{'='*110}")

    print(f"\n=== ТОП-30 ВСЕХ паттернов ===")
    print(f"{'#':<3} {'k':<2} {'dir':<5} {'n':>6} {'avgR':>7} {'WR%':>6} {'sumR':>9} {'score':>7}  pattern")
    print("-"*110)
    for i, r in enumerate(sorted(results, key=lambda r: -r["score"])[:30], 1):
        pat = r["pattern"][:60] + ("…" if len(r["pattern"])>60 else "")
        print(f"{i:<3} {r['k']:<2} {r['direction']:<5} {r['n']:>6} {r['avgR']:>+7.3f} {r['WR']:>5.1f}% {r['sumR']:>+9.1f} {r['score']:>+7.3f}  {pat}")

    for k in [1,2,3,4,5]:
        for d in ["LONG","SHORT"]:
            top = sorted([r for r in results if r["k"]==k and r["direction"]==d], key=lambda r: -r["score"])[:8]
            if not top: continue
            print(f"\n=== ТОП-8 {k}-факторных {d} ===")
            for r in top:
                pat = r["pattern"][:80] + ("…" if len(r["pattern"])>80 else "")
                print(f"  n={r['n']:>5} avgR={r['avgR']:>+.3f} WR={r['WR']:>4.1f}% sumR={r['sumR']:>+7.1f}  {pat}")

    out = Path("e:/tmp/smc_combinator_v2_results.csv")
    df_res = pd.DataFrame([{k:v for k,v in r.items() if not k.startswith("_")} for r in results])
    df_res = df_res.sort_values("score", ascending=False)
    df_res.to_csv(out, index=False, encoding="utf-8")
    print(f"\nПолный CSV: {out}  ({len(df_res)} строк)")


if __name__ == "__main__":
    main()
