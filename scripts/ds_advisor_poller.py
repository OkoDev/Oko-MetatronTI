# -*- coding: utf-8 -*-
"""DS-ADVISOR POLLER — конвейер сигналов DC → SIM-shadow (25.07, идея Егора «DS найдёт edge»).

DC (deepseek-v4-pro) пишет сигналы в ds_signals (свобода анализа: шина/287 фич/граф).
Этот поллер регистрирует их SIM-shadow через СТАНДАРТНЫЙ register-путь (те же гейты/косты/
фаза-снапшот, что у всех) — source=ds_advisor, exchange_enabled=false (БЕЗ биржи).
Судья: forward machine (group by signal_type подхватит ds_advisor автоматически).
ГЕЙТ: 20-30 сделок net+ → арминг VST. Красный форвард → трек закрывается честно.

Отдельный процесс (паттерн развязки). pm2: --name ds-advisor · тест: --once
"""
import sys, time, asyncio
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
sys.path.insert(0, ".")
import sqlite3
from types import SimpleNamespace

DB = "subscriptions.db"
POLL_SEC = 60


def _norm_symbol(s: str) -> str:
    s = s.strip().upper()
    if "/" in s:
        return s if ":" in s else s + ":USDT"
    return f"{s}/USDT:USDT"


async def process_batch() -> int:
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    rows = c.execute("SELECT * FROM ds_signals WHERE processed=0 ORDER BY id LIMIT 20").fetchall()
    if not rows:
        c.close()
        return 0
    from core.trading.trade_simulator import TradeSimulator
    ts = TradeSimulator(DB)
    done = 0
    for r in rows:
        try:
            sym = _norm_symbol(r["symbol"])
            d = (r["direction"] or "").upper()
            entry, sl = float(r["entry_price"]), float(r["stop_loss"])
            if d not in ("LONG", "SHORT") or entry <= 0 or sl <= 0:
                raise ValueError(f"bad signal: dir={d} entry={entry} sl={sl}")
            # sanity геометрии (урок класс-4: вход vs SL)
            if (d == "LONG" and sl >= entry) or (d == "SHORT" and sl <= entry):
                raise ValueError(f"inverted geometry: {d} entry={entry} sl={sl}")
            tp = float(r["take_profit"]) if r["take_profit"] else (
                entry + 2 * (entry - sl) if d == "LONG" else entry - 2 * (sl - entry))  # деф. 2R
            rec = SimpleNamespace(
                symbol=sym, direction=d, entry_price=entry, stop_loss=sl, take_profit=tp,
                signal_type="ds_advisor", strength=60,
                confidence=float(r["confidence"] or 0.6),
                timeframe="15m", metadata={"thesis": (r["thesis"] or "")[:500],
                                           "ds_signal_id": r["id"]},
                sl_source="ds_advisor", tp_source="ds_advisor")
            trade_id = await ts.register_trade_async(
                rec, data_collector=None,
                extra_features={"signal_type_override": "ds_advisor",   # иначе register пишет 'composite'
                                "trade_mode": "ds_advisor",
                                "ds_thesis": (r["thesis"] or "")[:300],
                                "ds_confidence": r["confidence"]})
            if trade_id:
                c.execute("UPDATE ds_signals SET processed=1, trade_id=? WHERE id=?",
                          (trade_id, r["id"]))
                print(f"[DS-ADVISOR] ✅ #{r['id']} {sym} {d} → trade {trade_id}")
                done += 1
            else:
                c.execute("UPDATE ds_signals SET processed=-1, error='register returned None (gate?)' "
                          "WHERE id=?", (r["id"],))
                print(f"[DS-ADVISOR] ⛔ #{r['id']} {sym} {d} — гейт отклонил")
        except Exception as e:  # noqa: BLE001
            c.execute("UPDATE ds_signals SET processed=-1, error=? WHERE id=?",
                      (str(e)[:200], r["id"]))
            print(f"[DS-ADVISOR] ❌ #{r['id']}: {e}")
        c.commit()
    c.close()
    return done


def main():
    once = "--once" in sys.argv
    print(f"[DS-ADVISOR] поллер: ds_signals → SIM-shadow (source=ds_advisor, БЕЗ биржи) · "
          f"судья=forward machine · гейт 20-30 net+ → VST")
    while True:
        try:
            n = asyncio.run(process_batch())
            if n:
                print(f"[DS-ADVISOR] {time.strftime('%H:%M:%S')}: зарегистрировано {n}")
        except KeyboardInterrupt:
            break
        except Exception as e:  # noqa: BLE001
            print(f"[DS-ADVISOR] err: {e}")
        if once:
            break
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
