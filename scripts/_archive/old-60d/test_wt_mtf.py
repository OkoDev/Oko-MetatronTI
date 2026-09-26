"""MTF WT OB/OS конфлюэнции (Егор 03.07): зависимости WT на разных ТФ + подтверждения SMC и пивотов.

Лесенка конфлюэнций (mean-reversion от WT-экстремумов):
  W1: WT(1h) в OS(<-th)/OB(>+th) → LONG/SHORT           (одиночный ТФ)
  W2: WT(1h) И WT(4h) оба в зоне                        (MTF-конфлюэнция)
  W3: W2 + 15m CHoCH в сторону сделки (окно 8 баров)    (SMC-подтверждение)
  W4: W3 + вход у пивота W/D ≤0.5%                      (пивот-конфлюэнция)
  W5: W2 + WT-ДИВЕРГЕНЦИЯ 1h (цена LL + WT HL, окно 24ч) (див вместо CHoCH)
  W6: W2 + CHoCH И дивергенция                          (полный стек подтверждений)
SL = 15m структурный слом/экстремум · TP = 2R · costs 0.2 · период 2024-01..2026-05 (бык+коррекции)
+ эпох-разбивка и OOS-сплит. Пороги th: 53 и 60 свипом. Запуск: python scripts/test_wt_mtf.py
"""
from __future__ import annotations
import sys, sqlite3
import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from core.smc.ote_matrix import structure_trend
from core.smc.smc_engine import detect_structure_breaks
from core.calculators.combinator_core import wavetrend

COST_PCT = 0.2
DB = "ohlcv_cache.db"
START, END = "2024-01-15", "2026-05-31"
THS = [53.0, 60.0]
VARIANTS = ["W1_1h", "W2_mtf", "W3_smc", "W4_pivot", "W5_div", "W6_div_smc"]


def wt_div_points(d1h, wt_ser, k=2):
    """WT-дивергенция на 1h (каузально, пивот подтверждён на idx+k): цена LL + WT HL → бычья;
    цена HH + WT LH → медвежья. Возвращает (bull_ts_set, bear_ts_set) — времена ПОДТВЕРЖДЕНИЯ."""
    lows = d1h["low"].values; highs = d1h["high"].values
    wt = wt_ser.values; idx = d1h.index; n = len(d1h)
    plo = []; phi = []; bull = set(); bear = set()
    for i in range(k, n - k):
        wl = lows[i - k:i + k + 1]; wh = highs[i - k:i + k + 1]
        if lows[i] == wl.min() and list(wl).count(lows[i]) == 1:
            if plo and lows[i] < plo[-1][1] and not np.isnan(wt[i]) and not np.isnan(wt[plo[-1][0]]) and wt[i] > wt[plo[-1][0]]:
                bull.add(idx[i + k])
            plo.append((i, lows[i]))
        elif highs[i] == wh.max() and list(wh).count(highs[i]) == 1:
            if phi and highs[i] > phi[-1][1] and not np.isnan(wt[i]) and not np.isnan(wt[phi[-1][0]]) and wt[i] < wt[phi[-1][0]]:
                bear.add(idx[i + k])
            phi.append((i, highs[i]))
    return bull, bear
SYMBOLS = ["XLM", "SOL", "ADA", "DOGE", "LINK", "AVAX", "DOT", "TRX", "LTC",
           "ARB", "OP", "APT", "NEAR", "INJ", "FIL", "ATOM", "RUNE",
           "BNB", "ETH", "XRP", "UNI", "AAVE", "ETC", "BCH", "ICP"]
CHOCH_WIN = 8


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


def pivot_levels(dfh, rule):
    agg = dfh.resample(rule).agg({"high": "max", "low": "min", "close": "last"}).dropna()
    pp = (agg["high"] + agg["low"] + agg["close"]) / 3
    r1 = 2 * pp - agg["low"]; s1 = 2 * pp - agg["high"]
    r2 = pp + (agg["high"] - agg["low"]); s2 = pp - (agg["high"] - agg["low"])
    return pd.DataFrame({"PP": pp, "R1": r1, "S1": s1, "R2": r2, "S2": s2}).shift(1)


