# -*- coding: utf-8 -*-
"""LEDGER-AUDIT (08.07, спринт «эксплуатируем доказанное», шаг 2) — Data Quality Gate.

Сверка закрытых биржевых сделок БД с income-ледгером BingX (REALIZED_PNL = $-истина, o.rp).
Три fake-класса за месяц (fake-R entry / fake-entry NULL / fake-exit LIMIT-маска 08.07) —
каждый раз статистика оказывалась грязной ПОСЛЕ выводов. Этот скрипт ловит рассинхрон ДО.

Метод: для каждой закрытой сделки (exchange_order_id есть) ищем REALIZED_PNL-записи того же
символа в окне closed_at ± 15 мин по ВСЕМ субаккам → ledger_pnl. Сравниваем с БД-PnL
(qty × Δцены × направление). Флаги:
  FAKE-BE   — БД говорит ~0% (BE), ледгер — заметный минус (класс fake-exit 08.07)
  SIGN-FLIP — знаки противоположны (БД плюс, биржа минус или наоборот)
  MAGNITUDE — |расхождение| > 50% от max(|db|,|ledger|) и > $0.5
  NO-MATCH  — в ледгере нет записей в окне (сделка-фантом? WS-потеря?)
  AMBIGUOUS — несколько сделок символа в одном окне — сверка агрегатом, не флагуем

Запуск:  python scripts/ledger_audit.py [--days 3] [--json] [--mark] [--tg]
  --mark: дописать в features_json помеченных сделок ledger_mismatch/ledger_usd
          (решение Егора 08.07: ПОМЕТИТЬ, не переписывать — аналитика исключает флагом,
          история не искажается ретро-правкой). Повторная пометка перезаписывает флаг.
  --tg:   при флагах отправить сводку в TG (oko_feed.alerts.send_tg).
Exit-код 1 при флагах (для cron-алертинга). Отчёт → logs/ledger_audit_last.json.
pm2 (ночной): pm2 start python --name ledger-audit --no-autorestart
    --cron-restart "15 3 * * *" -- scripts/ledger_audit.py --days 1 --mark --tg
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import time
import datetime as dt
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

from core.infra.config_loader import config
from core.exchange.order_manager import OrderManager

WINDOW_SEC = 45 * 60          # окно ledger-записей вокруг closed_at (09.07: 15м→45м —
                              # SAND: БД 19:00 vs реальные fills 14:43/22:00, время дрейфует)
BE_PCT = 0.05                 # |profit_pct| ниже — БД считает сделку BE
MIN_USD = 0.5                 # расхождения мельче не флагуем (пыль/комиссии)


def load_closed_trades(db_path: str, days: float) -> list[dict]:
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT id, symbol, direction, qty, entry_price, actual_entry_price, exit_price,
                      profit_pct, status, closed_at
               FROM simulated_trades
               WHERE status IN ('TP','SL','TSL','EXPIRED')
                 AND exchange_order_id IS NOT NULL AND exchange_order_id != ''
                 AND closed_at >= ? ORDER BY closed_at""", (since,)).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        t = dict(r)
        try:
            ca = dt.datetime.fromisoformat(str(t["closed_at"]).replace("Z", "+00:00"))
            if ca.tzinfo is None:
                ca = ca.replace(tzinfo=dt.timezone.utc)
            t["closed_ms"] = int(ca.timestamp() * 1000)
        except Exception:
            continue
        t["bx_symbol"] = str(t["symbol"]).replace("/USDT:USDT", "-USDT")
        out.append(t)
    return out


def db_pnl_usd(t: dict) -> float | None:
    """PnL сделки по БД: qty × Δцены × направление (линейный USDT-перп)."""
    try:
        entry = float(t["actual_entry_price"] or t["entry_price"] or 0)
        exitp = float(t["exit_price"] or 0)
        qty = float(t["qty"] or 0)
        if entry <= 0 or exitp <= 0 or qty <= 0:
            return None
        sgn = 1.0 if str(t["direction"]).upper() == "LONG" else -1.0
        return (exitp - entry) * qty * sgn
    except Exception:
        return None


