# -*- coding: utf-8 -*-
"""БЫСТРЫЙ OI-радар (60с цикл) — сквиз-алерт за 1-2 минуты, не 10 (Егор 03.07).

Источник: Binance /fapi/v1/openInterest (realtime, weight=1) + тикер цены.
Дельты в RAM-окне (12 точек = 12 мин). Условия:
  🌀 СКВИЗ:  |Δцена 3м| >= 0.6%  И  ΔOI 3м <= -0.15%   (движение закрытиями — GRT-механизм)
  📈 BUILD:  ΔOI 5м >= +0.5%                             (резкая загрузка)
  🚀 PUMP:   |Δцена 5м| >= 2.5% → подтверждение klines: объём ×3 + RSI-экстремум
             → алерт с уровнями Entry/SL/TP1-3 (спека docs/PUMP-BOT-FULL-SPEC.md, SHADOW —
             только алерт, НЕ торгуем). Grade по GRT-уроку: памп БЕЗ роста OI = стопы-топливо.
Алерт → TG сразу (cooldown 30-60 мин per монета через oko_feed.alerts.alert_log).
pm2: --name oi-fast · тест разбора монеты: python scripts/oi_fast_poller.py --test MANA
"""
import sys, time, json, urllib.request, collections
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)   # cp1251 роняла Δ/≥; pipe-буфер прятал логи
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
        "1000PEPE", "1000SHIB", "ORDI", "HBAR", "FET", "RENDER", "JUP", "PYTH",
        "STRK", "WIF", "1000BONK"]   # мемы = 1000-префикс на futures; TON делистнут → HBAR
INTERVAL = 60
WIN = collections.defaultdict(lambda: collections.deque(maxlen=12))   # sym -> [(ts, oi, price)]
_PRICES: dict[str, float] = {}

# ── PUMP-DETECTOR v0.5 (SFERA-14, спека docs/PUMP-BOT-FULL-SPEC.md) ──
PUMP_PCT_5M = 2.5      # ценовой кандидат: |Δцена 5м| >= порога → тянем klines на подтверждение
PUMP_PCT_12M = 4.0     # или медленный памп за всё окно радара
PUMP_VOL_RATIO = 3.0   # спека: объём последних баров ×3 к базе
PUMP_RSI_HI, PUMP_RSI_LO = 75, 25


def _rsi(closes: list[float], period: int = 14) -> float | None:
    """Wilder RSI на чистом python (скрипт без pandas)."""
    if len(closes) < period + 2:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gain = sum(d for d in deltas[:period] if d > 0) / period
    loss = sum(-d for d in deltas[:period] if d < 0) / period
    for d in deltas[period:]:
        gain = (gain * (period - 1) + max(d, 0)) / period
        loss = (loss * (period - 1) + max(-d, 0)) / period
    if loss == 0:
        return 100.0
    return 100 - 100 / (1 + gain / loss)


def _fmt(v: float) -> str:
    return f"{v:.6g}"


def _log_pump(row: dict) -> None:
    """Лог подтверждённого алерта → pump_signals (для WR-статистики SHADOW→ARMED)."""
    c = conn()
    try:
        c.execute("""CREATE TABLE IF NOT EXISTS pump_signals (
            ts INTEGER, symbol TEXT, side TEXT, d_px REAL, vol_ratio REAL, rsi REAL,
            d_oi REAL, grade TEXT, entry REAL, sl REAL, tp1 REAL, tp2 REAL, tp3 REAL,
            PRIMARY KEY (symbol, ts))""")
        c.execute("INSERT OR REPLACE INTO pump_signals VALUES "
                  "(:ts,:symbol,:side,:d_px,:vol_ratio,:rsi,:d_oi,:grade,:entry,:sl,:tp1,:tp2,:tp3)", row)
        c.commit()
    finally:
        c.close()


