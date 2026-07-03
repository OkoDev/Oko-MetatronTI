# -*- coding: utf-8 -*-
"""БЫСТРЫЙ OI-радар (60с цикл) — сквиз-алерт за 1-2 минуты, не 10 (Егор 03.07).

Источник: Binance /fapi/v1/openInterest (realtime, weight=1) + тикер цены.
Дельты в RAM-окне (12 точек = 12 мин). Условия:
  🌀 СКВИЗ:  |Δцена 3м| >= 0.6%  И  ΔOI 3м <= -0.15%   (движение закрытиями — GRT-механизм)
  📈 BUILD:  ΔOI 5м >= +0.5%                             (резкая загрузка)
Алерт → TG сразу (cooldown 30 мин per монета через oko_feed.alerts.alert_log).
pm2: --name oi-fast
"""
import sys, time, json, urllib.request, collections
try:
    sys.stdout.reconfigure(encoding="utf-8")   # pm2 Windows-консоль = cp1251, Δ/≥ роняли процесс
except Exception:
    pass
sys.path.insert(0, ".")
from oko_feed.alerts import send_tg
from oko_feed.store import conn

# ~50 ликвидных: мейджоры + бэктест-вселенная atr_S2 + активные альты
CORE = ["BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "LINK", "AVAX", "DOT",
        "TRX", "LTC", "GRT", "ARB", "OP", "APT", "NEAR", "INJ", "FIL", "ATOM",
        "RUNE", "SEI", "SUI", "UNI", "AAVE", "ETC", "BCH", "ICP", "TIA", "WLD",
        "SAND", "MANA", "ALGO", "EGLD", "CHZ", "KAVA", "ZIL", "IOTA", "ENJ",
        "PEPE", "SHIB", "ORDI", "TON", "FET", "RENDER", "JUP", "PYTH", "STRK", "WIF", "BONK"]
INTERVAL = 60
WIN = collections.defaultdict(lambda: collections.deque(maxlen=12))   # sym -> [(ts, oi, price)]
_PRICES: dict[str, float] = {}


def _refresh_prices():
    """ВСЕ цены одним batch-запросом (weight=2) — вместо 50 отдельных."""
    global _PRICES
    try:
        arr = _get("https://fapi.binance.com/fapi/v1/ticker/price")
        _PRICES = {x["symbol"]: float(x["price"]) for x in arr}
    except Exception:
        pass


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 oko-feed"})
    return json.load(urllib.request.urlopen(req, timeout=10))


def _cooldown_ok(key: str, sec: int = 1800) -> bool:
    c = conn()
    try:
        c.execute("CREATE TABLE IF NOT EXISTS alert_log (key TEXT PRIMARY KEY, ts INTEGER)")
        row = c.execute("SELECT ts FROM alert_log WHERE key=?", (key,)).fetchone()
        if row and time.time() - row[0] < sec:
            return False
        c.execute("INSERT OR REPLACE INTO alert_log VALUES (?, ?)", (key, int(time.time())))
        c.commit()
        return True
    finally:
        c.close()


def tick():
    alerts = []
    _refresh_prices()
    for sym in CORE:
        try:
            oi = float(_get(f"https://fapi.binance.com/fapi/v1/openInterest?symbol={sym}USDT")["openInterest"])
            px = _PRICES.get(f"{sym}USDT")
            if not px:
                continue
        except Exception:
            continue
        w = WIN[sym]
        w.append((time.time(), oi, px))
        if len(w) >= 4:
            t3, oi3, px3 = w[-4]                       # ~3 минуты назад
            d_oi3 = (oi / oi3 - 1) * 100 if oi3 else 0
            d_px3 = (px / px3 - 1) * 100 if px3 else 0
            if abs(d_px3) >= 0.6 and d_oi3 <= -0.15 and _cooldown_ok(f"fast_squeeze:{sym}"):
                side = "вверх (шорты горят)" if d_px3 > 0 else "вниз (лонги горят)"
                send_tg(f"🌀 <b>СКВИЗ LIVE: {sym}</b>\nцена {d_px3:+.2f}%/3м {side}\n"
                        f"OI {d_oi3:+.2f}%/3м — движение ЗАКРЫТИЯМИ\nцена {px}")
                alerts.append(f"squeeze {sym}")
        if len(w) >= 6:
            t5, oi5, _ = w[-6]
            d_oi5 = (oi / oi5 - 1) * 100 if oi5 else 0
            if d_oi5 >= 0.5 and _cooldown_ok(f"fast_build:{sym}"):
                send_tg(f"📈 <b>OI BUILD LIVE: {sym}</b> +{d_oi5:.2f}%/5м — грузятся. цена {px}")
                alerts.append(f"build {sym}")
        time.sleep(0.15)
    return alerts


if __name__ == "__main__":
    print(f"[OI-FAST] радар: {len(CORE)} монет, цикл {INTERVAL}с, сквиз=|Δp3м|≥0.6%+ΔOI≤−0.15%")
    while True:
        try:
            a = tick()
            if a:
                print(f"[OI-FAST] {time.strftime('%H:%M:%S')} ALERTS: {a}")
        except KeyboardInterrupt:
            break
        except Exception as e:  # noqa: BLE001
            print(f"[OI-FAST] err: {e}")
        time.sleep(INTERVAL)
