# -*- coding: utf-8 -*-
"""📡 МАРКЕТ-ПУЛЬС — ширина движения рынка в реальном времени. НЕ торгует.

Егор 08.10: «за 6 часов упали 81% монет, а мы этого не видим и не реагируем?!» · «сутки это ОООООЧЕНЬ долго на крипте!
тут за 15 минут рынок может обвалиться на 50%» · «схождение данных/конфлюенции в таких моментах нам нужны очень быстро».
До этого прибора ширину видели: суточный дрейф30 (universe-drift), 4h-фейд терминала (фон раз в 5 мин с 11.09),
72-часовой breadth10 в записях сетапов тени. Живого «сколько монет упало за 15 минут / 2 часа» не было нигде.

Раз в минуту — цены всех USDT-перпетуалов BingX (`/swap/v1/ticker/price`, ~14 КБ сжатыми), раз в 10 минут — оборот
(`/swap/v2/quote/ticker`, ~96 КБ): ширина считается по ЛИКВИДНЫМ (≥ MIN_TURN), без синтетики (NCSK/NCFX/NCCO/NCSI).
Окна 15м / 1ч / 2ч / 6ч: доля монет вниз и вверх сильнее порога, медиана хода, BTC/ETH. При старте история
досеивается закрытыми 15m-барами хранилища (`market_store`), поэтому 2ч/6ч доступны сразу.

Состояние рынка с гистерезисом: НОРМА · СЛИВ · ОБВАЛ (быстрый, внутри слива) · ВЫНОС, плюс событие «отскок в сливе».
Переход → алерт в канал Oko-WAVES (`data/wave5_shadow/tg.json`). Снимок → `data/market_pulse.json` (читают тень,
терминал, бот), история по минутам → `oko_feed/pulse.db` (свой писатель, `core.infra.sat_store`).

Запуск: python scripts/market_pulse.py            — разовый снимок (печать)
        python scripts/market_pulse.py loop       — постоянная работа (pm2 market-pulse)
        python scripts/market_pulse.py calibrate  — частота порогов на истории (журнал общего состояния, 1h)
"""
from __future__ import annotations

import json
import sys
import time
from collections import deque
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:                                        # noqa: BLE001
    pass

PRICE_URL = "https://open-api.bingx.com/openApi/swap/v1/ticker/price"
TICKER_URL = "https://open-api.bingx.com/openApi/swap/v2/quote/ticker"
SNAP = ROOT / "data" / "market_pulse.json"
MIN_TURN = 5e6                     # оборот 24ч, $ — та же граница ликвидности, что у повестки терминала
POLL_SEC, TURN_SEC = 60, 600
KEEP_SEC = 7 * 3600
# окно → (секунды, порог хода в долях): 15 минут — 2%, остальные — 3% (+ доля «сильнее 5%» для 2ч/6ч)
WINDOWS = {"15m": (900, 0.02), "1h": (3600, 0.03), "2h": (7200, 0.03), "6h": (21600, 0.03)}
# пороги состояний; выход — с гистерезисом, чтобы состояние не мигало. Калибровка 08.10 (`calibrate`, журнал 1h,
# 2023-01 → 2026-10-06): «2ч, ≥50% монет вниз >3%» — 327 эпизодов (≈7 в месяц, 277 дней); ≥70% — ≈5 в месяц;
# «медиана 1ч ≤ −5%» — 38 эпизодов за 3.8 года (обвал редок, слив — обычное событие рынка альтов)
DUMP_ON, DUMP_OFF = 0.50, 0.30     # доля монет вниз за 2ч
FAST_MED, FAST_SHARE = -0.015, 0.40  # 15 минут: медиана ≤ −1.5% и ≥40% монет вниз сильнее 2% — быстрый слив
CRASH_15M, CRASH_1H = -0.03, -0.05   # медиана 15м ≤ −3% или 1ч ≤ −5% — ОБВАЛ
BOUNCE_15M = 0.01                  # в сливе медиана 15м ≥ +1% — отскок
ALERT_GAP = 900                    # одинаковые алерты не чаще раза в 15 минут
HOLD_OFF = 3                       # выход из состояния — 3 минуты подряд под порогом выхода

