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

# ── HOT-LIST (11.07, Егор: «XPIN смотрели?!» — нет: CORE-50 слеп к хвосту, XPIN +47%
# прошёл мимо PUMP-детектора). Раз в 5 мин batch ticker/24hr (1 запрос ~700 пар) →
# топ-N горячих (|Δ24ч| ≥ 10%, объём ≥ $5M) добавляются в OI-поллинг на 24ч.
# CORE не меняется (стабильная вселенная atr_S2); хот-лист расширяет PUMP/SPRING/DUMP.
HOT_MAX = 15
HOT_MIN_VOL = 5e6
HOT_MIN_CHG = 10.0
HOT_TTL = 24 * 3600
_HOT: dict[str, float] = {}          # base -> последний раз видел горячим (ts)
_HOT_LAST = [0.0]


def _refresh_hot():
    if time.time() - _HOT_LAST[0] < 300:
        return
    _HOT_LAST[0] = time.time()
    try:
        arr = _get("https://fapi.binance.com/fapi/v1/ticker/24hr")
        cands = []
        for t in arr:
            s = str(t.get("symbol", ""))
            if not s.endswith("USDT"):
                continue
            base = s[:-4]
            if base in CORE:
                continue
            try:
                chg, qv = float(t["priceChangePercent"]), float(t["quoteVolume"])
            except (KeyError, TypeError, ValueError):
                continue
            if qv >= HOT_MIN_VOL and abs(chg) >= HOT_MIN_CHG:
                cands.append((abs(chg), base))
        now = time.time()
        fresh = []
        for _, base in sorted(cands, reverse=True)[:HOT_MAX]:
            if base not in _HOT:
                fresh.append(base)
            _HOT[base] = now
        for base, ts in list(_HOT.items()):
            if now - ts > HOT_TTL:
                _HOT.pop(base, None)
                WIN.pop(base, None)
        if fresh:
            print(f"[HOT] +{','.join(fresh)} → радар (движение дня); всего hot={len(_HOT)}")
    except Exception as e:
        print(f"[HOT] refresh err: {e}")
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


def _struct_dir(sym: str) -> tuple[str | None, str]:
    """СТРУКТУРНОЕ направление для BUILD (12.07, Егор: «build вообще знает про волны и где
    он относительно структуры?!» — не знал: направление было ИНВЕРСИЕЙ funding → WR 19%).

    Руль = структура 1h: последний слом (BOS/CHoCH, length=5 канон OKO-SM [[calib_choch_length5]]).
    CHoCH приоритетнее BOS (свежий разворот > продолжение). Fallback: EMA-тренд (_htf_trend).
    → (side, описание) · (None, '') если структура нема (RANGE без сломов) — сетап не строим.
    OI-build = ТОПЛИВО (кто-то грузится); структура говорит КУДА. Funding = инфо о толпе."""
    try:
        k = _get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}USDT&interval=1h&limit=120")
        if len(k) < 60:
            return None, ""
        import pandas as pd
        df = pd.DataFrame({"time": [int(x[0]) for x in k],
                           "open": [float(x[1]) for x in k], "high": [float(x[2]) for x in k],
                           "low": [float(x[3]) for x in k], "close": [float(x[4]) for x in k]})
        from core.smc.smc_engine import detect_structure_breaks
        brks = detect_structure_breaks(df, length=5)
        if brks:
            b = brks[-1]
            side = "LONG" if b.direction == "bull" else "SHORT"
            return side, f"структура 1h: {b.kind} {'↑' if side == 'LONG' else '↓'}"
    except Exception as e:
        print(f"[BUILD] struct_dir {sym}: {e}")
    t = _htf_trend(sym)                                  # fallback: EMA-тренд
    if t == "UP":
        return "LONG", "структура 1h: тренд EMA ↑"
    if t == "DOWN":
        return "SHORT", "структура 1h: тренд EMA ↓"
    return None, ""


def _htf_trend(sym: str, interval: str = "1h") -> str | None:
    """Лёгкий прокси старшего тренда (05.07, гейт BUILD «лонг на пике падения», CHZ/ORDI):
    EMA21 на interval×50. UP = цена > EMA и EMA растёт; DOWN = цена < EMA и EMA падает;
    иначе FLAT. Дублирует смысл atr_trend_1h_bias бота (DEV-169), но без pandas/ATR —
    радар stateless. Ошибка/недостаток данных → None (fail-open: гейт не блокирует)."""
    try:
        k = _get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}USDT&interval={interval}&limit=50")
    except Exception:
        return None
    closes = [float(x[4]) for x in k]
    if len(closes) < 25:
        return None
    ema = closes[0]
    a = 2 / (21 + 1)
    prev = ema
    for c in closes[1:]:
        prev, ema = ema, c * a + ema * (1 - a)
    if closes[-1] > ema and ema > prev:
        return "UP"
    if closes[-1] < ema and ema < prev:
        return "DOWN"
    return "FLAT"


def _recent_signals(sym: str, hours: float = 6.0) -> list[dict]:
    """⛓ ЦЕПОЧКИ (04.07, Егор «радар должен знать, что был сигнал ДО»): последние сигналы
    символа из копилок БД. Детекторы stateless — память подключаем ЧТЕНИЕМ уже пишущихся
    логов. Читается лениво (только при сформированном алерте). Свежие первыми."""
    since = int(time.time()) - int(hours * 3600)
    out = []
    c = conn()
    try:
        for tbl, typ, side_col in (("build_signals", "BUILD", "side"),
                                   ("spring_signals", "ПРУЖИНА", "dir"),
                                   ("pump_signals", "PUMP", "side")):
            try:
                for ts, sd in c.execute(
                        f"SELECT ts, {side_col} FROM {tbl} WHERE symbol=? AND ts>?",
                        (sym, since)).fetchall():
                    out.append({"ts": ts, "type": typ, "side": sd})
            except Exception:
                pass                                     # таблицы может ещё не быть
    finally:
        c.close()
    out.sort(key=lambda x: -x["ts"])
    return out[:5]


