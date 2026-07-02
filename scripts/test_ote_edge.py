"""ПОИСК EDGE: тугой SL за 5m-структуру + свип TP-R (Егор 03.07: «нужно найти эдж»).

Прошлый тест: SL за 4h-слом (далеко) → крупные лоси убивали mean. Лечение = SL за 5m-СТРУКТУРУ (тугой).
База: вход = свежий тэг 4h-OTE в сторону bias + младший 5m ТРИГГЕР. SL = за 5m-структуру (последний
5m swing в сторону риска). TP = R-мультипликатор (свип 1R..4R) ИЛИ 4h-цель −0.62 (что ближе/дальше).
Честный walk-forward (5m SMC каузальны, 4h-структура на прошлом). costs 0.2%.
Запуск: python scripts/test_ote_edge.py
"""
from __future__ import annotations
import sys, time
import pandas as pd
import ccxt

sys.path.insert(0, ".")
from core.smc.ote_matrix import structure_trend, build_ote
from core.smc.smc_engine import detect_structure_breaks, detect_fvg

COST_PCT = 0.2
ANCHOR_LB = 250
WIN = 12                       # окно свежести триггера (5m баров)
SL_LOOKBACK = 12               # за сколько 5m баров искать структурный экстремум для SL
SL_BUF = 0.0015
TP_RS = [1.0, 1.5, 2.0, 3.0]   # свип TP по R
TRIGGERS = ["choch", "fvg_then_choch"]
SYMBOLS = ["XLM", "GRT", "SOL", "ADA", "DOGE", "LINK", "AVAX", "DOT", "TRX", "LTC",
           "ARB", "OP", "SUI", "APT", "NEAR", "INJ", "FIL", "ATOM", "RUNE", "SEI",
           "BNB", "ETH", "XRP", "UNI", "AAVE", "ETC", "BCH", "ICP", "TIA", "WLD"]
_TF_MS = {"5m": 300000}


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


def fetch_paged(ex, sym, tf, chunks=3):
    step = _TF_MS.get(tf, 300000)
    latest = fetch(ex, sym, tf, 1440)
    if latest is None:
        return None
    frames = [latest]; earliest = int(latest["ts"].iloc[0])
    for _ in range(chunks - 1):
        df = fetch(ex, sym, tf, 1440, since=earliest - 1440 * step)
        if df is None or len(df) == 0:
            break
        frames.append(df); earliest = int(df["ts"].iloc[0])
    full = pd.concat(frames).sort_index()
    return full[~full.index.duplicated(keep="first")]


def precompute(d5):
    choch = {"bull": set(), "bear": set()}; fvg = {"bull": set(), "bear": set()}
    try:
        for b in detect_structure_breaks(d5, length=5):
            if b.kind == "CHoCH":
                choch[b.direction].add(b.idx)
    except Exception:
        pass
    try:
        for f in detect_fvg(d5):
            try: idx = d5.index.get_loc(f[4])
            except Exception: continue
            fvg["bull" if f[3] == "bull" else "bear"].add(idx)
    except Exception:
        pass
    return choch, fvg


def trig_fire(trig, d, i, choch, fvg):
    ch = [c for c in choch[d] if (i - WIN) <= c <= i]
    if trig == "choch":
        return len(ch) > 0
    if trig == "fvg_then_choch":
        fv = [f for f in fvg[d] if (i - WIN) <= f <= i]
        return any(f < c for f in fv for c in ch)
    return False


def run(d4h, d5, choch, fvg):
    """Один проход: копим сделки для каждого (trigger, TP_R). SL тугой за 5m-структуру."""
    keys = [(t, r) for t in TRIGGERS for r in TP_RS]
    res = {k: [] for k in keys}
    pos = {k: None for k in keys}
    last4 = -1; cache = None
    for i in range(200, len(d5)):
        t = d5.index[i]; bar = d5.iloc[i]
        price = float(bar["close"]); hi = float(bar["high"]); lo = float(bar["low"])
        for k in keys:
            p = pos[k]
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
                res[k].append({"net": net, "win": net > 0, "dir": dr})
                pos[k] = None
        d4 = d4h[d4h.index <= t]
        if len(d4) < 120:
            continue
        if len(d4) != last4:
            st = structure_trend(d4, lookback=ANCHOR_LB); last4 = len(d4)
            if st["trend"] and st["break_level"] is not None and st["extreme"] is not None:
                ob = build_ote(st["extreme"], st["break_level"])
                cache = {"bias": st["trend"], "lo": ob["ote"][0], "hi": ob["ote"][1]}
            else:
                cache = None
        if not cache:
            continue
        bias, lo_z, hi_z = cache["bias"], cache["lo"], cache["hi"]
        if not (lo_z <= price <= hi_z):
            continue
        if lo_z <= float(d5.iloc[i - 1]["close"]) <= hi_z:
            continue                        # не свежий тэг
        d = "bull" if bias == "long" else "bear"
        entry = price
        # ТУГОЙ SL за 5m-структуру: экстремум последних SL_LOOKBACK баров в сторону риска
        wlo = float(d5["low"].values[i - SL_LOOKBACK:i + 1].min())
        whi = float(d5["high"].values[i - SL_LOOKBACK:i + 1].max())
        sl = wlo * (1 - SL_BUF) if bias == "long" else whi * (1 + SL_BUF)
        if (bias == "long" and sl >= entry) or (bias == "short" and sl <= entry):
            continue
        risk = abs(entry - sl)
        if risk <= 0 or risk / entry > 0.06:     # тугой: cap 6%
            continue
        for trig in TRIGGERS:
            if not trig_fire(trig, d, i, choch, fvg):
                continue
            for r in TP_RS:
                k = (trig, r)
                if pos[k] is None:
                    tp = entry + risk * r if bias == "long" else entry - risk * r
                    pos[k] = {"dir": bias, "entry": entry, "sl": sl, "tp": tp}
    return res


def main():
    import statistics as s
    ex = ccxt.bingx({"enableRateLimit": True})
    agg = {(t, r): [] for t in TRIGGERS for r in TP_RS}
    for sym in SYMBOLS:
        d4h = fetch(ex, sym, "4h", 400); d5 = fetch_paged(ex, sym, "5m", 3)
        if d4h is None or d5 is None or len(d5) < 400:
            print(f"  {sym}: нет данных"); continue
        choch, fvg = precompute(d5)
        res = run(d4h, d5, choch, fvg)
        for k in agg:
            agg[k].extend(res[k])
        print(f"  {sym:5} ok")
    print("=" * 66)
    print(f"{'триггер / TP':22} {'n':>4} {'WR':>5} {'mean%':>8} {'med%':>8} {'sum%':>8}")
    for t in TRIGGERS:
        for r in TP_RS:
            tr = agg[(t, r)]
            if not tr:
                print(f"{t+' '+str(r)+'R':22} n=0"); continue
            nets = [x["net"] for x in tr]
            wr = 100 * sum(1 for x in tr if x["win"]) / len(tr)
            print(f"{t+' '+str(r)+'R':22} {len(tr):>4} {wr:>4.0f}% {s.mean(nets):>+7.3f} {s.median(nets):>+7.3f} {sum(nets):>+7.1f}")
    print(f"costs={COST_PCT}% · SL=тугой 5m-структура(cap6%) · WIN={WIN} · anchor=4h · 5m entry · walk-forward")


if __name__ == "__main__":
    main()