# ⚡ 08.10 (Егор: «у нас есть инструменты отслеживания ликвидаций — ты их тоже упустил из вида?»): поток ликвидаций
# Bybit (`scripts/liq_ws.py`, pm2 liq-ws, ~1 с) пишет факты в `liq_events`. side='BUY' — ликвидирован ЛОНГ (цена
# вниз), 'SELL' — шорт (вверх); только source='bybit_ws' (синтетика oi_synth — своя семантика, не сверена).
# 08.10 15:00 UTC: лонгов $56.2M за час в 40 монетах (×720 к медиане часа, максимум за 30 дней), предвестник с 12:00.
LIQ_DB = ROOT / "oko_feed" / "external_data.db"
LIQ_STALE_SEC = 900                # последний факт старше 15 мин — поток молчит, нули не показываем как «тихо»
_liq_base = {"ts": 0.0}

_hist: dict[str, deque] = {}
_liquid: set[str] = set()
_turn_ts = 0.0


def _liq_conn():
    import sqlite3
    return sqlite3.connect(f"file:{LIQ_DB.as_posix()}?mode=ro", uri=True, timeout=5)


def liq_flow(now: float) -> dict | None:
    """Ликвидации по всему рынку за 15 мин и 1 ч: лонги/шорты $, монет; база — перцентили часа за 30 дней (раз в час)."""
    try:
        with _liq_conn() as c:
            last = c.execute("SELECT MAX(ts) FROM liq_events WHERE source='bybit_ws'").fetchone()[0] or 0
            out = {"last_age_sec": int(now - last)}
            for w, sec in (("15m", 900), ("1h", 3600)):
                rows = c.execute("SELECT side, SUM(usd), COUNT(DISTINCT symbol) FROM liq_events WHERE source='bybit_ws' "
                                 "AND ts >= ? GROUP BY side", (int(now - sec),)).fetchall()
                d = {s: (u or 0.0, n) for s, u, n in rows}
                out[w] = {"long": round(d.get("BUY", (0, 0))[0]), "short": round(d.get("SELL", (0, 0))[0]),
                          "coins_long": d.get("BUY", (0, 0))[1], "coins_short": d.get("SELL", (0, 0))[1]}
            if now - _liq_base["ts"] > 3600:
                h = c.execute("SELECT ts/3600, SUM(CASE WHEN side='BUY' THEN usd ELSE 0 END), "
                              "SUM(CASE WHEN side='SELL' THEN usd ELSE 0 END) FROM liq_events WHERE source='bybit_ws' "
                              "AND ts >= ? AND ts < ? GROUP BY 1", (int(now - 30 * 86400), int(now - 3600))).fetchall()
                if len(h) > 100:
                    lo, sh = np.array([r[1] for r in h]), np.array([r[2] for r in h])
                    _liq_base.update(ts=now, l50=float(np.median(lo)), l99=float(np.quantile(lo, .99)),
                                     s50=float(np.median(sh)), s99=float(np.quantile(sh, .99)))
            out["base"] = {k: round(v) for k, v in _liq_base.items() if k != "ts"}
        return out
    except Exception as e:                               # noqa: BLE001
        print(f"[pulse] ликвидации: {e}", flush=True)
        return None


def liq_events(lq: dict | None) -> list[str]:
    """Каскад: ликвидации за 1 ч ≥ 99-го перцентиля часа (или за 15 мин ≥ его половины)."""
    if not lq or lq.get("last_age_sec", 1e9) > LIQ_STALE_SEC or not lq.get("base"):
        return []
    b, ev = lq["base"], []
    if lq["1h"]["long"] >= b.get("l99", 9e18) or lq["15m"]["long"] >= b.get("l99", 9e18) / 2:
        ev.append("КАСКАД ЛОНГОВ")
    if lq["1h"]["short"] >= b.get("s99", 9e18) or lq["15m"]["short"] >= b.get("s99", 9e18) / 2:
        ev.append("КАСКАД ШОРТОВ")
    return ev


