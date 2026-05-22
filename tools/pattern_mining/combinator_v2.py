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


# ───────── SMC + indicators флаги ─────────
def compute_flags(df: pd.DataFrame, label: str, include_pivots: bool = False) -> pd.DataFrame:
    n = len(df)
    high  = df["high"].values
    low   = df["low"].values
    close = df["close"].values
    open_ = df["open"].values
    volume= df["volume"].values if "volume" in df else np.zeros(n)

    out = {}

    # ─ FVG ────────────────────────────────────────────────────────────────
    bull_fvg = np.zeros(n, dtype=bool); bull_fvg_in = np.zeros(n, dtype=bool)
    bear_fvg = np.zeros(n, dtype=bool); bear_fvg_in = np.zeros(n, dtype=bool)
    L = 30
    for i in range(2, n):
        bz = None; sz = None
        for j in range(i, max(2, i-L), -1):
            if bz is None and j >= 2 and low[j] > high[j-2]:
                bot, top = high[j-2], low[j]
                if (top-bot)/bot*100 >= 0.05 and i > j and low[j+1:i+1].min() > bot * 0.998:
                    bz = (bot, top)
            if sz is None and j >= 2 and high[j] < low[j-2]:
                top, bot = low[j-2], high[j]
                if (top-bot)/bot*100 >= 0.05 and i > j and high[j+1:i+1].max() < top * 1.002:
                    sz = (bot, top)
            if bz and sz: break
        if bz:
            bull_fvg[i] = True
            if bz[0]*0.998 <= close[i] <= bz[1]*1.002: bull_fvg_in[i] = True
        if sz:
            bear_fvg[i] = True
            if sz[0]*0.998 <= close[i] <= sz[1]*1.002: bear_fvg_in[i] = True
    out[f"bull_fvg_{label}"]    = bull_fvg
    out[f"bull_fvg_in_{label}"] = bull_fvg_in
    out[f"bear_fvg_{label}"]    = bear_fvg
    out[f"bear_fvg_in_{label}"] = bear_fvg_in

    # ─ OB ─────────────────────────────────────────────────────────────────
    bull_ob = np.zeros(n, dtype=bool); bull_ob_near = np.zeros(n, dtype=bool)
    bear_ob = np.zeros(n, dtype=bool); bear_ob_near = np.zeros(n, dtype=bool)
    L = 25
    for i in range(4, n):
        bz = None; sz = None
        for j in range(i-2, max(4, i-L), -1):
            if bz is None and j+2 < n and close[j] < open_[j]:
                if close[j+1] > close[j] and close[j+2] > close[j+1]:
                    ob_bot, ob_top = low[j], high[j]
                    if low[j+1:i+1].min() > ob_bot * 0.999: bz = (ob_bot, ob_top)
            if sz is None and j+2 < n and close[j] > open_[j]:
                if close[j+1] < close[j] and close[j+2] < close[j+1]:
                    ob_bot, ob_top = low[j], high[j]
                    if high[j+1:i+1].max() < ob_top * 1.001: sz = (ob_bot, ob_top)
            if bz and sz: break
        if bz:
            bull_ob[i] = True
            if -0.5 <= (close[i] - bz[1])/close[i]*100 <= 3: bull_ob_near[i] = True
        if sz:
            bear_ob[i] = True
            if -0.5 <= (sz[0] - close[i])/close[i]*100 <= 3: bear_ob_near[i] = True
    out[f"bull_ob_{label}"]      = bull_ob
    out[f"bull_ob_near_{label}"] = bull_ob_near
    out[f"bear_ob_{label}"]      = bear_ob
    out[f"bear_ob_near_{label}"] = bear_ob_near

    # ─ BOS/CHoCH ──────────────────────────────────────────────────────────
    bull_bos = np.zeros(n, dtype=bool); bear_bos = np.zeros(n, dtype=bool)
    bull_choch = np.zeros(n, dtype=bool); bear_choch = np.zeros(n, dtype=bool)
    L = 20
    for i in range(L, n):
        hi_max = high[i-L:i].max()
        lo_min = low[i-L:i].min()
        if close[i] > hi_max:
            bull_bos[i] = True
            if bear_bos[i-L+5:i].any(): bull_choch[i] = True
        if close[i] < lo_min:
            bear_bos[i] = True
            if bull_bos[i-L+5:i].any(): bear_choch[i] = True
    out[f"bull_bos_{label}"]    = bull_bos
    out[f"bear_bos_{label}"]    = bear_bos
    out[f"bull_choch_{label}"]  = bull_choch
    out[f"bear_choch_{label}"]  = bear_choch

    # ─ OTE & Premium/Discount ─────────────────────────────────────────────
    ote_long  = np.zeros(n, dtype=bool); ote_short = np.zeros(n, dtype=bool)
    premium   = np.zeros(n, dtype=bool); discount  = np.zeros(n, dtype=bool)
    L = 40
    for i in range(L, n):
        hi = high[i-L:i].max(); lo = low[i-L:i].min()
        rng = hi - lo
        if rng < 1e-8: continue
        c = close[i]
        if hi - 0.79*rng <= c <= hi - 0.62*rng: ote_long[i] = True
        if lo + 0.62*rng <= c <= lo + 0.79*rng: ote_short[i] = True
        mid = (hi+lo)/2
        if c >= mid: premium[i] = True
        else:        discount[i] = True
    out[f"ote_long_{label}"]  = ote_long
    out[f"ote_short_{label}"] = ote_short
    out[f"premium_{label}"]   = premium
    out[f"discount_{label}"]  = discount

    # ─ ATR Supertrend ─────────────────────────────────────────────────────
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
    wt = wavetrend(df).values
    out[f"wt_os_{label}"] = wt < WT_OS
    out[f"wt_ob_{label}"] = wt > WT_OB
    wt_cu = np.zeros(n, dtype=bool); wt_cd = np.zeros(n, dtype=bool)
    for i in range(1, n):
        for j in range(max(1, i-2), i+1):
            if wt[j-1] < 0 and wt[j] >= 0: wt_cu[i] = True
            if wt[j-1] >= 0 and wt[j] < 0: wt_cd[i] = True
    out[f"wt_cross_up_{label}"]   = wt_cu
    out[f"wt_cross_down_{label}"] = wt_cd

    # ─ WT Divergences: 4 типа (regular + hidden, bull + bear) — D-040 (2026-05-22) ─
    # По образцу bull_div/bear_div (RSI ниже), но на WT и + hidden варианты.
    # Hidden = continuation: bull hidden = price HL + wt LL (тренд UP продолжается);
    # bear hidden = price LH + wt HH (тренд DOWN продолжается).
    # Persistent на 10 баров (как pivot_bounce).
    L_DIV = 14
    WT_DELTA = 1.5
    DIV_PERSIST = 10
    wt_div_bull_reg = np.zeros(n, dtype=bool)
    wt_div_bear_reg = np.zeros(n, dtype=bool)
    wt_div_bull_hid = np.zeros(n, dtype=bool)
    wt_div_bear_hid = np.zeros(n, dtype=bool)
    for i in range(L_DIV, n):
        w = wt[i-L_DIV:i]
        if np.isnan(w).all():
            continue
        lo_w = low[i-L_DIV:i]
        hi_w = high[i-L_DIV:i]
        first_half_wt = wt[i-L_DIV:i-L_DIV//2]
        # ─ Lows analysis (bull side) ─
        idx_min_p = int(np.argmin(lo_w))
        if 2 < idx_min_p < L_DIV-2:
            first_lo_min = lo_w[:idx_min_p].min()
            cur_low = low[i-1]
            if not np.isnan(first_half_wt).all():
                first_wt_min = np.nanmin(first_half_wt)
                if not np.isnan(first_wt_min):
                    cur_wt = wt[i-1]
                    if not np.isnan(cur_wt):
                        # Bull regular: price LL (cur < first) + wt HL (cur > first)
                        if cur_low < first_lo_min and cur_wt > first_wt_min + WT_DELTA:
                            wt_div_bull_reg[i] = True
                        # Bull hidden: price HL (cur > first) + wt LL (cur < first)
                        if cur_low > first_lo_min and cur_wt < first_wt_min - WT_DELTA:
                            wt_div_bull_hid[i] = True
        # ─ Highs analysis (bear side) ─
        idx_max_p = int(np.argmax(hi_w))
        if 2 < idx_max_p < L_DIV-2:
            first_hi_max = hi_w[:idx_max_p].max()
            cur_high = high[i-1]
            if not np.isnan(first_half_wt).all():
                first_wt_max = np.nanmax(first_half_wt)
                if not np.isnan(first_wt_max):
                    cur_wt = wt[i-1]
                    if not np.isnan(cur_wt):
                        # Bear regular: price HH + wt LH
                        if cur_high > first_hi_max and cur_wt < first_wt_max - WT_DELTA:
                            wt_div_bear_reg[i] = True
                        # Bear hidden: price LH + wt HH
                        if cur_high < first_hi_max and cur_wt > first_wt_max + WT_DELTA:
                            wt_div_bear_hid[i] = True
    # Persistent rolling
    for arr, name in [
        (wt_div_bull_reg, f"wt_div_bull_reg_{label}"),
        (wt_div_bear_reg, f"wt_div_bear_reg_{label}"),
        (wt_div_bull_hid, f"wt_div_bull_hidden_{label}"),
        (wt_div_bear_hid, f"wt_div_bear_hidden_{label}"),
    ]:
        out[name] = pd.Series(arr).rolling(window=DIV_PERSIST, min_periods=1).max().fillna(0).astype(bool).values

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

    # ─ Divergence (RSI vs price, упрощённо: цена ниже за окно но RSI выше) ─
    bull_div = np.zeros(n, dtype=bool); bear_div = np.zeros(n, dtype=bool)
    L = 14
    for i in range(L, n):
        # Bull div: цена сделала lower low, RSI сделал higher low
        recent_lows_price = low[i-L:i]
        recent_lows_rsi   = r[i-L:i] if not np.isnan(r[i-L:i]).all() else None
        if recent_lows_rsi is not None:
            idx_min_p = np.argmin(recent_lows_price)
            if idx_min_p > 2 and idx_min_p < L-2:
                first_part = recent_lows_price[:idx_min_p]; sec_part = recent_lows_price[idx_min_p:]
                if len(first_part)>0 and len(sec_part)>0:
                    if recent_lows_price[-1] < first_part.min() and not np.isnan(r[i-1]):
                        # цена ниже но RSI выше предыдущего минимума?
                        first_half = r[i-L:i-L//2]
                        if not np.isnan(first_half).all():
                            first_rsi_min = np.nanmin(first_half)
                            if not np.isnan(first_rsi_min) and r[i-1] > first_rsi_min + 3:
                                bull_div[i] = True
        # Bear div зеркально
        recent_highs_price = high[i-L:i]
        recent_highs_rsi = r[i-L:i] if not np.isnan(r[i-L:i]).all() else None
        if recent_highs_rsi is not None:
            idx_max_p = np.argmax(recent_highs_price)
            if 2 < idx_max_p < L-2:
                if recent_highs_price[-1] > recent_highs_price[:idx_max_p].max():
                    first_half = r[i-L:i-L//2]
                    if not np.isnan(first_half).all():
                        first_rsi_max = np.nanmax(first_half)
                        if not np.isnan(first_rsi_max) and r[i-1] < first_rsi_max - 3:
                            bear_div[i] = True
    out[f"bull_div_{label}"] = bull_div
    out[f"bear_div_{label}"] = bear_div

    # ─ RSI Hidden Divergence — D-040 (2026-05-22) ─
    # Bull hidden: price HL + RSI LL → continuation UP
    # Bear hidden: price LH + RSI HH → continuation DOWN
    rsi_div_bull_hid = np.zeros(n, dtype=bool)
    rsi_div_bear_hid = np.zeros(n, dtype=bool)
    L_RH = 14
    RSI_DELTA = 3.0
    DIV_PERSIST_RSI = 10
    for i in range(L_RH, n):
        lo_w = low[i-L_RH:i]
        hi_w = high[i-L_RH:i]
        r_w_first = r[i-L_RH:i-L_RH//2]
        if np.isnan(r_w_first).all() or np.isnan(r[i-1]):
            continue
        # Bull hidden: price HL + RSI LL
        idx_min_p = int(np.argmin(lo_w))
        if 2 < idx_min_p < L_RH-2:
            first_lo_min = lo_w[:idx_min_p].min()
            cur_low = low[i-1]
            first_r_min = np.nanmin(r_w_first)
            if not np.isnan(first_r_min):
                if cur_low > first_lo_min and r[i-1] < first_r_min - RSI_DELTA:
                    rsi_div_bull_hid[i] = True
        # Bear hidden: price LH + RSI HH
        idx_max_p = int(np.argmax(hi_w))
        if 2 < idx_max_p < L_RH-2:
            first_hi_max = hi_w[:idx_max_p].max()
            cur_high = high[i-1]
            first_r_max = np.nanmax(r_w_first)
            if not np.isnan(first_r_max):
                if cur_high < first_hi_max and r[i-1] > first_r_max + RSI_DELTA:
                    rsi_div_bear_hid[i] = True
    out[f"rsi_div_bull_hidden_{label}"] = pd.Series(rsi_div_bull_hid).rolling(window=DIV_PERSIST_RSI, min_periods=1).max().fillna(0).astype(bool).values
    out[f"rsi_div_bear_hidden_{label}"] = pd.Series(rsi_div_bear_hid).rolling(window=DIV_PERSIST_RSI, min_periods=1).max().fillna(0).astype(bool).values

    # ─ EQH/EQL sweep ──────────────────────────────────────────────────────
    eqh_sw = np.zeros(n, dtype=bool); eql_sw = np.zeros(n, dtype=bool)
    L = 30; TOL = 0.0015
    for i in range(L, n):
        rh = high[i-L:i]; max_h = rh.max()
        if sum(1 for h in rh if abs(h-max_h)/max_h < TOL) >= 2 and high[i] > max_h*(1+TOL) and close[i] < max_h:
            eqh_sw[i] = True
        rl = low[i-L:i]; min_l = rl.min()
        if sum(1 for l in rl if abs(l-min_l)/min_l < TOL) >= 2 and low[i] < min_l*(1-TOL) and close[i] > min_l:
            eql_sw[i] = True
    out[f"eqh_sweep_{label}"] = eqh_sw
    out[f"eql_sweep_{label}"] = eql_sw

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
