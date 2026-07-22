# -*- coding: utf-8 -*-
"""OTE-WAITING-LIMIT — ожидающий лимит на ГЛУБОКОМ fib (22.07, поправка Егора).

Реактивный лимит (на reaction-close) = adverse selection (доказано ote_limit_fill_backtest).
Егор: «вопрос в ОЖИДАЮЩИХ лимитках» — лимит выставлен ЗАРАНЕЕ на глубоком краю OTE-зоны
(zone_lo для LONG / zone_hi для SHORT, golden pocket), куда цена ещё НЕ дошла. Ловит глубокий
откат по ХОРОШЕЙ цене, а не там где уже отскочило.

Честная ре-симуляция (нужен OHLCV — докачка BingX 15m, июнь-июль):
  от created_at (сигнал вошёл в зону) ждём TTL баров: цена достигла глубокого края? →
  FILL по краю. Дальше walk-forward: что раньше, SL (stored) или TP1 (ote_tp1) → исход %.
  Не достигла за TTL → пропуск (откат не дошёл до golden pocket).
Сравниваем net% ожидающего-лимита vs SIM-baseline. + фильтр по слиппеджу (низкий срез).

net% = (exit−fill)/fill*dir − costs (ЗАКОН №1). Запуск: python scripts/ote_waiting_limit_backtest.py [--syms 40] [--ttl 8]
"""
import sys, json, time, urllib.request
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import sqlite3
from datetime import datetime

DB = "subscriptions.db"
COSTS = 0.10          # % round-trip (лимит-вход=мейкер, но консервативно)
TTL_BARS = 8          # сколько 15m-баров ждём достижения глубокого края (2ч)
WALK_BARS = 200       # макс баров на исход после fill


def _to_ms(iso):
    try:
        return int(datetime.fromisoformat(str(iso)).timestamp() * 1000)
    except Exception:
        return 0


def _bingx_15m(base, start_ms, end_ms):
    """BingX v3 klines 15m, пагинация start→end. → list[(t,o,h,l,c)] отсорт."""
    out, cur = [], start_ms
    for _ in range(8):
        url = (f"https://open-api.bingx.com/openApi/swap/v3/quote/klines?symbol={base}-USDT"
               f"&interval=15m&startTime={cur}&limit=1440")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "oko-bt"})
            d = json.load(urllib.request.urlopen(req, timeout=15)).get("data", [])
        except Exception:
            break
        if not d:
            break
        b = sorted(((int(k["time"]), float(k["open"]), float(k["high"]),
                     float(k["low"]), float(k["close"])) for k in d), key=lambda x: x[0])
        out.extend(b)
        last = b[-1][0]
        if last >= end_ms or last <= cur:
            break
        cur = last + 1
        time.sleep(0.25)
    # dedup+sort
    return sorted({x[0]: x for x in out}.values(), key=lambda x: x[0])