def _get(url: str):
    import requests
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json().get("data") or []


def _base(sym: str) -> str:
    return sym.split("-")[0].upper()


def refresh_turnover() -> None:
    global _turn_ts, _liquid
    from core.infra.market_store import is_synthetic
    rows = _get(TICKER_URL)
    liq = {_base(t["symbol"]) for t in rows if str(t.get("symbol", "")).endswith("-USDT")
           and float(t.get("quoteVolume") or 0) >= MIN_TURN and not is_synthetic(_base(t["symbol"]))}
    if liq:
        _liquid, _turn_ts = liq, time.time()


def seed_history() -> int:
    """Досев: закрытые 15m-бары хранилища за ~7 ч — окна 2ч/6ч считаются сразу, без ожидания."""
    from core.infra.market_store import closed_bars
    n = 0
    for b in sorted(_liquid):
        try:
            d = closed_bars(b, "15m", 30)
        except Exception:                                # noqa: BLE001
            continue
        if d is None or not len(d):
            continue
        dq = _hist.setdefault(b, deque())
        for t, c in zip(d.index, d.close.values):
            dq.append((t.timestamp() + 900, float(c)))      # время ЗАКРЫТИЯ бара
        n += 1
    return n


def poll_prices(now: float) -> int:
    rows = _get(PRICE_URL)
    k = 0
    for t in rows:
        s = str(t.get("symbol", ""))
        if not s.endswith("-USDT"):
            continue
        b = _base(s)
        try:
            p = float(t["price"])
        except (KeyError, TypeError, ValueError):
            continue
        if p <= 0:
            continue
        dq = _hist.setdefault(b, deque())
        dq.append((now, p))
        while dq and dq[0][0] < now - KEEP_SEC:
            dq.popleft()
        k += 1
    return k


def _ret(dq: deque, now: float, sec: int):
    """Ход за окно: последняя цена против последней точки не позже now − sec (не старше окна вдвое)."""
    if not dq or dq[-1][0] < now - 180:
        return None
    t_lo = now - sec
    past = None
    for t, p in reversed(dq):
        if t <= t_lo:
            past = (t, p)
            break
    if past is None or past[0] < t_lo - sec:
        return None
    return dq[-1][1] / past[1] - 1


def metrics(now: float) -> dict:
    out = {"ts": int(now), "n_liquid": len(_liquid)}
    for w, (sec, thr) in WINDOWS.items():
        r = np.array([x for x in (_ret(_hist.get(b, deque()), now, sec) for b in _liquid) if x is not None])
        if len(r) < 30:
            out[w] = None
            continue
        out[w] = {"n": int(len(r)), "dn": round(float((r < -thr).mean()), 3), "up": round(float((r > thr).mean()), 3),
                  "med": round(float(np.median(r)), 4), "dn5": round(float((r < -0.05).mean()), 3),
                  "up5": round(float((r > 0.05).mean()), 3)}
    for b in ("BTC", "ETH"):
        out[b.lower()] = {w: (None if (x := _ret(_hist.get(b, deque()), now, sec)) is None else round(x, 4))
                          for w, (sec, _) in WINDOWS.items()}
    out["liq"] = liq_flow(now)
    return out