def _fmt_chain(chain: list[dict]) -> str:
    """Строка «⛓ до этого: …» для алерта. Пусто если истории нет."""
    if not chain:
        return ""
    now = time.time()
    parts = []
    for s in chain:
        age_m = (now - s["ts"]) / 60
        age = f"{age_m:.0f}м" if age_m < 100 else f"{age_m / 60:.1f}ч"
        sd = {"UP": "↑", "DOWN": "↓", "LONG": "↑", "SHORT": "↓"}.get(str(s["side"] or "?"), "?")
        parts.append(f"{s['type']}{sd} {age} назад")
    return "⛓ до этого: " + " · ".join(parts)


def _with_orderbook(msg: str, sym: str, px: float) -> str:
    """Вставить «📖 стакан» перед подвалом ссылок (маркер как у _with_chain/_with_targets)."""
    try:
        line = _orderbook_line(sym, px)
    except Exception:
        line = ""
    if not line:
        return msg
    marker = "\n\n- <a href"
    i = msg.find(marker)
    return f"{msg[:i]}\n\n{line}{msg[i:]}" if i != -1 else f"{msg}\n{line}"


def _with_chain(msg: str, chain: list[dict]) -> str:
    """Вставить блок цепочки перед подвалом ссылок (тот же маркер, что _with_targets)."""
    block = _fmt_chain(chain)
    if not block:
        return msg
    marker = "\n\n- <a href"
    i = msg.find(marker)
    if i != -1:
        return f"{msg[:i]}\n\n{block}{msg[i:]}"
    return f"{msg}\n{block}"


def _chain_same_dir(chain: list[dict], pump_up: bool, hours: float = 3.0) -> dict | None:
    """Цикл «загрузка→выстрел»: ПРУЖИНА/BUILD за N часов В СТОРОНУ пампа.
    GRT-урок 04.07 02:08→02:30: пружина за 22м до пампа = загрузка началась ЗАРАНЕЕ,
    5м-окно ΔOI её не видит → разворот шортить РАНО (грейд разворота честно ↓C)."""
    want = ("UP", "LONG") if pump_up else ("DOWN", "SHORT")
    since = time.time() - hours * 3600
    for s in chain:
        if s["ts"] >= since and s["type"] in ("ПРУЖИНА", "BUILD") and str(s["side"]) in want:
            return s
    return None


def _zigzag(highs: list[float], lows: list[float], dev_pct: float):
    """%-zigzag на чистом питоне (радар без pandas). Возврат: (пивоты [(i, px, 'H'|'L')], trend)."""
    piv = []
    trend = 0
    hi, hi_i = highs[0], 0
    lo, lo_i = lows[0], 0
    for i in range(1, len(highs)):
        h, l = highs[i], lows[i]
        if trend == 0:
            if h > hi:
                hi, hi_i = h, i
            if l < lo:
                lo, lo_i = l, i
            if h >= lo * (1 + dev_pct / 100):
                piv.append((lo_i, lo, "L")); trend = 1; hi, hi_i = h, i
            elif l <= hi * (1 - dev_pct / 100):
                piv.append((hi_i, hi, "H")); trend = -1; lo, lo_i = l, i
        elif trend == 1:
            if h > hi:
                hi, hi_i = h, i
            if l <= hi * (1 - dev_pct / 100):
                piv.append((hi_i, hi, "H")); trend = -1; lo, lo_i = l, i
        else:
            if l < lo:
                lo, lo_i = l, i
            if h >= lo * (1 + dev_pct / 100):
                piv.append((lo_i, lo, "L")); trend = 1; hi, hi_i = h, i
    return piv, trend


def _wave_leg(sym: str, up: bool) -> dict | None:
    """〰 SHADOW волновой счёт (04.07, рамка Егора «5 волн в импульс, 3 в коррекцию»):
    какая по счёту импульсная нога в направлении пампа идёт от базы (15m, 24ч).

    n направленных свингов от базы → волна ≈ 2n−1 (1-я/3-я/5-я). База = конец цепочки
    higher lows (для пампа) / lower highs (для дампа). dev адаптивный (2.5× средний |ret|
    бара, кламп 1-3%). Grade НЕ трогаем — копим форвард (WR разворота по ногам решит,
    станет ли правилом: разворот после 5-й зрел, после 1/3-й ранний). Радар = real-time,
    look-ahead невозможен by design (урок wave_phase_filter: бэктест-счёт волн врёт)."""
    try:
        k = _get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}USDT&interval=15m&limit=96")
    except Exception:
        return None
    if len(k) < 30:
        return None
    highs = [float(x[2]) for x in k]
    lows = [float(x[3]) for x in k]
    closes = [float(x[4]) for x in k]
    rets = [abs(closes[i] / closes[i - 1] - 1) * 100 for i in range(1, len(closes)) if closes[i - 1]]
    dev = min(3.0, max(1.0, 2.5 * sum(rets) / len(rets))) if rets else 1.5
    piv, trend = _zigzag(highs, lows, dev)
    if not piv:
        return None
    base_kind, leg_kind = ("L", "H") if up else ("H", "L")
    base_i = base_px = None
    last_px = None
    for idx, px, kind in reversed(piv):                  # назад, пока цепочка HL (up) / LH (down)
        if kind != base_kind:
            continue
        if last_px is None or ((px < last_px) if up else (px > last_px)):
            base_i, base_px, last_px = idx, px, px
        else:
            break
    if base_i is None:
        return None
    n_dir = sum(1 for idx, _px, kind in piv if kind == leg_kind and idx > base_i)
    if (trend == 1) == up:
        n_dir += 1                                       # текущая незавершённая нога — наша
    if n_dir <= 0:
        return None
    return {"leg": 2 * n_dir - 1, "n_swings": n_dir, "dev": round(dev, 2), "base": base_px}


def _send_chart(sym: str, msg_id, tf: str = "1h") -> None:
    """SMC-чарт reply'ем к алерту (11.07 Егор: «сюда чарты подтянем + BOS/CHoCH не хватает»).
    Reuse build_signal_chart(wave_overlay=True): свечи+пивоты+объём+WT+ZigZag+OB+FVG+BOS/CHoCH.
    bot=None → standalone fetch (ccxt bingx→binance). ~2-4с на алерт — редкость, тик переживёт."""
    if not msg_id:
        return
    try:
        import asyncio as _aio
        from core.ui.chart_builder import build_signal_chart
        png = _aio.run(build_signal_chart(f"{sym}/USDT:USDT", tf=tf, bot=None,
                                          wave_overlay=True))
        if png:
            from oko_feed.alerts import send_tg_photo
            send_tg_photo(png, caption=f"<code>{sym}</code> {tf} · SMC-разметка",
                          channel="action", reply_to=msg_id)
    except Exception as e:
        print(f"[CHART] {sym}: {e}")


