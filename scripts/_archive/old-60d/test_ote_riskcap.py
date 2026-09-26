"""ПОИСК EDGE ч.2 (Егор 03.07): медиана + / mean − → хвостовые лоси. Фильтр по КАЧЕСТВУ R:R.

Гипотеза: вход (15m CHoCH/aligned в 4h-OTE) даёт + медиану, но широкий 4h-SL (до 15%) даёт редкие
крупные лоси → mean −. Решение: брать ТОЛЬКО сетапы где risk% мал (цена близко к структурному SL) →
хвост срежется. Свип risk_cap × TP_R. SL = 4h-слом (структурный). Мера % net. Честный walk-forward.
Запуск: python scripts/test_ote_riskcap.py
"""
from __future__ import annotations
import sys, time
import pandas as pd
import ccxt

sys.path.insert(0, ".")
from core.smc.ote_matrix import structure_trend, build_ote
from core.smc.smc_engine import detect_structure_breaks

COST_PCT = 0.2
ANCHOR_LB = 250
WIN = 6
RISK_CAPS = [3.0, 4.0, 5.0]           # % макс риск (близость к структурному SL)
TP_RS = [2.0, 2.5, 3.0]
TRIGGERS = ["choch", "aligned"]
FOCUS = ("choch", 4.0, 2.0)           # ключ для разбивки по символам
SYMBOLS = ["XLM", "GRT", "SOL", "ADA", "DOGE", "LINK", "AVAX", "DOT", "TRX", "LTC",
           "ARB", "OP", "SUI", "APT", "NEAR", "INJ", "FIL", "ATOM", "RUNE", "SEI",
           "BNB", "ETH", "XRP", "UNI", "AAVE", "ETC", "BCH", "ICP", "TIA", "WLD"]


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
    step = 900000
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


def precompute(d):
    choch = {"bull": set(), "bear": set()}; brk = {"bull": set(), "bear": set()}
    try:
        for b in detect_structure_breaks(d, length=5):
            brk[b.direction].add(b.idx)
            if b.kind == "CHoCH":
                choch[b.direction].add(b.idx)
    except Exception:
        pass
    return choch, brk


def fires(trig, d, i, choch, brk):
    if trig == "choch":
        return any((i - WIN) <= c <= i for c in choch[d])
    return any((i - WIN) <= c <= i for c in brk[d])       # aligned = любой слом в сторону


def run(d4h, d15, choch, brk):
    keys = [(t, rc, r) for t in TRIGGERS for rc in RISK_CAPS for r in TP_RS]
    res = {k: [] for k in keys}; pos = {k: None for k in keys}
    last4 = -1; cache = None
    for i in range(200, len(d15)):
        t = d15.index[i]; bar = d15.iloc[i]
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
                res[k].append({"net": net, "win": net > 0, "ts": p["ts"]}); pos[k] = None
        d4 = d4h[d4h.index <= t]
        if len(d4) < 120:
            continue
        if len(d4) != last4:
            st = structure_trend(d4, lookback=ANCHOR_LB); last4 = len(d4)
            if st["trend"] and st["break_level"] is not None and st["extreme"] is not None:
                ob = build_ote(st["extreme"], st["break_level"])
                cache = {"bias": st["trend"], "brk": st["break_level"], "lo": ob["ote"][0], "hi": ob["ote"][1]}
            else:
                cache = None
        if not cache:
            continue
        bias, brk_lvl, lo_z, hi_z = cache["bias"], cache["brk"], cache["lo"], cache["hi"]
        if not (lo_z <= price <= hi_z):
            continue
        if lo_z <= float(d15.iloc[i - 1]["close"]) <= hi_z:
            continue
        d = "bull" if bias == "long" else "bear"
        entry = price
        sl = brk_lvl * 0.999 if (bias == "long" and brk_lvl < entry) else (brk_lvl * 1.001 if (bias == "short" and brk_lvl > entry) else None)
        if sl is None:
            continue
        risk = abs(entry - sl); risk_pct = risk / entry * 100
        if risk <= 0:
            continue
        for trig in TRIGGERS:
            if not fires(trig, d, i, choch, brk):
                continue
            for rc in RISK_CAPS:
                if risk_pct > rc:
                    continue
                for r in TP_RS:
                    k = (trig, rc, r)
                    if pos[k] is None:
                        tp = entry + risk * r if bias == "long" else entry - risk * r
                        pos[k] = {"dir": bias, "entry": entry, "sl": sl, "tp": tp, "ts": t}
    return res


def main():
    import statistics as s
    ex = ccxt.bingx({"enableRateLimit": True})
    agg = {(t, rc, r): [] for t in TRIGGERS for rc in RISK_CAPS for r in TP_RS}
    per_sym = {}
    for sym in SYMBOLS:
        d4h = fetch(ex, sym, "4h", 720); d15 = fetch_paged(ex, sym, "15m", 6)
        if d4h is None or d15 is None or len(d15) < 400:
            print(f"  {sym}: нет данных"); continue
        choch, brk = precompute(d15)
        res = run(d4h, d15, choch, brk)
        for k in agg:
            agg[k].extend(res[k])
        ft = res.get(FOCUS, [])
        per_sym[sym] = (len(ft), sum(x["net"] for x in ft))
        print(f"  {sym:5} ok")
    print("=" * 70)
    print(f"{'триггер cap TP':24} {'n':>4} {'WR':>5} {'mean%':>8} {'med%':>8} {'sum%':>8}")
    for t in TRIGGERS:
        for rc in RISK_CAPS:
            for r in TP_RS:
                tr = agg[(t, rc, r)]
                if len(tr) < 8:
                    continue
                nets = [x["net"] for x in tr]
                wr = 100 * sum(1 for x in tr if x["win"]) / len(tr)
                tag = f"{t} cap{rc} {r}R"
                print(f"{tag:24} {len(tr):>4} {wr:>4.0f}% {s.mean(nets):>+7.3f} {s.median(nets):>+7.3f} {sum(nets):>+7.1f}")
    print(f"costs={COST_PCT}% · SL=4h-слом · 15m entry+trigger · walk-forward ~90дн")
    # OOS-СПЛИТ: делим по медианному времени входа, сравниваем 1-я половина vs 2-я
    print(f"\nOOS-СПЛИТ (in-sample 1я половина / out-of-sample 2я) для рабочих конфигов:")
    for key in [("choch", 4.0, 2.0), ("aligned", 4.0, 2.0), ("aligned", 3.0, 2.0)]:
        tr = agg.get(key, [])
        if len(tr) < 12:
            print(f"  {key}: мало данных n={len(tr)}"); continue
        tr = sorted(tr, key=lambda x: x["ts"])
        mid = len(tr) // 2
        for lbl, part in [("IS ", tr[:mid]), ("OOS", tr[mid:])]:
            nets = [x["net"] for x in part]
            wr = 100 * sum(1 for x in part if x["win"]) / len(part)
            print(f"  {str(key):26} {lbl} n={len(part):2} WR={wr:3.0f}% mean={s.mean(nets):+.3f}% sum={sum(nets):+.1f}%")


if __name__ == "__main__":
    main()
