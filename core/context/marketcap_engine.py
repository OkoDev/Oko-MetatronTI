# -*- coding: utf-8 -*-
"""core.context.marketcap_engine — SELF-COMPUTED DOMINANCE (24.07, продукт-грейд).

Егор: «Куб как продукт — у юзера может не быть открытого TW». Значит USDT.D/BTC.D Куб считает
САМ из первичных данных, без TW, на любой машине:

  USDT.D = usdt_mcap / TOTAL,  TOTAL = Σ(supply_i × price_i) + tail

- supply_i (circulating) — медленно меняется → daily-снапшот CMC listings (ключ юзера).
- price_i — ЖИВЫЕ цены Binance ticker (713 USDT-пар, один REST-запрос, tick-fast, без ключа).
- tail — рынок за пределами топ-N (global_total − Σ listed на снапшоте): статичная база.

Результат: живой USDT.D/BTC.D/ETH.D без TW, без лага снапшотов. Топ-500 ≈ 98% total → структура
трекает CRYPTOCAP; абсолютный уровень чуть смещён (для режима нормализуется). Чистый модуль +
таблицы в ohlcv_cache.db. Refresh supply — раз в день (scripts/marketcap_refresh.py, pm2 cron).
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import urllib.request
from datetime import datetime, timezone

_DB = "ohlcv_cache.db"
_BINANCE_TICKER = "https://api.binance.com/api/v3/ticker/price"
_CMC_LIST = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest?limit={n}&convert=USD"
_CMC_GLOBAL = "https://pro-api.coinmarketcap.com/v1/global-metrics/quotes/latest"

_live_cache: dict = {"ts": 0.0, "val": None}
_LIVE_TTL = 45.0
# ротация из CMC-истории (18ч-дельта, часовая гранулярность) — кэш 5 мин бережёт CMC-кредиты:
# без него терминал дёргал CMC каждые 45с пока вкладка открыта (~80/час). Егор 25.07.
_rot_cache: dict = {"ts": 0.0, "val": None, "w": None}
_ROT_TTL = 300.0


def _cmc_key() -> str | None:
    k = os.getenv("CMC_API_KEY")
    if not k:
        try:
            from dotenv import load_dotenv; load_dotenv(); k = os.getenv("CMC_API_KEY")
        except Exception:
            pass
    return k


def _get(url: str, key: str | None = None):
    headers = {"User-Agent": "oko-mcap"}
    if key:
        headers["X-CMC_PRO_API_KEY"] = key
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=25))


def _ensure(c: sqlite3.Connection) -> None:
    c.execute("""CREATE TABLE IF NOT EXISTS mcap_supply(
        date TEXT, symbol TEXT, supply REAL, cmc_price REAL, cmc_mcap REAL,
        PRIMARY KEY(date, symbol))""")
    c.execute("""CREATE TABLE IF NOT EXISTS mcap_meta(
        date TEXT PRIMARY KEY, ts INTEGER, tail REAL, usdt_mcap REAL,
        total_snapshot REAL, n INTEGER)""")


def refresh_supply_snapshot(top: int = 500) -> dict | None:
    """Daily: CMC listings топ-N (supply/price/mcap) + global total → tail. Пишет в БД."""
    key = _cmc_key()
    if not key:
        print("[MCAP] нет CMC_API_KEY"); return None
    try:
        lst = _get(_CMC_LIST.format(n=top), key)
        if lst.get("status", {}).get("error_code") != 0:
            print(f"[MCAP] listings err: {lst['status'].get('error_message')}"); return None
        glob = _get(_CMC_GLOBAL, key)
        total_global = float(glob["data"]["quote"]["USD"]["total_market_cap"])
    except Exception as e:
        print(f"[MCAP] fetch err: {e}"); return None

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = []
    listed_sum = 0.0
    usdt_mcap = 0.0
    seen = set()
    for c in lst["data"]:
        sym = c["symbol"].upper()
        if sym in seen:               # коллизии тикеров — берём первый (крупнейший по mcap)
            continue
        seen.add(sym)
        q = c["quote"]["USD"]
        supply = float(c.get("circulating_supply") or 0)
        price = float(q.get("price") or 0)
        mcap = float(q.get("market_cap") or 0)
        if mcap <= 0:
            continue
        rows.append((today, sym, supply, price, mcap))
        listed_sum += mcap
        if sym == "USDT":
            usdt_mcap = mcap
    tail = max(0.0, total_global - listed_sum)

    c = sqlite3.connect(_DB)
    _ensure(c)
    c.executemany("INSERT OR REPLACE INTO mcap_supply VALUES(?,?,?,?,?)", rows)
    c.execute("INSERT OR REPLACE INTO mcap_meta VALUES(?,?,?,?,?,?)",
              (today, int(time.time()), tail, usdt_mcap, total_global, len(rows)))
    c.commit(); c.close()
    print(f"[MCAP] снапшот {today}: {len(rows)} монет, tail=${tail/1e9:.0f}B, "
          f"total=${total_global/1e9:.0f}B, USDT.D_снапшот={usdt_mcap/total_global*100:.3f}%")
    return {"n": len(rows), "tail": tail, "usdt_mcap": usdt_mcap, "total": total_global}


def _load_snapshot() -> tuple[dict, dict] | None:
    """→ ({symbol: (supply, cmc_price, cmc_mcap)}, meta) из последнего daily-снапшота."""
    try:
        c = sqlite3.connect(_DB)
        c.row_factory = sqlite3.Row
        m = c.execute("SELECT * FROM mcap_meta ORDER BY date DESC LIMIT 1").fetchone()
        if not m:
            c.close(); return None
        rows = c.execute("SELECT symbol, supply, cmc_price, cmc_mcap FROM mcap_supply WHERE date=?",
                         (m["date"],)).fetchall()
        c.close()
    except Exception:
        return None
    snap = {r["symbol"]: (r["supply"], r["cmc_price"], r["cmc_mcap"]) for r in rows}
    return snap, dict(m)


_BINGX_TICKER = "https://open-api.bingx.com/openApi/swap/v2/quote/ticker"


def _live_prices() -> dict:
    """{base: price_usdt} — Binance ticker + BingX perps (биржа бота, больше монет). Один запрос каждой."""
    out = {}
    try:
        for x in _get(_BINANCE_TICKER):
            s = x["symbol"]
            if s.endswith("USDT"):
                out[s[:-4]] = float(x["price"])
    except Exception:
        pass
    try:
        bx = _get(_BINGX_TICKER).get("data", [])
        for x in bx:
            s = str(x.get("symbol", ""))          # 'BTC-USDT'
            if s.endswith("-USDT"):
                base = s[:-5]
                p = float(x.get("lastPrice") or x.get("last") or 0)
                if p > 0 and base not in out:      # Binance приоритетнее (спот), BingX добивает хвост
                    out[base] = p
    except Exception:
        pass
    return out


def live_dominance() -> dict | None:
    """ЖИВОЙ USDT.D/BTC.D/ETH.D: supply(daily) × price(live Binance) + tail. Кэш 45с."""
    now = time.time()
    if now - _live_cache["ts"] < _LIVE_TTL and _live_cache["val"] is not None:
        return _live_cache["val"]
    loaded = _load_snapshot()
    if loaded is None:
        return None
    snap, meta = loaded
    prices = _live_prices()
    # стейблы: их mcap ≈ supply, live-цена ~1 не нужна (иначе шум ±0.1%)
    _STABLES = {"USDT", "USDC", "DAI", "TUSD", "FDUSD", "USDE", "PYUSD", "USDD", "USDS"}
    total = float(meta["tail"] or 0)
    btc_m = eth_m = usdt_m = stable_m = 0.0
    live_mcap = 0.0
    for sym, (supply, cmc_price, cmc_mcap) in snap.items():
        p = prices.get(sym)
        if sym not in _STABLES and p and p > 0 and supply > 0:
            m = supply * p
            live_mcap += m
        else:
            m = cmc_mcap                          # стейбл/нет live-пары → daily-mcap
        total += m
        if sym == "BTC":
            btc_m = m
        elif sym == "ETH":
            eth_m = m
        elif sym == "USDT":
            usdt_m = m
        if sym in _STABLES:
            stable_m += m
    if total <= 0:
        return None
    alt_m = total - btc_m - stable_m              # TOTAL2-подобно: рынок без BTC и стейблов
    val = {"usdt_d": usdt_m / total * 100, "btc_d": btc_m / total * 100,
           "eth_d": eth_m / total * 100, "alt_d": alt_m / total * 100,
           "total_mcap": total, "total2_mcap": total - btc_m, "alt_mcap": alt_m,
           "cov_mcap": live_mcap / total, "n": len(snap),
           "source": "self_computed", "ts": int(now)}
    _live_cache["ts"] = now
    _live_cache["val"] = val
    return val


_CMC_GHIST = "https://pro-api.coinmarketcap.com/v1/global-metrics/quotes/historical?interval=1h&count={n}"


def rotation_now(window_h: int = 18) -> dict | None:
    """ТРИАДА-РОТАЦИЯ (наблюдение Егора): тренды USDT.D / BTC.D / ALT за window_h из CMC-истории
    (total+altcoin) → классификация. usdt_d = usdt_mcap/total. Возвращает дельты + вердикт.
      USDT.D↑ & BTC.D↓ & alt≈flat → альты СТОЯТ (risk-off тянет, но альты отбирают долю у BTC).
      USDT.D↓                     → альты ЛЕТЯТ (деньги из стейблов в крипту).
      USDT.D↑ & alt↓              → risk-off, всё вниз.
    """
    now = time.time()
    if (now - _rot_cache["ts"] < _ROT_TTL and _rot_cache["val"] is not None
            and _rot_cache["w"] == window_h):
        return _rot_cache["val"]
    key = _cmc_key()
    if not key:
        return None
    try:
        q = _get(_CMC_GHIST.format(n=max(window_h + 4, 24)), key)["data"]["quotes"]
    except Exception as e:
        print(f"[MCAP] rotation hist err: {e}"); return None
    loaded = _load_snapshot()
    usdt_mcap = float(loaded[1]["usdt_mcap"]) if loaded else 0.0
    ser = []
    for pt in q:
        u = pt["quote"]["USD"]
        tot = float(u.get("total_market_cap") or 0)
        alt = float(u.get("altcoin_market_cap") or 0)   # CMC: всё кроме BTC
        if tot <= 0:
            continue
        btc = tot - alt
        ser.append({"total": tot, "alt": alt, "btc_d": btc / tot * 100,
                    "usdt_d": (usdt_mcap / tot * 100) if usdt_mcap else None})
    if len(ser) < 4:
        return None
    a, b = ser[-min(window_h, len(ser))], ser[-1]      # окно назад → сейчас
    d_usdtd = (b["usdt_d"] - a["usdt_d"]) if (b["usdt_d"] and a["usdt_d"]) else 0.0
    d_btcd = b["btc_d"] - a["btc_d"]
    d_alt = (b["alt"] / a["alt"] - 1) * 100 if a["alt"] else 0.0    # % изм. альт-mcap
    FLAT = 1.2                                          # порог «стоят», % (калибр. по глазу Егора 24.07)
    if d_usdtd < -0.03:
        verdict = "🟢 АЛЬТЫ ЛЕТЯТ — USDT.D корректируется вниз (деньги из стейблов в крипту)"
    elif d_usdtd > 0.03 and d_btcd < 0 and abs(d_alt) < FLAT:
        verdict = "🟡 АЛЬТЫ СТОЯТ — USDT.D↑ (risk-off) тянет, но BTC.D↓ (альты отбирают долю) — гасятся"
    elif d_usdtd > 0.03 and d_alt < -FLAT:
        verdict = "🔴 RISK-OFF — USDT.D↑ и альты вниз (деньги в стейблы)"
    elif d_btcd > 0 and d_alt < -FLAT:
        verdict = "🟠 BTC-СЕЗОН — BTC.D↑, альты сливаются в BTC"
    else:
        verdict = "⚪ смешанно — чёткой ротации нет"
    val = {"d_usdtd": d_usdtd, "d_btcd": d_btcd, "d_alt_pct": d_alt,
           "usdt_d": b["usdt_d"], "btc_d": b["btc_d"], "window_h": window_h, "verdict": verdict}
    _rot_cache.update(ts=now, val=val, w=window_h)
    return val


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    if "--refresh" in sys.argv:
        refresh_supply_snapshot()
    d = live_dominance()
    if d:
        print(f"[MCAP] LIVE: USDT.D={d['usdt_d']:.3f}% · BTC.D={d['btc_d']:.3f}% · "
              f"ETH.D={d['eth_d']:.3f}% · ALT.D={d['alt_d']:.3f}% · total=${d['total_mcap']/1e12:.3f}T · "
              f"покрытие по mcap {d['cov_mcap']:.0%} ({d['n']} монет)")
    r = rotation_now()
    if r:
        print(f"[MCAP] РОТАЦИЯ {r['window_h']}ч: ΔUSDT.D={r['d_usdtd']:+.3f}пп · ΔBTC.D={r['d_btcd']:+.3f}пп · "
              f"альт-mcap {r['d_alt_pct']:+.2f}%")
        print(f"       {r['verdict']}")
    else:
        print("[MCAP] нет снапшота — сначала: python core/context/marketcap_engine.py --refresh")