def classify(m: dict, prev: dict) -> tuple[str, list[str]]:
    """Новое состояние и события. prev — {'state', 'below', 'bounce_sent'}."""
    w15, w1, w2 = m.get("15m"), m.get("1h"), m.get("2h")
    st, ev = prev.get("state", "НОРМА"), []
    if not w2 or not w15:
        return st, ev
    crash = (w15["med"] <= CRASH_15M) or (w1 is not None and w1["med"] <= CRASH_1H)
    dump = w2["dn"] >= DUMP_ON or (w15["med"] <= FAST_MED and w15["dn"] >= FAST_SHARE)
    pump = w2["up"] >= DUMP_ON or (w15["med"] >= -FAST_MED and w15["up"] >= FAST_SHARE)
    if crash:
        new = "ОБВАЛ"
    elif dump:
        new = "СЛИВ"
    elif pump:
        new = "ВЫНОС"
    elif st in ("СЛИВ", "ОБВАЛ"):
        calm = w2["dn"] < DUMP_OFF and w15["med"] > -0.005
        prev["below"] = prev.get("below", 0) + 1 if calm else 0
        new = "НОРМА" if prev["below"] >= HOLD_OFF else st
    elif st == "ВЫНОС":
        calm = w2["up"] < DUMP_OFF and w15["med"] < 0.005
        prev["below"] = prev.get("below", 0) + 1 if calm else 0
        new = "НОРМА" if prev["below"] >= HOLD_OFF else st
    else:
        new = "НОРМА"
    # 🔴 09.10: обнулять счётчик спокойных минут — только когда условие состояния РЕАЛЬНО горит. Раньше обнуляли по
    # `new in (СЛИВ, ОБВАЛ, ВЫНОС)`, а `new` при переносе состояния тоже СЛИВ — счётчик сбрасывался каждую минуту и
    # выход в НОРМУ был невозможен: 08.10 СЛИВ 16:15 → ВЫНОС 19:50 и дальше ВЫНОС часами при 3% монет вверх за 2 ч.
    if crash or dump or pump:
        prev["below"] = 0
    if new in ("СЛИВ", "ОБВАЛ") and w15["med"] >= BOUNCE_15M and not prev.get("bounce_sent"):
        ev.append("ОТСКОК")
        prev["bounce_sent"] = True
    if new != st and new in ("СЛИВ", "ОБВАЛ"):
        prev["bounce_sent"] = False
    return new, ev


def _pct(x) -> str:
    return "—" if x is None else f"{x * 100:+.1f}%"


def text(m: dict, state: str, ev: str | None = None) -> str:
    w15, w1, w2, w6 = (m.get(k) or {} for k in ("15m", "1h", "2h", "6h"))
    head = {"СЛИВ": "🔴 СЛИВ РЫНКА", "ОБВАЛ": "🆘 ОБВАЛ РЫНКА", "ВЫНОС": "🟢 ВЫНОС РЫНКА", "НОРМА": "⚪ рынок успокоился"}[state]
    if ev == "ОТСКОК":
        head = "🔄 ОТСКОК В СЛИВЕ"
    elif ev in ("КАСКАД ЛОНГОВ", "КАСКАД ШОРТОВ"):
        head = "⚡ КАСКАД ЛИКВИДАЦИЙ " + ("ЛОНГОВ — рынок вниз" if ev == "КАСКАД ЛОНГОВ" else "ШОРТОВ — рынок вверх")
    t = time.strftime("%d.%m %H:%M", time.gmtime(m["ts"]))
    lines = [f"<b>{head}</b> · {t} UTC · ликвидных пар {m['n_liquid']}"]
    for nm, w in (("15 мин", w15), ("1 ч", w1), ("2 ч", w2), ("6 ч", w6)):
        if w:
            lines.append(f"{nm}: вниз {w['dn'] * 100:.0f}% монет · вверх {w['up'] * 100:.0f}% · медиана {_pct(w['med'])}")
    b, e = m.get("btc") or {}, m.get("eth") or {}
    lines.append(f"BTC {_pct(b.get('15m'))} / {_pct(b.get('2h'))} · ETH {_pct(e.get('15m'))} / {_pct(e.get('2h'))} (15 мин / 2 ч)")
    lines.append(liq_line(m.get("liq")))
    if state in ("СЛИВ", "ОБВАЛ") and ev not in ("ОТСКОК", "КАСКАД ШОРТОВ"):
        lines.append("По замерам: доказанные лонги ядра волн в такой слив исторически +8.2%/сд (неустойчиво по годам) — "
                     "вход после завершённой пятёрки, в массовый день; шорт-механики бота входят лимитом на откате.")
    return "\n".join(lines)


def _usd(x) -> str:
    return f"${x / 1e6:.1f}M" if x >= 1e6 else f"${x / 1e3:.0f}k"


