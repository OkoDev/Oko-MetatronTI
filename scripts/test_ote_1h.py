"""EDGE ч.3 — идеи Егора (03.07): 1h OTE + вход от возврата + SL=15m-слом (=1h часто, короче) + фибо TP.

Прошлое: 4h-зона + произвольный cap4% risk = режим-зависим (OOS нестабилен). Идея Егора структурнее:
  • ЗОНА  = 1h OTE (structure_trend на 1h), bias = 1h тренд.
  • ВХОД  = свежий возврат (тэг) в 1h OTE в сторону bias.
  • SL    = 15m-СЛОМ (structure_trend на 15m break_level) — по матрице часто = 1h-слом → КОРОЧЕ, тугой
           СТРУКТУРНО (не произвольный %). Это лечит хвостовые лоси от структуры.
  • TP    = ФИБО 1h-ноги (свип: -0.62 / -1.0 / 0.0=retest / +2R для сравнения).
Честный walk-forward + OOS-сплит. Мера % net.  Запуск: python scripts/test_ote_1h.py
"""
from __future__ import annotations
import sys, time
import pandas as pd
import ccxt

sys.path.insert(0, ".")
from core.smc.ote_matrix import structure_trend, build_ote

COST_PCT = 0.2
SYMBOLS = ["XLM", "GRT", "SOL", "ADA", "DOGE", "LINK", "AVAX", "DOT", "TRX", "LTC",
           "ARB", "OP", "SUI", "APT", "NEAR", "INJ", "FIL", "ATOM", "RUNE", "SEI",
           "BNB", "ETH", "XRP", "UNI", "AAVE", "ETC", "BCH", "ICP", "TIA", "WLD"]
TP_MODES = ["fib_-0.62", "fib_-1.0", "fib_0.0", "R_2.0"]
RISK_CAP = 6.0                 # мягкий предохранитель (структурный SL сам должен быть тугим)


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


def run(d1h, d15):
    res = {m: [] for m in TP_MODES}; pos = {m: None for m in TP_MODES}
    last1 = -1; cache = None
    for i in range(200, len(d15)):
        t = d15.index[i]; bar = d15.iloc[i]
        price = float(bar["close"]); hi = float(bar["high"]); lo = float(bar["low"])
        for m in TP_MODES:
            p = pos[m]
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
                net = (ex_px - p["entry"]) / p["entry"] * 100 * sign - COST_PCT
                res[m].append({"net": net, "win": net > 0, "ts": p["ts"]}); pos[m] = None
        # 1h структура (кэш на 1h-бар)
        d1 = d1h[d1h.index <= t]
        if len(d1) < 120:
            continue
        if len(d1) != last1:
            st1 = structure_trend(d1, lookback=250); last1 = len(d1)
            if st1["trend"] and st1["break_level"] is not None and st1["extreme"] is not None:
                ob = build_ote(st1["extreme"], st1["break_level"])
                cache = {"bias": st1["trend"], "lo": ob["ote"][0], "hi": ob["ote"][1],
                         "lv": ob["levels"]}
            else:
                cache = None
        if not cache:
            continue
        bias, lo_z, hi_z, lv = cache["bias"], cache["lo"], cache["hi"], cache["lv"]
        if not (lo_z <= price <= hi_z):
            continue
        if lo_z <= float(d15.iloc[i - 1]["close"]) <= hi_z:
            continue                          # не свежий возврат
        # SL = 15m-СЛОМ (structure_trend на 15m срезе) в сторону риска
        st15 = structure_trend(d15.iloc[:i + 1], lookback=250)
        brk15 = st15.get("break_level")
        entry = price
        if brk15 is not None and ((bias == "long" and brk15 < entry) or (bias == "short" and brk15 > entry)):
            sl = brk15 * (0.999 if bias == "long" else 1.001)
        else:
            continue                          # нет валидного 15m-слома в сторону риска
        risk = abs(entry - sl)
        if risk <= 0 or risk / entry * 100 > RISK_CAP:
            continue
        for m in TP_MODES:
            if pos[m] is not None:
                continue
            if m == "R_2.0":
                tp = entry + risk * 2 if bias == "long" else entry - risk * 2
            else:
                fib = float(m.split("_")[1])
                tp = lv.get(fib)
                if tp is None:
                    continue
                if (bias == "long" and tp <= entry) or (bias == "short" and tp >= entry):
                    continue                  # цель не в сторону сделки
            pos[m] = {"dir": bias, "entry": entry, "sl": sl, "tp": tp, "ts": t}
    return res


def main():
    import statistics as s
    ex = ccxt.bingx({"enableRateLimit": True})
    agg = {m: [] for m in TP_MODES}
    for sym in SYMBOLS:
        d1h = paged(ex, sym, "1h", 3, 3600000); d15 = paged(ex, sym, "15m", 6, 900000)
        if d1h is None or d15 is None or len(d15) < 400 or len(d1h) < 200:
            print(f"  {sym}: нет данных"); continue
        res = run(d1h, d15)
        for m in agg:
            agg[m].extend(res[m])
        print(f"  {sym:5} ok")
    print("=" * 66)
    print(f"{'TP-режим':14} {'n':>4} {'WR':>5} {'mean%':>8} {'med%':>8} {'sum%':>8}")
    for m in TP_MODES:
        tr = agg[m]
        if not tr:
            print(f"{m:14} n=0"); continue
        nets = [x["net"] for x in tr]; wr = 100 * sum(1 for x in tr if x["win"]) / len(tr)
        print(f"{m:14} {len(tr):>4} {wr:>4.0f}% {s.mean(nets):>+7.3f} {s.median(nets):>+7.3f} {sum(nets):>+7.1f}")
    print(f"\nOOS-СПЛИТ (IS 1я пол / OOS 2я):")
    for m in TP_MODES:
        tr = sorted(agg[m], key=lambda x: x["ts"])
        if len(tr) < 12:
            continue
        mid = len(tr) // 2
        for lbl, part in [("IS ", tr[:mid]), ("OOS", tr[mid:])]:
            nets = [x["net"] for x in part]; wr = 100 * sum(1 for x in part if x["win"]) / len(part)
            print(f"  {m:12} {lbl} n={len(part):2} WR={wr:3.0f}% mean={s.mean(nets):+.3f}% sum={sum(nets):+.1f}%")
    print(f"costs={COST_PCT}% · зона=1h OTE · SL=15m-слом · вход=возврат · walk-forward ~90дн")


if __name__ == "__main__":
    main()
