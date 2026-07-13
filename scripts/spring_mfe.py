# -*- coding: utf-8 -*-
"""SPRING-MFE (09.07, SPRING-RUNNER-TSL шаг 1) — сколько ракет упускаем после выхода.

Для закрытых radar-сделок: MFE ПОСЛЕ выхода (ход в сторону сделки от exit_price за 24ч,
Binance 15m) + MFE от входа. Ответ на вопрос дизайна: стоит ли держать остаток
«пока above R-пивотов до потолков старшего ТФ» (ARB-кейс: вышли +0.4%, ушло +11%).
"""
import sys, sqlite3, json, time, urllib.request
import datetime as dt
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HORIZON_H = 24


def klines(sym: str, start_ms: int, end_ms: int):
    url = (f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}USDT&interval=15m"
           f"&startTime={start_ms}&endTime={end_ms}&limit=100")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=15))


def main():
    c = sqlite3.connect("subscriptions.db")
    c.row_factory = sqlite3.Row
    rows = c.execute("""SELECT id, symbol, direction, signal_type, status, profit_pct,
        entry_price, actual_entry_price, exit_price, closed_at
        FROM simulated_trades
        WHERE features_json LIKE '%\"trade_mode\": \"radar\"%'
          AND status IN ('SL','TP','TSL','EXPIRED') AND exit_price IS NOT NULL
        ORDER BY id""").fetchall()
    c.close()
    out = []
    for r in rows:
        try:
            ca = dt.datetime.fromisoformat(str(r["closed_at"]).replace("Z", "+00:00"))
            if ca.tzinfo is None:
                ca = ca.replace(tzinfo=dt.timezone.utc)
            start_ms = int(ca.timestamp() * 1000)
        except Exception:
            continue
        end_ms = start_ms + HORIZON_H * 3600 * 1000
        base = str(r["symbol"]).split("/")[0]
        try:
            ks = klines(base, start_ms, end_ms)
        except Exception as e:
            print(f"  {base}: klines err {e}")
            continue
        if not ks:
            continue
        exitp = float(r["exit_price"])
        entry = float(r["actual_entry_price"] or r["entry_price"] or 0)
        if exitp <= 0 or entry <= 0:
            continue
        highs = [float(k[2]) for k in ks]
        lows = [float(k[3]) for k in ks]
        if str(r["direction"]).upper() == "LONG":
            mfe_after = (max(highs) - exitp) / exitp * 100
            mfe_entry = (max(highs) - entry) / entry * 100
        else:
            mfe_after = (exitp - min(lows)) / exitp * 100
            mfe_entry = (entry - min(lows)) / entry * 100
        out.append({"id": r["id"], "sym": base, "sig": (r["signal_type"] or "")[6:],
                    "status": r["status"], "pp": float(r["profit_pct"] or 0),
                    "after": mfe_after, "full": mfe_entry})
        time.sleep(0.15)
    if not out:
        print("нет сделок")
        return
    print(f"radar-сделок разобрано: {len(out)} · горизонт {HORIZON_H}ч после выхода\n")
    print(f"{'тип':8} {'n':>3} {'взято avg%':>10} {'MFE-после avg%':>14} {'ракет>2%':>9} {'>5%':>5} {'полный потенциал avg%':>21}")
    from collections import defaultdict
    g = defaultdict(list)
    for o in out:
        g[o["sig"]].append(o)
    g["ВСЕ"] = out
    for k, v in g.items():
        taken = sum(x["pp"] for x in v) / len(v)
        after = sum(x["after"] for x in v) / len(v)
        r2 = sum(1 for x in v if x["after"] > 2)
        r5 = sum(1 for x in v if x["after"] > 5)
        full = sum(x["full"] for x in v) / len(v)
        print(f"{k:8} {len(v):3} {taken:+10.2f} {after:+14.2f} {r2:6}/{len(v):<3} {r5:5} {full:+21.2f}")
    print("\nтоп упущенных (MFE-после выхода):")
    for o in sorted(out, key=lambda x: -x["after"])[:8]:
        print(f"  #{o['id']} {o['sym']:8} {o['sig']:7} {o['status']:8} взято {o['pp']:+.2f}% · после ушло +{o['after']:.1f}% · потенциал от входа +{o['full']:.1f}%")


if __name__ == "__main__":
    main()