_BINGX_PERPS: set[str] = set()
_BINGX_TS = [0.0]


def _on_bingx(base: str) -> bool:
    """Есть ли перп на BingX (торгуемость сетапа). Кэш 24ч, 1 batch-запрос.
    При недоступности API — fail-open (True): лучше лишний сетап, чем слепота."""
    now = time.time()
    if now - _BINGX_TS[0] > 24 * 3600:
        try:
            d = _get("https://open-api.bingx.com/openApi/swap/v2/quote/ticker")
            perps = {str(t.get("symbol", "")).replace("-USDT", "")
                     for t in (d.get("data") or [])}
            if perps:
                _BINGX_PERPS.clear()
                _BINGX_PERPS.update(perps)
                _BINGX_TS[0] = now
                print(f"[RADAR] BingX-перпы обновлены: {len(perps)}")
        except Exception as e:
            print(f"[RADAR] BingX perps refresh err: {e}")
            _BINGX_TS[0] = now - 23 * 3600               # ретрай через час
    return (base in _BINGX_PERPS) if _BINGX_PERPS else True


def _build_phase_feats(sym: str) -> dict:
    """ФАЗА серии (12.07, VANRY-разбор Егора): не «сколько BUILD», а «есть ли прогресс цены
    на единицу BUILD». chain_n = BUILD за 6ч; hh_progress: max(high) последних 4×15m-баров
    против пика окна 32 бара — 1=новые хаи (тренд жив), 0=BUILD'ы в стену (поглощение)."""
    out: dict = {}
    try:
        n = conn().execute("SELECT COUNT(*) FROM build_signals WHERE symbol=? AND ts>?",
                           (sym, int(time.time()) - 6 * 3600)).fetchone()[0]
        out["build_chain_n"] = int(n)
    except Exception:
        pass
    try:
        k = _get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}USDT&interval=15m&limit=32")
        highs = [float(x[2]) for x in k]
        if len(highs) >= 12:
            peak, recent = max(highs[:-4]), max(highs[-4:])
            out["ltf_hh_progress"] = int(recent >= peak * 0.999)
            out["ltf_peak_dist_pct"] = round((recent / peak - 1) * 100, 2)
    except Exception:
        pass
    return out