def analyze_pump(sym: str, px: float, d_px: float, d_oi5: float | None,
                 debug: bool = False) -> tuple[str, dict] | None:
    """Подтверждение ценового кандидата по 5m-свечам → (текст алерта, строка лога) или None.

    Спека: volume_ratio>3 + RSI-экстремум; уровни = откат 50/75/100% к цене ДО пампа,
    SL за хай пампа +1%. Grade — наш GRT-урок: OI не вырос = двигали СТОПЫ (сквиз),
    возврат вероятнее (A/B); OI вырос = настоящая загрузка, разворот опасен (C).
    """
    try:
        k = _get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}USDT&interval=5m&limit=30")
    except Exception:
        return None
    if len(k) < 25:
        return None
    closes = [float(x[4]) for x in k]
    highs = [float(x[2]) for x in k]
    lows = [float(x[3]) for x in k]
    vols = [float(x[5]) for x in k]
    base = sum(vols[-23:-3]) / 20
    vol_ratio = (sum(vols[-3:]) / 3) / base if base else 0.0
    rsi = _rsi(closes)
    if debug:
        print(f"[PUMP-TEST] {sym}: Δцена={d_px:+.2f}% vol_ratio=×{vol_ratio:.1f} "
              f"RSI={rsi and round(rsi, 1)} ΔOI5м={d_oi5}")
    if vol_ratio < PUMP_VOL_RATIO or rsi is None:
        return None
    up = d_px > 0
    if up and rsi < PUMP_RSI_HI:
        return None
    if not up and rsi > PUMP_RSI_LO:
        return None
    if up:                                    # памп → сетап на SHORT-разворот
        ext = max(highs[-3:])                 # хай пампа
        pre = min(lows[-10:-3])               # цена ДО пампа
        rng = ext - pre
        sl, tp1, tp2, tp3 = ext * 1.01, ext - rng * 0.5, ext - rng * 0.75, pre
        side = "SHORT-разворот"
    else:                                     # дамп → зеркально LONG-разворот
        ext = min(lows[-3:])
        pre = max(highs[-10:-3])
        rng = pre - ext
        sl, tp1, tp2, tp3 = ext * 0.99, ext + rng * 0.5, ext + rng * 0.75, pre
        side = "LONG-разворот"
    if rng <= 0:
        return None
    oi_fuel = d_oi5 is not None and d_oi5 <= 0.1
    grade = "A" if (oi_fuel and vol_ratio >= 5) else ("B" if oi_fuel else "C")
    oi_txt = (f"OI {d_oi5:+.2f}%/5м — {'СТОПЫ, не загрузка (возврат вероятен)' if oi_fuel else 'настоящая загрузка (разворот опасен!)'}"
              if d_oi5 is not None else "OI: нет данных")
    msg = (f"🚀 <b>PUMP: {sym} {d_px:+.1f}%</b> · Grade {grade}\n"
           f"объём ×{vol_ratio:.1f} · RSI {rsi:.0f} · {oi_txt}\n"
           f"━ {side} (SHADOW, уровни-ориентир):\n"
           f"Entry ~{_fmt(px)} · SL {_fmt(sl)} (за экстремум +1%)\n"
           f"TP1 {_fmt(tp1)} (50%) · TP2 {_fmt(tp2)} (75%) · TP3 {_fmt(tp3)} (до пампа)")
    row = {"ts": int(time.time()), "symbol": sym, "side": side.split("-")[0],
           "d_px": round(d_px, 2), "vol_ratio": round(vol_ratio, 2), "rsi": round(rsi, 1),
           "d_oi": d_oi5 if d_oi5 is None else round(d_oi5, 3), "grade": grade,
           "entry": px, "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3}
    return msg, row


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
            t5, oi5, px5 = w[-6]
            d_oi5 = (oi / oi5 - 1) * 100 if oi5 else 0
            if d_oi5 >= 0.5 and _cooldown_ok(f"fast_build:{sym}"):
                send_tg(f"📈 <b>OI BUILD LIVE: {sym}</b> +{d_oi5:.2f}%/5м — грузятся. цена {px}")
                alerts.append(f"build {sym}")
            # 🚀 PUMP-кандидат по цене → подтверждение объёмом/RSI (klines только для кандидатов)
            d_px5 = (px / px5 - 1) * 100 if px5 else 0
            d_px12 = (px / w[0][2] - 1) * 100 if (len(w) == 12 and w[0][2]) else 0
            d_px = d_px5 if abs(d_px5) >= PUMP_PCT_5M else (d_px12 if abs(d_px12) >= PUMP_PCT_12M else 0)
            if d_px:
                res = analyze_pump(sym, px, d_px, d_oi5)
                if res and _cooldown_ok(f"pump:{sym}", 3600):
                    msg, row = res
                    if send_tg(msg):
                        _log_pump(row)          # → pump_signals: WR-статистика для SHADOW→ARMED
                        alerts.append(f"PUMP {sym}")
        time.sleep(0.15)
    return alerts


if __name__ == "__main__":
    if "--test" in sys.argv:                  # разбор монеты без TG: метрики + текст алерта
        sym = sys.argv[sys.argv.index("--test") + 1].upper()
        k = _get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}USDT&interval=5m&limit=2")
        px = float(k[-1][4])
        d_px = (px / float(k[0][1]) - 1) * 100
        res = analyze_pump(sym, px, d_px if d_px else 0.01, None, debug=True)
        print(res[0] if res else "[PUMP-TEST] условия НЕ выполнены (объём/RSI/range) — алерта не было бы")
        sys.exit(0)
    print(f"[OI-FAST] радар: {len(CORE)} монет, цикл {INTERVAL}с, "
          f"сквиз=|Δp3м|≥0.6%+ΔOI≤−0.15% · PUMP=|Δp5м|≥{PUMP_PCT_5M}%+vol×{PUMP_VOL_RATIO}+RSI")
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
