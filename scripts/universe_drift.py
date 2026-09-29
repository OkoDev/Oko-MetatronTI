"""
universe_drift.py — ДРЕЙФ ВСЕЛЕННОЙ в реальном времени.

Зачем: 21.08.2026 слепой тест (дважды, независимо) показал, что short механики
impulse_fib резко улучшается, когда медианная 30-дневная доходность вселенной
высока — фейдим отскок внутри падающего рынка:

    short + drift30 >= +10%  →  OOS PF 5.54 против базы 1.22, охват 59%

Боевой `ohlcv_cache.db` для этого не годится — он отстаёт на 20 дней.
Поэтому качаем дневные бары сами, инкрементально, и держим в своей таблице.

🔴 ПРИЧИННОСТЬ: дрейф на дату D считается по барам, ЗАКРЫТЫМ до D включительно,
а потребитель обязан брать значение за ВЧЕРА (лаг 1 день) — ровно как в замере.
Сегодняшний незакрытый день в расчёт не идёт.

Запуск:
    python scripts/universe_drift.py              # инкрементально (3 бара/монету)
    python scripts/universe_drift.py --bootstrap  # первичная загрузка (250 баров)
    python scripts/universe_drift.py --show       # показать последние значения
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_DB = ROOT / "ohlcv_cache.db"
# N16 29.09: своя база (один писатель), не subscriptions.db; путь = core/infra/sat_store.path("universe")
UNIVERSE_DB = ROOT / "oko_feed" / "universe.db"
API = "https://fapi.binance.com/fapi/v1/klines"
NL = chr(10)
WORKERS = 6
MIN_COINS = 20          # ниже этого медиана по вселенной не считается

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass


def _binance_symbol(sym: str) -> str:
    """'BTC/USDT:USDT' → 'BTCUSDT'."""
    return sym.split(":")[0].replace("/", "").replace("-", "")


def _universe() -> list[str]:
    """Вселенная = символы с достаточной историей в боевом кэше."""
    with sqlite3.connect(f"file:{CACHE_DB}?mode=ro", uri=True) as c:
        rows = c.execute(
            "SELECT symbol FROM ohlcv_cache WHERE timeframe='1h' "
            "GROUP BY symbol HAVING COUNT(*)>4000"
        ).fetchall()
    return [r[0] for r in rows]


def _init_db() -> None:
    with sqlite3.connect(UNIVERSE_DB, timeout=30) as c:
        c.execute("PRAGMA busy_timeout=10000")
        c.execute("""
            CREATE TABLE IF NOT EXISTS universe_daily (
                symbol TEXT NOT NULL,
                day    TEXT NOT NULL,
                close  REAL NOT NULL,
                PRIMARY KEY (symbol, day)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS universe_drift (
                day       TEXT PRIMARY KEY,
                drift30   REAL,
                drift90   REAL,
                drift180  REAL,
                n_coins   INTEGER,
                updated_at TEXT NOT NULL
            )
        """)


def _fetch(sym: str, limit: int) -> tuple[str, list[tuple[str, float]]]:
    url = f"{API}?symbol={_binance_symbol(sym)}&interval=1d&limit={limit}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "oko-mtf/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code in (400, 404):        # пары нет на Binance — норма для BingX-эксклюзивов
            return sym, []
        raise
    except Exception:                    # noqa: BLE001
        return sym, []
    out = []
    now_ms = int(time.time() * 1000)
    for k in data:
        close_ms = int(k[6])
        if close_ms >= now_ms:           # 🔴 незакрытый день — не берём
            continue
        day = datetime.fromtimestamp(int(k[0]) / 1000, timezone.utc).strftime("%Y-%m-%d")
        out.append((day, float(k[4])))
    return sym, out


def refresh(limit: int) -> int:
    syms = _universe()
    print(f"вселенная: {len(syms)} символов, тянем по {limit} дневных баров")
    rows, ok, miss = [], 0, 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(_fetch, s, limit): s for s in syms}
        for i, f in enumerate(as_completed(futs), 1):
            sym, bars = f.result()
            if bars:
                ok += 1
                rows.extend((sym, d, c) for d, c in bars)
            else:
                miss += 1
            if i % 100 == 0:
                print(f"  ... {i}/{len(syms)} (получено {ok}, пусто {miss})", flush=True)
    with sqlite3.connect(UNIVERSE_DB, timeout=30) as c:
        c.execute("PRAGMA busy_timeout=10000")
        c.executemany("INSERT OR REPLACE INTO universe_daily (symbol,day,close) VALUES (?,?,?)", rows)
    print(f"записано баров: {len(rows)} · монет с данными: {ok} · без данных: {miss}")
    return ok


def compute() -> None:
    """Пересчёт дрейфа по всей накопленной истории."""
    import numpy as np
    import pandas as pd

    with sqlite3.connect(f"file:{UNIVERSE_DB}?mode=ro", uri=True) as c:
        df = pd.read_sql("SELECT symbol,day,close FROM universe_daily", c)
    if df.empty:
        print("🔴 нет данных — сначала --bootstrap"); return
    px = df.pivot(index="day", columns="symbol", values="close").sort_index()
    px.index = pd.to_datetime(px.index, utc=True)
    alive = px.notna().sum(axis=1)
    out = {}
    for win, name in ((30, "drift30"), (90, "drift90"), (180, "drift180")):
        r = (px.pct_change(win, fill_method=None) * 100).median(axis=1)
        out[name] = r.where(alive >= MIN_COINS)
    res = pd.DataFrame(out)
    res["n_coins"] = alive
    res = res.dropna(subset=["drift30"])
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with sqlite3.connect(UNIVERSE_DB, timeout=30) as c:
        c.execute("PRAGMA busy_timeout=10000")
        c.executemany(
            "INSERT OR REPLACE INTO universe_drift "
            "(day,drift30,drift90,drift180,n_coins,updated_at) VALUES (?,?,?,?,?,?)",
            [(d.strftime("%Y-%m-%d"),
              None if np.isnan(r.drift30) else float(r.drift30),
              None if np.isnan(r.drift90) else float(r.drift90),
              None if np.isnan(r.drift180) else float(r.drift180),
              int(r.n_coins), now)
             for d, r in res.iterrows()])
    print(f"дрейф пересчитан: {len(res)} дней, {px.index[0].date()} → {px.index[-1].date()}")
    show()


def show(n: int = 8) -> None:
    with sqlite3.connect(f"file:{UNIVERSE_DB}?mode=ro", uri=True) as c:
        rows = c.execute(
            "SELECT day,drift30,drift90,drift180,n_coins FROM universe_drift "
            "ORDER BY day DESC LIMIT ?", (n,)).fetchall()
    if not rows:
        print("нет значений"); return
    print(f"\n  {'день':<12}{'drift30':>10}{'drift90':>10}{'drift180':>10}{'монет':>8}   сигнал")
    for d, d30, d90, d180, nc in rows:
        f = lambda x: "—" if x is None else f"{x:+.1f}%"  # noqa: E731
        # порог из ПРОЙДЕННОГО слепого теста (два независимых прогона)
        sig = "🟢 SHORT-ЗОНА" if (d30 is not None and d30 >= 10) else ""
        print(f"  {d:<12}{f(d30):>10}{f(d90):>10}{f(d180):>10}{nc:>8}   {sig}")
    print("\n  🔑 порог drift30 ≥ +10% — из слепого теста (OOS PF 5.54 против базы 1.22).")
    print("  🔴 Потребитель обязан брать значение за ВЧЕРА (лаг 1 день), как в замере.")


def announce_zone() -> None:
    """
    Сообщает о СМЕНЕ состояния зоны: открылась / закрылась.

    Зона — условие, при котором дрейф-гейт пропускает short на 15m
    (`trading.impulse_fib_15m.drift_gate`). Её открытие означает, что стратегия
    НАЧНЁТ торговать, закрытие — что перестанет. Это не «полезно знать»,
    а событие, меняющее поведение системы.

    Куб: состояние пишется в `watch_state`, откуда `core/context/watch_bridge.py`
    публикует его в шину как `regime_change` — узнают все сферы, а не только
    Telegram. Плюс след в TASKS.md: сообщение можно пропустить, задачу — нет.
    """
    try:
        sys.path.insert(0, str(ROOT))
        from core.context.universe_drift import get_drift
        from core.infra.config_loader import config
        from scripts._alert import notify
    except Exception as e:                                       # noqa: BLE001
        print(f"  оповещение недоступно: {type(e).__name__}: {e}")
        return
    d = get_drift()
    if d is None or d.get("drift30") is None:
        return
    g = (config.get("trading.impulse_fib_15m.drift_gate") or {})
    thr_d = float(g.get("min_drift30", 5.0))
    thr_s = g.get("min_slope180")
    d30, sl = float(d["drift30"]), d.get("slope180")
    ok_d = d30 >= thr_d
    ok_s = True if (thr_s is None or sl is None) else float(sl) >= float(thr_s)
    inside = ok_d and ok_s
    state = "IN" if inside else "OUT"
    sl_txt = "—" if sl is None else f"{float(sl):+.1f}"
    body = (f"drift30 {d30:+.2f}% (нужно {thr_d:+.1f}) · производная {sl_txt} "
            f"(нужно {'—' if thr_s is None else f'{float(thr_s):+.1f}'}) · день {d['day']}")
    res = notify(
        "drift_zone", state,
        title="Зона дрейфа · short 15m",
        tg_text=("*ЗОНА ОТКРЫЛАСЬ* — short на 15m пойдёт в работу" + NL + body
                 if inside else "*Зона закрылась* — short на 15m снова заблокирован"
                 + NL + body),
        task_detail=(("**Зона открылась** — impulse_fib_15m начнёт торговать. " + body)
                     if inside else ("Зона закрылась, гейт блокирует. " + body)),
    )
    if res["tg"] or res["tasks"]:
        print(f"  🔔 зона {res['prev']} → {state}: telegram="
              f"{'✅' if res['tg'] else '—'} · TASKS.md={'✅' if res['tasks'] else '—'}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Дрейф вселенной для режимного фильтра")
    ap.add_argument("--bootstrap", action="store_true", help="первичная загрузка (250 баров)")
    ap.add_argument("--show", action="store_true", help="только показать последние значения")
    a = ap.parse_args()
    _init_db()
    if a.show:
        show(14); return 0
    refresh(250 if a.bootstrap else 3)
    compute()
    announce_zone()
    return 0


if __name__ == "__main__":
    sys.exit(main())