def _log_radar_order(sig_type: str, sym: str, side: str | None, entry: float,
                     sl: float | None, targets_json: str | None,
                     grade: str | None = None, tps: tuple | None = None,
                     chain: list[dict] | None = None,
                     wave_leg: int | None = None,
                     tg_msg_id: int | None = None) -> None:
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
        # BINGX-ФИЛЬТР (11.07, Егор: «ZIL на BingX нет)))» — радар живёт на Binance-данных,
        # но торгуем BingX: делистнутые (ZIL) и Binance-only из HOT-LIST не армим.
        if not _on_bingx(sym):
            try:
                send_tg(f"⚠️ <code>{sym}</code> нет на BingX — сетап наблюдательный, не армится",
                        channel="action", reply_to=tg_msg_id)
            except Exception:
                pass
            print(f"[RADAR] {sym} {sig_type}: NO_BINGX — ордер не пишем")
            return
        try:
            t = json.loads(targets_json) if targets_json else []
        except Exception:
            t = []
        starred = 1 if any(c.get("star") for c in t) else 0
        if tps is None:
            # лестница TP1→TP3 = от entry в сторону движения (не полагаемся на порядок json).
            # RR-гейт (07.07, gap пружины): цель ближе 1×риска — не цель (HBAR tp1 +0.23% при
            # SL 0.65% = RR1 0.35; исполнение душится до микро-целей). Отбросили — следующая
            # цель карты становится TP1; не осталось ни одной дальше риска → сетап не армится.
            risk = abs(entry - sl)
            px_list = [c["px"] for c in t if c.get("px")
                       and ((c["px"] > entry) == (side == "LONG"))
                       and abs(c["px"] - entry) >= risk]
            px_list.sort(reverse=(side == "SHORT"))
            tps = tuple((px_list + [None, None, None])[:3])
        tp1, tp2, tp3 = tps
        if not tp1 or (tp1 > entry) != (side == "LONG"):  # без цели в сторону сделки не армим
            return
        # ФАЗА-ФИЧИ (12.07, разбор VANRY с Егором: «серия BUILD без новых HH = поглощение»):
        # build_chain_n = серия BUILD за 6ч · ltf_hh_progress = делает ли 15m новые хаи
        # после пика окна (1=тренд жив, 0=BUILD'ы в стену). Прозрачно, НЕ гейт.
        phase = _build_phase_feats(sym)
        c = conn()
        try:
            c.execute("""CREATE TABLE IF NOT EXISTS radar_orders (
                ts INTEGER, symbol TEXT, sig_type TEXT, side TEXT,
                entry REAL, sl REAL, tp1 REAL, tp2 REAL, tp3 REAL,
                grade TEXT, starred INTEGER, targets_json TEXT,
                status TEXT DEFAULT 'NEW', taken_ts INTEGER, note TEXT,
                PRIMARY KEY (symbol, ts))""")
            for _mig in ("ALTER TABLE radar_orders ADD COLUMN chain TEXT",
                         "ALTER TABLE radar_orders ADD COLUMN wave_leg INTEGER",
                         "ALTER TABLE radar_orders ADD COLUMN tg_msg_id INTEGER",
                         "ALTER TABLE radar_orders ADD COLUMN phase_json TEXT"):
                try:                                      # ⛓/〰/💬/🌊 миграция ранних строк
                    c.execute(_mig)
                except Exception:
                    pass
            c.execute("INSERT OR REPLACE INTO radar_orders "
                      "(ts, symbol, sig_type, side, entry, sl, tp1, tp2, tp3, "
                      "grade, starred, targets_json, status, chain, wave_leg, tg_msg_id, phase_json) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'NEW',?,?,?,?)",
                      (int(time.time()), sym, sig_type, side, entry, sl, tp1, tp2, tp3,
                       grade, starred, targets_json,
                       json.dumps(chain, ensure_ascii=False) if chain else None, wave_leg,
                       int(tg_msg_id) if isinstance(tg_msg_id, int) else None,
                       json.dumps(phase) if phase else None))
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
            targets_json TEXT, wave_leg INTEGER, PRIMARY KEY (symbol, ts))""")
        for _mig in ("ALTER TABLE pump_signals ADD COLUMN targets_json TEXT",
                     "ALTER TABLE pump_signals ADD COLUMN wave_leg INTEGER"):
            try:                                         # миграция ранних строк без колонок
                c.execute(_mig)
            except Exception:
                pass
        c.execute("INSERT OR REPLACE INTO pump_signals VALUES "
                  "(:ts,:symbol,:side,:d_px,:vol_ratio,:rsi,:d_oi,:grade,"
                  ":entry,:sl,:tp1,:tp2,:tp3,:targets_json,:wave_leg)", row)
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
                 debug: bool = False, chain: list[dict] | None = None) -> tuple[str, dict] | None:
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
    # тип сетапа зависит от OI (GRT-урок + зеркало 05.07, добро Егора): обвал+OI НЕ вырос =
    # ликвидация лонгов, топливо кончилось → LONG-отскок (фейд); обвал+OI ВЫРОС = свежие шорты,
    # реальные продажи → SHORT-ПРОДОЛЖЕНИЕ (раньше был отброшенный Grade-C LONG-разворот).
    oi_fuel = d_oi5 is not None and d_oi5 <= 0.1         # OI не вырос = стопы/ликвидация
    dump_cont = (not up) and (d_oi5 is not None and d_oi5 > 0.1)   # обвал + свежая загрузка вниз
    # RSI-гейт зависит от типа: фейд требует экстремума; продолжение — нет (сигнал = OI+объём).
    if up and rsi < PUMP_RSI_HI:
        return None                                     # памп-фейд: нужен перекуп RSI>75
    if (not up) and (not dump_cont) and rsi > PUMP_RSI_LO:
        return None                                     # дамп-фейд (LONG): нужен перепрод RSI<25
    if dump_cont and rsi < 15:
        return None                                     # SHORT-продолжение: не шортить капитуляцию дна (v1 порог, тюнить)
    if up:                                    # памп → SHORT-разворот (фейд)
        ext = max(highs[-3:])                 # хай пампа
        pre = min(lows[-10:-3])               # цена ДО пампа
        rng = ext - pre
        sl, tp1, tp2, tp3 = ext * 1.01, ext - rng * 0.5, ext - rng * 0.75, pre
        head = "🔻 сетап: <b>SHORT</b> (разворот пампа ВНИЗ)"
        side, sl_note, tp_note = "SHORT", "за экстремум +1%", "до пампа"
    elif dump_cont:                           # обвал+OI вырос → SHORT-ПРОДОЛЖЕНИЕ (зеркало GRT, 05.07)
        ext = min(lows[-3:])                  # лоу дампа
        pre = max(highs[-10:-3])              # хай ДО дампа
        rng = pre - ext                       # размер плеча дампа
        # вход у лоу по импульсу; SL за середину плеча (реклейм 50% = импульс выдохся);
        # цели = measured-move расширение вниз от лоу
        sl, tp1, tp2, tp3 = ext + rng * 0.5, ext - rng * 0.5, ext - rng * 1.0, ext - rng * 1.5
        head = "🔻 сетап: <b>SHORT</b> (ПРОДОЛЖЕНИЕ дампа — OI растёт)"
        side, sl_note, tp_note = "SHORT", "за середину плеча дампа", "расширение вниз"
    else:                                     # дамп+OI не вырос → LONG-разворот (фейд отскока)
        ext = min(lows[-3:])
        pre = max(highs[-10:-3])
        rng = pre - ext
        sl, tp1, tp2, tp3 = ext * 0.99, ext + rng * 0.5, ext + rng * 0.75, pre
        head = "🔺 сетап: <b>LONG</b> (разворот дампа ВВЕРХ)"
        side, sl_note, tp_note = "LONG", "за экстремум +1%", "до дампа"
    if rng <= 0:
        return None
    # STOP-FVG-AWARE (10.07): стоп в незакрытом FVG = магнит для свипа → двигаем за край
    sl, _fvg_moved = _sl_fvg_adjust(sl, px, side, highs, lows)
    if dump_cont:
        grade = "A" if (d_oi5 >= 0.5 and vol_ratio >= 5) else "B"   # OI-грев = сама суть сетапа
        oi_txt = f"OI {d_oi5:+.2f}%/5м — СВЕЖИЕ ШОРТЫ грузятся → продолжение вниз вероятно"
    else:
        grade = "A" if (oi_fuel and vol_ratio >= 5) else ("B" if oi_fuel else "C")
        oi_txt = (f"OI {d_oi5:+.2f}%/5м — {'СТОПЫ, не загрузка → возврат вероятен' if oi_fuel else 'НАСТОЯЩАЯ загрузка → не спешить, ждать выдоха!'}"
                  if d_oi5 is not None else "OI: нет данных")
    # ⛓ цикл «загрузка→выстрел» (04.07, GRT 02:08→02:30): предыдущий сигнал в сторону движения.
    # Для ФЕЙДА (разворота) = предупреждение (загрузка началась ЗАРАНЕЕ → разворот преждевременен,
    # грейд ↓C). Для ПРОДОЛЖЕНИЯ (dump_cont) = наоборот ПОДТВЕРЖДЕНИЕ (загрузка в ту же сторону).
    cyc = _chain_same_dir(chain or [], up)
    if cyc is not None:
        _cyc_age = (time.time() - cyc["ts"]) / 60
        if dump_cont:
            oi_txt += f"\n⛓ {cyc['type']}↓ {_cyc_age:.0f}м назад — загрузка вниз ПОДТВЕРЖДАЕТ продолжение"
        else:
            oi_txt += (f"\n⛓ цикл {cyc['type']}→ВЫСТРЕЛ ({_cyc_age:.0f}м) — загрузка началась "
                       f"раньше, разворот НЕ спешить")
            if grade != "C":
                oi_txt += f" (Grade {grade}→C)"
                grade = "C"
    # 〰 волновой счёт SHADOW (рамка 5-3): нога импульса от базы. Grade НЕ меняет — копим WR по ногам.
    wave = _wave_leg(sym, up)
    if wave is not None:
        _dirw = "подъёма" if up else "спуска"
        oi_txt += (f"\n〰 нога импульса: ~{wave['leg']}-я ({wave['n_swings']} {_dirw} "
                   f"от базы {_fmt(wave['base'])}, dev {wave['dev']}%)")
    grade_txt = {"A": "A (вход надёжнее)", "B": "B", "C": "C (⚠️ против свежего потока)"}[grade]
    dot = "🔴" if side == "SHORT" else "🟢"
    title = "🚀 <b>PUMP</b>" if up else "💥 <b>DUMP</b>"   # верх-заголовок по ДВИЖЕНИЮ (не по стороне)
    tag = "PUMP" if up else "DUMP"
    msg = (f"{title}:\n\n"
           f"{dot} <code>{sym}</code> {d_px:+.1f}%\n"
           f"{head}\n"
           f"Grade {grade_txt} · объём ×{vol_ratio:.1f} · RSI {rsi:.0f}\n"
           f"{oi_txt}\n\n"
           f"Вход: ~{_c(px)}\n"
           f"Стоп: {_c(sl)} ({sl_note}{'; сдвинут за FVG' if _fvg_moved else ''})\n"
           f"TP1 {_c(tp1)} · TP2 {_c(tp2)} · TP3 {_c(tp3)} ({tp_note})\n\n"
           f"{_links(sym)}\n\n"
           f"#{sym} #{tag}")
    row = {"ts": int(time.time()), "symbol": sym, "side": side,
           "d_px": round(d_px, 2), "vol_ratio": round(vol_ratio, 2), "rsi": round(rsi, 1),
           "d_oi": d_oi5 if d_oi5 is None else round(d_oi5, 3), "grade": grade,
           "entry": px, "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3,
           "wave_leg": wave["leg"] if wave else None}
    return msg, row


def check_spring(w, sym: str, px: float, fund: float | None,
                 d1d: float | None = None) -> tuple[str, dict] | None:
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
    elif fund <= -0.0002:                      # 10.07 ФИКС (entry-анализ: MANA/IOTA лоси на
        dir_side = "UP"                        # fund −0.00003≈НОЛЬ читался «шорты грузятся» →
        dir_txt = f"🔺 funding {fund * 100:.4f}% → грузятся ШОРТЫ → топливо ВВЕРХ (вероятно)"
    elif fund >= 0.0002:                       # LONG на пике; симметрия порога = BUILD-фикс 05.07
        dir_side = "DOWN"
        dir_txt = f"🔻 funding {fund * 100:.4f}% → грузятся ЛОНГИ → топливо ВНИЗ (вероятно)"
    else:
        dir_side, dir_txt = "?", f"funding {fund * 100:.4f}% нейтрален — направление неясно"
    dot = {"UP": "🟢", "DOWN": "🔴"}.get(dir_side, "⚪")
    _day = f" · за день {d1d:+.1f}%" if d1d is not None else ""
    msg = (f"⏳ <b>ПРУЖИНА:</b>\n\n"
           f"{dot} <code>{sym}</code> OI {d_oi15:+.2f}%/15м{_day} · цена флэт (range {rng_pct:.2f}%)\n"
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


def _quadrant15(w, px: float, oi: float) -> str | None:
    """Квадрант OI×цена за 15м — ЕДИНЫЙ расчёт (BUILD-гейт + radar_state, reuse).
    PUP/PDN/PFL × OIUP/OIDN/OIFL. None если окна <16 точек."""
    if len(w) < 16 or not w[-16][2] or not w[-16][1]:
        return None
    d_px15 = (px / w[-16][2] - 1) * 100
    d15 = (oi / w[-16][1] - 1) * 100
    _p = "PUP" if d_px15 > 0.2 else "PDN" if d_px15 < -0.2 else "PFL"
    _o = "OIUP" if d15 > 0.15 else "OIDN" if d15 < -0.15 else "OIFL"
    return f"{_p}+{_o}"


def analyze_build(sym: str, px: float, d_oi5: float, fund: float | None,
                  d1d: float | None = None, quadrant: str | None = None) -> tuple[str, dict | None]:
    """📈 BUILD → полный сетап в сообщении (Егор 03.07: «нужно быстро реагировать» —
    вход-стоп-тейк сразу, без переспрашивания).

    Направление по funding СИММЕТРИЧНО (05.07 фикс «лонг в падающем тренде», CHZ/ORDI):
    fund<=-0.02% → грузятся шорты → LONG (сквиз вверх); fund>=+0.02% → лонги → SHORT.
    |funding|<0.02% = нейтрал → голый BUILD без сетапа (РАНЬШЕ любой fund<0 давал LONG —
    нейтральный -0.004% открывал контр-трендовый лонг). Плюс гейт 1h-тренда: сетап против
    старшего тренда (LONG@DOWN / SHORT@UP) не строим — остаётся голый алерт.
    SL — за структуру последнего часа (экстремум 5m×12), цели — карта целей 2.0.
    """
    # 🔴 12.07 v2 (Егор: «build знает про волны/структуру?!» — НЕ знал: направление =
    # инверсия funding → WR 19%, −22.8%/48ч). Теперь: OI-BUILD = ТОПЛИВО (грузятся),
    # НАПРАВЛЕНИЕ = СТРУКТУРА 1h (последний BOS/CHoCH, канон length=5). Funding — инфо
    # о толпе (сквиз-топливо), НЕ руль. VST-форвард покажет за дни (27 сд/48ч).
    side, struct_txt = _struct_dir(sym)
    veto_txt = None
    # 🚦 13.07 КВАДРАНТ-КОНКОРДАНС ГЕЙТ (Егор): вход ПРОТИВ 15м-потока OI×цена не строим.
    # Ночь 13.07: против квадранта 5/5 лоссов (SHORT при PUP+*: UAI/STRK/TIA/AGLD/SXT),
    # по квадранту — LAB профит + все живые. Ретро n=80: PDN+OIUP +0.88% vs PUP+OIUP −0.69%.
    # Блокируем ТОЛЬКО явный противоход (PFL/нет данных = пропуск): сетап → голый алерт.
    if side is not None and quadrant:
        _pq = quadrant.split("+")[0]
        if (side == "SHORT" and _pq == "PUP") or (side == "LONG" and _pq == "PDN"):
            veto_txt = (f"🚦 структура 1h даёт {side}, но 15м-поток против ({quadrant}) — "
                        f"вход не строим (конкорданс-гейт) 🔄")
            side = None
    if side is not None:
        _f_txt = (f"толпа: funding {fund * 100:+.3f}%" +
                  (" (шорты платят — топливо сквиза ↑)" if fund and fund < -0.0002 else
                   " (лонги платят — топливо сквиза ↓)" if fund and fund > 0.0002 else " нейтрал")
                  ) if fund is not None else "funding: нет данных"
        dir_txt = f"{'🔺' if side == 'LONG' else '🔻'} {struct_txt} · {_f_txt}"
    else:
        dir_txt = None
        # конкорданс-гейт выше мог уже поставить свой veto_txt — не затираем
        veto_txt = veto_txt or "⚪ структура 1h нема (боковик без сломов) — сетапа нет 🔄"
    # шапка (макет Егора 03.07): тип отдельно, тикер копируемый + цвет направления
    dot = {"LONG": "🟢", "SHORT": "🔴"}.get(side, "⚪")
    _day = f" · за день {d1d:+.1f}%" if d1d is not None else ""
    head = f"📈 <b>OI BUILD LIVE:</b>\n\n{dot} <code>{sym}</code> +{d_oi5:.2f}%/5м{_day}"
    if side is None:                                     # нейтрал/контр-тренд — сетап не строим,
        fund_txt = (veto_txt if veto_txt else
                    (f"funding {fund * 100:.4f}% — нейтрален\nсетапа нет 🔄"
                     if fund is not None else "funding: нет данных\nсетапа нет 🔄"))
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


_OI_ANCHOR: dict = {}           # sym -> (utc_date, oi_00) — якорь дня в RAM


def _oi_day_delta(sym: str, oi: float) -> float | None:
    """📅 OI-DAY-DELTA (10.07, Егор «детектор видит объёмы, зашедшие ЗА ДЕНЬ?» — не видел:
    окно радара 30м). Якорь = первый замер OI новых суток UTC (персист в oi_anchor —
    рестарт радара не теряет день). Возврат: % изменения OI с начала дня."""
    today = time.strftime("%Y-%m-%d", time.gmtime())
    cached = _OI_ANCHOR.get(sym)
    if cached is None or cached[0] != today:
        c = conn()
        try:
            c.execute("CREATE TABLE IF NOT EXISTS oi_anchor (symbol TEXT PRIMARY KEY, date TEXT, oi REAL)")
            row = c.execute("SELECT date, oi FROM oi_anchor WHERE symbol=?", (sym,)).fetchone()
            if row and row[0] == today and row[1]:
                _OI_ANCHOR[sym] = (today, float(row[1]))
            else:                                    # новые сутки → якорь = текущий OI
                c.execute("INSERT OR REPLACE INTO oi_anchor VALUES (?,?,?)", (sym, today, oi))
                c.commit()
                _OI_ANCHOR[sym] = (today, oi)
        finally:
            c.close()
    anchor = _OI_ANCHOR[sym][1]
    return (oi / anchor - 1) * 100 if anchor else None


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
        try:
            c.execute("ALTER TABLE radar_state ADD COLUMN oi_d1d REAL")   # 📅 дельта дня
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE radar_state ADD COLUMN quadrant TEXT")  # 12.07 OI×цена 15м
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE radar_state ADD COLUMN is_hot INTEGER")  # 12.07 HOT-LIST метка
        except Exception:
            pass
        c.executemany("INSERT OR REPLACE INTO radar_state VALUES (?,?,?,?,?,?,?,?,?)", rows)
        c.commit()
    finally:
        c.close()


def _fvg_zones(highs: list, lows: list) -> list[dict]:
    """FVG (трёхсвечный гэп) по спискам high/low. → [{kind: bear|bull, top, bot, i}].
    bear: low[i-1] > high[i+1] (гэп СВЕРХУ, магнит для ретрейса вверх); bull зеркально.
    Возвращаются только НЕзакрытые последующей ценой зоны."""
    out = []
    n = len(highs)
    for i in range(1, n - 1):
        if lows[i - 1] > highs[i + 1]:               # bearish FVG
            top, bot = lows[i - 1], highs[i + 1]
            if not any(highs[j] >= top for j in range(i + 2, n)):     # не закрыт полностью
                out.append({"kind": "bear", "top": top, "bot": bot, "i": i})
        if highs[i - 1] < lows[i + 1]:               # bullish FVG
            top, bot = lows[i + 1], highs[i - 1]
            if not any(lows[j] <= bot for j in range(i + 2, n)):
                out.append({"kind": "bull", "top": top, "bot": bot, "i": i})
    return out


def _sl_fvg_adjust(sl: float, entry: float, side: str,
                   highs: list, lows: list) -> tuple[float, bool]:
    """STOP-FVG-AWARE (10.07, IOTA #45257, Егор): стоп НЕ должен лежать в FVG — цена
    стремится закрыть гэп → свип стопа → уход по сетапу. Стоп внутри зоны → за ДАЛЬНИЙ
    край гэпа + буфер 0.2%. → (sl, был_ли_сдвиг)."""
    for z in _fvg_zones(highs, lows):
        if side == "SHORT" and z["kind"] == "bear" and z["top"] > entry:
            if z["bot"] <= sl <= z["top"]:           # стоп внутри магнита сверху
                return z["top"] * 1.002, True
        if side == "LONG" and z["kind"] == "bull" and z["bot"] < entry:
            if z["bot"] <= sl <= z["top"]:
                return z["bot"] * 0.998, True
    return sl, False


def _depth_read(sym: str, px: float = 0.0, zone_pct: float = 0.5) -> dict | None:
    """📖 ORDERBOOK-WALLS (09.07, Егор «видно как цену двигают»): снимок стакана.

    mid — ИЗ САМОГО стакана (тикер-цена разъезжается со срезом на быстрых движениях —
    ETH-кейс). Окно = min(zone_pct, фактическое покрытие среза): у мейджоров 500 уровней
    покрывают доли %, у альтов — много (адаптивно, сравнение bid/ask всегда симметрично)."""
    try:
        d = _get(f"https://fapi.binance.com/fapi/v1/depth?symbol={sym}USDT&limit=500")
        bids = [(float(p), float(q)) for p, q in d.get("bids", [])]
        asks = [(float(p), float(q)) for p, q in d.get("asks", [])]
        if not bids or not asks:
            return None
        mid = (bids[0][0] + asks[0][0]) / 2
        cov_bid = 1 - bids[-1][0] / mid
        cov_ask = asks[-1][0] / mid - 1
        win = min(zone_pct / 100, cov_bid, cov_ask)
        if win <= 0:
            return None
        out = {"px": mid, "win_pct": round(win * 100, 3)}
        for side, rows_all in (("bids", bids), ("asks", asks)):
            lo, hi = ((mid * (1 - win), mid) if side == "bids" else (mid, mid * (1 + win)))
            rows = [(p, q) for p, q in rows_all if lo <= p <= hi]
            usd = sum(p * q for p, q in rows)
            wall = max(rows, key=lambda r: r[0] * r[1], default=None)
            out[side] = {"usd": usd,
                         "wall_px": wall[0] if wall else None,
                         "wall_usd": wall[0] * wall[1] if wall else 0.0,
                         "wall_share": (wall[0] * wall[1] / usd) if (wall and usd) else 0.0}
        return out
    except Exception:
        return None


def _log_depth(sym: str, snap: dict, note: str) -> None:
    c = conn()
    try:
        c.execute("""CREATE TABLE IF NOT EXISTS depth_snap (
            ts INTEGER, symbol TEXT, px REAL, bid_usd REAL, ask_usd REAL,
            bid_wall_px REAL, bid_wall_usd REAL, ask_wall_px REAL, ask_wall_usd REAL, note TEXT)""")
        c.execute("INSERT INTO depth_snap VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (int(time.time()), sym, snap["px"], snap["bids"]["usd"], snap["asks"]["usd"],
                   snap["bids"]["wall_px"], snap["bids"]["wall_usd"],
                   snap["asks"]["wall_px"], snap["asks"]["wall_usd"], note))
        c.commit()
    finally:
        c.close()


def _orderbook_line(sym: str, px: float) -> str:
    """Строка «📖 стакан» для алерта: дисбаланс + стены + ДИНАМИКА (2 замера через 4с:
    стена переставилась за ценой = «двигают», исчезла = спуфер). Пусто при ошибке."""
    a = _depth_read(sym, px)
    if not a or not (a["bids"]["usd"] + a["asks"]["usd"]):
        return ""
    time.sleep(4)
    b = _depth_read(sym, px) or a
    try:
        _log_depth(sym, b, "alert")
    except Exception:
        pass
    bid_u, ask_u = b["bids"]["usd"], b["asks"]["usd"]
    if not bid_u or not ask_u:
        return ""
    imb = bid_u / ask_u
    side, ratio = ("bid", imb) if imb >= 1 else ("ask", 1 / imb)
    parts = [f"дисбаланс {side} {ratio:.1f}:1"]
    for sd, label in (("bids", "bid"), ("asks", "ask")):
        w = b[sd]
        if w["wall_usd"] > 50_000 and w["wall_share"] > 0.25:      # значимая стена: >25% зоны
            dist = (w["wall_px"] / px - 1) * 100
            wa = a[sd]
            if wa["wall_px"] and abs(w["wall_px"] / wa["wall_px"] - 1) > 0.0005:
                dyn = " ДВИГАЕТСЯ за ценой!"                       # переставилась за 4с
            elif wa["wall_usd"] and w["wall_usd"] < wa["wall_usd"] * 0.5:
                dyn = " тает (спуф?)"
            else:
                dyn = ""
            parts.append(f"{label}-стена ${w['wall_usd']/1e3:.0f}K на {dist:+.2f}%{dyn}")
    return "📖 стакан: " + " · ".join(parts)


def _squeeze_thr(w) -> tuple[float, float | None]:
    """ATR-адаптивный порог СКВИЗ-алерта (07.07, ENJ −0.73% = шум для его волы, Егор
    «на BingX не вижу такого»). Обычный 3м-ход монеты = средний |Δцена за 3 точки| по
    RAM-окну (без запросов). Порог алерта = 2.5× обычного, floor 0.6% (тихие монеты —
    прежняя чувствительность), потолок 2.5% (выше — территория PUMP-детектора).
    Мало истории → (0.6, None) = старое поведение. Возврат (порог, обычный_ход)."""
    px = [p for _, _, p in w]
    rets = [abs(px[i] / px[i - 3] - 1) * 100 for i in range(3, len(px)) if px[i - 3]]
    if len(rets) < 8:
        return 0.6, None
    avg = sum(rets) / len(rets)
    return min(max(0.6, 2.5 * avg), 2.5), avg


def tick():
    alerts = []
    state_rows = []
    _refresh_prices()
    _refresh_funding()
    _refresh_hot()                                     # HOT-LIST: горячие хвоста → в поллинг
    for sym in list(CORE) + [b for b in _HOT if b not in CORE]:
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
                # факт для копилки (сверка с магнитами) — каждый тик сквиза, без cooldown.
                # 🔴 05.07 согласование с Bybit (fix инверсии): side = POSITION ликвидированного.
                # рост цены (d_px>0) = шорты горят = ликвидируется ШОРТ → SELL (шорт position);
                # падение = лонги горят → BUY (лонг position). Было BUY при росте — инверсия
                # относительно bybit-ветки в той же таблице liq_events (единая семантика теперь).
                try:
                    _log_liq_synth(sym, "SELL" if d_px3 > 0 else "BUY", (oi3 - oi) * px, px)
                except Exception:
                    pass
            # АЛЕРТ — ATR-адаптивный порог (07.07): копилка выше пишется по старому 0.6
            # (статистика магнитов не меняется), а в TG идёт только значимое ДЛЯ ЭТОЙ монеты.
            _thr, _avg3 = _squeeze_thr(w)
            if abs(d_px3) >= _thr and d_oi3 <= -0.15 and _cooldown_ok(f"fast_squeeze:{sym}"):
                side = "вверх (шорты горят)" if d_px3 > 0 else "вниз (лонги горят)"
                _dot = "🟢" if d_px3 > 0 else "🔴"
                _scale = f" (×{abs(d_px3) / _avg3:.1f} обычного хода)" if _avg3 else ""
                send_tg(f"🌀 <b>СКВИЗ LIVE:</b>\n\n"
                        f"{_dot} <code>{sym}</code> Δцена {d_px3:+.2f}%/3м {side}{_scale}\n"
                        f"OI {d_oi3:+.2f}%/3м — движение ЗАКРЫТИЯМИ\nцена {_c(px)}\n\n"
                        f"{_links(sym)}\n\n"
                        f"#{sym} #SQUEEZE", channel="feed")
                alerts.append(f"squeeze {sym}")
        if len(w) >= 6:
            t5, oi5, px5 = w[-6]
            d_oi5 = (oi / oi5 - 1) * 100 if oi5 else 0
            if d_oi5 >= 0.5 and _cooldown_ok(f"fast_build:{sym}"):
                b_msg, b_row = analyze_build(sym, px, d_oi5, _FUND.get(f"{sym}USDT"),
                                             d1d=_oi_day_delta(sym, oi),
                                             quadrant=_quadrant15(w, px, oi))
                b_chain = _recent_signals(sym)           # ⛓ лениво: только при алерте
                # BUILD с сетапом (side+SL) → action + стакан; голый BUILD → feed
                if b_row:
                    b_msg = _with_orderbook(b_msg, sym, px)
                _mid_b = send_tg(_with_chain(b_msg, b_chain), channel=("action" if b_row else "feed"))
                if _mid_b:
                    if b_row:
                        _send_chart(sym, _mid_b)         # 📸 SMC-чарт тредом (только сетапы)
                        _log_build(b_row)
                        # ARMED-порт: BUILD-с-сетапом → radar_orders (цели из карты 2.0)
                        _log_radar_order("build", sym, b_row["side"], px,
                                         b_row["sl"], b_row["targets_json"], chain=b_chain,
                                         tg_msg_id=_mid_b)
                    alerts.append(f"build {sym}")
            # ⏳ ПРУЖИНА: скрытая загрузка ДО движения (окно 16 точек = 15 мин)
            res_sp = check_spring(w, sym, px, _FUND.get(f"{sym}USDT"),
                                  d1d=_oi_day_delta(sym, oi))
            if res_sp and _cooldown_ok(f"spring:{sym}", 3600):
                sp_msg, sp_row = res_sp
                # цели в сторону выстрела (dir UP → цели СВЕРХУ = LONG-сторона)
                sp_side = {"UP": "LONG", "DOWN": "SHORT"}.get(sp_row["dir"])
                if sp_side:
                    sp_msg, sp_row = _with_targets(sp_msg, sp_row, sym, sp_side, px)
                else:
                    sp_row["targets_json"] = None
                sp_chain = _recent_signals(sym)          # ⛓ лениво: только при алерте
                sp_msg = _with_orderbook(sp_msg, sym, px)
                _mid_sp = send_tg(_with_chain(sp_msg, sp_chain), channel="action")
                if _mid_sp:
                    _send_chart(sym, _mid_sp)            # 📸 SMC-чарт тредом
                    _log_spring(sp_row)
                    if sp_side:
                        # ARMED-порт: ПРУЖИНА с направлением → сетап (SL за структуру, цели 2.0)
                        _log_radar_order("spring", sym, sp_side, px,
                                         _sl_structure(sym, sp_side), sp_row["targets_json"],
                                         chain=sp_chain, tg_msg_id=_mid_sp)
                    alerts.append(f"SPRING {sym}")
            # 🚀 PUMP-кандидат по цене → подтверждение объёмом/RSI (klines только для кандидатов)
            d_px5 = (px / px5 - 1) * 100 if px5 else 0
            d_px12 = (px / w[-12][2] - 1) * 100 if (len(w) >= 12 and w[-12][2]) else 0
            d_px = d_px5 if abs(d_px5) >= PUMP_PCT_5M else (d_px12 if abs(d_px12) >= PUMP_PCT_12M else 0)
            if d_px:
                p_chain = _recent_signals(sym)           # ⛓ до analyze: grade-коррекция цикла
                res = analyze_pump(sym, px, d_px, d_oi5, chain=p_chain)
                if res and _cooldown_ok(f"pump:{sym}", 3600):
                    msg, row = res
                    msg, row = _with_targets(msg, row, sym, row["side"], px)
                    msg = _with_orderbook(msg, sym, px)
                    _mid_p = send_tg(_with_chain(msg, p_chain), channel="action")
                    if _mid_p:
                        _send_chart(sym, _mid_p)         # 📸 SMC-чарт тредом
                        _log_pump(row)          # → pump_signals: WR-статистика для SHADOW→ARMED
                        # ARMED-порт: PUMP-разворот → radar_orders (tp1-3 по откатам, grade)
                        _log_radar_order("pump", sym, row["side"], px, row["sl"],
                                         row.get("targets_json"), grade=row["grade"],
                                         tps=(row["tp1"], row["tp2"], row["tp3"]), chain=p_chain,
                                         wave_leg=row.get("wave_leg"), tg_msg_id=_mid_p)
                        alerts.append(f"PUMP {sym}")
        # live-контекст → radar_state (мост в Куб)
        d5 = (oi / w[-6][1] - 1) * 100 if (len(w) >= 6 and w[-6][1]) else None
        d15 = (oi / w[-16][1] - 1) * 100 if (len(w) >= 16 and w[-16][1]) else None
        d1d = _oi_day_delta(sym, oi)
        # КВАДРАНТ OI×ЦЕНА за 15м (12.07, Егор «расхождение OI с ценой — сильный показатель»,
        # ретро n=80 ПОДТВЕРДИЛ: PDN+OIUP +0.88% vs PUP+OIUP −0.69% WR14 / PUP+OIFL −1.06% WR0).
        # Фича в radar_state → bridge → features всех сделок; с 13.07 ещё и конкорданс-гейт
        # BUILD (расчёт единый — _quadrant15, reuse).
        quadrant = _quadrant15(w, px, oi)
        state_rows.append((sym, int(time.time()), px, d5, d15, _FUND.get(f"{sym}USDT"), d1d, quadrant,
                           1 if sym in _HOT else 0))
        time.sleep(0.15)
    _flush_radar_state(state_rows)
    return alerts


if __name__ == "__main__":
    if "--test" in sys.argv:                  # разбор монеты без TG: метрики + текст алерта
        sym = sys.argv[sys.argv.index("--test") + 1].upper()
        k = _get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}USDT&interval=5m&limit=2")
        px = float(k[-1][4])
        d_px = (px / float(k[0][1]) - 1) * 100
        res = analyze_pump(sym, px, d_px if d_px else 0.01, None, debug=True,
                           chain=_recent_signals(sym))
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
