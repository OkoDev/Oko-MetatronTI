"""СОБРАТЬ ВОЕДИНО (Егор 03.07): робастная база (1h OTE + 15m-слом SL + fib−1.0) + КОНФЛЮЭНЦИЯ MTF+пивоты.

База (OOS-робаст): зона=1h OTE, вход=возврат, SL=15m-слом, TP=fib−1.0. Накладываем фильтры «смотри на
матрицу» и смотрим что поднимает WR/mean/OOS:
  base       — без фильтра
  htf_align  — 4h bias == 1h bias (старший согласен)
  nested     — цена ТАКЖЕ в 4h OTE (вложенность зон)
  pivot      — 1h-зона у недельного пивота (S/R/PP, ≤1%)
  all        — все фильтры вместе
Честный walk-forward + OOS-сплит. Запуск: python scripts/test_ote_combine.py
"""
from __future__ import annotations
import sys, time
import pandas as pd
import ccxt

sys.path.insert(0, ".")
from core.smc.ote_matrix import structure_trend, build_ote

COST_PCT = 0.2
PIVOT_NEAR = 1.0               # % близости зоны к недельному пивоту
SYMBOLS = ["XLM", "GRT", "SOL", "ADA", "DOGE", "LINK", "AVAX", "DOT", "TRX", "LTC",
           "ARB", "OP", "SUI", "APT", "NEAR", "INJ", "FIL", "ATOM", "RUNE", "SEI",
           "BNB", "ETH", "XRP", "UNI", "AAVE", "ETC", "BCH", "ICP", "TIA", "WLD"]
VARIANTS = ["base", "htf_align", "nested", "pivot", "all"]


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


def weekly_pivots(d1h):
    """Недельные пивоты из ПРЕДЫДУЩЕЙ недели (каузально). Возвращает DataFrame по неделям: PP,S1,R1,S2,R2."""
    wk = d1h.resample("W").agg({"high": "max", "low": "min", "close": "last"}).dropna()
    pp = (wk["high"] + wk["low"] + wk["close"]) / 3
    r1 = 2 * pp - wk["low"]; s1 = 2 * pp - wk["high"]
    r2 = pp + (wk["high"] - wk["low"]); s2 = pp - (wk["high"] - wk["low"])
    piv = pd.DataFrame({"PP": pp, "R1": r1, "S1": s1, "R2": r2, "S2": s2})
    return piv.shift(1)            # сдвиг: текущая неделя использует пивоты ПРОШЛОЙ (каузально)


def near_pivot(zone_mid, piv_row):
    if piv_row is None or piv_row.isna().all():
        return False
    for lv in piv_row.values:
        if lv and abs(zone_mid - lv) / zone_mid * 100 <= PIVOT_NEAR:
            return True
    return False


def run(d4h, d1h, d15, piv):
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
                gross = (ex_px - p["entry"]) / p["entry"] * 100 * sign      # ДО costs (для свипа)
                net = gross - COST_PCT
                res[v].append({"net": net, "gross": gross, "win": net > 0,
                               "ts": p["ts"], "dir": dr}); pos[v] = None
        d1 = d1h[d1h.index <= t]
        if len(d1) < 120:
            continue
        if len(d1) != l1:
            st1 = structure_trend(d1, lookback=250); l1 = len(d1)
            if st1["trend"] and st1["break_level"] is not None and st1["extreme"] is not None:
                ob = build_ote(st1["extreme"], st1["break_level"])
                c1 = {"bias": st1["trend"], "lo": ob["ote"][0], "hi": ob["ote"][1], "lv": ob["levels"]}
            else:
                c1 = None
        d4 = d4h[d4h.index <= t]
        if len(d4) != l4:
            l4 = len(d4)
            if len(d4) >= 120:
                st4 = structure_trend(d4, lookback=250)
                if st4["trend"] and st4["break_level"] is not None and st4["extreme"] is not None:
                    ob4 = build_ote(st4["extreme"], st4["break_level"])
                    c4 = {"bias": st4["trend"], "lo": ob4["ote"][0], "hi": ob4["ote"][1]}
                else:
                    c4 = None
        if not c1:
            continue
        bias, lo_z, hi_z, lv = c1["bias"], c1["lo"], c1["hi"], c1["lv"]
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
        tp = lv.get(-1.0)
        if tp is None or (bias == "long" and tp <= entry) or (bias == "short" and tp >= entry):
            continue
        # фильтры конфлюэнции
        htf_ok = bool(c4 and c4["bias"] == bias)
        nested_ok = bool(c4 and c4["lo"] <= price <= c4["hi"] and c4["bias"] == bias)
        try:
            prow = piv[piv.index <= t].iloc[-1] if len(piv[piv.index <= t]) else None
        except Exception:
            prow = None
        pivot_ok = near_pivot((lo_z + hi_z) / 2, prow)
        passes = {"base": True, "htf_align": htf_ok, "nested": nested_ok,
                  "pivot": pivot_ok, "all": htf_ok and nested_ok and pivot_ok}
        for v in VARIANTS:
            if pos[v] is None and passes[v]:
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
        piv = weekly_pivots(d1h)
        res = run(d4h, d1h, d15, piv)
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
    print(f"\nOOS-СПЛИТ (IS/OOS):")
    for v in VARIANTS:
        tr = sorted(agg[v], key=lambda x: x["ts"])
        if len(tr) < 12:
            continue
        mid = len(tr) // 2
        parts = [("IS ", tr[:mid]), ("OOS", tr[mid:])]
        line = f"  {v:10}"
        for lbl, part in parts:
            nets = [x["net"] for x in part]
            line += f"  {lbl} n={len(part):3} mean={s.mean(nets):+.3f}% sum={sum(nets):+.0f}%"
        print(line)
    print(f"costs={COST_PCT}% · база=1h OTE+15m-слом+fib−1.0 · +конфлюэнция · walk-forward ~90дн")
    # ДО-ВАЛИДАЦИЯ htf_align: чувствительность к costs + LONG/SHORT
    tr = agg.get("htf_align", [])
    if tr:
        print("\nhtf_align — чувствительность к costs (mean%/сделку):")
        for c in [0.2, 0.3, 0.4, 0.5]:
            nets = [x["gross"] - c for x in tr]
            wr = 100 * sum(1 for x in nets if x > 0) / len(nets)
            print(f"  costs={c}%: mean={s.mean(nets):+.3f}% sum={sum(nets):+.0f}% WR={wr:.0f}%")
        print("htf_align — LONG vs SHORT:")
        for d in ["long", "short"]:
            part = [x for x in tr if x["dir"] == d]
            if not part:
                continue
            nets = [x["net"] for x in part]
            wr = 100 * sum(1 for x in part if x["win"]) / len(part)
            print(f"  {d:5}: n={len(part)} WR={wr:.0f}% mean={s.mean(nets):+.3f}% sum={sum(nets):+.0f}%")


if __name__ == "__main__":
    main()
