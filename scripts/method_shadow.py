# -*- coding: utf-8 -*-
"""МЕТОД ЕГОРА — SHADOW-forward на живом крае (05.07, решение Егора).

Метод оцифрован (`core/smc/method_egor.py`, WR55% на историчке), но эдж упирается в ТОЛПУ/funding
у экстремума — её в OHLCV нет. Поэтому: детектим метод LIVE, подсвечиваем сетап Егору
(decision-support) С контекстом толпы из радара, копим forward-WR. НЕ торгуем. Если толпа лифтит
WR → ARMED на VST.

Геометрия (ядро detect_method_egor): вход на откате (ote_retest provisional) на РАЗВОРОТЕ у
экстремума большого 4h (structure_trend) + OTE-цели + тугой стоп. Крауд читаем из radar_state
(radar пишет funding/oi_d5/oi_d15). Толпа-фильтр (что проверяем forward):
  SHORT у вершины: funding>0 (лонги перегреты, платят) = топливо ВНИЗ → подтверждает;
  LONG у дна:      funding<0 (шорты платят) = топливо ВВЕРХ → подтверждает.

Reuse: send_tg/conn (oko_feed), radar_state (контекст), detect_method_egor (ядро).
pm2: --name method-shadow · тест одной монеты: python scripts/method_shadow.py --test ZEC
"""
import sys, time, json, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
sys.path.insert(0, ".")
import pandas as pd

from oko_feed.alerts import send_tg
from oko_feed.store import conn
from core.smc.method_egor import detect_method_egor
from core.smc.ote_matrix import structure_trend, _atr

# те же ликвидные, что радар (крауд-контекст в radar_state есть только для них)
from oi_fast_poller import CORE  # noqa: E402

SCAN_SEC = 900            # ~15 мин = 1 бар 15m: скан на закрытии свежего бара
# 15m-сигнал + 4h-сторона: пониженный ТФ дал OOS-плюс и устойчивый SHORT (Егор 05.07,
# «25-26 медвежьи, прогони на пониженных ТФ» → n=559 WR47 OOS+0.052%, SHORT все годы+).
LTF, HTF = "15m", "4h"
LTF_LIMIT, HTF_LIMIT = 1500, 400
EDGE = 0.5
COOLDOWN_SEC = 6 * 3600   # один алерт по символу раз в 6ч


def _klines(sym: str, interval: str, limit: int) -> pd.DataFrame | None:
    url = (f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}USDT"
           f"&interval={interval}&limit={limit}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 oko-shadow"})
    try:
        arr = json.load(urllib.request.urlopen(req, timeout=10))
    except Exception:
        return None
    if not arr:
        return None
    df = pd.DataFrame(arr, columns=["ot", "open", "high", "low", "close", "volume",
                                    "ct", "qv", "n", "tb", "tq", "ig"])
    df.index = pd.to_datetime(df["ot"], unit="ms")
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    return df[["open", "high", "low", "close", "volume"]]


def _crowd(sym: str) -> dict:
    """Контекст толпы из radar_state (radar пишет funding/oi_d5/oi_d15 каждый цикл)."""
    c = conn()
    try:
        row = c.execute("SELECT funding, oi_d5, oi_d15, ts FROM radar_state WHERE symbol=?",
                        (sym,)).fetchone()
    except Exception:
        row = None
    finally:
        c.close()
    if not row:
        return {}
    return {"funding": row[0], "oi_d5": row[1], "oi_d15": row[2], "ts": row[3]}


def _cooldown_ok(key: str, sec: int) -> bool:
    c = conn()
    try:
        c.execute("CREATE TABLE IF NOT EXISTS alert_log (key TEXT PRIMARY KEY, ts INTEGER)")
        row = c.execute("SELECT ts FROM alert_log WHERE key=?", (key,)).fetchone()
        if row and time.time() - row[0] < sec:
            return False
        c.execute("INSERT OR REPLACE INTO alert_log VALUES (?,?)", (key, int(time.time())))
        c.commit()
        return True
    finally:
        c.close()


def _log_shadow(sym: str, m: dict, crowd: dict, fuel: str) -> None:
    c = conn()
    try:
        c.execute("""CREATE TABLE IF NOT EXISTS method_shadow (
            ts INTEGER, symbol TEXT, direction TEXT, entry REAL, sl REAL,
            tp1 REAL, tp2 REAL, tp3 REAL, htf_trend TEXT, pos REAL,
            funding REAL, oi_d5 REAL, oi_d15 REAL, fuel TEXT,
            resolved INTEGER DEFAULT 0, outcome TEXT)""")
        t = m["targets"]
        c.execute("INSERT INTO method_shadow (ts,symbol,direction,entry,sl,tp1,tp2,tp3,"
                  "htf_trend,pos,funding,oi_d5,oi_d15,fuel) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (int(time.time()), sym, m["direction"], m["entry"], m["sl"],
                   t[0], t[1], t[2], m["htf_trend"], round(m["pos"], 3),
                   crowd.get("funding"), crowd.get("oi_d5"), crowd.get("oi_d15"), fuel))
        c.commit()
    finally:
        c.close()


