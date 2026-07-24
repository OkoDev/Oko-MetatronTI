# -*- coding: utf-8 -*-
"""USDT.D INTRADAY — автономный 1h-ряд доминации из CMC (24.07, вопрос Егора «в кубе те же
данные что в TW?»). ОТВЕТ: ДА — USDT.D = mcap(USDT)/total, ровно как CRYPTOCAP:USDT.D на TW.
TW не имеет секрета; Куб просто недосэмплил (CG раз в 4ч → дневной). CMC-ключ (тариф Егора)
отдаёт intraday-историю global-metrics → строим 1h USDT.D сами, без TW-зависимости.

USDT.D[t] = usdt_mcap / total_market_cap[t]. total_mcap[t] — CMC historical global-metrics 1h;
usdt_mcap — CMC latest (интрадей supply ≈ const, движет знаменатель = total). Уровень чуть
отличается от TW (разный состав TOTAL) — структура/пивоты/WT не зависят (относительные движения).

Хранит в ohlcv_cache.db → usdtd_1h(time,close). pm2 cron hourly. Тест: python scripts/usdtd_intraday.py
"""
import sys, os, json, sqlite3, urllib.request
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from datetime import datetime, timezone

_DB = "ohlcv_cache.db"
_G_HIST = "https://pro-api.coinmarketcap.com/v1/global-metrics/quotes/historical?interval=1h&count={n}"
_USDT_Q = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest?symbol=USDT"


def _key():
    k = os.getenv("CMC_API_KEY")
    if not k:
        try:
            from dotenv import load_dotenv; load_dotenv(); k = os.getenv("CMC_API_KEY")
        except Exception:
            pass
    return k


def _get(url, key):
    req = urllib.request.Request(url, headers={"X-CMC_PRO_API_KEY": key})
    return json.load(urllib.request.urlopen(req, timeout=25))


def fetch_series(count=480):
    key = _key()
    if not key:
        print("[USDTD-1H] нет CMC_API_KEY"); return []
    try:
        usdt_mcap = float(_get(_USDT_Q, key)["data"]["USDT"][0]["quote"]["USD"]["market_cap"])
    except Exception as e:
        print(f"[USDTD-1H] USDT mcap err: {e}"); return []
    try:
        q = _get(_G_HIST.format(n=count), key)["data"]["quotes"]
    except Exception as e:
        print(f"[USDTD-1H] global hist err: {e}"); return []
    out = []
    for pt in q:
        tot = float(pt["quote"]["USD"]["total_market_cap"] or 0)
        if tot <= 0:
            continue
        ts = pt["quote"]["USD"].get("timestamp") or pt.get("timestamp")
        t_ms = int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)
        out.append((t_ms, usdt_mcap / tot * 100.0))
    return sorted(out)


def store(series):
    c = sqlite3.connect(_DB)
    c.execute("CREATE TABLE IF NOT EXISTS usdtd_1h (time INTEGER PRIMARY KEY, close REAL)")
    c.executemany("INSERT OR REPLACE INTO usdtd_1h(time, close) VALUES (?,?)", series)
    c.commit()
    n = c.execute("SELECT COUNT(*) FROM usdtd_1h").fetchone()[0]
    c.close()
    return n


def _ema(v, span):
    a = 2.0 / (span + 1.0); o = [v[0]]
    for x in v[1:]:
        o.append(x * a + o[-1] * (1 - a))
    return o


def _wt(cl):
    esa = _ema(cl, 10)
    d = _ema([abs(c - e) for c, e in zip(cl, esa)], 10)
    ci = [(c - e) / (0.015 * dd) if dd > 1e-12 else 0.0 for c, e, dd in zip(cl, esa, d)]
    wt1 = _ema(ci, 21)
    wt2 = [wt1[0]] * 3 + [sum(wt1[i-3:i+1]) / 4 for i in range(3, len(wt1))]
    return wt1, wt2


def read_now():
    """Текущий structure-read 1h USDT.D — сверяемо с TW-глазом Егора."""
    c = sqlite3.connect(_DB)
    rows = c.execute("SELECT time,close FROM usdtd_1h ORDER BY time").fetchall()
    c.close()
    if len(rows) < 60:
        return f"1h-ряда мало ({len(rows)})"
    cl = [r[1] for r in rows]
    wt1, wt2 = _wt(cl)
    cross_dn = wt1[-2] >= wt2[-2] and wt1[-1] < wt2[-1]
    cross_up = wt1[-2] <= wt2[-2] and wt1[-1] > wt2[-1]
    # недельный пивот из 1h (агрегат прошлой ISO-недели)
    wk = {}; order = []
    for t, v in rows:
        k = datetime.fromtimestamp(t/1000, timezone.utc).isocalendar()[:2]
        wk.setdefault(k, []).append(v)
        if k not in order:
            order.append(k)
    pp = None
    if len(order) >= 2:
        prev = wk[order[-2]]; H, L, C = max(prev), min(prev), prev[-1]
        pp = (H + L + C) / 3
    cur = cl[-1]
    tag = ""
    if cross_dn: tag = "WT CrossDown ▼"
    elif cross_up: tag = "WT CrossUp ▲"
    else: tag = ("WT ▲" if wt1[-1] > wt1[-2] else "WT ▼")
    ppos = (f"{'ПОД' if cur < pp else 'НАД'} нед.PP {pp:.3f}% ({pp-cur:+.3f}пп)") if pp else "нет нед.PP"
    return f"USDT.D(1h) {cur:.3f}% · {tag} (wt {wt1[-1]:+.0f}) · {ppos} · баров {len(rows)}"


def main():
    ser = fetch_series()
    if not ser:
        return
    n = store(ser)
    span_h = (ser[-1][0] - ser[0][0]) / 3.6e6
    print(f"[USDTD-1H] докачано {len(ser)} 1h-точек (~{span_h:.0f}ч), в БД всего {n}")
    print(f"[USDTD-1H] {read_now()}")


if __name__ == "__main__":
    main()
