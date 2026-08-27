# -*- coding: utf-8 -*-
"""РЕЖИМ РЫНКА НА ЖИВЫХ ДАННЫХ (11.08.2026).

Детектор `core/context/market_drift` проверен на истории (причинность подтверждена запуском,
переключатель PF 1.62 против контроля 0.54). Но кэш `ohlcv_cache.db` отстаёт на 71 день —
для бэктеста это неважно, для продукта смертельно: «какая сторона платит сейчас» нельзя
считать по позавчерашним данным.

Здесь тот же калькулятор кормится ЖИВЫМИ барами с биржи. Один калькулятор на историю и бой
([[principle_reuse_not_duplication]]) — иначе продукт будет мерить не то, что проверено.

Пишет строку в таблицу `regime_state` и печатает человеческое чтение — это одновременно:
  · гейт для бота (какую сторону разрешать)
  · ежедневная строка для контента
  · ядро продукта «чтение рынка»

pm2 (крон каждый час): --name regime-now · разово: python scripts/regime_now.py
"""
import datetime as _dt
import json
import sqlite3
import sys
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
sys.path.insert(0, ".")
sys.path.insert(0, "scripts")
import pandas as pd

from oko_feed.store import conn
from core.context.market_drift import regime_series, BULL, BEAR, FLAT
from oi_fast_poller import CORE  # noqa: E402

TF, LIMIT = "4h", 1000        # живой хвост с биржи; история берётся из кэша (см. build_panel)
CACHE_DB = "ohlcv_cache.db"
HIST_FROM_MS = int(_dt.datetime(2022, 1, 1, tzinfo=_dt.timezone.utc).timestamp() * 1000)
DRIFT_BARS, MA_BARS, MIN_HOLD = 180, 48, 12    # конфигурация, выжившая развёртку

# Что предписывает режим — из замера 11.08 (120 монет, 2022-26, косты 0.35%):
#   БЫК → LONG (PF 1.46) · МЕДВЕДЬ → SHORT (PF 1.95) · НЕЙТРАЛЬ → обе стороны ~0.70, не торговать.
# Контроль «против режима» дал PF 0.54 — сторона действительно решает.
PRESCRIPTION = {
    BULL: ("LONG", "лонг с отката; шорт запрещён (PF 0.33 в быке)"),
    BEAR: ("SHORT", "шорт с отката; лонг запрещён (PF 0.64 в медведе)"),
    FLAT: ("—", "ни одна сторона: обе дают PF ~0.70. Работает только фейд пролива (bigflush)"),
}


def _klines(sym: str):
    url = (f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}USDT"
           f"&interval={TF}&limit={LIMIT}")
    try:
        arr = json.load(urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "oko-regime"}), timeout=12))
    except Exception:
        return None
    if not arr or len(arr) < 600:
        return None
    # последний бар формирующийся — отбрасываем (причинность)
    return pd.Series([float(k[4]) for k in arr[:-1]], index=[int(k[0]) for k in arr[:-1]])


def _cache_hist(sym: str):
    """История 4h из ohlcv_cache с 2022 — БЕЗ неё пороги считаются не по той выборке."""
    try:
        c = sqlite3.connect(CACHE_DB, timeout=20)
        try:
            rows = c.execute(
                "SELECT time,close FROM ohlcv_cache WHERE symbol=? AND timeframe='4h' "
                "AND time>=? ORDER BY time", (f"{sym}/USDT", HIST_FROM_MS)).fetchall()
        finally:
            c.close()
    except Exception:
        return None
    if len(rows) < 500:
        return None
    return pd.Series([r[1] for r in rows], index=[r[0] for r in rows])


def build_panel():
    """ПОЛНАЯ история (кэш) + живой хвост (биржа).

    🔴 БАГ, найденный DS 12.08 и подтверждённый замером: `regime_series` считает пороги
    РАСШИРЯЮЩИМСЯ перцентилем по ПЕРЕДАННОМУ ряду. Если подать только свежее окно
    (1000 баров ≈ 166 дней), пороги берутся с медвежьего куска: медианный дрейф −0.027
    против −0.0595 по всей истории. Итог: метки разошлись в 34% баров, «БЫК» объявлялся
    ВТРОЕ чаще (148 против 44) — обычный отскок в медведе получал бычью метку.
    То есть в бою мерилось НЕ ТО, что проверено на истории.

    Фикс: панель собирается как история из кэша (с 2022) + живые бары после последнего
    кэшированного. Один ряд — одни пороги — один калькулятор.
    """
    px, bad, no_hist = {}, [], []
    for s in CORE:
        live = _klines(s)
        hist = _cache_hist(s)
        if live is None and hist is None:
            bad.append(s)
            continue
        if hist is None:
            no_hist.append(s)          # без истории монета исказит пороги — не берём
            continue
        if live is not None:
            tail = live[live.index > hist.index[-1]]
            px[s] = pd.concat([hist, tail]) if len(tail) else hist
        else:
            px[s] = hist
        time.sleep(0.12)
    if no_hist:
        print(f"[REGIME] без истории в кэше, исключены: {len(no_hist)}")
    return pd.DataFrame(px).sort_index(), bad


def save(ts_ms, drift, breadth, label, side):
    c = conn()
    try:
        c.execute("""CREATE TABLE IF NOT EXISTS regime_state (
            ts INTEGER PRIMARY KEY, bar_ts INTEGER, drift REAL, breadth REAL,
            label TEXT, side TEXT, n_coins INTEGER)""")
        c.execute("INSERT OR REPLACE INTO regime_state VALUES (?,?,?,?,?,?,?)",
                  (int(time.time()), int(ts_ms), float(drift), float(breadth),
                   label, side, int(_N)))
        c.commit()
    finally:
        c.close()


def main():
    panel, bad = build_panel()
    global _N
    _N = panel.shape[1]
    if _N < 20:
        print(f"[REGIME] мало монет ({_N}) — не считаю")
        return 1
    R = regime_series(panel, drift_bars=DRIFT_BARS, ma_bars=MA_BARS,
                      min_periods=500, min_hold=MIN_HOLD)
    live = R.dropna(subset=["label"])
    if live.empty:
        print("[REGIME] недостаточно истории для метки")
        return 1
    row = live.iloc[-1]
    bar = pd.to_datetime(live.index[-1], unit="ms")
    label = str(row["label"])
    side, note = PRESCRIPTION.get(label, ("?", ""))
    # сколько уже длится текущий режим
    lab = live["label"]
    run = 1
    for v in lab.iloc[::-1][1:]:
        if v == label:
            run += 1
        else:
            break
    save(live.index[-1], row["drift"], row["breadth"], label, side)
    print(f"[REGIME] {bar:%d.%m.%Y %H:%M} UTC · монет {_N}"
          + (f" (нет данных: {len(bad)})" if bad else ""))
    print(f"  РЕЖИМ: {label}   (длится {run} баров 4h ≈ {run*4/24:.1f} сут)")
    print(f"  дрейф 30д: {100*row['drift']:+.2f}%   ширина рынка: {100*row['breadth']:.0f}% "
          f"монет выше своей MA")
    print(f"  → торгуем: {side} — {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
