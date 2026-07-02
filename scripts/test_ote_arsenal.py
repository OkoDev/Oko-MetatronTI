"""АРСЕНАЛ (Егор 03.07): «от OTE до OTE забираем всё на разных ТФ» + MTF WT / DIV / fib-конфлюэнция.

База (OOS-робаст): зона=1h OTE · 4h bias==1h bias · вход=свежий возврат · SL=15m-слом.
Варианты (что тестируем):
  ЦЕЛИ «от OTE до OTE» (по 4h-карте матрицы, раз bias согласован):
    A_fib1_1h   — TP = fib−1.0 1h-ноги (эталон, +0.352)
    B_ext4h     — TP = ЭКСТРЕМУМ 4h-ноги (0.0 уровня 4h = «дальняя станция» пути)
    C_m062_4h   — TP = fib−0.62 4h-ноги (цель СТАРШЕГО масштаба)
  ФИЛЬТРЫ на базе A:
    D_wt1h      — WT(1h) в экстремуме в сторону сделки (long: wt<-40, short: wt>+40) = откат выжат
    E_wt15      — WT(15m) в экстремуме
    F_div15     — RSI-дивергенция 15m на пивотах (long: цена LL + RSI HL) в окне 40 баров
    G_fibconf   — вход-цена у fib-уровня 4h-ноги (≤0.3%) = конфлюэнция уровней разных ТФ
    H_pivotW    — вход-цена у НЕДЕЛЬНОГО пивота (PP/S/R, ≤0.5%) — конфлюэнция пивотов
    I_pivotD    — вход-цена у ДНЕВНОГО пивота (≤0.3%)
Всё каузально (ewm/rolling/pivot k=2 подтверждён задним числом). OOS-сплит. % net, costs 0.2.
Запуск: python scripts/test_ote_arsenal.py
"""
from __future__ import annotations
import sys, time
import numpy as np
import pandas as pd
import ccxt

sys.path.insert(0, ".")
from core.smc.ote_matrix import structure_trend, build_ote
from core.calculators.combinator_core import wavetrend, rsi

COST_PCT = 0.2
WT_TH = 40.0
SYMBOLS = ["XLM", "GRT", "SOL", "ADA", "DOGE", "LINK", "AVAX", "DOT", "TRX", "LTC",
           "ARB", "OP", "SUI", "APT", "NEAR", "INJ", "FIL", "ATOM", "RUNE", "SEI",
           "BNB", "ETH", "XRP", "UNI", "AAVE", "ETC", "BCH", "ICP", "TIA", "WLD"]
VARIANTS = ["A_fib1_1h", "G_fibconf", "I_pivotD", "J_G_or_piv", "K_G_and_piv", "L_G_or_wt"]


def pivot_levels(dfh, rule):
    """Флор-пивоты предыдущего периода (W/D), каузально (shift 1). {period_start: [PP,R1,S1,R2,S2]}"""
    agg = dfh.resample(rule).agg({"high": "max", "low": "min", "close": "last"}).dropna()
    pp = (agg["high"] + agg["low"] + agg["close"]) / 3
    r1 = 2 * pp - agg["low"]; s1 = 2 * pp - agg["high"]
    r2 = pp + (agg["high"] - agg["low"]); s2 = pp - (agg["high"] - agg["low"])
    piv = pd.DataFrame({"PP": pp, "R1": r1, "S1": s1, "R2": r2, "S2": s2}).shift(1)
    return piv


def fetch(ex, sym, tf, limit, since=None):
    for _ in range(5):
        try:
            o = ex.fetch_ohlcv(f"{sym}/USDT:USDT", tf, since=since, limit=limit)
            if o:
                df = pd.DataFrame(o, columns=["ts", "open", "high", "low", "close", "volume"])
                df["time"] = pd.to_datetime(df["ts"], unit="ms")
                return df.set_index("time")
        except Exception:
            time.sleep(1.5)
    return None


def paged(ex, sym, tf, chunks, step):
    latest = fetch(ex, sym, tf, 1440)
    if latest is None:
        return None
    frames = [latest]; earliest = int(latest["ts"].iloc[0])
    for _ in range(chunks - 1):
        df = fetch(ex, sym, tf, 1440, since=earliest - 1440 * step)
        if df is None or len(df) == 0:
            break
        frames.append(df); earliest = int(df["ts"].iloc[0])
    return pd.concat(frames).sort_index().pipe(lambda x: x[~x.index.duplicated(keep="first")])