def _fuel_read(direction: str, crowd: dict) -> tuple[str, bool]:
    """Толпа как топливо разворота. Возвращает (текст, confirms)."""
    f = crowd.get("funding")
    if f is None:
        return "толпа: нет данных радара", False
    fp = f * 100
    if direction == "SHORT":   # у вершины: лонги перегреты (funding>0) = топливо вниз
        ok = f > 0
        return (f"funding {fp:+.4f}% → {'лонги платят = топливо ВНИЗ ✅' if ok else 'шорты платят — против ⚠️'}", ok)
    else:                      # LONG у дна: шорты платят (funding<0) = топливо вверх
        ok = f < 0
        return (f"funding {fp:+.4f}% → {'шорты платят = топливо ВВЕРХ ✅' if ok else 'лонги платят — против ⚠️'}", ok)


def _links(sym: str) -> str:
    return (f'📊 <a href="https://ru.tradingview.com/chart/?symbol=BINGX%3A{sym}USDT.P">'
            f'{sym} график</a>')


def scan_one(sym: str, test: bool = False) -> str | None:
    d1 = _klines(sym, LTF, LTF_LIMIT)
    d4 = _klines(sym, HTF, HTF_LIMIT)
    if d1 is None or d4 is None or len(d1) < 300 or len(d4) < 80:
        return None
    t4 = d4.tail(400)
    st = structure_trend(t4)
    # гейты аудита 06.07 (LINK микро-нога): ATR(4h) для мин-масштаба ноги + возраст экстремума
    # в 4h-барах (LL/HH только что = слом в моменте, не разворачивать против)
    ext_age = None
    if st.get("extreme_ts") is not None:
        try:
            ext_age = int((t4.index[-1] - st["extreme_ts"]) / pd.Timedelta(HTF))
        except Exception:
            pass
    # НОГА = impulse_origin→extreme (07.07, Егор: вершина ВСЕГО импульса, не дрейфующий слом)
    ms = detect_method_egor(d1, htf_trend=st.get("trend"),
                            htf_break=st.get("impulse_origin") or st.get("break_level"),
                            htf_extreme=st.get("extreme"), edge=EDGE, fresh_bars=2,
                            htf_atr=_atr(t4), htf_extreme_age_bars=ext_age)
    if not ms:
        return "нет свежего сетапа" if test else None
    m = ms[0]
    crowd = _crowd(sym)
    fuel_txt, confirms = _fuel_read(m["direction"], crowd)
    sl_pct = abs(m["entry"] - m["sl"]) / m["entry"] * 100
    top = "вершины" if m["direction"] == "SHORT" else "дна"
    oi5 = crowd.get("oi_d5"); oi15 = crowd.get("oi_d15")
    oi_txt = (f"OI 5м {oi5:+.2f}% · 15м {oi15:+.2f}%" if oi5 is not None and oi15 is not None
              else "OI: нет данных радара")
    msg = (f"🎯 <b>МЕТОД (SHADOW):</b> <code>{sym}</code>\n\n"
           f"РАЗВОРОТ у {top} большого 4h (trend={st.get('trend')})\n"
           f"<b>{m['direction']}</b> на откате @ <code>{m['entry']:.6g}</code>\n"
           f"SL <code>{m['sl']:.6g}</code> (тугой, {sl_pct:.2f}%)\n"
           f"Цели OTE большого: <code>{m['targets'][0]:.6g}</code> / "
           f"<code>{m['targets'][1]:.6g}</code> / <code>{m['targets'][2]:.6g}</code>\n\n"
           f"🧲 ТОЛПА: {fuel_txt}\n{oi_txt}\n\n"
           f"{_links(sym)}\n\n#{sym} #METHOD_SHADOW")
    if test:
        return msg
    if not _cooldown_ok(f"method_shadow:{sym}", COOLDOWN_SEC):
        return None
    _log_shadow(sym, m, crowd, "confirm" if confirms else "against")
    # 17.07 (Егор «нет чарта»): SMC-чарт одним сообщением (фото+caption), фолбэк на текст.
    _sent = False
    if len(msg) <= 1024:
        try:
            import asyncio as _aio
            from core.ui.chart_builder import build_signal_chart
            from oko_feed.alerts import send_tg_photo
            _png = _aio.run(build_signal_chart(f"{sym}/USDT:USDT", tf="1h", bot=None, wave_overlay=True))
            if _png and send_tg_photo(_png, caption=msg, channel="action"):
                _sent = True
        except Exception as _ce:
            print(f"[METHOD-SHADOW] chart {sym}: {_ce}")
    if not _sent:
        send_tg(msg, channel="action")   # фолбэк: текст (чарт не собрался / caption длинный)
    return f"SHADOW {sym} {m['direction']} fuel={'✅' if confirms else '⚠️'}"


def main():
    if "--test" in sys.argv:
        sym = sys.argv[sys.argv.index("--test") + 1].upper()
        print(scan_one(sym, test=True) or "нет данных/сетапа")
        return
    print(f"[METHOD-SHADOW] метод Егора live: {len(CORE)} монет, скан {SCAN_SEC}с "
          f"(разворот у экстремума 4h + вход на откате + OTE-цели + толпа из radar_state)")
    while True:
        try:
            hits = []
            for sym in CORE:
                r = scan_one(sym)
                if r:
                    hits.append(r)
                time.sleep(0.2)
            if hits:
                print(f"[METHOD-SHADOW] {time.strftime('%H:%M:%S')}: {hits}")
        except KeyboardInterrupt:
            break
        except Exception as e:  # noqa: BLE001
            print(f"[METHOD-SHADOW] err: {e}")
        time.sleep(SCAN_SEC)


if __name__ == "__main__":
    main()
