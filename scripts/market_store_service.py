# -*- coding: utf-8 -*-
"""Сервис Сферы 1: наполняет хранилище закрытых баров BingX (core/infra/market_store.py, BACKLOG N15).

Единственный процесс, который качает свечи для хранилища; все остальные читают read_bars(...).
Канал — core/waves/bingx_klines.fetch_closed (v3, только закрытые бары; сверен с ccxt 28.09: 0 расхождений).

Два режима в одном цикле:
  1) начальная глубина (однократно, возобновляемо): 4h → 1h → 1d → 15m → 5m → 3m — 4h первым, он нужен первому
     клиенту (oko-sm-watch, 4h × 1000);
  2) живая догрузка каждую минуту: для 15m/1h/4h/1d после закрытия бара качается только то, чего нет
     (n = бары с последнего сохранённого + 1). 3m/5m живьём ведёт хук WebSocket-процесса бота (следующий шаг N15):
     REST по ним для 620 пар = ~5 запросов/с — больше, чем даёт безопасный лимит прямого IP.

Лимит — 3 запроса/с на весь процесс (bingx_klines.set_min_interval): бот уже переживал баны BingX,
а сервис ходит без прокси.

pm2: pm2 start python --name market-store --interpreter none -- scripts/market_store_service.py
"""
from __future__ import annotations

import argparse
import json
import sys
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
LIVE_TFS = ["4h", "1d", "1h", "15m"]                                                   # редкие и важные — первыми
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
    return ms.append_bars(base, tf, df) if len(df) else 0


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", help="ограничить вселенную (для проверки)")
    ap.add_argument("--once", action="store_true", help="глубина + один проход догрузки, без цикла")
    a = ap.parse_args()
    bingx_klines.set_min_interval(1.0 / RPS)
    bases = [s.upper() for s in a.symbols] if a.symbols else universe()
    print(f"[market-store] {len(bases)} монет · хранилище {ms.ROOT} · {RPS:g} запр/с")
    backfill(bases)
    last_close: dict = {}
    while True:
        live_pass(bases, last_close)
        if a.once:
            break
        time.sleep(60 - time.time() % 60 + 5)             # раз в минуту, через 5 с после её начала


if __name__ == "__main__":
    main()
