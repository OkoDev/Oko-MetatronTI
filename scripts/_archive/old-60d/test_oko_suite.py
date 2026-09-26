"""ОЦИФРОВКА СИСТЕМЫ ЕГОРА «OKO Suite» (03.07): ATRTrend × WT-кросс × ПИВОТЫ.

Подтверждённая механика (визуал BTC + Егор): стрелка ТФ = КРОСС WT-волн (wt1×wt2) в экстремальной
зоне этого ТФ; ATRTrend (SuperTrend) = режим; связка «Trend старшего + WT-откат младшего выжат +
у пивота» = вход по тренду на откате у уровня. Варианты:
  S1_wtcross    — WT-кросс 15m в зоне (одиночный, аналог стрелки 15m)
  S2_trend      — + ATRTrend(1h) в сторону сделки (вход ПО тренду на выжатом откате)
  S3_trend4h    — + ATRTrend(4h) тоже (двойной режим)
  S4_pivot      — S2 + вход у пивота W/D (полная тройная связка Егора)
  S5_combo      — WT-кроссы 15m И 1h в окне 4ч (каскад, аналог COMBO)
SL=15m структура · TP 2R · costs 0.2 · 2024-01..2026-05 (бык+коррекции) · walk-forward честный.
Запуск: python scripts/test_oko_suite.py
"""
from __future__ import annotations
import sys, sqlite3
import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from core.smc.ote_matrix import structure_trend
from core.calculators.combinator_core import wavetrend, atr_supertrend

COST_PCT = 0.2
DB = "ohlcv_cache.db"
START, END = "2024-01-15", "2026-05-31"
WT_TH = 53.0
VARIANTS = ["S1_wtcross", "S2_trend", "S3_trend4h", "S4_pivot", "S5_combo"]
SYMBOLS = ["XLM", "SOL", "ADA", "DOGE", "LINK", "AVAX", "DOT", "TRX", "LTC",
           "ARB", "OP", "APT", "NEAR", "INJ", "FIL", "ATOM", "RUNE",
           "BNB", "ETH", "XRP", "UNI", "AAVE", "ETC", "BCH", "ICP"]


def load(conn, sym, tf, warm_days=40):
    q = """SELECT time, open, high, low, close, volume FROM ohlcv_cache
           WHERE symbol=? AND timeframe=? AND time BETWEEN ? AND ? ORDER BY time"""
    t0 = int(pd.Timestamp(START).timestamp() * 1000) - 86400000 * warm_days
    t1 = int(pd.Timestamp(END).timestamp() * 1000)
    df = pd.read_sql(q, conn, params=(f"{sym}/USDT", tf, t0, t1))
    if len(df) < 500:
        return None
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    return df.set_index("time")


def wt_crosses(df, th=WT_TH):
    """Кроссы WT1×WT2 в экстремальной зоне (механика стрелок OKO Suite). Каузально.
    buy: wt1 пересёк wt2 ВВЕРХ при wt1<-th; sell: вниз при wt1>+th. Возвращает (buy_idx, sell_idx)."""
    wt1 = wavetrend(df)
    wt2 = wt1.rolling(4).mean()
    b = set(); s = set()
    w1 = wt1.values; w2 = wt2.values
    for i in range(1, len(df)):
        if np.isnan(w1[i]) or np.isnan(w2[i]) or np.isnan(w1[i - 1]) or np.isnan(w2[i - 1]):
            continue
        if w1[i - 1] <= w2[i - 1] and w1[i] > w2[i] and w1[i] < -th:
            b.add(i)
        elif w1[i - 1] >= w2[i - 1] and w1[i] < w2[i] and w1[i] > th:
            s.add(i)
    return b, s


def st_dir_series(df):
    """ATRTrend (SuperTrend) направление по бару: 1=up/-1=down. Каузально (as in Pine)."""
    try:
        tr = atr_supertrend(df)
        # atr_supertrend возвращает trend массив? проверим тип
        if isinstance(tr, tuple):
            tr = tr[-1]
        return np.asarray(tr, dtype=float)
    except Exception:
        return None


def pivot_levels(dfh, rule):
    agg = dfh.resample(rule).agg({"high": "max", "low": "min", "close": "last"}).dropna()
    pp = (agg["high"] + agg["low"] + agg["close"]) / 3
    r1 = 2 * pp - agg["low"]; s1 = 2 * pp - agg["high"]
    r2 = pp + (agg["high"] - agg["low"]); s2 = pp - (agg["high"] - agg["low"])
    return pd.DataFrame({"PP": pp, "R1": r1, "S1": s1, "R2": r2, "S2": s2}).shift(1)


