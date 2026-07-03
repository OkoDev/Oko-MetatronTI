# -*- coding: utf-8 -*-
"""БЫСТРЫЙ OI-радар (60с цикл) — сквиз-алерт за 1-2 минуты, не 10 (Егор 03.07).

Источник: Binance /fapi/v1/openInterest (realtime, weight=1) + тикер цены.
Дельты в RAM-окне (30 точек = 30 мин). Условия:
  🌀 СКВИЗ:  |Δцена 3м| >= 0.6%  И  ΔOI 3м <= -0.15%   (движение закрытиями — GRT-механизм)
  📈 BUILD:  ΔOI 5м >= +0.5%                             (резкая загрузка)
  ⏳ ПРУЖИНА: ΔOI 15м >= +1% И range цены 15м < 0.7%    (скрытая загрузка ДО движения —
             MANA-читка 03.07 формулой; funding подсказывает направление выстрела)
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
from oko_feed.targets import build_targets, format_targets_block

# ~50 ликвидных: мейджоры + бэктест-вселенная atr_S2 + активные альты
CORE = ["BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "LINK", "AVAX", "DOT",
        "TRX", "LTC", "GRT", "ARB", "OP", "APT", "NEAR", "INJ", "FIL", "ATOM",
        "RUNE", "SEI", "SUI", "UNI", "AAVE", "ETC", "BCH", "ICP", "TIA", "WLD",
        "SAND", "MANA", "ALGO", "EGLD", "CHZ", "KAVA", "ZIL", "IOTA", "ENJ",
        "1000PEPE", "1000SHIB", "ORDI", "HBAR", "FET", "RENDER", "JUP", "PYTH",
        "STRK", "WIF", "1000BONK"]   # мемы = 1000-префикс на futures; TON делистнут → HBAR
INTERVAL = 60
WIN = collections.defaultdict(lambda: collections.deque(maxlen=30))   # sym -> [(ts, oi, price)]
_PRICES: dict[str, float] = {}
_FUND: dict[str, float] = {}   # sym -> lastFundingRate (batch premiumIndex раз в цикл)

# ── PUMP-DETECTOR v0.5 (SFERA-14, спека docs/PUMP-BOT-FULL-SPEC.md) ──
PUMP_PCT_5M = 2.5      # ценовой кандидат: |Δцена 5м| >= порога → тянем klines на подтверждение
PUMP_PCT_12M = 4.0     # или медленный памп за 12 мин
PUMP_VOL_RATIO = 3.0   # спека: объём последних баров ×3 к базе
PUMP_RSI_HI, PUMP_RSI_LO = 75, 25

# ── ПРУЖИНА (03.07, добро Егора): детект ЗА 30-60 мин ДО пампа, а не на вершине ──
SPRING_OI_15M = 1.0    # ΔOI 15м >= +1.0% — существенная скрытая загрузка
SPRING_RANGE_PCT = 0.7  # ВЕСЬ ценовой диапазон 15м < 0.7% — настоящий флэт (не болтанка)


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


def _c(v: float) -> str:
    """Цена копируемая одним тапом (моноширинный <code> в TG) — Егор 03.07."""
    return f"<code>{_fmt(v)}</code>"


def _links(sym: str) -> str:
    """Подвал ссылок (макет Егора 03.07): график TW + страница биржи BingX."""
    return (f'- <a href="https://ru.tradingview.com/chart/?symbol=BINGX%3A{sym}USDT.P'
            f'&interval=5">TW</a>\n'
            f'- <a href="https://bingx.com/ru/perpetual/{sym}-USDT">BINGX</a>')


def _sl_structure(sym: str, side: str) -> float | None:
    """SL за структуру последнего часа: экстремум 5m×12 + буфер 0.2% (reuse: BUILD и ПРУЖИНА)."""
    try:
        k = _get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}USDT&interval=5m&limit=13")
        return (min(float(x[3]) for x in k) * 0.998 if side == "LONG"
                else max(float(x[2]) for x in k) * 1.002)
    except Exception:
        return None


def _log_radar_order(sig_type: str, sym: str, side: str | None, entry: float,
                     sl: float | None, targets_json: str | None,
                     grade: str | None = None, tps: tuple | None = None) -> None:
    """Порт ARMED-фазы (docs/RADAR_ARMED_PLAN.md): полный сетап → radar_orders.

    Радар о боте НЕ знает: пишет status='NEW' и забывает. Бот (radar_armed_loop)
    подхватывает и меняет status: TAKEN / SKIPPED / STALE. Пишем только ПОЛНЫЕ
    сетапы: side+entry+sl согласованы и есть хотя бы одна цель в сторону сделки.
    tps: явные цели (PUMP tp1-3 по откатам); None → из targets_json (карта целей 2.0).
    """
    try:
        if side not in ("LONG", "SHORT") or not entry or not sl:
            return
        if (sl < entry) != (side == "LONG"):             # SL не с той стороны — сетап битый
            return
        try:
            t = json.loads(targets_json) if targets_json else []
        except Exception:
            t = []
        starred = 1 if any(c.get("star") for c in t) else 0
        if tps is None:
            # лестница TP1→TP3 = от entry в сторону движения (не полагаемся на порядок json)
            px_list = [c["px"] for c in t if c.get("px") and ((c["px"] > entry) == (side == "LONG"))]
            px_list.sort(reverse=(side == "SHORT"))
            tps = tuple((px_list + [None, None, None])[:3])
        tp1, tp2, tp3 = tps
        if not tp1 or (tp1 > entry) != (side == "LONG"):  # без цели в сторону сделки не армим
            return
        c = conn()
        try:
            c.execute("""CREATE TABLE IF NOT EXISTS radar_orders (
                ts INTEGER, symbol TEXT, sig_type TEXT, side TEXT,
                entry REAL, sl REAL, tp1 REAL, tp2 REAL, tp3 REAL,
                grade TEXT, starred INTEGER, targets_json TEXT,
                status TEXT DEFAULT 'NEW', taken_ts INTEGER, note TEXT,
                PRIMARY KEY (symbol, ts))""")
            c.execute("INSERT OR REPLACE INTO radar_orders "
                      "(ts, symbol, sig_type, side, entry, sl, tp1, tp2, tp3, "
                      "grade, starred, targets_json, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'NEW')",
                      (int(time.time()), sym, sig_type, side, entry, sl, tp1, tp2, tp3,
                       grade, starred, targets_json))
            c.commit()
        finally:
            c.close()
    except Exception as e:  # noqa: BLE001 — порт не должен ронять алерты
        print(f"[OI-FAST] radar_order err {sym}: {e}")


def _log_pump(row: dict) -> None:
    """Лог подтверждённого алерта → pump_signals (для WR-статистики SHADOW→ARMED)."""
    c = conn()
    try:
        c.execute("""CREATE TABLE IF NOT EXISTS pump_signals (
            ts INTEGER, symbol TEXT, side TEXT, d_px REAL, vol_ratio REAL, rsi REAL,
            d_oi REAL, grade TEXT, entry REAL, sl REAL, tp1 REAL, tp2 REAL, tp3 REAL,
            targets_json TEXT, PRIMARY KEY (symbol, ts))""")
        try:                                             # миграция ранних строк без колонки
            c.execute("ALTER TABLE pump_signals ADD COLUMN targets_json TEXT")
        except Exception:
            pass
        c.execute("INSERT OR REPLACE INTO pump_signals VALUES "
                  "(:ts,:symbol,:side,:d_px,:vol_ratio,:rsi,:d_oi,:grade,"
                  ":entry,:sl,:tp1,:tp2,:tp3,:targets_json)", row)
        c.commit()
    finally:
        c.close()


def _with_targets(msg: str, row: dict, sym: str, side: str, px: float) -> tuple[str, dict]:
    """Карта целей 2.0: блок «🧲 цели» перед хештег-строкой + targets_json в лог."""
    try:
        targets = build_targets(sym, side, px)
    except Exception:
        targets = []
    row["targets_json"] = json.dumps(targets) if targets else None
    block = format_targets_block(targets, px)
    if block:
        marker = "\n\n- <a href"                         # перед подвалом ссылок (макет)
        i = msg.find(marker)
        if i != -1:
            msg = f"{msg[:i]}\n\n{block}{msg[i:]}"
        else:
            body, tags_line = msg.rsplit("\n", 1)
            msg = f"{body}\n{block}\n{tags_line}"
    return msg, row


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
        head = "🔻 сетап: <b>SHORT</b> (разворот пампа ВНИЗ)"
    else:                                     # дамп → зеркально LONG-разворот
        ext = min(lows[-3:])
        pre = max(highs[-10:-3])
        rng = pre - ext
        sl, tp1, tp2, tp3 = ext * 0.99, ext + rng * 0.5, ext + rng * 0.75, pre
        head = "🔺 сетап: <b>LONG</b> (разворот дампа ВВЕРХ)"
    if rng <= 0:
        return None
    oi_fuel = d_oi5 is not None and d_oi5 <= 0.1
    grade = "A" if (oi_fuel and vol_ratio >= 5) else ("B" if oi_fuel else "C")
    oi_txt = (f"OI {d_oi5:+.2f}%/5м — {'СТОПЫ, не загрузка → возврат вероятен' if oi_fuel else 'НАСТОЯЩАЯ загрузка → не спешить, ждать выдоха!'}"
              if d_oi5 is not None else "OI: нет данных")
    grade_txt = {"A": "A (вход надёжнее)", "B": "B", "C": "C (⚠️ против свежего потока)"}[grade]
    dot = "🔴" if up else "🟢"                            # сетап-разворот: памп → SHORT
    msg = (f"🚀 <b>PUMP:</b>\n\n"
           f"{dot} <code>{sym}</code> {d_px:+.1f}%\n"
           f"{head}\n"
           f"Grade {grade_txt} · объём ×{vol_ratio:.1f} · RSI {rsi:.0f}\n"
           f"{oi_txt}\n\n"
           f"Вход: ~{_c(px)}\n"
           f"Стоп: {_c(sl)} (за экстремум +1%)\n"
           f"TP1 {_c(tp1)} (50%) · TP2 {_c(tp2)} (75%) · TP3 {_c(tp3)} (до пампа)\n\n"
           f"{_links(sym)}\n\n"
           f"#{sym} #PUMP")
    row = {"ts": int(time.time()), "symbol": sym, "side": "SHORT" if up else "LONG",
           "d_px": round(d_px, 2), "vol_ratio": round(vol_ratio, 2), "rsi": round(rsi, 1),
           "d_oi": d_oi5 if d_oi5 is None else round(d_oi5, 3), "grade": grade,
           "entry": px, "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3}
    return msg, row


def check_spring(w, sym: str, px: float, fund: float | None) -> tuple[str, dict] | None:
    """⏳ ПРУЖИНА: OI грузится 15 мин, цена стоит в узком рейндже = скрытая загрузка ДО движения.

    Направление выстрела — эвристика по funding: платящая сторона = кто грузится
    (fund<0 → шорты платят → топливо для сквиза ВВЕРХ; заметно >базовой 0.01% → лонги → ВНИЗ).
    """
    if len(w) < 16 or not px:
        return None
    oi15 = w[-16][1]
    d_oi15 = (w[-1][1] / oi15 - 1) * 100 if oi15 else 0
    if d_oi15 < SPRING_OI_15M:
        return None
    prices = [p for _, _, p in list(w)[-16:]]
    rng_pct = (max(prices) - min(prices)) / px * 100
    if rng_pct >= SPRING_RANGE_PCT:
        return None
    if fund is None:
        dir_side, dir_txt = "?", "funding: нет данных — направление неясно"
    elif fund < 0:
        dir_side = "UP"
        dir_txt = f"🔺 funding {fund * 100:.4f}% → грузятся ШОРТЫ → топливо ВВЕРХ (вероятно)"
    elif fund >= 0.0002:                       # заметно выше базовой ставки 0.01%
        dir_side = "DOWN"
        dir_txt = f"🔻 funding {fund * 100:.4f}% → грузятся ЛОНГИ → топливо ВНИЗ (вероятно)"
    else:
        dir_side, dir_txt = "?", f"funding {fund * 100:.4f}% нейтрален — направление неясно"
    dot = {"UP": "🟢", "DOWN": "🔴"}.get(dir_side, "⚪")
    msg = (f"⏳ <b>ПРУЖИНА:</b>\n\n"
           f"{dot} <code>{sym}</code> OI {d_oi15:+.2f}%/15м · цена флэт (range {rng_pct:.2f}%)\n"
           f"{dir_txt}\n"
           f"цена {_c(px)}\n\n"
           f"{_links(sym)}\n\n"
           f"#{sym} #SPRING")
    row = {"ts": int(time.time()), "symbol": sym, "d_oi15": round(d_oi15, 3),
           "range_pct": round(rng_pct, 3), "funding": fund, "dir": dir_side, "px": px}
    return msg, row


def _log_spring(row: dict) -> None:
    """Лог пружин → spring_signals (оценить «заранее» количественно: пружина → был ли памп?)."""
    c = conn()
    try:
        c.execute("""CREATE TABLE IF NOT EXISTS spring_signals (
            ts INTEGER, symbol TEXT, d_oi15 REAL, range_pct REAL, funding REAL,
            dir TEXT, px REAL, targets_json TEXT, PRIMARY KEY (symbol, ts))""")
        try:
            c.execute("ALTER TABLE spring_signals ADD COLUMN targets_json TEXT")
        except Exception:
            pass
        c.execute("INSERT OR REPLACE INTO spring_signals VALUES "
                  "(:ts,:symbol,:d_oi15,:range_pct,:funding,:dir,:px,:targets_json)", row)
        c.commit()
    finally:
        c.close()


def analyze_build(sym: str, px: float, d_oi5: float, fund: float | None) -> tuple[str, dict | None]:
    """📈 BUILD → полный сетап в сообщении (Егор 03.07: «нужно быстро реагировать» —
    вход-стоп-тейк сразу, без переспрашивания).

    Направление по funding (пороги = check_spring): fund<0 → грузятся шорты → сетап LONG
    (сквиз вверх); fund>=+0.02% → лонги → SHORT. Нейтрален → голый BUILD без сетапа.
    SL — за структуру последнего часа (экстремум 5m×12), цели — карта целей 2.0.
    """
    side = dir_txt = None
    if fund is not None and fund < 0:
        side = "LONG"
        dir_txt = f"🔺 funding {fund * 100:.3f}% → грузятся ШОРТЫ"
    elif fund is not None and fund >= 0.0002:
        side = "SHORT"
        dir_txt = f"🔻 funding {fund * 100:.3f}% → грузятся ЛОНГИ"
    # шапка (макет Егора 03.07): тип отдельно, тикер копируемый + цвет направления
    dot = {"LONG": "🟢", "SHORT": "🔴"}.get(side, "⚪")
    head = f"📈 <b>OI BUILD LIVE:</b>\n\n{dot} <code>{sym}</code> +{d_oi5:.2f}%/5м"
    if side is None:                                     # funding нейтрален — сетап не строим,
        fund_txt = (f"funding {fund * 100:.4f}% — нейтрален\nсетапа нет 🔄"
                    if fund is not None else "funding: нет данных\nсетапа нет 🔄")
        bias_txt = ""                                    # но перекос топлива показать можем
        try:
            from scripts.liq_magnets import build_magnets, fmt_usd
            m = build_magnets(sym)
            if m:
                bias = ("⬆ ВВЕРХ" if m["tot_above"] > m["tot_below"] * 1.3 else
                        "⬇ ВНИЗ" if m["tot_below"] > m["tot_above"] * 1.3 else "≈ баланс")
                bias_txt = (f"\nтопливо: сверху {fmt_usd(m['tot_above'])} / "
                            f"снизу {fmt_usd(m['tot_below'])} → магнит {bias}")
        except Exception:
            pass
        return (f"{head}\nцена {_c(px)}\n{fund_txt}{bias_txt}\n\n{_links(sym)}\n\n"
                f"#{sym} #OI_BUILD"), None
    sl = _sl_structure(sym, side)                        # SL за структуру часа
    try:
        targets = build_targets(sym, side, px)
    except Exception:
        targets = []
    lines = [head, dir_txt, ""]
    risk_pct = None
    if sl:
        risk_pct = abs(px - sl) / px * 100
        lines.append(f"Вход: ~{_c(px)}")
        lines.append(f"Стоп: {_c(sl)} (за структуру часа, риск {risk_pct:.1f}%)")
    if targets:
        far = max(targets, key=lambda t: abs(t["px"] - px))
        if risk_pct:
            rr = abs(far["px"] - px) / px * 100 / risk_pct
            lines.append(f"R:R ~{rr:.1f} · у магнита ФИКСИРУЮТ, не входят")
        lines.append("")
        lines.append(format_targets_block(targets, px))
    lines.append("")
    lines.append(_links(sym))
    lines.append("")
    lines.append(f"#{sym} #OI_BUILD")
    row = {"ts": int(time.time()), "symbol": sym, "d_oi5": round(d_oi5, 3),
           "funding": fund, "side": side, "px": px, "sl": sl,
           "targets_json": json.dumps(targets) if targets else None}
    return "\n".join(lines), row


def _log_build(row: dict) -> None:
    """Лог BUILD-сетапов → build_signals (Егор рисует сетап → смотрим отработку форвардом)."""
    c = conn()
    try:
        c.execute("""CREATE TABLE IF NOT EXISTS build_signals (
            ts INTEGER, symbol TEXT, d_oi5 REAL, funding REAL, side TEXT,
            px REAL, sl REAL, targets_json TEXT, PRIMARY KEY (symbol, ts))""")
        c.execute("INSERT OR REPLACE INTO build_signals VALUES "
                  "(:ts,:symbol,:d_oi5,:funding,:side,:px,:sl,:targets_json)", row)
        c.commit()
    finally:
        c.close()


def _refresh_prices():
    """ВСЕ цены одним batch-запросом (weight=2) — вместо 50 отдельных."""
    global _PRICES
    try:
        arr = _get("https://fapi.binance.com/fapi/v1/ticker/price")
        _PRICES = {x["symbol"]: float(x["price"]) for x in arr}
    except Exception:
        pass


def _refresh_funding():
    """ВСЕ funding-ставки одним batch premiumIndex (weight=10, раз в 60с цикл — дёшево)."""
    global _FUND
    try:
        arr = _get("https://fapi.binance.com/fapi/v1/premiumIndex")
        _FUND = {x["symbol"]: float(x["lastFundingRate"]) for x in arr if "lastFundingRate" in x}
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


def _log_liq_synth(sym: str, side: str, usd: float, px: float) -> None:
    """Синтетические ликвидации из OI-унвинда → liq_events (source='oi_synth').

    fstream WS с этой машины молчит (03.07, см. liq_ws.py) — оцениваем сгоревшее по
    падению OI на сквизе: usd = |ΔOI монет| × цена. Для сверки с magnet_snapshots
    (зона+время+масштаб) точности достаточно.
    """
    c = conn()
    try:
        c.execute("""CREATE TABLE IF NOT EXISTS liq_events (
            ts INTEGER, symbol TEXT, side TEXT, usd REAL, px REAL, source TEXT)""")
        try:
            c.execute("ALTER TABLE liq_events ADD COLUMN source TEXT")
        except Exception:
            pass
        c.execute("INSERT INTO liq_events VALUES (?,?,?,?,?,'oi_synth')",
                  (int(time.time()), sym, side, round(usd, 2), px))
        c.commit()
    finally:
        c.close()


def _flush_radar_state(rows: list[tuple]) -> None:
    """Live-контекст радара → radar_state (порт для Куба: features_json-мост, Егор 03.07).

    Бот при регистрации сделки читает отсюда oi_delta/funding — RAM радара ему недоступен.
    """
    if not rows:
        return
    c = conn()
    try:
        c.execute("""CREATE TABLE IF NOT EXISTS radar_state (
            symbol TEXT PRIMARY KEY, ts INTEGER, px REAL,
            oi_d5 REAL, oi_d15 REAL, funding REAL)""")
        c.executemany("INSERT OR REPLACE INTO radar_state VALUES (?,?,?,?,?,?)", rows)
        c.commit()
    finally:
        c.close()


def tick():
    alerts = []
    state_rows = []
    _refresh_prices()
    _refresh_funding()
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
            if abs(d_px3) >= 0.6 and d_oi3 <= -0.15:
                # факт для копилки (сверка с магнитами) — каждый тик сквиза, без cooldown
                try:
                    _log_liq_synth(sym, "BUY" if d_px3 > 0 else "SELL", (oi3 - oi) * px, px)
                except Exception:
                    pass
            if abs(d_px3) >= 0.6 and d_oi3 <= -0.15 and _cooldown_ok(f"fast_squeeze:{sym}"):
                side = "вверх (шорты горят)" if d_px3 > 0 else "вниз (лонги горят)"
                _dot = "🟢" if d_px3 > 0 else "🔴"
                send_tg(f"🌀 <b>СКВИЗ LIVE:</b>\n\n"
                        f"{_dot} <code>{sym}</code> Δцена {d_px3:+.2f}%/3м {side}\n"
                        f"OI {d_oi3:+.2f}%/3м — движение ЗАКРЫТИЯМИ\nцена {_c(px)}\n\n"
                        f"{_links(sym)}\n\n"
                        f"#{sym} #SQUEEZE")
                alerts.append(f"squeeze {sym}")
        if len(w) >= 6:
            t5, oi5, px5 = w[-6]
            d_oi5 = (oi / oi5 - 1) * 100 if oi5 else 0
            if d_oi5 >= 0.5 and _cooldown_ok(f"fast_build:{sym}"):
                b_msg, b_row = analyze_build(sym, px, d_oi5, _FUND.get(f"{sym}USDT"))
                if send_tg(b_msg):
                    if b_row:
                        _log_build(b_row)
                        # ARMED-порт: BUILD-с-сетапом → radar_orders (цели из карты 2.0)
                        _log_radar_order("build", sym, b_row["side"], px,
                                         b_row["sl"], b_row["targets_json"])
                    alerts.append(f"build {sym}")
            # ⏳ ПРУЖИНА: скрытая загрузка ДО движения (окно 16 точек = 15 мин)
            res_sp = check_spring(w, sym, px, _FUND.get(f"{sym}USDT"))
            if res_sp and _cooldown_ok(f"spring:{sym}", 3600):
                sp_msg, sp_row = res_sp
                # цели в сторону выстрела (dir UP → цели СВЕРХУ = LONG-сторона)
                sp_side = {"UP": "LONG", "DOWN": "SHORT"}.get(sp_row["dir"])
                if sp_side:
                    sp_msg, sp_row = _with_targets(sp_msg, sp_row, sym, sp_side, px)
                else:
                    sp_row["targets_json"] = None
                if send_tg(sp_msg):
                    _log_spring(sp_row)
                    if sp_side:
                        # ARMED-порт: ПРУЖИНА с направлением → сетап (SL за структуру, цели 2.0)
                        _log_radar_order("spring", sym, sp_side, px,
                                         _sl_structure(sym, sp_side), sp_row["targets_json"])
                    alerts.append(f"SPRING {sym}")
            # 🚀 PUMP-кандидат по цене → подтверждение объёмом/RSI (klines только для кандидатов)
            d_px5 = (px / px5 - 1) * 100 if px5 else 0
            d_px12 = (px / w[-12][2] - 1) * 100 if (len(w) >= 12 and w[-12][2]) else 0
            d_px = d_px5 if abs(d_px5) >= PUMP_PCT_5M else (d_px12 if abs(d_px12) >= PUMP_PCT_12M else 0)
            if d_px:
                res = analyze_pump(sym, px, d_px, d_oi5)
                if res and _cooldown_ok(f"pump:{sym}", 3600):
                    msg, row = res
                    msg, row = _with_targets(msg, row, sym, row["side"], px)
                    if send_tg(msg):
                        _log_pump(row)          # → pump_signals: WR-статистика для SHADOW→ARMED
                        # ARMED-порт: PUMP-разворот → radar_orders (tp1-3 по откатам, grade)
                        _log_radar_order("pump", sym, row["side"], px, row["sl"],
                                         row.get("targets_json"), grade=row["grade"],
                                         tps=(row["tp1"], row["tp2"], row["tp3"]))
                        alerts.append(f"PUMP {sym}")
        # live-контекст → radar_state (мост в Куб)
        d5 = (oi / w[-6][1] - 1) * 100 if (len(w) >= 6 and w[-6][1]) else None
        d15 = (oi / w[-16][1] - 1) * 100 if (len(w) >= 16 and w[-16][1]) else None
        state_rows.append((sym, int(time.time()), px, d5, d15, _FUND.get(f"{sym}USDT")))
        time.sleep(0.15)
    _flush_radar_state(state_rows)
    return alerts


if __name__ == "__main__":
    if "--test" in sys.argv:                  # разбор монеты без TG: метрики + текст алерта
        sym = sys.argv[sys.argv.index("--test") + 1].upper()
        k = _get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}USDT&interval=5m&limit=2")
        px = float(k[-1][4])
        d_px = (px / float(k[0][1]) - 1) * 100
        res = analyze_pump(sym, px, d_px if d_px else 0.01, None, debug=True)
        if res:
            msg, row = _with_targets(res[0], res[1], sym, res[1]["side"], px)
            print(msg)
        else:
            print("[PUMP-TEST] условия НЕ выполнены (объём/RSI/range) — алерта не было бы")
            print("[PUMP-TEST] карта целей (как для SHORT):")
            print(format_targets_block(build_targets(sym, "SHORT", px), px) or "  целей не найдено")
        sys.exit(0)
    print(f"[OI-FAST] радар: {len(CORE)} монет, цикл {INTERVAL}с, "
          f"сквиз=|Δp3м|≥0.6%+ΔOI≤−0.15% · PUMP=|Δp5м|≥{PUMP_PCT_5M}%+vol×{PUMP_VOL_RATIO}+RSI · "
          f"ПРУЖИНА=ΔOI15м≥{SPRING_OI_15M}%+range<{SPRING_RANGE_PCT}%+funding-направление")
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