def main():
    nsyms = 40; ttl = TTL_BARS
    if "--syms" in sys.argv: nsyms = int(sys.argv[sys.argv.index("--syms")+1])
    if "--ttl" in sys.argv: ttl = int(sys.argv[sys.argv.index("--ttl")+1])

    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    rows = c.execute(
        """SELECT symbol, direction, entry_price, stop_loss, features_json, created_at,
                  profit_pct, costs_pct, min_price, max_price
           FROM simulated_trades WHERE signal_type='ote_nested' AND execution_mode!='VST'
           AND status IN ('SL','TP','TSL') AND profit_pct IS NOT NULL AND entry_price>0
           AND created_at>='2026-06-04' AND features_json LIKE '%ote_zone_lo%'""").fetchall()
    # разложим + возьмём топ символов по частоте
    trades = []
    from collections import Counter
    freq = Counter()
    for r in rows:
        try:
            f = json.loads(r["features_json"])
            zlo, zhi = float(f["ote_zone_lo"]), float(f["ote_zone_hi"])
            tp1 = float(f.get("ote_tp1") or 0)
        except Exception:
            continue
        if zlo <= 0 or zhi <= zlo or tp1 <= 0 or not r["stop_loss"]:
            continue
        base = r["symbol"].split("/")[0].replace("USDT", "")
        trades.append({"base": base, "d": r["direction"].upper(), "entry": float(r["entry_price"]),
                       "sl": float(r["stop_loss"]), "zlo": zlo, "zhi": zhi, "tp1": tp1,
                       "ms": _to_ms(r["created_at"]),
                       "sim_net": float(r["profit_pct"]) - float(r["costs_pct"] or 0)})
        freq[base] += 1
    top = [b for b, _ in freq.most_common(nsyms)]
    print(f"🎯 OTE WAITING-LIMIT (глубокий fib) · топ-{nsyms} символов · TTL={ttl}бар ({ttl*15}мин)")
    print(f"   всего ote-сделок с зоной: {len(trades)}, тестируем на {sum(freq[b] for b in top)} (топ символы)\n")

    # СВИП ГЛУБИНЫ (23.07, Егор «до каких fib цена не доходит?»): лимит на доле d зоны
    # (0=shallow-край, 1=golden pocket deep-край). Один фетч на символ — все глубины разом.
    DEPTHS = (0.25, 0.5, 0.618, 0.705, 0.786, 1.0)
    res = {d: {"net": [], "miss": 0} for d in DEPTHS}
    import bisect
    for base in top:
        sub = [t for t in trades if t["base"] == base]
        if not sub:
            continue
        lo = min(t["ms"] for t in sub) - 3600_000
        hi = max(t["ms"] for t in sub) + WALK_BARS * 900_000
        bars = _bingx_15m(base, lo, hi)
        if len(bars) < 20:
            continue
        times = [b[0] for b in bars]
        for t in sub:
            i0 = bisect.bisect_left(times, t["ms"])
            if i0 >= len(bars):
                continue
            span = t["zhi"] - t["zlo"]
            for d in DEPTHS:
                # цена лимита на глубине d: LONG от zhi вниз, SHORT от zlo вверх
                lim = (t["zhi"] - d * span) if t["d"] == "LONG" else (t["zlo"] + d * span)
                fill_i = None
                for i in range(i0, min(i0 + ttl + 1, len(bars))):
                    _, o, h, l, cl = bars[i]
                    if (t["d"] == "LONG" and l <= lim) or (t["d"] == "SHORT" and h >= lim):
                        fill_i = i; break
                if fill_i is None:
                    res[d]["miss"] += 1
                    continue
                outcome = None
                for j in range(fill_i, min(fill_i + WALK_BARS, len(bars))):
                    _, o, h, l, cl = bars[j]
                    if t["d"] == "LONG":
                        if l <= t["sl"]: outcome = ("SL", t["sl"]); break
                        if h >= t["tp1"]: outcome = ("TP", t["tp1"]); break
                    else:
                        if h >= t["sl"]: outcome = ("SL", t["sl"]); break
                        if l <= t["tp1"]: outcome = ("TP", t["tp1"]); break
                if outcome is None:
                    outcome = ("END", bars[min(fill_i + WALK_BARS - 1, len(bars) - 1)][4])
                exitp = outcome[1]
                net = ((exitp - lim) / lim if t["d"] == "LONG" else (lim - exitp) / lim) * 100 - COSTS
                res[d]["net"].append(net)
        time.sleep(0.15)

    def _st(a):
        if not a: return 0, 0, 0
        return len(a), 100*sum(1 for x in a if x > 0)/len(a), sum(a)/len(a)
    print("── СВИП ГЛУБИНЫ ЛИМИТА (доля зоны: 0=shallow-край, 1=golden pocket) ──")
    print(f"   {'глубина':>8} {'fill%':>6} {'n':>5} {'WR':>4} {'net/фил':>9} {'E/сетап':>9}   (E = fill_rate × net)")
    best = None
    for d in DEPTHS:
        nets = res[d]["net"]; miss = res[d]["miss"]
        n, wr, net = _st(nets)
        tot = n + miss
        if not tot:
            continue
        fr = n / tot
        exp = fr * (net or 0)
        mark = ""
        if best is None or exp > best[1]:
            best = (d, exp)
        print(f"   {d:8.3f} {100*fr:5.0f}% {n:5} {wr:3.0f}% {net:+8.3f}% {exp:+8.3f}%")
    if best:
        print(f"\n   🎯 ОПТИМУМ по матожиданию на сетап: глубина {best[0]:.3f} (E={best[1]:+.3f}%/сетап)")


if __name__ == "__main__":
    main()