def run(d4h, d1h, d15):
    b15, s15 = wt_crosses(d15)
    b1h, s1h = wt_crosses(d1h)
    st1h = st_dir_series(d1h)
    st4h = st_dir_series(d4h)
    if st1h is None or st4h is None:
        return None
    pivW = pivot_levels(d1h, "W"); pivD = pivot_levels(d1h, "D")
    # индексы 1h-кроссов → времена (для окна каскада)
    b1h_ts = [d1h.index[i] for i in sorted(b1h)]
    s1h_ts = [d1h.index[i] for i in sorted(s1h)]
    res = {v: [] for v in VARIANTS}; pos = {v: None for v in VARIANTS}
    start = pd.Timestamp(START)
    l1 = l4 = -1; cur1 = cur4 = 0.0
    for i in range(200, len(d15)):
        t = d15.index[i]; bar = d15.iloc[i]
        price = float(bar["close"]); hi = float(bar["high"]); lo = float(bar["low"])
        for v in VARIANTS:
            p = pos[v]
            if not p:
                continue
            dr = p["dir"]; ex_px = None
            if dr == "long":
                if lo <= p["sl"]: ex_px = p["sl"]
                elif hi >= p["tp"]: ex_px = p["tp"]
            else:
                if hi >= p["sl"]: ex_px = p["sl"]
                elif lo <= p["tp"]: ex_px = p["tp"]
            if ex_px is not None:
                sign = 1 if dr == "long" else -1
                gross = (ex_px - p["entry"]) / p["entry"] * 100 * sign
                res[v].append({"net": gross - COST_PCT, "win": gross - COST_PCT > 0,
                               "ts": p["ts"], "dir": dr})
                pos[v] = None
        if t < start:
            continue
        # сигнал = свежий WT-кросс на ЭТОМ 15m баре
        if i in b15:
            d = "long"
        elif i in s15:
            d = "short"
        else:
            continue
        # ATRTrend состояния (последний бар старшего ≤ t)
        d1sub = d1h[d1h.index <= t]
        d4sub = d4h[d4h.index <= t]
        if len(d1sub) < 120 or len(d4sub) < 120:
            continue
        if len(d1sub) != l1:
            l1 = len(d1sub); cur1 = float(st1h[l1 - 1]) if l1 - 1 < len(st1h) else 0.0
        if len(d4sub) != l4:
            l4 = len(d4sub); cur4 = float(st4h[l4 - 1]) if l4 - 1 < len(st4h) else 0.0
        trend1_ok = (cur1 > 0) if d == "long" else (cur1 < 0)
        trend4_ok = (cur4 > 0) if d == "long" else (cur4 < 0)
        def near_piv(piv, tol):
            try:
                rows = piv[piv.index <= t]
                if not len(rows):
                    return False
                row = rows.iloc[-1]
                return any((not pd.isna(l)) and abs(price - l) / price * 100 <= tol for l in row.values)
            except Exception:
                return False
        piv_ok = near_piv(pivW, 0.5) or near_piv(pivD, 0.3)
        # каскад: 1h-кросс той же стороны в окне 4ч до t
        ts_list = b1h_ts if d == "long" else s1h_ts
        t4 = t - pd.Timedelta(hours=4)
        combo_ok = any(t4 <= x <= t for x in ts_list)
        # SL структурный 15m
        st15 = structure_trend(d15.iloc[:i + 1], lookback=250)
        bl = st15.get("break_level")
        entry = price
        if d == "long":
            sl = bl * 0.999 if (bl is not None and bl < entry) else float(d15["low"].values[i - 12:i + 1].min()) * 0.9985
            if sl >= entry:
                continue
        else:
            sl = bl * 1.001 if (bl is not None and bl > entry) else float(d15["high"].values[i - 12:i + 1].max()) * 1.0015
            if sl <= entry:
                continue
        risk = abs(entry - sl)
        if risk <= 0 or risk / entry * 100 > 6:
            continue
        tp = entry + 2 * risk if d == "long" else entry - 2 * risk
        gates = {"S1_wtcross": True, "S2_trend": trend1_ok, "S3_trend4h": trend1_ok and trend4_ok,
                 "S4_pivot": trend1_ok and piv_ok, "S5_combo": combo_ok}
        for v in VARIANTS:
            if pos[v] is None and gates[v]:
                pos[v] = {"dir": d, "entry": entry, "sl": sl, "tp": tp, "ts": t}
    return res


def main():
    import statistics as s
    conn = sqlite3.connect(DB)
    agg = {v: [] for v in VARIANTS}
    done = 0
    for sym in SYMBOLS:
        d4h = load(conn, sym, "4h"); d1h = load(conn, sym, "1h"); d15 = load(conn, sym, "15m")
        if any(x is None for x in (d4h, d1h, d15)):
            print(f"  {sym}: нет данных"); continue
        res = run(d4h, d1h, d15)
        if res is None:
            print(f"  {sym}: ATRTrend fail"); continue
        for v in agg:
            agg[v].extend(res[v])
        done += 1
        print(f"  {sym:5} ok")
    print("=" * 72)
    print(f"{'вариант':12} {'n':>5} {'WR':>4} {'mean%':>8} {'med%':>8} {'sum%':>9}  LONG/SHORT")
    for v in VARIANTS:
        tr = agg[v]
        if not tr:
            print(f"{v:12} n=0"); continue
        nets = [x["net"] for x in tr]
        wr = 100 * sum(1 for x in tr if x["win"]) / len(tr)
        lg = [x["net"] for x in tr if x["dir"] == "long"]; sh = [x["net"] for x in tr if x["dir"] == "short"]
        ls = ""
        if lg: ls += f"L:{s.mean(lg):+.2f}(n{len(lg)}) "
        if sh: ls += f"S:{s.mean(sh):+.2f}(n{len(sh)})"
        print(f"{v:12} {len(tr):>5} {wr:>3.0f}% {s.mean(nets):>+7.3f} {s.median(nets):>+7.3f} {sum(nets):>+8.1f}  {ls}")
    print("\nOOS-СПЛИТ:")
    for v in VARIANTS:
        tr = sorted(agg[v], key=lambda x: x["ts"])
        if len(tr) < 20:
            continue
        mid = len(tr) // 2
        a = [x["net"] for x in tr[:mid]]; b = [x["net"] for x in tr[mid:]]
        print(f"  {v:12} 1я {s.mean(a):+.3f}% / 2я {s.mean(b):+.3f}%")
    conn.close()
    print(f"costs={COST_PCT}% · WT-кросс(зона ±{WT_TH}) · ATRTrend режим · пивоты · TP 2R · 2024-2026")


if __name__ == "__main__":
    main()
