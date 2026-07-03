# -*- coding: utf-8 -*-
"""⚡ Ликвидации realtime — WS !forceOrder@arr (Егор 03.07: «ускорить сигналы» п.3).

Один WS-стрим = ВСЕ ликвидации фьючерсного рынка Binance с задержкой ~1с
(против 60с REST-цикла oi-fast). Binance шлёт максимум 1 событие/символ/1000мс —
крупные каскады видны, тонкая гранулярность не нужна.

Два продукта:
  1. ⚡ КАСКАД-алерт → TG: сумма ликвидаций по монете за 90с превысила порог
     (мейджоры $1M, остальные $100k) — каскад ИДЁТ, узнаём на первой секунде.
     Направление: SELL-ликвидации = лонги горят (ход ВНИЗ), BUY = шорты горят (ВВЕРХ).
     + карта целей 2.0 по направлению хода.
  2. Копилка ФАКТОВ → liq_events (все события CORE-монет): сверка с magnet_snapshots
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
from scripts.oi_fast_poller import CORE, _tv, _c

WS_URL = "wss://fstream.binance.com/ws/!forceOrder@arr"
MAJORS = {"BTC", "ETH", "SOL", "XRP", "BNB", "DOGE"}
CASCADE_WIN_SEC = 90
CASCADE_USD_MAJOR = 1_000_000
CASCADE_USD_ALT = 100_000
COOLDOWN_SEC = 1800
CORE_SET = {f"{s}USDT" for s in CORE}

_EVENTS = collections.defaultdict(lambda: collections.deque())   # sym -> [(ts, usd, side)]
_LAST_ALERT: dict[str, float] = {}
_BUF: list[tuple] = []                                           # батч для liq_events


def _flush_events():
    if not _BUF:
        return
    c = conn()
    try:
        c.execute("""CREATE TABLE IF NOT EXISTS liq_events (
            ts INTEGER, symbol TEXT, side TEXT, usd REAL, px REAL)""")
        c.executemany("INSERT INTO liq_events VALUES (?,?,?,?,?)", _BUF)
        c.commit()
        _BUF.clear()
    finally:
        c.close()


def _on_liq(o: dict):
    sym_full = o.get("s", "")
    if sym_full not in CORE_SET:
        return
    sym = sym_full[:-4]
    side = o.get("S", "")                                # SELL = лонг ликвидирован
    px = float(o.get("ap") or o.get("p") or 0)
    usd = float(o.get("z") or o.get("q") or 0) * px
    if not px or not usd:
        return
    now = time.time()
    _BUF.append((int(now), sym, side, round(usd, 2), px))
    w = _EVENTS[sym]
    w.append((now, usd, side))
    while w and now - w[0][0] > CASCADE_WIN_SEC:
        w.popleft()
    tot = sum(u for _, u, _ in w)
    thr = CASCADE_USD_MAJOR if sym in MAJORS else CASCADE_USD_ALT
    if tot < thr or now - _LAST_ALERT.get(sym, 0) < COOLDOWN_SEC:
        return
    _LAST_ALERT[sym] = now
    sell_usd = sum(u for _, u, s in w if s == "SELL")
    longs_burn = sell_usd > tot / 2
    move_side = "SHORT" if longs_burn else "LONG"        # лонги горят → ход вниз
    head = ("🔥 лонги горят → каскад ВНИЗ" if longs_burn else "🔥 шорты горят → каскад ВВЕРХ")
    try:
        targets = build_targets(sym, move_side, px)
    except Exception:
        targets = []
    block = format_targets_block(targets, px)
    msg = (f"⚡ <b>ЛИКВИДАЦИИ: {_tv(sym)}</b> ${tot/1e3:.0f}k за {CASCADE_WIN_SEC}с\n"
           f"{head} · цена {_c(px)}\n"
           + (block + "\n" if block else "")
           + f"#{sym} #LIQ_CASCADE")
    if send_tg(msg):
        print(f"[LIQ-WS] {time.strftime('%H:%M:%S')} CASCADE {sym} ${tot/1e3:.0f}k {move_side}")


async def run():
    while True:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.ws_connect(WS_URL, heartbeat=30) as ws:
                    print(f"[LIQ-WS] connected: {WS_URL} · CORE={len(CORE_SET)} монет · "
                          f"каскад {CASCADE_WIN_SEC}с ≥ $1M мейджоры / $100k альты")
                    last_flush = time.time()
                    async for m in ws:
                        if m.type != aiohttp.WSMsgType.TEXT:
                            continue
                        d = json.loads(m.data)
                        if d.get("e") == "forceOrder":
                            _on_liq(d.get("o", {}))
                        if time.time() - last_flush > 30:
                            _flush_events()
                            last_flush = time.time()
        except Exception as e:  # noqa: BLE001
            print(f"[LIQ-WS] reconnect after err: {e}")
            _flush_events()
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(run())