def liq_line(lq: dict | None) -> str:
    if not lq:
        return "⚡ ликвидации: нет данных (liq-ws недоступен)"
    if lq.get("last_age_sec", 1e9) > LIQ_STALE_SEC:
        return f"⚡ ликвидации: 🔴 поток молчит {lq['last_age_sec'] // 60} мин (liq-ws)"
    h, q, b = lq["1h"], lq["15m"], lq.get("base") or {}
    k = f" (×{h['long'] / b['l50']:.0f} к обычному часу)" if b.get("l50") else ""
    return (f"⚡ ликвидации лонгов: 15 мин {_usd(q['long'])} · 1 ч {_usd(h['long'])}{k} · монет {h['coins_long']} · "
            f"шортов за 1 ч {_usd(h['short'])}")


def _db():
    from core.infra import sat_store
    c = sat_store.connect("pulse")
    c.execute("""CREATE TABLE IF NOT EXISTS pulse(ts INTEGER PRIMARY KEY, state TEXT, n INTEGER,
        dn15 REAL, up15 REAL, med15 REAL, dn1h REAL, up1h REAL, med1h REAL, dn2h REAL, up2h REAL, med2h REAL,
        dn6h REAL, up6h REAL, med6h REAL, dn5_2h REAL, dn5_6h REAL, btc15 REAL, btc2h REAL, eth15 REAL, eth2h REAL)""")
    return c


def save(m: dict, state: str, prev: dict) -> None:
    g = lambda w, k: (m.get(w) or {}).get(k)                  # noqa: E731
    snap = {**m, "state": state, "since": prev.get("since"), "last_alert": prev.get("last_alert") or {},
            "updated": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())}
    tmp = SNAP.with_suffix(".tmp")
    tmp.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    tmp.replace(SNAP)
    try:
        with _db() as c:
            c.execute("INSERT OR REPLACE INTO pulse VALUES (" + ",".join("?" * 21) + ")",
                      (m["ts"], state, m["n_liquid"], g("15m", "dn"), g("15m", "up"), g("15m", "med"), g("1h", "dn"),
                       g("1h", "up"), g("1h", "med"), g("2h", "dn"), g("2h", "up"), g("2h", "med"), g("6h", "dn"),
                       g("6h", "up"), g("6h", "med"), g("2h", "dn5"), g("6h", "dn5"), (m.get("btc") or {}).get("15m"),
                       (m.get("btc") or {}).get("2h"), (m.get("eth") or {}).get("15m"), (m.get("eth") or {}).get("2h")))
            lq = m.get("liq")
            if lq:
                c.execute("""CREATE TABLE IF NOT EXISTS pulse_liq(ts INTEGER PRIMARY KEY, long15 REAL, short15 REAL,
                    long1h REAL, short1h REAL, coins_long1h INTEGER, l99 REAL, age_sec INTEGER)""")
                c.execute("INSERT OR REPLACE INTO pulse_liq VALUES (?,?,?,?,?,?,?,?)",
                          (m["ts"], lq["15m"]["long"], lq["15m"]["short"], lq["1h"]["long"], lq["1h"]["short"],
                           lq["1h"]["coins_long"], (lq.get("base") or {}).get("l99"), lq.get("last_age_sec")))
    except Exception as e:                               # noqa: BLE001
        print(f"[pulse] БД: {e}", flush=True)


def alert(txt: str) -> None:
    try:
        from core.waves.wave_tg import send_text, tg_config
        if tg_config().get("enabled"):
            res = send_text(txt)                       # отказ Telegram исключения не бросает — пишем его в лог
            print(f"[pulse] TG {'ок' if res.get('ok') else 'ОТКАЗ: ' + str(res)[:200]}", flush=True)
    except Exception as e:                               # noqa: BLE001
        print(f"[pulse] TG: {e}", flush=True)


