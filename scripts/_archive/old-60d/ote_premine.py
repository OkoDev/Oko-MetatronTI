# -*- coding: utf-8 -*-
"""ПЕРМАЙН (Track 1) — условные edge на СУЩЕСТВУЮЩИХ OTE-сделках без фетча/бэктеста.

Использует то, что УЖЕ в БД: features_json (базовые поля) × честная метрика входа MFE%
(=max_R_possible×|entry-sl|/entry, SL-независимо) + хвост %≥2R/3R по max_R_possible.
БД-R = фикция → НЕ используется. Цель: «найти хоть что-то» до главного майна на Data Vision.

Вывод: console + data/research/<date>--ote-premine/RESULTS.md (под Qwen/рой).
Запуск: python scripts/ote_premine.py
"""
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "subscriptions.db"
OUT_DIR = ROOT / "data" / "research" / f"{datetime.now(timezone.utc):%Y-%m-%d}--ote-premine"
MIN_N = 30


def mfe_pct(t):
    e, sl, mr = t["entry_price"], t["stop_loss"], t["max_R_possible"]
    if not e or not sl or mr is None or e <= 0:
        return None
    return mr * abs(e - sl) / e * 100.0


def metrics(trades):
    """list[(mfe%, max_R)] → dict метрик."""
    n = len(trades)
    if n == 0:
        return None
    mfes = [m for m, _ in trades]
    mr = [r for _, r in trades]
    return {
        "n": n,
        "mfe%": round(sum(mfes) / n, 2),
        "p1": round(100 * sum(1 for r in mr if r >= 1) / n),
        "p2": round(100 * sum(1 for r in mr if r >= 2) / n),
        "p3": round(100 * sum(1 for r in mr if r >= 3) / n),
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    rows = c.execute("""SELECT direction, entry_price, stop_loss, max_R_possible, features_json
        FROM simulated_trades WHERE signal_type='ote_nested' AND status!='OPEN'
        AND max_R_possible IS NOT NULL AND features_json IS NOT NULL""").fetchall()

    # парс + базовые поля
    data = []
    for r in rows:
        m = mfe_pct(r)
        if m is None:
            continue
        try:
            fj = json.loads(r["features_json"])
        except Exception:
            fj = {}
        data.append((m, float(r["max_R_possible"]), r["direction"], fj))
    base = metrics([(m, mr) for m, mr, _, _ in data])

    # измерения условий: (имя, функция-бакетизатор(direction, fj) -> ключ или None)
    def b_setup(d, fj): return f"{fj.get('ote_setup_id')}|{d}"
    def b_conf(d, fj):
        v = fj.get("ote_conf_score"); return f"conf={v}" if v is not None else None
    def b_confkind(d, fj):
        v = fj.get("ote_confirmations"); return str(v) if v else None
    def b_mtf(d, fj):
        v = fj.get("mtf_aligned_pct")
        if v is None: return None
        return "mtf<50" if v < 50 else "mtf50-75" if v < 75 else "mtf75+"
    def b_choch(d, fj):
        v = fj.get("smc_has_choch")
        return None if v is None else (f"choch={int(bool(v))}|{d}")
    def b_div(d, fj):
        v = fj.get("div_count")
        if v is None: return None
        return f"div={v}|{d}" if v <= 4 else f"div5+|{d}"
    def b_hidden(d, fj):
        v = fj.get("hidden_div"); return None if v is None else f"hidden={int(bool(v))}"
    def b_btc(d, fj):
        v = fj.get("btc_4h_regime"); return f"btc={v}|{d}" if v else None
    def b_sess(d, fj):
        v = fj.get("session"); return f"sess={v}" if v else None
    def b_rev(d, fj):
        v = fj.get("reversal_mode"); return f"rev={v}" if v else None

    DIMS = [("setup×dir", b_setup), ("conf_score", b_conf), ("confirmations", b_confkind),
            ("mtf_aligned", b_mtf), ("choch×dir", b_choch), ("div_count×dir", b_div),
            ("hidden_div", b_hidden), ("btc_regime×dir", b_btc), ("session", b_sess),
            ("reversal_mode", b_rev)]

    lines = [f"# ПЕРМАЙН OTE — условные edge на существующих сделках\n",
             f"> {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC · n={len(data)} OTE-сделок · метрика=MFE% (вход, SL-незав.) + хвост\n",
             f"\n**BASELINE (все OTE):** n={base['n']} · MFE% {base['mfe%']} · ≥1R {base['p1']}% · ≥2R {base['p2']}% · ≥3R {base['p3']}%\n",
             "\n> Ищем условия с MFE%/хвостом ВЫШЕ baseline. ⚠️ это existing-fires (не полный бэктест); главный майн — на Data Vision.\n"]

    for name, fn in DIMS:
        buckets = defaultdict(list)
        for m, mr, d, fj in data:
            k = fn(d, fj)
            if k is not None:
                buckets[k].append((m, mr))
        res = [(k, metrics(v)) for k, v in buckets.items()]
        res = [(k, mm) for k, mm in res if mm and mm["n"] >= MIN_N]
        res.sort(key=lambda x: x[1]["p3"], reverse=True)  # по хвосту ≥3R
        if not res:
            continue
        lines.append(f"\n## {name}\n")
        lines.append("| бакет | n | MFE% | ≥1R | ≥2R | ≥3R | хвост vs base |")
        lines.append("|---|---|---|---|---|---|---|")
        for k, mm in res:
            lift = mm["p3"] - base["p3"]
            flag = "🟢" if lift >= 3 else "🔴" if lift <= -3 else ""
            lines.append(f"| {k} | {mm['n']} | {mm['mfe%']} | {mm['p1']}% | {mm['p2']}% | {mm['p3']}% | {lift:+d}pp {flag} |")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "RESULTS.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()
