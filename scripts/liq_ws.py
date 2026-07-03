# -*- coding: utf-8 -*-
"""⚡ Ликвидации realtime — Bybit v5 allLiquidation WS (Егор 03.07: «ускорить сигналы» п.3).

⚠️ ИСТОРИЯ ИСТОЧНИКА (03.07): Binance fstream WS с этой машины МОЛЧИТ (коннект ок, данных 0
и на forceOrder, и на aggTrade; через SG-прокси то же — фьючерсный WS зарезан для NL/SG гео,
SPOT при этом работает). Bybit v5 public linear — живой (проверено: 157 тиков/20с) →
ликвидации берём с Bybit. Каскады кросс-биржевые: Bybit-тики = честный след того же события.
Масштаб $ у Bybit меньше Binance — пороги калибровать по факту. Второй слой копилки —
синтетика из OI-унвинда Binance (oi_fast_poller._log_liq_synth, source='oi_synth').

Два продукта:
  1. ⚡ КАСКАД-алерт → TG: сумма ликвидаций по монете за 90с превысила порог
     (мейджоры $500k, остальные $50k — Bybit-масштаб) — каскад ИДЁТ, узнаём за ~1с.
     Направление: Sell-ликвидации = лонги горят (ход ВНИЗ), Buy = шорты горят (ВВЕРХ).
     + карта целей 2.0 по направлению хода.
  2. Копилка ФАКТОВ → liq_events (source='bybit_ws'): сверка с magnet_snapshots
     (предсказание) — доказательство/опровержение формулы магнитов.

pm2: pm2 start scripts/liq_ws.py --name liq-ws --interpreter <python>
"""
import asyncio
import collections
import json
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
sys.path.insert(0, ".")

import aiohttp

from oko_feed.alerts import send_tg
from oko_feed.store import conn
from oko_feed.targets import build_targets, format_targets_block
from scripts.oi_fast_poller import CORE, _links, _c

WS_URL = "wss://stream.bybit.com/v5/public/linear"
MAJORS = {"BTC", "ETH", "SOL", "XRP", "BNB", "DOGE"}
CASCADE_WIN_SEC = 90
CASCADE_USD_MAJOR = 500_000               # Bybit-масштаб (< Binance) — калибровать по факту
CASCADE_USD_ALT = 50_000
COOLDOWN_SEC = 1800

_EVENTS = collections.defaultdict(lambda: collections.deque())   # sym -> [(ts, usd, side)]
_LAST_ALERT: dict[str, float] = {}
_BUF: list[tuple] = []                                           # батч для liq_events


def _flush_events():
    if not _BUF:
        return
    c = conn()
    try:
        c.execute("""CREATE TABLE IF NOT EXISTS liq_events (
            ts INTEGER, symbol TEXT, side TEXT, usd REAL, px REAL, source TEXT)""")
        try:
            c.execute("ALTER TABLE liq_events ADD COLUMN source TEXT")
        except Exception:
            pass
        c.executemany("INSERT INTO liq_events VALUES (?,?,?,?,?,'bybit_ws')", _BUF)
        c.commit()
        _BUF.clear()
    finally:
        c.close()


def _on_liq(sym_full: str, rows: list[dict]):
    """topic allLiquidation.{SYM}USDT → data=[{T,s,S,v,p}]. S: Sell = лонг ликвидирован."""
    sym = sym_full[:-4] if sym_full.endswith("USDT") else sym_full
    now = time.time()
    w = _EVENTS[sym]
    for o in rows:
        side = "SELL" if o.get("S") == "Sell" else "BUY"
        px = float(o.get("p") or 0)
        usd = float(o.get("v") or 0) * px
        if not px or not usd:
            continue
        _BUF.append((int(now), sym, side, round(usd, 2), px))
        w.append((now, usd, side))
    while w and now - w[0][0] > CASCADE_WIN_SEC:
        w.popleft()
    tot = sum(u for _, u, _ in w)
    thr = CASCADE_USD_MAJOR if sym in MAJORS else CASCADE_USD_ALT
    if tot < thr or now - _LAST_ALERT.get(sym, 0) < COOLDOWN_SEC:
        return
    _LAST_ALERT[sym] = now
    px = float(rows[-1].get("p") or 0)
    sell_usd = sum(u for _, u, s in w if s == "SELL")
    longs_burn = sell_usd > tot / 2
    move_side = "SHORT" if longs_burn else "LONG"        # лонги горят → ход вниз
    head = ("🔥 лонги горят → каскад ВНИЗ" if longs_burn else "🔥 шорты горят → каскад ВВЕРХ")
    try:
        targets = build_targets(sym, move_side, px)
    except Exception:
        targets = []
    block = format_targets_block(targets, px)
    dot = "🔴" if longs_burn else "🟢"
    msg = (f"⚡ <b>ЛИКВИДАЦИИ:</b>\n\n"
           f"{dot} <code>{sym}</code> ${tot/1e3:.0f}k за {CASCADE_WIN_SEC}с (Bybit)\n"
           f"{head} · цена {_c(px)}\n"
           + (f"\n{block}\n" if block else "")
           + f"\n{_links(sym)}\n\n"
           + f"#{sym} #LIQ_CASCADE")
    if send_tg(msg):
        print(f"[LIQ-WS] {time.strftime('%H:%M:%S')} CASCADE {sym} ${tot/1e3:.0f}k {move_side}")


async def _subscribe(ws):
    topics = [f"allLiquidation.{s}USDT" for s in CORE]
    for i in range(0, len(topics), 10):                  # чанками по 10 args
        await ws.send_json({"op": "subscribe", "args": topics[i:i + 10]})
        await asyncio.sleep(0.1)


async def run():
    while True:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.ws_connect(WS_URL, heartbeat=20) as ws:
                    await _subscribe(ws)
                    print(f"[LIQ-WS] connected: Bybit v5 linear · {len(CORE)} монет · "
                          f"каскад {CASCADE_WIN_SEC}с ≥ ${CASCADE_USD_MAJOR/1e3:.0f}k мейджоры "
                          f"/ ${CASCADE_USD_ALT/1e3:.0f}k альты")
                    last_flush = last_ping = time.time()
                    while True:
                        try:
                            m = await asyncio.wait_for(ws.receive(), timeout=15)
                        except asyncio.TimeoutError:
                            m = None
                        now = time.time()
                        if now - last_ping > 20:          # Bybit просит op:ping каждые ~20с
                            await ws.send_json({"op": "ping"})
                            last_ping = now
                        if m is None:
                            continue
                        if m.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            raise ConnectionError(f"ws closed: {m.type}")
                        if m.type != aiohttp.WSMsgType.TEXT:
                            continue
                        d = json.loads(m.data)
                        topic = d.get("topic", "")
                        if topic.startswith("allLiquidation.") and d.get("data"):
                            _on_liq(topic.split(".", 1)[1], d["data"])
                        if now - last_flush > 30:
                            _flush_events()
                            last_flush = now
        except Exception as e:  # noqa: BLE001
            print(f"[LIQ-WS] reconnect after err: {e}")
            _flush_events()
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(run())