async def fetch_ledger(om: OrderManager, start_ms: int, end_ms: int) -> list[dict]:
    """Сырые REALIZED_PNL записи со ВСЕХ субаккаунтов (реюз паттерна get_income_per_account)."""
    recs: list[dict] = []
    accounts = list(om._get_router().accounts) if om._multiacct else [1]
    for acc in accounts:
        try:
            if om._multiacct:
                cli = om._get_router().client_for_account(acc)
                if cli is None:
                    continue
                await cli.sync_time()
            else:
                cli = await om._get_client_synced()
            for d in await cli.get_income(start_ms, end_ms, income_type="REALIZED_PNL"):
                if str(d.get("incomeType", "")).upper() != "REALIZED_PNL":
                    continue
                try:
                    recs.append({"symbol": str(d.get("symbol", "")),
                                 "usd": float(d.get("income") or 0),
                                 "ts": int(d.get("time") or 0), "acc": acc})
                except (TypeError, ValueError):
                    continue
        except Exception as e:
            print(f"[LEDGER-AUDIT] acc{acc} income err: {e}")
    return recs


async def main() -> None:
    ap = argparse.ArgumentParser(description="Сверка закрытых сделок БД с биржевым income-ледгером")
    ap.add_argument("--days", type=float, default=3.0)
    ap.add_argument("--db-path", default="subscriptions.db")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--mark", action="store_true", help="пометить расхождения в features_json")
    ap.add_argument("--tg", action="store_true", help="TG-алерт при флагах")
    args = ap.parse_args()

    trades = load_closed_trades(args.db_path, args.days)
    if not trades:
        print(f"[LEDGER-AUDIT] нет закрытых биржевых сделок за {args.days}д — нечего сверять")
        return
    om = OrderManager(config)
    if not om.is_live():
        raise RuntimeError("trading.execution_mode must be vst or live")
    start_ms = min(t["closed_ms"] for t in trades) - WINDOW_SEC * 1000
    end_ms = max(t["closed_ms"] for t in trades) + WINDOW_SEC * 1000
    ledger = await fetch_ledger(om, start_ms, end_ms)
    print(f"[LEDGER-AUDIT] сделок {len(trades)} · ledger-записей {len(ledger)} · окно ±{WINDOW_SEC//60}мин")

    # группировка сделок по символу для детекта коллизий окон
    by_sym_trades = defaultdict(list)
    for t in trades:
        by_sym_trades[t["bx_symbol"]].append(t)

    flags: list[dict] = []
    ok = fake_be = sign = mag = nomatch = ambig = 0
    for t in trades:
        win_lo, win_hi = t["closed_ms"] - WINDOW_SEC * 1000, t["closed_ms"] + WINDOW_SEC * 1000
        # коллизия: другая сделка того же символа с closed_at в этом же окне
        others = [o for o in by_sym_trades[t["bx_symbol"]]
                  if o["id"] != t["id"] and win_lo <= o["closed_ms"] <= win_hi]
        recs = [r for r in ledger if r["symbol"] == t["bx_symbol"] and win_lo <= r["ts"] <= win_hi]
        if others:
            ambig += 1
            continue
        if not recs:
            # 09.07 fallback (ARB-кейс: сделка НА бирже подтверждена ордерами, а income-фид
            # REALIZED_PNL не отдал — дыра фида): прежде чем флаговать, ищем closing-fill
            # в filled-orders. Нашли → TIME-DRIFT/FEED-GAP (не тревога), нет → NO-MATCH.
            filled_ok = False
            try:
                for acc in (list(om._get_router().accounts) if om._multiacct else [1]):
                    cli = (om._get_router().client_for_account(acc) if om._multiacct
                           else await om._get_client_synced(t["symbol"]))
                    if cli is None:
                        continue
                    for o in await cli.get_filled_orders(t["symbol"], limit=20):
                        ots = int(o.get("updateTime") or o.get("time") or 0)
                        if (o.get("reduceOnly") in (True, "true") and
                                abs(ots - t["closed_ms"]) <= WINDOW_SEC * 1000):
                            filled_ok = True
                            break
                    if filled_ok:
                        break
            except Exception:
                pass
            if filled_ok:
                ok += 1                              # закрытие биржей подтверждено ордером
                continue
            nomatch += 1
            flags.append({"flag": "NO-MATCH", "id": t["id"], "symbol": t["bx_symbol"],
                          "status": t["status"], "db_pct": t["profit_pct"]})
            continue
        led = sum(r["usd"] for r in recs)
        db = db_pnl_usd(t)
        pct = float(t["profit_pct"] or 0)
        if db is None:
            continue
        diff = abs(db - led)
        base = max(abs(db), abs(led))
        if abs(pct) <= BE_PCT and led < -MIN_USD:
            fake_be += 1
            flags.append({"flag": "FAKE-BE", "id": t["id"], "symbol": t["bx_symbol"],
                          "status": t["status"], "db_pct": pct, "db_usd": round(db, 2),
                          "ledger_usd": round(led, 2)})
        elif db * led < 0 and diff > MIN_USD:
            sign += 1
            flags.append({"flag": "SIGN-FLIP", "id": t["id"], "symbol": t["bx_symbol"],
                          "status": t["status"], "db_usd": round(db, 2), "ledger_usd": round(led, 2)})
        elif base > 0 and diff / base > 0.5 and diff > MIN_USD:
            mag += 1
            flags.append({"flag": "MAGNITUDE", "id": t["id"], "symbol": t["bx_symbol"],
                          "status": t["status"], "db_usd": round(db, 2), "ledger_usd": round(led, 2)})
        else:
            ok += 1

    summary = {"ts": int(time.time()), "days": args.days, "trades": len(trades),
               "ok": ok, "fake_be": fake_be, "sign_flip": sign, "magnitude": mag,
               "no_match": nomatch, "ambiguous": ambig, "flags": flags}
    os.makedirs("logs", exist_ok=True)
    with open("logs/ledger_audit_last.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=1))
    else:
        print(f"[LEDGER-AUDIT] OK={ok} FAKE-BE={fake_be} SIGN-FLIP={sign} "
              f"MAGNITUDE={mag} NO-MATCH={nomatch} AMBIGUOUS={ambig}")
        for fl in flags[:25]:
            print("  ", fl)

    # --mark: пометить строки БД (features_json.ledger_mismatch) — НЕ переписывая profit
    if args.mark and flags:
        conn = sqlite3.connect(args.db_path, timeout=10)
        try:
            marked = 0
            for fl in flags:
                r = conn.execute("SELECT features_json FROM simulated_trades WHERE id=?",
                                 (fl["id"],)).fetchone()
                feats = {}
                try:
                    feats = json.loads(r[0]) if (r and r[0]) else {}
                except Exception:
                    pass
                feats["ledger_mismatch"] = fl["flag"]
                if "ledger_usd" in fl:
                    feats["ledger_usd"] = fl["ledger_usd"]
                conn.execute("UPDATE simulated_trades SET features_json=? WHERE id=?",
                             (json.dumps(feats), fl["id"]))
                marked += 1
            conn.commit()
            print(f"[LEDGER-AUDIT] помечено ledger_mismatch: {marked} строк")
        finally:
            conn.close()

    # --tg: алерт при флагах (сводка, не простыня)
    if args.tg and flags:
        try:
            from oko_feed.alerts import send_tg
            worst = sorted((f for f in flags if "ledger_usd" in f),
                           key=lambda x: x.get("ledger_usd", 0))[:5]
            lines = [f"🧾 <b>LEDGER-AUDIT:</b> {len(flags)} расхождений за {args.days:g}д",
                     f"OK {ok} · FAKE-BE {fake_be} · SIGN {sign} · MAG {mag} · NO-MATCH {nomatch}"]
            for f_ in worst:
                lines.append(f"  #{f_['id']} {f_['symbol']} {f_['flag']}: "
                             f"БД {f_.get('db_usd', f_.get('db_pct'))} vs биржа {f_['ledger_usd']}$")
            send_tg("\n".join(lines) + "\n\n#LEDGER_AUDIT", channel="system")
        except Exception as e:
            print(f"[LEDGER-AUDIT] tg err: {e}")
    if flags:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
