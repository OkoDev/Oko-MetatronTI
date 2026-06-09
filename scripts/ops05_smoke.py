#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""OPS-05 smoke-тест: регресс check_open_trades_with_tsl ДО/ПОСЛЕ параллелизации.

Идея (детерминизм): снимаем snapshot OHLCV для символов OPEN-сделок ОДИН раз →
MockDC отдаёт зафиксированные данные → check_open даёт ВОСПРОИЗВОДИМЫЙ результат.
Прогон «до» (последовательный) и «после» (параллельный) на ОДНОЙ копии БД + ОДНОМ
snapshot → результаты ДОЛЖНЫ СОВПАСТЬ (closed_count, какие сделки закрылись, статусы).

Режимы:
  python scripts/ops05_smoke.py --baseline   # снять snapshot + baseline (ДО рефактора)
  python scripts/ops05_smoke.py --compare    # прогнать снова, сверить с baseline (ПОСЛЕ)

Защита close_trade: работаем на КОПИИ БД (subscriptions_smoke.db), боевую не трогаем.
"""
import sys, os, shutil, json, pickle, asyncio, argparse
sys.path.insert(0, r"e:/MTF BOT/CURSOR/crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv; load_dotenv()
import sqlite3

SRC_DB = "subscriptions.db"
SMOKE_DB = "subscriptions_smoke.db"
SMOKE_ORIG = "subscriptions_smoke_orig.db"  # эталонная копия (фиксируется при --baseline)
SNAP = "data/research/ops05_ohlcv_snapshot.pkl"
BASELINE = "data/research/ops05_baseline.json"
N_TRADES = 25  # выборка OPEN-сделок для теста (скорость + детерминизм)


class MockDC:
    """Детерминированный data_collector: отдаёт зафиксированный OHLCV из snapshot."""
    def __init__(self, snap: dict):
        self.snap = snap  # {(symbol, tf): list_of_ohlcv}
        self.misses = 0

    async def get_ohlcv(self, symbol, timeframe="15m", limit=150, since=None, force_refresh=False):
        import pandas as pd
        key = (symbol, timeframe)
        data = self.snap.get(key)
        if data is None:
            self.misses += 1
            return None
        df = pd.DataFrame(data, columns=["time", "open", "high", "low", "close", "volume"])
        return df.tail(limit).reset_index(drop=True)

    async def get_ticker(self, symbol):
        # последняя цена из 15m snapshot
        d = self.snap.get((symbol, "15m")) or self.snap.get((symbol, "1h"))
        if d:
            return {"last": d[-1][4], "quoteVolume": 0}
        return None


def _select_trades():
    c = sqlite3.connect(SRC_DB)
    rows = c.execute(
        "SELECT id, symbol FROM simulated_trades WHERE status='OPEN' ORDER BY id DESC LIMIT ?",
        (N_TRADES,)).fetchall()
    c.close()
    return rows


async def _snapshot_ohlcv(symbols):
    """Реальный fetch OHLCV для символов (15m/1h/4h) → snapshot dict."""
    import ccxt.async_support as ccxt
    ex = ccxt.bingx({"enableRateLimit": True})
    snap = {}
    try:
        for sym in symbols:
            for tf, lim in [("15m", 200), ("1h", 200), ("4h", 100)]:
                try:
                    o = await ex.fetch_ohlcv(sym, tf, limit=lim)
                    if o:
                        snap[(sym, tf)] = o
                except Exception:
                    pass
    finally:
        await ex.close()
    return snap


async def _run_check_open(db_path, snap):
    """Прогон check_open на копии БД с MockDC. Возвращает (closed_count, статусы после)."""
    from core.trading.trade_simulator import TradeSimulator
    ts = TradeSimulator(db_path=db_path)
    before = _statuses(db_path)
    closed_count, tsl_moved = await ts.check_open_trades_with_tsl(MockDC(snap))
    after = _statuses(db_path)
    changed = {tid: (before.get(tid), after.get(tid)) for tid in before if before.get(tid) != after.get(tid)}
    return {"closed_count": closed_count, "tsl_moved_n": len(tsl_moved or []),
            "changed": {str(k): v for k, v in changed.items()}}


def _statuses(db_path):
    c = sqlite3.connect(db_path)
    d = dict(c.execute("SELECT id, status FROM simulated_trades").fetchall())
    c.close()
    return d


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--compare", action="store_true")
    a = ap.parse_args()
    os.makedirs("data/research", exist_ok=True)

    if a.baseline:
        trades = _select_trades()
        syms = sorted({s for _, s in trades})
        print(f"Выборка: {len(trades)} OPEN-сделок, {len(syms)} символов. Снимаю OHLCV snapshot...")
        snap = await _snapshot_ohlcv(syms)
        pickle.dump(snap, open(SNAP, "wb"))
        print(f"Snapshot: {len(snap)} (symbol,tf) серий → {SNAP}")
        shutil.copy(SRC_DB, SMOKE_ORIG)   # ЭТАЛОН — фиксируем состояние БД для обоих прогонов
        shutil.copy(SMOKE_ORIG, SMOKE_DB)
        print(f"Эталонная копия БД → {SMOKE_ORIG} (compare возьмёт ИЗ НЕЁ, не из боевой)")
        res = await _run_check_open(SMOKE_DB, snap)
        json.dump(res, open(BASELINE, "w"), ensure_ascii=False, indent=2)
        print(f"\n✅ BASELINE (ДО рефактора):")
        print(f"   closed_count={res['closed_count']} tsl_moved={res['tsl_moved_n']} changed={len(res['changed'])}")
        print(f"   → сохранён {BASELINE}. После рефактора: python scripts/ops05_smoke.py --compare")

    elif a.compare:
        snap = pickle.load(open(SNAP, "rb"))
        base = json.load(open(BASELINE))
        shutil.copy(SMOKE_ORIG, SMOKE_DB)  # из ЭТАЛОНА (то же состояние что baseline!)
        res = await _run_check_open(SMOKE_DB, snap)
        print(f"BASELINE: closed={base['closed_count']} tsl={base['tsl_moved_n']} changed={len(base['changed'])}")
        print(f"ПОСЛЕ:    closed={res['closed_count']} tsl={res['tsl_moved_n']} changed={len(res['changed'])}")
        # нормализация: JSON конвертит tuple→list, сравниваем через json.dumps (tuple==list по содержанию)
        _norm = lambda d: json.dumps({k: list(v) for k, v in d.items()}, sort_keys=True)
        same = (res["closed_count"] == base["closed_count"]
                and res["tsl_moved_n"] == base["tsl_moved_n"]
                and _norm(res["changed"]) == _norm(base["changed"]))
        print(f"\n{'✅ ИДЕНТИЧНО — рефактор НЕ изменил поведение!' if same else '🔴 РАСХОЖДЕНИЕ — рефактор сломал логику!'}")
        if not same:
            b, r = set(base["changed"]), set(res["changed"])
            print(f"   только в baseline: {b - r}")
            print(f"   только после: {r - b}")
    else:
        print("Укажи --baseline (ДО) или --compare (ПОСЛЕ)")


if __name__ == "__main__":
    asyncio.run(main())
