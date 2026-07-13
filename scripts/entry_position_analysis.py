# -*- coding: utf-8 -*-
"""ENTRY-POSITION (10.07, вопрос Егора: «где сделка открывается в импульсе? видел radar-лонги
на пике ARB при смене funding») — позиция входа относительно предшествующего движения.

Для каждой сделки (radar все + ote_nested выборка):
  pos24  = (entry − low24h) / (high24h − low24h)  — 1.0 = вход на пике диапазона
  ret4h  = движение за 4ч ДО входа (LONG после +4% = погоня за импульсом)
Split winners/losers → подтверждаем/опровергаем «лоси = поздние входы на пике».
Funding-разрез radar: гипотеза Егора «BUILD-LONG при fund<0 на пике = ловушка
(минус funding после ракеты = фиксация лонгов, не загрузка шортов)».
"""
import sys, sqlite3, json, time, urllib.request
import datetime as dt
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def klines_before(sym: str, ts_ms: int, bars: int = 96):
    url = (f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}USDT&interval=15m"
           f"&endTime={ts_ms}&limit={bars}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=15))


def analyze(rows, label):
    out = []
    for r in rows:
        try:
            ca = dt.datetime.fromisoformat(str(r["created_at"]).replace("Z", "+00:00"))
            if ca.tzinfo is None:
                ca = ca.replace(tzinfo=dt.timezone.utc)
            ts_ms = int(ca.timestamp() * 1000)
            base = str(r["symbol"]).split("/")[0]
            ks = klines_before(base, ts_ms)
            if len(ks) < 40:
                continue
            entry = float(r["actual_entry_price"] or r["entry_price"] or 0)
            if entry <= 0:
                continue
            highs = [float(k[2]) for k in ks]
            lows = [float(k[3]) for k in ks]
            closes = [float(k[4]) for k in ks]
            hi, lo = max(highs), min(lows)
            pos24 = (entry - lo) / (hi - lo) if hi > lo else 0.5
            ret4h = (entry / closes[-17] - 1) * 100 if len(closes) >= 17 else 0
            ret1h = (entry / closes[-5] - 1) * 100 if len(closes) >= 5 else 0
            fund = None
            try:
                f = json.loads(r["features_json"] or "{}")
                fund = f.get("radar_funding")
            except Exception:
                pass
            out.append({"id": r["id"], "sym": base, "dir": str(r["direction"]).upper(),
                        "sig": (r["signal_type"] or ""), "pp": float(r["profit_pct"] or 0),
                        "pos24": pos24, "ret4h": ret4h, "ret1h": ret1h, "fund": fund})
            time.sleep(0.12)
        except Exception as e:
            print(f"  {r['id']}: {e}")
    return out


def report(data, label):
    if not data:
        print(f"{label}: нет данных")
        return
    win = [d for d in data if d["pp"] > 0.05]
    loss = [d for d in data if d["pp"] < -0.05]
    print(f"\n=== {label}: n={len(data)} (win {len(win)} / loss {len(loss)}) ===")
    print(f"{'группа':10} {'pos24 avg':>9} {'ret4h avg':>9} {'вход в верхней 20% диапазона':>29}")
    for name, grp in (("WIN", win), ("LOSS", loss)):
        if not grp:
            continue
        pos_a = sum(d["pos24"] for d in grp) / len(grp)
        ret_a = sum(d["ret4h"] for d in grp) / len(grp)
        # для LONG «на пике» = pos24>0.8; для SHORT зеркально pos24<0.2
        peak = sum(1 for d in grp if (d["pos24"] > 0.8 if d["dir"] == "LONG" else d["pos24"] < 0.2))
        print(f"{name:10} {pos_a:9.2f} {ret_a:+9.2f} {peak:>12}/{len(grp)} ({100*peak/len(grp):.0f}%)")
    # LONG-детализация (вопрос Егора про пики)
    ll = [d for d in data if d["dir"] == "LONG" and d["pp"] < -0.05]
    lw = [d for d in data if d["dir"] == "LONG" and d["pp"] > 0.05]
    if ll and lw:
        print(f"LONG: лоси pos24={sum(d['pos24'] for d in ll)/len(ll):.2f} ret4h={sum(d['ret4h'] for d in ll)/len(ll):+.2f}% "
              f"| виннеры pos24={sum(d['pos24'] for d in lw)/len(lw):.2f} ret4h={sum(d['ret4h'] for d in lw)/len(lw):+.2f}%")


def main():
    c = sqlite3.connect("subscriptions.db")
    c.row_factory = sqlite3.Row
    radar = c.execute("""SELECT id, symbol, direction, signal_type, profit_pct, entry_price,
        actual_entry_price, created_at, features_json FROM simulated_trades
        WHERE features_json LIKE '%\"trade_mode\": \"radar\"%'
          AND status IN ('SL','TP','TSL','EXPIRED') AND profit_pct IS NOT NULL""").fetchall()
    ote = c.execute("""SELECT id, symbol, direction, signal_type, profit_pct, entry_price,
        actual_entry_price, created_at, features_json FROM simulated_trades
        WHERE signal_type LIKE 'ote%' AND status IN ('SL','TP','TSL')
          AND profit_pct IS NOT NULL ORDER BY id DESC LIMIT 250""").fetchall()
    c.close()
    d_r = analyze(radar, "radar")
    report(d_r, "RADAR (все закрытые)")
    # funding-ловушка Егора: BUILD/SPRING LONG при fund<0 — где входили?
    trap = [d for d in d_r if d["dir"] == "LONG" and d["fund"] is not None and d["fund"] < 0]
    if trap:
        tl = [d for d in trap if d["pp"] < -0.05]
        print(f"\n🔥 ГИПОТЕЗА ЕГОРА (LONG при fund<0): n={len(trap)}, лосей {len(tl)}, "
              f"avg pos24={sum(d['pos24'] for d in trap)/len(trap):.2f}, "
              f"avg ret4h ДО входа={sum(d['ret4h'] for d in trap)/len(trap):+.2f}%")
        for d in sorted(trap, key=lambda x: -x["pos24"])[:6]:
            print(f"   #{d['id']} {d['sym']:8} {d['sig'][6:]:7} pos24={d['pos24']:.2f} "
                  f"ret4h={d['ret4h']:+.1f}% fund={d['fund']:+.5f} → pp={d['pp']:+.2f}%")
    d_o = analyze(ote, "ote")
    report(d_o, "OTE_NESTED (последние 250)")


if __name__ == "__main__":
    main()
