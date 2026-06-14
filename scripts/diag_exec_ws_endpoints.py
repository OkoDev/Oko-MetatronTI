# -*- coding: utf-8 -*-
"""
diag_exec_ws_endpoints v2 (14.06) — проверка ACCOUNT_UPDATE на swap user-data.

Docs-v3: swap user-data шлёт ТОЛЬКО ACCOUNT_UPDATE (позиции/баланс, причина m),
push автоматом по listenKey, subscribe НЕ нужен. Отдельного order-event (orderId) нет.
→ EXEC-WS цель = 2b (close/position sync через ACCOUNT_UPDATE pa=0), НЕ 2a (exch_id).

Слушает swap-market по listenKey КАЖДОГО аккаунта (acc1+acc2) параллельно, ловит
ACCOUNT_UPDATE при реальных открытиях/закрытиях. В конце сверяем с БД.
Запуск: python scripts/diag_exec_ws_endpoints.py
"""
from __future__ import annotations
import asyncio, gzip, io, json, os, sys, time
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import aiohttp
from dotenv import load_dotenv
load_dotenv()

VST_REST = "https://open-api-vst.bingx.com"
# 🎯 VST WS endpoint (docs-v3): vst-open-api-ws, НЕ open-api-swap (=PROD/LIVE).
# Корень orders=0 — код слушал PROD-домен с VST-listenKey.
WS = "wss://vst-open-api-ws.bingx.com/swap-market?listenKey="
LISTEN_SEC = 420

ACCOUNTS = [
    ("acc1", os.getenv("BINGX_VST_API_KEY")),
    ("acc2", os.getenv("BINGX_VST_API_KEY_2")),
]


def _decode(data) -> str:
    if isinstance(data, (bytes, bytearray)):
        try:
            return gzip.GzipFile(fileobj=io.BytesIO(data)).read().decode("utf-8", "ignore")
        except Exception:
            return bytes(data).decode("utf-8", "ignore")
    return str(data)


async def get_listen_key(session, key) -> str | None:
    url = f"{VST_REST}/openApi/user/auth/userDataStream"
    async with session.post(url, headers={"X-BX-APIKEY": key},
                            timeout=aiohttp.ClientTimeout(total=15)) as r:
        data = await r.json(content_type=None)
        return data.get("listenKey") if isinstance(data, dict) else None


async def listen(tag: str, key: str, stats: dict, deadline: float):
    cls = Counter()
    acc_events = []  # сырьё ACCOUNT_UPDATE
    stats[tag] = {"cls": cls, "acc": acc_events, "connected": False, "err": None, "lk": None}
    if not key:
        stats[tag]["err"] = "нет ключа"
        return
    try:
        async with aiohttp.ClientSession() as s:
            lk = await get_listen_key(s, key)
            stats[tag]["lk"] = (lk or "")[:16]
            if not lk:
                stats[tag]["err"] = "listenKey не получен"
                return
            async with s.ws_connect(WS + lk, timeout=aiohttp.ClientTimeout(total=20),
                                    heartbeat=30) as ws:
                stats[tag]["connected"] = True
                print(f"[{tag}] connected lk={lk[:14]}")
                async for m in ws:
                    if time.time() > deadline:
                        break
                    if m.type not in (aiohttp.WSMsgType.BINARY, aiohttp.WSMsgType.TEXT):
                        continue
                    dec = _decode(m.data)
                    if dec == "Ping" or '"ping"' in dec.lower():
                        cls["ping"] += 1
                        try:
                            await ws.send_str("Pong")
                        except Exception:
                            pass
                        continue
                    try:
                        msg = json.loads(dec)
                    except Exception:
                        cls["unparseable"] += 1
                        continue
                    if not isinstance(msg, dict):
                        continue
                    e = str(msg.get("e") or msg.get("dataType") or "").upper()
                    if e == "SNAPSHOT":
                        cls["SNAPSHOT"] += 1
                    elif "ACCOUNT" in e:
                        cls["ACCOUNT_UPDATE"] += 1
                        a = msg.get("a") or {}
                        reason = a.get("m")
                        # позиции с pa (pa=0 → закрыта)
                        positions = [(p.get("s"), p.get("pa"), p.get("ps"))
                                     for p in (a.get("P") or [])]
                        if len(acc_events) < 20:
                            acc_events.append({"m": reason, "P": positions, "raw": dec[:260]})
                        print(f"[{tag}] *** ACCOUNT_UPDATE m={reason} P={positions}")
                    elif isinstance(msg.get("o"), dict) and msg.get("o"):
                        cls["ORDER(o)!"] += 1  # неожиданно — отдельный order event
                        print(f"[{tag}] *** ORDER(o) {dec[:200]}")
                    else:
                        cls[f"other:{e or '?'}"] += 1
    except Exception as ex:
        stats[tag]["err"] = f"{type(ex).__name__}: {ex}"
        print(f"[{tag}] ERROR {ex}")


async def main():
    if not any(k for _, k in ACCOUNTS):
        print("НЕТ ключей в env — стоп")
        return
    print(f"window={LISTEN_SEC}s start_utc={time.strftime('%H:%M:%S', time.gmtime())}")
    deadline = time.time() + LISTEN_SEC
    stats: dict = {}
    await asyncio.gather(*[listen(tag, key, stats, deadline) for tag, key in ACCOUNTS])
    print("\n" + "=" * 60)
    print(f"ИТОГ (end_utc={time.strftime('%H:%M:%S', time.gmtime())}):")
    for tag, _ in ACCOUNTS:
        st = stats.get(tag, {})
        cls = st.get("cls", Counter())
        print(f"\n[{tag}] connected={st.get('connected')} lk={st.get('lk')} err={st.get('err')}")
        print(f"   ACCOUNT_UPDATE: {cls.get('ACCOUNT_UPDATE',0)} | разбивка: {dict(cls)}")
        for ev in st.get("acc", [])[:8]:
            print(f"     {ev['m']}: {ev['P']}")
    print("\nВЕРДИКТ: если ACCOUNT_UPDATE m=ORDER с P[] приходят при открытиях →")
    print("  EXEC-WS 2b (position sync) жизнеспособен. Если 0 при реальных откр → VST не пушит.")


if __name__ == "__main__":
    asyncio.run(main())
