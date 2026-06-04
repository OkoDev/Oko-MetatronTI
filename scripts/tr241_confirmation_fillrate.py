"""
TR-241 — DEV-200 Phase 2: валидация заполняемости confirmations + avgR split.

Замеряет на ЗАКРЫТЫХ сделках (TP/SL/TSL/EXPIRED) post-рестарт DEV-200 Phase 2:
  (A) % сделок с >=1 confirmation (по signal_type, фокус wt_signal/pivot_reversal)
  (B) avgR/WR/median при confirm_count>0 vs ==0
  (C) split по confirmations_no_trigger (trigger-path vs observe-path)

Вердикт: если Δ avgR(confirm>0 − ==0) > +0.3R → разблокирует Phase 3 (SOFT penalty).

Запуск (триггер ~06.06, когда накопятся закрытые сделки):
  python scripts/tr241_confirmation_fillrate.py [--since "2026-06-04 00:00:00"] [--min-n 10]
created_at в БД — UTC.
"""
import argparse
import json
import sqlite3
import statistics
from collections import defaultdict

DB = "subscriptions.db"
CLOSED = ("TP", "SL", "TSL", "EXPIRED")
FOCUS = ("wt_signal", "pivot_reversal")


def _agg(rs):
    """rs: list[R_multiple] → dict(n, avgR, median, WR)."""
    rs = [r for r in rs if r is not None]
    if not rs:
        return {"n": 0, "avgR": None, "median": None, "WR": None}
    return {
        "n": len(rs),
        "avgR": round(statistics.mean(rs), 3),
        "median": round(statistics.median(rs), 3),
        "WR": round(100 * sum(1 for r in rs if r > 0) / len(rs), 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-06-04 00:00:00",
                    help="created_at >= (UTC); по умолчанию пост-рестарт DEV-200 Phase 2")
    ap.add_argument("--min-n", type=int, default=10)
    args = ap.parse_args()

    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    rows = db.execute(
        f"""SELECT signal_type, R_multiple, features_json
            FROM simulated_trades
            WHERE status IN ({','.join('?' * len(CLOSED))})
              AND created_at >= ?
              AND R_multiple IS NOT NULL""",
        (*CLOSED, args.since),
    ).fetchall()
    db.close()

    print(f"TR-241 — закрытых сделок с R с {args.since} (UTC): {len(rows)}\n")
    if not rows:
        print("Нет данных — ждём накопления закрытых сделок.")
        return

    # сбор: per signal_type → confirm>0 / ==0 / no_trigger split
    by_type = defaultdict(lambda: {"all": [], "conf": [], "noconf": [],
                                   "notrig": [], "trig": []})
    fill = defaultdict(lambda: [0, 0])  # type → [с_conf, всего]

    for r in rows:
        try:
            f = json.loads(r["features_json"] or "{}")
        except Exception:
            f = {}
        st = r["signal_type"]
        R = r["R_multiple"]
        confs = f.get("confirmations") or []
        has = len(confs) > 0
        d = by_type[st]
        d["all"].append(R)
        fill[st][1] += 1
        if has:
            d["conf"].append(R)
            fill[st][0] += 1
            if f.get("confirmations_no_trigger") is True:
                d["notrig"].append(R)
            elif f.get("confirmations_no_trigger") is False:
                d["trig"].append(R)
        else:
            d["noconf"].append(R)

    # (A) заполняемость
    print("=== (A) Заполняемость confirmations ===")
    for st, (c, tot) in sorted(fill.items(), key=lambda x: -x[1][1]):
        mark = " [FOCUS]" if st in FOCUS else ""
        pct = round(100 * c / tot, 1) if tot else 0
        print(f"  {st}{mark}: {c}/{tot} = {pct}%")

    # (B)/(C) avgR split
    print("\n=== (B) avgR: confirm>0 vs ==0 | (C) trigger vs observe ===")
    for st in sorted(by_type, key=lambda s: (s not in FOCUS, s)):
        d = by_type[st]
        conf, noconf = _agg(d["conf"]), _agg(d["noconf"])
        mark = " [FOCUS]" if st in FOCUS else ""
        print(f"\n  {st}{mark} (всего {len(d['all'])}):")
        print(f"    confirm>0 : {conf}")
        print(f"    confirm==0: {noconf}")
        if conf["avgR"] is not None and noconf["avgR"] is not None \
                and conf["n"] >= args.min_n and noconf["n"] >= args.min_n:
            delta = round(conf["avgR"] - noconf["avgR"], 3)
            verdict = "-> Phase 3 (SOFT penalty)" if delta > 0.3 else "(Delta<+0.3R, derzhim)"
            print(f"    Delta avgR = {delta:+.3f}R  {verdict}")
        else:
            print(f"    (недостаточно данных для вердикта, min_n={args.min_n})")
        trig, notrig = _agg(d["trig"]), _agg(d["notrig"])
        if trig["n"] or notrig["n"]:
            print(f"    trigger-path : {trig}")
            print(f"    observe-path : {notrig}")


if __name__ == "__main__":
    main()
