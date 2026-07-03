# -*- coding: utf-8 -*-
"""WR-оценка сигналов радара — first-hit по свечам ПОСЛЕ алерта (Егор 03.07).

По каждому сигналу из pump_signals / build_signals / spring_signals тянем 5m-свечи
с момента алерта и смотрим, что цена тронула ПЕРВЫМ: стоп или цель (метод проверки
MANA-алерта 03.07: TP1 за 3 мин, ход 4.1%).

  PUMP:    entry/sl/tp1-3 из строки сигнала.
  BUILD:   entry=px, sl из строки; цели из targets_json (1-я = ближняя).
  ПРУЖИНА: стопа нет (пре-сигнал) → мерим MFE в сторону dir за горизонт.

Запуск:  python scripts/radar_wr.py [--days 14] [--horizon-bars 288]
Вывод:   таблица по типам сигналов; для PUMP — разбивка по Grade; ★-цели отдельно.
Копится с 03.07.2026 — до ~20-30 сигналов/тип выводы предварительные (печатаем n).
"""
import sys
import json
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
sys.path.insert(0, ".")

from oko_feed.store import conn

HORIZON_BARS = 288                                       # 24ч по 5m


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 oko-feed"})
    return json.load(urllib.request.urlopen(req, timeout=15))


def _klines_after(sym: str, ts: int, bars: int):
    k = _get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}USDT&interval=5m"
             f"&startTime={ts * 1000}&limit={min(bars, 1000)}")
    return [(float(x[2]), float(x[3])) for x in k]       # (hi, lo)


def first_hit(kl, side: str, sl: float | None, tps: list[float]) -> tuple[str, int]:
    """Что тронуто первым: 'SL' | 'TP1..n' | 'NONE'. Возвращает (исход, бар)."""
    for i, (hi, lo) in enumerate(kl):
        if side == "SHORT":
            if sl and hi >= sl:
                return "SL", i
            for j, tp in enumerate(tps, 1):
                if lo <= tp:
                    return f"TP{j}", i
        else:
            if sl and lo <= sl:
                return "SL", i
            for j, tp in enumerate(tps, 1):
                if hi >= tp:
                    return f"TP{j}", i
    return "NONE", len(kl)


def mfe_pct(kl, side: str, entry: float) -> float:
    """Максимальный ход в сторону сигнала, %."""
    if not kl or not entry:
        return 0.0
    if side in ("LONG", "UP"):
        return (max(h for h, _ in kl) / entry - 1) * 100
    return (entry / min(l for _, l in kl) - 1) * 100


def eval_rows(rows, kind: str, horizon: int):
    out = []
    for r in rows:
        ts, sym, side, entry, sl = r["ts"], r["symbol"], r["side"], r["entry"], r.get("sl")
        tps = r.get("tps") or []
        try:
            kl = _klines_after(sym, ts, horizon)
        except Exception:
            continue
        if not kl:
            continue
        hit, bar = first_hit(kl, side, sl, tps) if (sl or tps) else ("NONE", 0)
        out.append({"sym": sym, "grade": r.get("grade", "-"), "star": r.get("star", False),
                    "hit": hit, "bar": bar, "mfe": mfe_pct(kl, side, entry)})
        time.sleep(0.1)
    if not out:
        print(f"  {kind}: сигналов нет")
        return
    n = len(out)
    tp_n = sum(1 for x in out if x["hit"].startswith("TP"))
    sl_n = sum(1 for x in out if x["hit"] == "SL")
    none_n = n - tp_n - sl_n
    avg_mfe = sum(x["mfe"] for x in out) / n
    print(f"  {kind}: n={n} · TP-first {tp_n} ({tp_n/n*100:.0f}%) · SL-first {sl_n} "
          f"({sl_n/n*100:.0f}%) · не дошло {none_n} · avg MFE {avg_mfe:+.2f}%")
    for g in sorted({x['grade'] for x in out}):
        gs = [x for x in out if x["grade"] == g]
        if g != "-" and gs:
            gtp = sum(1 for x in gs if x["hit"].startswith("TP"))
            print(f"    Grade {g}: n={len(gs)} TP-first {gtp/len(gs)*100:.0f}% "
                  f"avg MFE {sum(x['mfe'] for x in gs)/len(gs):+.2f}%")
    stars = [x for x in out if x["star"]]
    if stars:
        stp = sum(1 for x in stars if x["hit"].startswith("TP"))
        print(f"    ★-цели: n={len(stars)} TP-first {stp/len(stars)*100:.0f}%")


def _tps_from_targets(tj: str | None, entry: float, side: str) -> tuple[list[float], bool]:
    """targets_json → отсортированные от ближней цели + был ли ★ у первой."""
    if not tj:
        return [], False
    try:
        ts = json.loads(tj)
    except Exception:
        return [], False
    ts.sort(key=lambda t: abs(t["px"] - entry))
    return [t["px"] for t in ts], bool(ts and ts[0].get("star"))


def main():
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 14
    horizon = (int(sys.argv[sys.argv.index("--horizon-bars") + 1])
               if "--horizon-bars" in sys.argv else HORIZON_BARS)
    since = int(time.time()) - days * 86400
    c = conn()
    print(f"=== WR радара (last {days}d, горизонт {horizon} × 5m) ===")

    rows = []
    for r in c.execute("SELECT ts,symbol,side,grade,entry,sl,tp1,tp2,tp3 FROM pump_signals "
                       "WHERE ts>=?", (since,)):
        rows.append({"ts": r[0], "symbol": r[1], "side": r[2], "grade": r[3],
                     "entry": r[4], "sl": r[5], "tps": [r[6], r[7], r[8]]})
    eval_rows(rows, "PUMP", horizon)

    rows = []
    try:
        for r in c.execute("SELECT ts,symbol,side,px,sl,targets_json FROM build_signals "
                           "WHERE ts>=? AND side IS NOT NULL", (since,)):
            tps, star = _tps_from_targets(r[5], r[3], r[2])
            rows.append({"ts": r[0], "symbol": r[1], "side": r[2], "entry": r[3],
                         "sl": r[4], "tps": tps, "star": star})
    except Exception:
        pass
    eval_rows(rows, "BUILD", horizon)

    rows = []
    try:
        for r in c.execute("SELECT ts,symbol,dir,px,targets_json FROM spring_signals "
                           "WHERE ts>=? AND dir IN ('UP','DOWN')", (since,)):
            side = "LONG" if r[2] == "UP" else "SHORT"
            tps, star = _tps_from_targets(r[4], r[3], side)
            rows.append({"ts": r[0], "symbol": r[1], "side": side, "entry": r[3],
                         "sl": None, "tps": tps, "star": star})
    except Exception:
        pass
    eval_rows(rows, "ПРУЖИНА", horizon)
    c.close()


if __name__ == "__main__":
    main()