def rsi_div_points(d15, k=2, rsi_len=14):
    """Каузальные точки бычьей/медвежьей RSI-дивергенции: пивот подтверждён на idx+k.
    Возвращает (bull_set, bear_set) индексов ПОДТВЕРЖДЕНИЯ дивергенции."""
    r = rsi(d15["close"].values, rsi_len)
    lows = d15["low"].values; highs = d15["high"].values; n = len(d15)
    plo = []; phi = []; bull = set(); bear = set()
    for i in range(k, n - k):
        wl = lows[i - k:i + k + 1]; wh = highs[i - k:i + k + 1]
        if lows[i] == wl.min() and list(wl).count(lows[i]) == 1:
            if plo and lows[i] < plo[-1][1] and not np.isnan(r[i]) and not np.isnan(r[plo[-1][0]]) and r[i] > r[plo[-1][0]]:
                bull.add(i + k)                    # цена LL + RSI HL → бычья див, подтверждена на i+k
            plo.append((i, lows[i]))
        elif highs[i] == wh.max() and list(wh).count(highs[i]) == 1:
            if phi and highs[i] > phi[-1][1] and not np.isnan(r[i]) and not np.isnan(r[phi[-1][0]]) and r[i] < r[phi[-1][0]]:
                bear.add(i + k)
            phi.append((i, highs[i]))
    return bull, bear


def run(d4h, d1h, d15, wt1h_ser, wt15_arr, div_bull, div_bear, pivW, pivD):
    res = {v: [] for v in VARIANTS}; pos = {v: None for v in VARIANTS}
    l1 = l4 = -1; c1 = c4 = None
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
                res[v].append({"net": gross - COST_PCT, "gross": gross, "win": gross - COST_PCT > 0,
                               "ts": p["ts"], "dir": dr}); pos[v] = None
        d1 = d1h[d1h.index <= t]
        if len(d1) < 120:
            continue
        if len(d1) != l1:
            st1 = structure_trend(d1, lookback=250); l1 = len(d1)
            c1 = None
            if st1["trend"] and st1["break_level"] is not None and st1["extreme"] is not None:
                ob = build_ote(st1["extreme"], st1["break_level"])
                c1 = {"bias": st1["trend"], "lo": ob["ote"][0], "hi": ob["ote"][1], "lv": ob["levels"]}
        d4 = d4h[d4h.index <= t]
        if len(d4) != l4:
            l4 = len(d4); c4 = None
            if len(d4) >= 120:
                st4 = structure_trend(d4, lookback=250)
                if st4["trend"] and st4["break_level"] is not None and st4["extreme"] is not None:
                    ob4 = build_ote(st4["extreme"], st4["break_level"])
                    c4 = {"bias": st4["trend"], "ext": st4["extreme"], "lv": ob4["levels"]}
        if not c1 or not c4 or c4["bias"] != c1["bias"]:
            continue                                    # база: 4h align обязателен
        bias, lo_z, hi_z, lv1 = c1["bias"], c1["lo"], c1["hi"], c1["lv"]
        if not (lo_z <= price <= hi_z):
            continue
        if lo_z <= float(d15.iloc[i - 1]["close"]) <= hi_z:
            continue
        st15 = structure_trend(d15.iloc[:i + 1], lookback=250)
        brk15 = st15.get("break_level")
        entry = price
        if brk15 is None or not ((bias == "long" and brk15 < entry) or (bias == "short" and brk15 > entry)):
            continue
        sl = brk15 * (0.999 if bias == "long" else 1.001)
        risk = abs(entry - sl)
        if risk <= 0 or risk / entry * 100 > 6:
            continue
        # цели
        tp_fib1 = lv1.get(-1.0)
        tp_ext4 = c4["ext"]
        tp_m062_4 = c4["lv"].get(-0.62)
        def ok_tp(tp):
            return tp is not None and ((bias == "long" and tp > entry) or (bias == "short" and tp < entry))
        # фильтры
        w1 = wt1h_ser[wt1h_ser.index <= t]
        wt1 = float(w1.iloc[-1]) if len(w1) else np.nan
        wt15v = float(wt15_arr[i]) if not np.isnan(wt15_arr[i]) else np.nan
        wt1_ok = (bias == "long" and wt1 < -WT_TH) or (bias == "short" and wt1 > WT_TH)
        wt15_ok = (bias == "long" and wt15v < -WT_TH) or (bias == "short" and wt15v > WT_TH)
        divset = div_bull if bias == "long" else div_bear
        div_ok = any((i - 40) <= x <= i for x in divset)
        fib_ok = any(l is not None and abs(entry - l) / entry * 100 <= 0.3
                     for f, l in c4["lv"].items() if f in (0.5, 0.62, 0.705, 0.79, -0.27))
        def near_piv(piv, tol):
            try:
                rows = piv[piv.index <= t]
                if not len(rows):
                    return False
                row = rows.iloc[-1]
                return any((not pd.isna(l)) and abs(entry - l) / entry * 100 <= tol for l in row.values)
            except Exception:
                return False
        pivW_ok = near_piv(pivW, 0.5)
        pivD_ok = near_piv(pivD, 0.3)
        piv_any = pivW_ok or pivD_ok
        gates = {"A_fib1_1h": (True, tp_fib1),
                 "G_fibconf": (fib_ok, tp_fib1),
                 "I_pivotD": (pivD_ok, tp_fib1),
                 "J_G_or_piv": (fib_ok or piv_any, tp_fib1),      # ЛЮБАЯ конфлюэнция уровня
                 "K_G_and_piv": (fib_ok and piv_any, tp_fib1),    # двойная конфлюэнция
                 "L_G_or_wt": (fib_ok or wt15_ok, tp_fib1)}
        for v, (g, tp) in gates.items():
            if pos[v] is None and g and ok_tp(tp):
                pos[v] = {"dir": bias, "entry": entry, "sl": sl, "tp": tp, "ts": t}
    return res


