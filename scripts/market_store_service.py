# -*- coding: utf-8 -*-
"""Сервис Сферы 1: наполняет хранилище закрытых баров BingX (core/infra/market_store.py, BACKLOG N15).

Единственный процесс, который качает свечи для хранилища; все остальные читают read_bars(...).
Канал — core/waves/bingx_klines.fetch_closed (v3, только закрытые бары; сверен с ccxt 28.09: 0 расхождений).

Два режима в одном цикле:
  1) начальная глубина (однократно, возобновляемо): 4h → 1h → 1d → 15m → 5m → 3m — 4h первым, он нужен первому
     клиенту (oko-sm-watch, 4h × 1000);
  2) живая догрузка каждую минуту: для 1h/4h/1d после закрытия бара качается только то, чего нет
     (n = бары с последнего сохранённого + 1). 3m/5m/15m живьём ведёт WebSocket бота через очередь
     core/infra/market_spool (29.09): сервис забирает её раз в минуту (писатель один — этот сервис), а раз в час
     по REST лечит пропуски (бот стоял). REST по 3m/5m для 620 пар живьём = ~5 запросов/с — выше лимита прямого IP.

Лимит — 3 запроса/с на весь процесс (bingx_klines.set_min_interval): бот уже переживал баны BingX,
а сервис ходит без прокси.

pm2: pm2 start python --name market-store --interpreter none -- scripts/market_store_service.py
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.infra import market_store as ms  # noqa: E402
from core.trading.source_registry import _TF_MIN as TF_MIN  # noqa: E402
from core.waves import bingx_klines  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

DEPTH = {"4h": 2_190, "1h": 8_760, "1d": 1_500, "15m": 8_640, "5m": 8_640, "3m": 14_400}   # ≈ 1г · 1г · 4г · 90д · 30д · 30д
LIVE_TFS = ["4h", "1d", "1h"]            # REST после закрытия бара; 3m/5m/15m — очередь WS бота (SPOOL_TFS)
TICKER = "https://open-api.bingx.com/openApi/swap/v2/quote/ticker"
RPS = 3.0
WORKERS = 16                                                                           # запросы в полёте (латентность 1–20 с)


def universe() -> list[str]:
    """USDT-свопы BingX без синтетики, по обороту (ликвидные первыми)."""
    d = json.loads(urllib.request.urlopen(urllib.request.Request(TICKER, headers={"User-Agent": "oko"}), timeout=20).read())
    rows = [(float(t.get("quoteVolume") or 0), t["symbol"].split("-")[0]) for t in d.get("data", [])
            if t.get("symbol", "").endswith("-USDT")]
    return [b for _, b in sorted(rows, reverse=True) if not ms.is_synthetic(b)]


def tf_ms(tf: str) -> int:
    return TF_MIN[tf] * 60_000


# 29.09: приём очереди WS и лечение идут СВОИМИ потоками (иначе проход 1h/4h/1d по 584 монетам по 5 мин и лечение
# держали приём до получаса — клиенты хранилища видели 15m/3m устаревшими). Процесс-писатель по-прежнему один,
# а запись одного файла (монета, ТФ) — под своим замком: лечение и приём пишут одни и те же 3m/5m/15m.
_locks: dict = {}
_locks_guard = threading.Lock()


def _append(base: str, tf: str, df) -> int:
    with _locks_guard:
        lk = _locks.setdefault((base, tf), threading.Lock())
    with lk:
        return ms.append_bars(base, tf, df)


def top_up(base: str, tf: str, depth: int | None = None) -> int:
    """Докачать недостающее. depth задан и в хранилище пусто → начальная глубина."""
    last = ms.last_time(base, tf)
    now = int(pd.Timestamp.utcnow().value // 1_000_000)
    if last is None:
        if depth is None:
            return 0
        n = depth
    else:
        n = int((now - last) // tf_ms(tf))            # сколько баров могло закрыться после последнего
        if n < 1:
            return 0
        n = min(n + 1, max(depth or 0, 1000))
    df = bingx_klines.fetch_closed(base, tf, n)
    return _append(base, tf, df) if len(df) else 0


def _safe(b: str, tf: str, depth: int | None) -> int:
    try:
        return top_up(b, tf, depth)
    except Exception as e:  # noqa: BLE001
        print(f"[market-store] {b} {tf}: {type(e).__name__}: {e}")
        return 0


def backfill(bases: list[str]) -> None:
    for tf, depth in DEPTH.items():
        t0, added = time.time(), 0
        todo = [b for b in bases if ms.last_time(b, tf) is None]
        # параллельно: прямой BingX отвечает 1–20 с, темп всё равно держит set_min_interval (≤ RPS)
        with ThreadPoolExecutor(WORKERS) as pool:
            for i, n in enumerate(pool.map(lambda b: _safe(b, tf, depth), todo), 1):
                added += n
                if i % 100 == 0:
                    print(f"[market-store] глубина {tf}: {i}/{len(todo)} · +{added:,} баров · {time.time() - t0:.0f} с")
        print(f"[market-store] глубина {tf} готова: {len(todo)} монет, +{added:,} баров за {time.time() - t0:.0f} с")


def live_pass(bases: list[str], last_close: dict) -> None:
    now = int(pd.Timestamp.utcnow().value // 1_000_000)
    for tf in LIVE_TFS:
        close = now // tf_ms(tf) * tf_ms(tf)          # время закрытия последнего завершённого бара
        if last_close.get(tf) == close:
            continue
        t0 = time.time()
        with ThreadPoolExecutor(WORKERS) as pool:
            added = sum(pool.map(lambda b: _safe(b, tf, None), bases))
        last_close[tf] = close
        print(f"[market-store] {tf} закрыт {pd.to_datetime(close, unit='ms'):%m-%d %H:%M} UTC: "
              f"+{added} баров по {len(bases)} монетам за {time.time() - t0:.0f} с")


# живьём ведёт очередь WS бота (market_spool); REST — только лечение пропусков. 15m переведён 29.09 (Егор):
# после досылки финала бар из потока = биржевой (сверка 3m/5m 440 баров — 100%), минус ~2 300 REST/ч.
SPOOL_TFS = ("3m", "5m", "15m")


def ingest_spool() -> int:
    """Закрытые бары из очереди WS бота → хранилище. Писатель хранилища один — этот сервис."""
    from core.infra import market_spool
    files = market_spool.completed_files()
    if not files:
        return 0
    parts = []
    for p in files:
        try:
            parts.append(pd.read_csv(p, header=None, names=list(market_spool.FIELDS)))
        except Exception as e:  # noqa: BLE001 — битый/пустой файл не должен стопорить остальные
            print(f"[market-store] очередь {p.name}: {type(e).__name__}: {e}")
    added = 0
    if parts:
        df = pd.concat(parts, ignore_index=True)
        for c in ("time", *ms.COLS):     # до 29.09 15:10 бот писал «np.float64(0.323)» — снимаем обёртку
            if df[c].dtype == object:
                df[c] = df[c].astype(str).str.replace(r"^np\.float64\((.*)\)$", r"\1", regex=True)
            df[c] = pd.to_numeric(df[c], errors="coerce")
        bad = int(df[["time", *ms.COLS]].isna().any(axis=1).sum())
        if bad:
            print(f"[market-store] очередь: {bad} нечисловых строк отброшено")
        df = df.dropna(subset=["time", *ms.COLS]).astype({"time": "int64"})
        for (base, tf), g in df.groupby(["base", "tf"]):
            added += _append(base, tf, g[["time", *ms.COLS]])
    for p in files:
        p.unlink(missing_ok=True)
    return added


HEAL_WINDOW_MS = 48 * 3_600_000          # простой 24–25.09 длился 36 ч; 3m × 48 ч = 960 баров ≤ 1000 за запрос


def first_hole(base: str, tf: str, now: int) -> int | None:
    """Время первого отсутствующего бара за последние сутки (дыра внутри ИЛИ отставший хвост) или None.
    По last_time дыру внутри не видно: бот стоял 10:00–10:05, очередь продолжила с 10:05 — хвост свежий."""
    step = tf_ms(tf)
    t = ms.read_bars(base, tf, since_ms=now - HEAL_WINDOW_MS).index.asi8 // 1_000_000
    if len(t) == 0:
        return now - HEAL_WINDOW_MS
    gaps = (t[1:] - t[:-1] != step).nonzero()[0]
    if len(gaps):
        return int(t[gaps[0]] + step)
    last_closed = now // step * step - step
    return int(t[-1] + step) if t[-1] < last_closed - step else None   # 1 бар допуска: очередь не забрана


def _heal_one(base: str, tf: str, now: int) -> int:
    try:
        hole = first_hole(base, tf, now)
        if hole is None:
            return 0
        n = min(int((now - hole) // tf_ms(tf)) + 1, 1000)
        df = bingx_klines.fetch_closed(base, tf, n)
        return _append(base, tf, df) if len(df) else 0
    except Exception as e:  # noqa: BLE001
        print(f"[market-store] лечение {base} {tf}: {type(e).__name__}: {e}")
        return 0


# СВЕРКА (Егор 29.09, вариант A): бары из очереди WS ≈ биржевые, но не эталон — в обычном режиме неточны ~0.7–3%
# (объём, изредка close), в сбоях почти все (закрытие 14:30 UTC, рестарты). Раз в час (в :30, мимо прохода 1h/4h/1d
# в начале часа) закрытые бары последних 75 мин перекачиваются по REST поверх очереди — каждый бар хранилища
# становится биржевым не позже чем через час; 75 > 60 — бар на стыке запусков проверяется дважды.
SETTLE_MIN = 75


def _settle_one(base: str, tf: str) -> tuple[int, int, int]:
    """(не было, отличался, проверено) — REST-бары окна пишутся поверх хранилища."""
    try:
        rest = bingx_klines.fetch_closed(base, tf, SETTLE_MIN * 60_000 // tf_ms(tf) + 1)
        if rest.empty:
            return 0, 0, 0
        have = ms.read_bars(base, tf, since_ms=int(rest.index[0].value // 1_000_000))
        j = rest.join(have, how="left", rsuffix="_s")
        missing = j["close_s"].isna()
        diff = pd.Series(False, index=j.index)
        for c in ms.COLS:
            diff |= (j[c] - j[f"{c}_s"]).abs() > 1e-9 * j[c].abs().clip(lower=1e-12)
        _append(base, tf, rest)
        return int(missing.sum()), int((diff & ~missing).sum()), len(rest)
    except Exception as e:  # noqa: BLE001
        print(f"[market-store] сверка {base} {tf}: {type(e).__name__}: {e}")
        return 0, 0, 0


def settle_ltf(bases: list[str]) -> None:
    for tf in SPOOL_TFS:
        t0 = time.time()
        with ThreadPoolExecutor(WORKERS) as pool:
            res = list(pool.map(lambda b: _settle_one(b, tf), bases))
        miss, diff, checked = (sum(r[i] for r in res) for i in range(3))
        n = max(checked, 1)
        print(f"[market-store] сверка {tf}: баров {checked} · не было {miss} ({100 * miss / n:.1f}%) · "
              f"неточных из очереди {diff} ({100 * diff / n:.2f}%) · за {time.time() - t0:.0f} с")


def heal_ltf(bases: list[str]) -> None:
    """Раз в час: 3m/5m, где очередь не покрыла (бот стоял, монеты нет в WS бота) — докачать по REST.
    Монеты без дыр запросов не получают."""
    now = int(pd.Timestamp.utcnow().value // 1_000_000)
    for tf in SPOOL_TFS:
        t0 = time.time()
        with ThreadPoolExecutor(WORKERS) as pool:
            res = list(pool.map(lambda b: _heal_one(b, tf, now), bases))
        print(f"[market-store] лечение {tf}: {sum(1 for r in res if r)} монет с дырами · +{sum(res)} баров "
              f"за {time.time() - t0:.0f} с")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", help="ограничить вселенную (для проверки)")
    ap.add_argument("--once", action="store_true", help="глубина + один проход догрузки, без цикла")
    a = ap.parse_args()
    bingx_klines.set_min_interval(1.0 / RPS)
    bases = [s.upper() for s in a.symbols] if a.symbols else universe()
    print(f"[market-store] {len(bases)} монет · хранилище {ms.ROOT} · {RPS:g} запр/с")
    backfill(bases)

    def _every_minute(job, name):
        while True:
            try:
                job()
            except Exception as e:  # noqa: BLE001 — поток не должен умирать от одной ошибки
                print(f"[market-store] {name}: {type(e).__name__}: {e}")
            time.sleep(60 - time.time() % 60 + 5)          # раз в минуту, через 5 с после её начала

    def _ingest():
        n = ingest_spool()
        if n:
            print(f"[market-store] очередь WS: +{n} баров")

    heal_state = {"last": 0.0, "settle_hour": -1}

    def _heal():                     # один поток: лечение дыр раз в час + сверка в :30
        if time.time() - heal_state["last"] >= 3600:
            heal_ltf(bases)
            heal_state["last"] = time.time()
        now = time.time()
        if 30 <= time.gmtime(now).tm_min < 40 and heal_state["settle_hour"] != int(now // 3600):
            heal_state["settle_hour"] = int(now // 3600)
            settle_ltf(bases)

    last_close: dict = {}
    if a.once:
        _ingest(); live_pass(bases, last_close); heal_ltf(bases); settle_ltf(bases)
        return
    threading.Thread(target=_every_minute, args=(_ingest, "очередь WS"), name="ingest", daemon=True).start()
    threading.Thread(target=_every_minute, args=(_heal, "лечение"), name="heal", daemon=True).start()
    _every_minute(lambda: live_pass(bases, last_close), "проход 1h/4h/1d")


if __name__ == "__main__":
    main()
