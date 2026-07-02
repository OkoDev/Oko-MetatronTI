"""ПОИСК LONG-ЭДЖА (Егор 03.07: «нужно найти лонг!»). LONG ≠ зеркальный SHORT — своя механика.

На SHORT-базе LONG льёт (−0.221). Гипотезы (память: LONG=cont [[ote_all_setups_honest_map]], gravity-LONG;
механика Егора GRT: лонг = вход на ПЕРЕВОРОТЕ матрицы снизу):
  LA_base     — LONG на short-базе (эталон, ~−0.22): 1h OTE long + 4h==long + возврат
  LB_1d       — + гейт 1d bias==long (СТАРШИЙ бычий — торгуем лонг только в бычьем макро)
  LC_m062     — цель ближе: fib−0.62 (лонги едут медленнее — забирать раньше)
  LD_retest   — цель 0.0 (ретест экстремума ноги)
  LE_reversal — ПЕРЕВОРОТ (механика Егора): 1h структура short + ПРОБОЙ слома ВВЕРХ (CHoCH up) =
                ранний разворот; вход по пробою, SL за LL, TP = measured move (2*слом − LL)
  LF_wt       — base + WT15 oversold (<−40): глубокая перепроданность в зоне
Честный walk-forward + OOS. % net, costs 0.2. Запуск: python scripts/test_ote_long.py
"""
from __future__ import annotations
import sys, time
import numpy as np
import pandas as pd
import ccxt

sys.path.insert(0, ".")
from core.smc.ote_matrix import structure_trend, build_ote
from core.calculators.combinator_core import wavetrend

COST_PCT = 0.2
SYMBOLS = ["XLM", "GRT", "SOL", "ADA", "DOGE", "LINK", "AVAX", "DOT", "TRX", "LTC",
           "ARB", "OP", "SUI", "APT", "NEAR", "INJ", "FIL", "ATOM", "RUNE", "SEI",
           "BNB", "ETH", "XRP", "UNI", "AAVE", "ETC", "BCH", "ICP", "TIA", "WLD"]
VARIANTS = ["LA_base", "LB_1d", "LC_m062", "LD_retest", "LE_reversal", "LF_wt"]


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


def run(d1d, d4h, d1h, d15, wt15):
    res = {v: [] for v in VARIANTS}; pos = {v: None for v in VARIANTS}
    l1 = l4 = ld = -1; c1 = c4 = cd = None
    prev_broken = False                     # для LE: ловим МОМЕНТ пробоя (переход broken False→True)
    for i in range(200, len(d15)):
        t = d15.index[i]; bar = d15.iloc[i]
        price = float(bar["close"]); hi = float(bar["high"]); lo = float(bar["low"])
        for v in VARIANTS:
            p = pos[v]
            if not p:
                continue
            ex_px = None
            if lo <= p["sl"]:
                ex_px = p["sl"]
            elif hi >= p["tp"]:
                ex_px = p["tp"]
            if ex_px is not None:
                gross = (ex_px - p["entry"]) / p["entry"] * 100        # long only
                res[v].append({"net": gross - COST_PCT, "win": gross - COST_PCT > 0, "ts": p["ts"]})
                pos[v] = None
        # структуры (кэш на бар старшего ТФ)
        d1 = d1h[d1h.index <= t]
        if len(d1) < 120:
            continue
        if len(d1) != l1:
            st1 = structure_trend(d1, lookback=250); l1 = len(d1)
            c1 = st1
        d4 = d4h[d4h.index <= t]
        if len(d4) != l4:
            l4 = len(d4)
            c4 = structure_trend(d4, lookback=250) if len(d4) >= 120 else None
        dd = d1d[d1d.index <= t]
        if len(dd) != ld:
            ld = len(dd)
            cd = structure_trend(dd, lookback=250) if len(dd) >= 100 else None
        if not c1 or not c4:
            continue
        # ---- LE_reversal: 1h short-структура, момент пробоя слома ВВЕРХ (CHoCH up) ----
        if c1["trend"] == "short" and c1["break_level"] is not None and c1["extreme"] is not None:
            broken_now = price > c1["break_level"]
            if broken_now and not prev_broken and pos["LE_reversal"] is None:
                brk = c1["break_level"]; llow = c1["extreme"]
                entry = price
                # SL за 15m-слом если валиден, иначе за LL
                st15 = structure_trend(d15.iloc[:i + 1], lookback=250)
                b15 = st15.get("break_level")
                sl = b15 * 0.999 if (b15 is not None and b15 < entry) else llow * 0.999
                risk = abs(entry - sl)
                tp = 2 * brk - llow                          # measured move вверх от слома
                if risk > 0 and risk / entry * 100 <= 6 and tp > entry:
                    pos["LE_reversal"] = {"entry": entry, "sl": sl, "tp": tp, "ts": t}
            prev_broken = broken_now
        else:
            prev_broken = False
        # ---- остальные: LONG в 1h OTE (long bias) ----
        if c1["trend"] != "long" or c1["break_level"] is None or c1["extreme"] is None:
            continue
        if c4["trend"] != "long":
            continue                                          # 4h align
        ob = build_ote(c1["extreme"], c1["break_level"])
        lo_z, hi_z = ob["ote"]; lv = ob["levels"]
        if not (lo_z <= price <= hi_z):
            continue
        if lo_z <= float(d15.iloc[i - 1]["close"]) <= hi_z:
            continue
        st15 = structure_trend(d15.iloc[:i + 1], lookback=250)
        b15 = st15.get("break_level")
        entry = price
        if b15 is None or b15 >= entry:
            continue
        sl = b15 * 0.999
        risk = abs(entry - sl)
        if risk <= 0 or risk / entry * 100 > 6:
            continue
        tp1 = lv.get(-1.0); tp062 = lv.get(-0.62); tp0 = lv.get(0.0)
        wt_ok = not np.isnan(wt15[i]) and wt15[i] < -40
        d1d_ok = bool(cd and cd["trend"] == "long")
        gates = {"LA_base": (True, tp1), "LB_1d": (d1d_ok, tp1), "LC_m062": (True, tp062),
                 "LD_retest": (True, tp0), "LF_wt": (wt_ok, tp1)}
        for v, (g, tp) in gates.items():
            if pos[v] is None and g and tp is not None and tp > entry:
                pos[v] = {"entry": entry, "sl": sl, "tp": tp, "ts": t}
    return res


def main():
    import statistics as s
    ex = ccxt.bingx({"enableRateLimit": True})
    agg = {v: [] for v in VARIANTS}
    for sym in SYMBOLS:
        d1d = fetch(ex, sym, "1d", 400)
        d4h = paged(ex, sym, "4h", 2, 14400000); d1h = paged(ex, sym, "1h", 3, 3600000); d15 = paged(ex, sym, "15m", 6, 900000)
        if any(x is None for x in (d1d, d4h, d1h, d15)) or len(d15) < 400:
            print(f"  {sym}: нет данных"); continue
        wt15 = wavetrend(d15).values
        res = run(d1d, d4h, d1h, d15, wt15)
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
        line = f"  {v:11}"
        for lbl, part in [("IS ", tr[:mid]), ("OOS", tr[mid:])]:
            nets = [x["net"] for x in part]
            line += f"  {lbl} n={len(part):3} mean={s.mean(nets):+.3f}% sum={sum(nets):+.0f}%"
        print(line)
    print(f"costs={COST_PCT}% · LONG-гипотезы · walk-forward ~90дн")


if __name__ == "__main__":
    main()
