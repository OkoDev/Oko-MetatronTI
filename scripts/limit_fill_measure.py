"""
limit_fill_measure.py — исполнение лимитных заявок бота: бой против реального рынка (ARCH-107, шаг 1, 30.09).

Вопрос: где теряются заявки LIMIT-источников — не доходит цена, отменяет бот, не уходит ордер, фантомный филл VST?
Для каждой заявки из simulated_trades (с 01.08) — два исхода:
  • БОЙ (журнал бота): исполнена / отменена по сроку (ордер был на бирже) / ордер не ушёл / ждёт;
  • РЫНОК (переигрывание на свечах хранилища Сферы 1: 5m с 30.08, раньше 15m): филл / стоп до филла / нет филла.
Правило филла как в scripts/vst_real_resolve.py: лимит по entry_price в окне TTL источника, стоп раньше входа
в том же баре = сделки нет. TTL — из реестра (config), у impulse_fib 12 ч до 26.09 20:13 UTC, дальше 48 ч.
Для неисполненных на рынке — «ушёл без нас»: дошла ли цена до цели в окне удержания (HOLD из vst_real_resolve).

    python scripts/limit_fill_measure.py            (Python312: нужен pyarrow)
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from core.infra import market_store as ms          # noqa: E402
from core.trading import source_registry as sr     # noqa: E402
from vst_real_resolve import HOLD_H                # noqa: E402 — окна удержания: один источник чисел

SOURCES = ["impulse_fib", "impulse_fib_15m", "choch_wavec", "choch_wavec_4h", "ote_nested", "radar"]
T_FROM = "2026-08-01"
IMPULSE_TTL48_FROM = pd.Timestamp("2026-09-26 20:13", tz="UTC")     # коммит 6b1ac45 (23:13 МСК)
FIVE_MIN_FROM = pd.Timestamp("2026-08-30", tz="UTC")                # 5m в хранилище с 29.08 21:00
HOLD_H.setdefault("radar", HOLD_H.get("radar_pump", 24))
HOLD_H.setdefault("choch_wavec_4h", HOLD_H.get("choch_wavec", 96))


def ttl_hours(src: str, t0: pd.Timestamp) -> float:
    if src == "impulse_fib" and t0 < IMPULSE_TTL48_FROM:
        return 12.0
    return sr.ttl_for(src) / 3600.0


_bars: dict = {}


def bars(base: str, tf: str) -> pd.DataFrame:
    key = (base, tf)
    if key not in _bars:
        since = int(pd.Timestamp("2026-07-25", tz="UTC").timestamp() * 1000)
        _bars[key] = ms.read_bars(base, tf, since_ms=since)
    return _bars[key]


def market(row: dict) -> dict:
    """Исход заявки на реальном рынке."""
    t0, long_ = row["t0"], row["side"] == "LONG"
    tf = "5m" if t0 >= FIVE_MIN_FROM else "15m"
    k = bars(ms.base_of(row["sym"]), tf)
    step = pd.Timedelta(tf.replace("m", "min"))
    w = k[k.index >= t0]
    if w.empty or w.index[0] > t0 + step:
        return {"mkt": "нет данных", "tf": tf}
    hi, lo, idx = w.high.values, w.low.values, w.index
    n_ttl = int(row["ttl_h"] * 3600 / step.total_seconds())
    e, sl, tp = row["entry"], row["sl"], row["tp"]
    for j in range(min(n_ttl, len(w))):
        hit_e = (lo[j] <= e) if long_ else (hi[j] >= e)
        hit_sl = (lo[j] <= sl) if long_ else (hi[j] >= sl)
        if hit_e:
            # 🔴 30.09: вход и стоп в ОДНОЙ свече — это филл и тут же стоп (цена непрерывна: вход лежит
            # между ценой и стопом, у радара лимит часто сразу «в рынке»). В vst_real_resolve такие
            # случаи — «стоп до фила = нет сделки»: быстрые убыточные сделки выпадают из счёта.
            return {"mkt": "филл", "tf": tf, "fill_min": (idx[j] - t0).total_seconds() / 60,
                    "stop_same_bar": bool(hit_sl)}
        if hit_sl:
            return {"mkt": "стоп до филла", "tf": tf}
    # не исполнилась: ушла ли цена к цели без нас (в окне удержания от момента заявки)
    n_hold = int(HOLD_H.get(row["src"], 24) * 3600 / step.total_seconds())
    reached = False
    if tp:
        for j in range(min(n_hold, len(w))):
            if (hi[j] >= tp) if long_ else (lo[j] <= tp):
                reached = True
                break
    ref = w.close.values[min(n_ttl, len(w)) - 1]
    away = (ref - e) / e * 100 * (1 if long_ else -1)                # как далеко ушла цена от лимита к концу TTL
    return {"mkt": "нет филла", "tf": tf, "tp_without_us": reached, "away_pct": away}


def journal(r: dict) -> str:
    st = r["status"]
    if st in ("SL", "TP", "TSL", "OPEN", "EXPIRED") or (r["actual"] or 0) > 0:
        return "исполнена"
    if st == "PENDING_ENTRY":
        return "ждёт"
    if st == "CANCELLED":
        if not r["oid"]:
            return "ордер не ушёл" if r["mode"] == "VST" else "SIM отменена"
        return "снята по сроку" if r["closed"] else "снята (иное)"
    return st


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    db = sqlite3.connect(f"file:{ROOT / 'subscriptions.db'}?mode=ro", uri=True, timeout=20)
    # 🔴 стоп — ИСХОДНЫЙ (original_sl): stop_loss у исполненных уже подтянут трейлингом (SPX шорт: вход 0.459,
    # stop_loss 0.444 в прибыли, original_sl 0.516) — с ним прогон видел «стоп раньше входа»
    q = ("SELECT id, symbol, direction, entry_price, COALESCE(original_sl, stop_loss), take_profit, created_at, status, closed_at, "
         "actual_entry_price, exchange_order_id, execution_mode, source_router FROM simulated_trades "
         f"WHERE source_router IN ({','.join('?' * len(SOURCES))}) AND created_at >= ?")
    R = []
    for (tid, sym, side, e, sl, tp, ca, st, cl, act, oid, mode, src) in db.execute(q, (*SOURCES, T_FROM)):
        t0 = pd.Timestamp(ca.replace("T", " ")[:19], tz="UTC")
        R.append(dict(id=tid, sym=sym, side=side, entry=e, sl=sl, tp=tp, t0=t0, status=st, closed=cl, actual=act,
                      oid=oid, mode=mode, src=src, ttl_h=ttl_hours(src, t0),
                      stop_pct=abs(e - sl) / e * 100 if e and sl else None))
    # ── инвентаризация (протокол: печатать ДО прогона) ──
    print(f"ИНВЕНТАРИЗАЦИЯ: заявок {len(R)} с {T_FROM}; окна TTL и числа по источникам:")
    inv = Counter((r["src"], r["t0"].strftime("%m"), r["mode"], r["ttl_h"]) for r in R)
    for (s, m, md, ttl), n in sorted(inv.items()):
        print(f"   {s:16} мес {m} {md:3} TTL {ttl:>4.1f} ч: {n}")
    print("   (один год, 2026: BTC во флэте, альты дрейфуют вниз — противоположного режима в окне НЕТ)\n")

    for r in R:
        r["jr"] = journal(r)
        r.update(market(r))

    def pct(a, b):
        return f"{a / b * 100:.0f}%" if b else "—"

    for src in SOURCES:
        rs = [r for r in R if r["src"] == src]
        if not rs:
            continue
        judged = [r for r in rs if r["mkt"] != "нет данных" and r["jr"] != "ждёт"]
        print(f"■ {src}: заявок {len(rs)}, судимых {len(judged)}")
        jc, mc = Counter(r["jr"] for r in judged), Counter(r["mkt"] for r in judged)
        print("   бой:  " + " · ".join(f"{k} {v} ({pct(v, len(judged))})" for k, v in jc.most_common()))
        print("   рынок: " + " · ".join(f"{k} {v} ({pct(v, len(judged))})" for k, v in mc.most_common()))
        x = Counter((r["jr"], r["mkt"]) for r in judged)
        print("   бой × рынок: " + " · ".join(f"[{a} / {b}] {v}" for (a, b), v in x.most_common(8)))
        nf = [r for r in judged if r["mkt"] == "нет филла"]
        if nf:
            tpw = sum(r.get("tp_without_us") for r in nf)
            away = sorted(r["away_pct"] for r in nf)
            print(f"   без филла на рынке: цель взята без нас {tpw}/{len(nf)} ({pct(tpw, len(nf))}); "
                  f"цена к концу TTL ушла от лимита медиана {away[len(away) // 2]:+.2f}%")
        fl = [r["fill_min"] for r in judged if r["mkt"] == "филл"]
        ssb = sum(1 for r in judged if r.get("stop_same_bar") is True)
        if fl:
            print(f"   из филлов на рынке — стоп в той же свече: {ssb}/{len(fl)} ({pct(ssb, len(fl))})")
            fl.sort()
            print(f"   время до филла на рынке: медиана {fl[len(fl) // 2] / 60:.1f} ч, 90% {fl[int(len(fl) * .9)] / 60:.1f} ч")
        # срезы протокола: сторона · месяц · окно TTL · режим · стоп
        for nm, f in (("сторона", lambda r: r["side"]), ("месяц", lambda r: r["t0"].strftime("%m")),
                      ("TTL", lambda r: f"{r['ttl_h']:.0f}ч"), ("режим", lambda r: r["mode"]),
                      ("стоп", lambda r: "?" if r["stop_pct"] is None else "<1.5%" if r["stop_pct"] < 1.5
                       else "1.5-3%" if r["stop_pct"] < 3 else "≥3%")):
            g = defaultdict(list)
            for r in judged:
                g[f(r)].append(r)
            cells = [f"{k}: рынок {pct(sum(1 for r in v if r['mkt'] == 'филл'), len(v))} / бой "
                     f"{pct(sum(1 for r in v if r['jr'] == 'исполнена'), len(v))} (n={len(v)})"
                     for k, v in sorted(g.items())]
            print(f"   филл по «{nm}»: " + " · ".join(cells))
        print()
    pd.DataFrame([{k: v for k, v in r.items() if k != "t0"} | {"t0": str(r["t0"])} for r in R]).to_csv(
        ROOT / "obsidian" / "Research" / "2026-09-30-limit-fill-rows.csv", index=False, encoding="utf-8")


if __name__ == "__main__":
    main()