def loop() -> None:
    prev = {}
    try:
        old = json.loads(SNAP.read_text(encoding="utf-8"))
        prev = {"state": old.get("state", "НОРМА"), "since": old.get("since")}   # рестарт не повторяет алерт
        last_alert: dict[str, float] = dict(old.get("last_alert") or {})       # 08.10: 16:15 СЛИВ ушёл повторно
    except Exception:                                    # noqa: BLE001
        last_alert = {}
    prev["last_alert"] = last_alert
    refresh_turnover()
    print(f"[pulse] старт · ликвидных пар {len(_liquid)} · досеяно историей 15m: {seed_history()} · "
          f"состояние {prev.get('state', 'НОРМА')}", flush=True)
    while True:
        t0 = time.time()
        try:
            if t0 - _turn_ts > TURN_SEC:
                refresh_turnover()
            poll_prices(t0)
            m = metrics(t0)
            st0 = prev.get("state", "НОРМА")
            st, evs = classify(m, prev)
            evs = evs + liq_events(m.get("liq"))
            if st != st0:
                prev["state"], prev["since"] = st, int(t0)
                if st != "НОРМА" or st0 in ("СЛИВ", "ОБВАЛ", "ВЫНОС"):
                    if t0 - last_alert.get(st, 0) >= ALERT_GAP or st == "ОБВАЛ":
                        alert(text(m, st)); last_alert[st] = t0
                print(f"[pulse] {time.strftime('%H:%M', time.gmtime(t0))} UTC · {st0} → {st}", flush=True)
            for ev in evs:
                if t0 - last_alert.get(ev, 0) >= ALERT_GAP:
                    alert(text(m, st, ev)); last_alert[ev] = t0
            save(m, st, prev)
            if int(t0) % 600 < POLL_SEC:
                w2 = m.get("2h") or {}
                print(f"[pulse] {time.strftime('%H:%M', time.gmtime(t0))} UTC · {st} · 2ч вниз {w2.get('dn')} "
                      f"медиана {w2.get('med')} · пар {m['n_liquid']}", flush=True)
        except Exception as e:                           # noqa: BLE001
            print(f"[pulse] ошибка цикла: {type(e).__name__} {e}", flush=True)
        time.sleep(max(5.0, POLL_SEC - (time.time() - t0)))


def _ret_k(args):
    f, k = args
    import pandas as pd
    c = pd.read_parquet(f, columns=["close"]).close
    return (c / c.shift(k) - 1).rename(Path(f).stem)


def calibrate() -> None:
    """Частота порогов на истории: журнал общего состояния (1h close, 469 монет, 2023 → 06.10.2026)."""
    import glob
    from multiprocessing import Pool
    import pandas as pd
    files = sorted(glob.glob("G:/oko_lab/joint/1h/*.parquet"))
    with Pool(12) as p:
        R1 = pd.concat(p.map(_ret_k, [(f, 1) for f in files]), axis=1)
        R2 = pd.concat(p.map(_ret_k, [(f, 2) for f in files]), axis=1)
    ok = R2.notna().sum(axis=1) >= 50
    months = ok.sum() / 24 / 30.4
    for nm, R, thr in (("2 ч, вниз > 3%", R2, -0.03), ("1 ч, вниз > 3%", R1, -0.03)):
        sh = ((R < thr).sum(axis=1) / R.notna().sum(axis=1))[ok]
        for q in (0.3, 0.5, 0.7):
            m = sh >= q
            ep = int((m & ~m.shift(1, fill_value=False)).sum())
            print(f"{nm}: доля ≥ {q:.0%} — {m.mean() * 100:.2f}% часов · эпизодов {ep} (≈{ep / months:.1f} в месяц) · "
                  f"дней {sh.index[m].floor('D').nunique()}")
    med1 = R1.median(axis=1)[ok]
    for x in (-0.03, -0.05):
        m = med1 <= x
        print(f"медиана 1 ч ≤ {x:.0%}: эпизодов {int((m & ~m.shift(1, fill_value=False)).sum())}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "once"
    if cmd == "loop":
        loop()
    elif cmd == "calibrate":
        calibrate()
    else:
        refresh_turnover()
        print(f"ликвидных пар {len(_liquid)} · досеяно {seed_history()}")
        poll_prices(time.time())
        m = metrics(time.time())
        st, _ = classify(m, {})
        print(text(m, st))