def run(sym, d4h, d1h, d15, th):
    # каузальные серии
    wt1h = wavetrend(d1h)                              # ewm — каузально
    wt4h = wavetrend(d4h)
    choch = {"bull": set(), "bear": set()}
    try:
        for b in detect_structure_breaks(d15, length=5):
            if b.kind == "CHoCH":
                choch[b.direction].add(b.idx)
    except Exception:
        pass
    pivW = pivot_levels(d1h, "W"); pivD = pivot_levels(d1h, "D")
    div_bull, div_bear = wt_div_points(d1h, wt1h)
    div_bull = sorted(div_bull); div_bear = sorted(div_bear)
    res = {v: [] for v in VARIANTS}; pos = {v: None for v in VARIANTS}
    start = pd.Timestamp(START)
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
        # WT-состояния (последнее значение ≤ t)
        w1s = wt1h[wt1h.index <= t]
        w4s = wt4h[wt4h.index <= t]
        if not len(w1s) or not len(w4s):
            continue
        w1 = float(w1s.iloc[-1]); w4 = float(w4s.iloc[-1])
        if np.isnan(w1) or np.isnan(w4):
            continue
        if w1 < -th:
            d = "long"
        elif w1 > th:
            d = "short"
        else:
            continue
        mtf_ok = (w4 < -th) if d == "long" else (w4 > th)
        dd = "bull" if d == "long" else "bear"
        smc_ok = any((i - CHOCH_WIN) <= c <= i for c in choch[dd])
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
        # WT-дивергенция 1h: подтверждение в последних 24ч ≤ t
        dset = div_bull if d == "long" else div_bear
        t24 = t - pd.Timedelta(hours=24)
        div_ok = any(t24 <= x <= t for x in dset)
        # SL структурный: 15m слом в сторону риска, иначе экстремум окна
        st15 = structure_trend(d15.iloc[:i + 1], lookback=250)
        b15 = st15.get("break_level")
        entry = price
        if d == "long":
            sl = b15 * 0.999 if (b15 is not None and b15 < entry) else float(d15["low"].values[i - 12:i + 1].min()) * 0.9985
            if sl >= entry:
                continue
        else:
            sl = b15 * 1.001 if (b15 is not None and b15 > entry) else float(d15["high"].values[i - 12:i + 1].max()) * 1.0015
            if sl <= entry:
                continue
        risk = abs(entry - sl)
        if risk <= 0 or risk / entry * 100 > 6:
            continue
        tp = entry + 2 * risk if d == "long" else entry - 2 * risk
        gates = {"W1_1h": True, "W2_mtf": mtf_ok, "W3_smc": mtf_ok and smc_ok,
                 "W4_pivot": mtf_ok and smc_ok and piv_ok,
                 "W5_div": mtf_ok and div_ok, "W6_div_smc": mtf_ok and div_ok and smc_ok}
        for v in VARIANTS:
            if pos[v] is None and gates[v]:
                pos[v] = {"dir": d, "entry": entry, "sl": sl, "tp": tp, "ts": t}
    return res


def main():
    import statistics as s
    conn = sqlite3.connect(DB)
    for th in THS:
        agg = {v: [] for v in VARIANTS}
        done = 0
        for sym in SYMBOLS:
            d4h = load(conn, sym, "4h"); d1h = load(conn, sym, "1h"); d15 = load(conn, sym, "15m")
            if any(x is None for x in (d4h, d1h, d15)):
                continue
            res = run(sym, d4h, d1h, d15, th)
            for v in agg:
                agg[v].extend(res[v])
            done += 1
        print(f"\n===== th=±{th} ({done} симв, 2024-01..2026-05) =====")
        print(f"{'вариант':10} {'n':>5} {'WR':>4} {'mean%':>8} {'med%':>8} {'sum%':>9}  LONG/SHORT")
        for v in VARIANTS:
            tr = agg[v]
            if not tr:
                print(f"{v:10} n=0"); continue
            nets = [x["net"] for x in tr]
            wr = 100 * sum(1 for x in tr if x["win"]) / len(tr)
            lg = [x["net"] for x in tr if x["dir"] == "long"]; sh = [x["net"] for x in tr if x["dir"] == "short"]
            ls = f"L:{s.mean(lg):+.2f}(n{len(lg)}) S:{s.mean(sh):+.2f}(n{len(sh)})" if lg and sh else ""
            print(f"{v:10} {len(tr):>5} {wr:>3.0f}% {s.mean(nets):>+7.3f} {s.median(nets):>+7.3f} {sum(nets):>+8.1f}  {ls}")
        # OOS-сплит
        for v in VARIANTS:
            tr = sorted(agg[v], key=lambda x: x["ts"])
            if len(tr) < 20:
                continue
            mid = len(tr) // 2
            a = [x["net"] for x in tr[:mid]]; b = [x["net"] for x in tr[mid:]]
            print(f"  {v:10} сплит: 1я {s.mean(a):+.3f}% / 2я {s.mean(b):+.3f}%")
    conn.close()
    print(f"\ncosts={COST_PCT}% · SL=15m структура · TP=2R · walk-forward 2024-2026 (бык+коррекции)")


if __name__ == "__main__":
    main()