def main():
    import statistics as s
    ex = ccxt.bingx({"enableRateLimit": True})
    agg = {v: [] for v in VARIANTS}
    for sym in SYMBOLS:
        d4h = paged(ex, sym, "4h", 2, 14400000); d1h = paged(ex, sym, "1h", 3, 3600000); d15 = paged(ex, sym, "15m", 6, 900000)
        if any(x is None for x in (d4h, d1h, d15)) or len(d15) < 400:
            print(f"  {sym}: нет данных"); continue
        wt1h = wavetrend(d1h)                       # каузально (ewm)
        wt15 = wavetrend(d15).values
        div_bull, div_bear = rsi_div_points(d15)
        pivW = pivot_levels(d1h, "W"); pivD = pivot_levels(d1h, "D")
        res = run(d4h, d1h, d15, wt1h, wt15, div_bull, div_bear, pivW, pivD)
        for v in agg:
            agg[v].extend(res[v])
        print(f"  {sym:5} ok")
    print("=" * 66)
    print(f"{'вариант':12} {'n':>4} {'WR':>5} {'mean%':>8} {'med%':>8} {'sum%':>8}")
    for v in VARIANTS:
        tr = agg[v]
        if not tr:
            print(f"{v:12} n=0"); continue
        nets = [x["net"] for x in tr]; wr = 100 * sum(1 for x in tr if x["win"]) / len(tr)
        print(f"{v:12} {len(tr):>4} {wr:>4.0f}% {s.mean(nets):>+7.3f} {s.median(nets):>+7.3f} {sum(nets):>+7.1f}")
    print("\nOOS-СПЛИТ (IS/OOS):")
    for v in VARIANTS:
        tr = sorted(agg[v], key=lambda x: x["ts"])
        if len(tr) < 12:
            continue
        mid = len(tr) // 2
        line = f"  {v:10}"
        for lbl, part in [("IS ", tr[:mid]), ("OOS", tr[mid:])]:
            nets = [x["net"] for x in part]
            line += f"  {lbl} n={len(part):3} mean={s.mean(nets):+.3f}% sum={sum(nets):+.0f}%"
        print(line)
    print("\nSHORT-only срез:")
    for v in VARIANTS:
        part = [x for x in agg[v] if x["dir"] == "short"]
        if len(part) < 8:
            continue
        nets = [x["net"] for x in part]; wr = 100 * sum(1 for x in part if x["win"]) / len(part)
        srt = sorted(part, key=lambda x: x["ts"]); mid = len(srt) // 2
        is_m = s.mean([x["net"] for x in srt[:mid]]); oos_m = s.mean([x["net"] for x in srt[mid:]])
        print(f"  {v:12} n={len(part):3} WR={wr:3.0f}% mean={s.mean(nets):+.3f}% sum={sum(nets):+.0f}%  OOS {is_m:+.3f}/{oos_m:+.3f}")
    print(f"costs={COST_PCT}% · база=1h OTE+4h-align+15m-слом SL · walk-forward ~90дн")


if __name__ == "__main__":
    main()
