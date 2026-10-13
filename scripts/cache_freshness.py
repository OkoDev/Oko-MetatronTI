# -*- coding: utf-8 -*-
"""Свежесть кэша свечей — страж против молчаливого сужения замеров.

🔴 Повод (24.08.2026): `ohlcv_cache.db` отстал на три недели (последний бар 31.07),
и августовские сигналы просто выпали из прогона — 224 из 330. Замер не упал и не
предупредил, он ТИХО сузился до июля, а слепой тест «июль→август» стал невозможен.
Тот же класс, что порог `min_bars` в харнессе: пустой результат вместо отказа.

Запуск:
    python scripts/cache_freshness.py            # отчёт
    python scripts/cache_freshness.py --max-age 3  # exit 1, если отставание больше
Годится и для pm2-крона: ненулевой код возврата = повод докачать.
"""
import argparse, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "ohlcv_cache.db"
sys.path.insert(0, str(ROOT))          # чтобы видеть core.infra.market_store (второе хранилище)
BAR_MIN = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}


def _mixed_sources(c) -> list:
    """Пары «монета+ТФ», где лежат ряды от РАЗНЫХ бирж (префикс `binance:` / `bingx:` / без префикса).

    🔴 13.10.2026: нашлось 45 таких пар. Цены бирж расходятся (на BTC — сотни пунктов), поэтому склейка
    даёт экстремумы, которых не было ни на одной бирже: разметка ноги и уровни врут, а замер молчит."""
    q = """SELECT base, timeframe, GROUP_CONCAT(DISTINCT src) FROM (
             SELECT CASE WHEN symbol LIKE 'binance:%' THEN 'binance'
                         WHEN symbol LIKE 'bingx:%'   THEN 'bingx' ELSE 'без префикса' END src,
                    REPLACE(REPLACE(symbol,'binance:',''),'bingx:','') base, timeframe
             FROM ohlcv_cache GROUP BY 1,2,3)
           GROUP BY base, timeframe HAVING COUNT(DISTINCT src) > 1"""
    try:
        return c.execute(q).fetchall()
    except Exception as e:                                   # noqa: BLE001
        print(f"   (источники не проверены: {type(e).__name__}: {e})")
        return []


def _store_table() -> None:
    """Второе хранилище — parquet (`core.infra.market_store`), из него читают БОТ и карточка.

    Свежесть у них разная: 13.10 в parquet 3m был текущий, а в SQLite-кэше отставал на 184 дня.
    Поэтому «проверил кэш» ничего не говорит о том, на чём работает бой, и наоборот."""
    try:
        import pandas as pd
        from core.infra import market_store as ms
    except Exception as e:                                   # noqa: BLE001
        print(f"\n(хранилище parquet не проверено: {type(e).__name__})")
        return
    now = pd.Timestamp.utcnow().tz_localize(None)
    print("\nВТОРОЕ ХРАНИЛИЩЕ — parquet (его читают бот, терминал, карточка):")
    for tf in ("3m", "5m", "15m", "1h", "4h", "1d"):
        try:
            d = ms.read_bars("BTC", tf)
            if d is None or not len(d):
                print(f"   {tf:<4} пусто")
                continue
            last = pd.Timestamp(d.index[-1]).tz_localize(None)
            age = (now - last).total_seconds() / 86400
            print(f"   {tf:<4} последний бар {last:%Y-%m-%d %H:%M} · отстаёт {age:6.2f} сут{'  🔴' if age > 2 else ''}")
        except Exception as e:                               # noqa: BLE001
            print(f"   {tf:<4} ошибка: {type(e).__name__}: {e}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age", type=float, default=2.0, help="допустимое отставание, суток")
    a = ap.parse_args()

    now = datetime.now(timezone.utc)
    c = sqlite3.connect(f"file:{CACHE}?mode=ro", uri=True)
    tfs = [r[0] for r in c.execute("SELECT DISTINCT timeframe FROM ohlcv_cache")]
    print(f"{'ТФ':<6}{'последний бар (UTC)':<24}{'отставание':>12}   источник")
    stale = []
    for tf in sorted(tfs, key=lambda x: BAR_MIN.get(x, 999)):
        # 🔴 MAX(time) по всей таблице на 19 ГБ идёт минутами: uniq-индекс начинается
        # с symbol, поэтому фильтр по timeframe его не использует. Берём ЭТАЛОННЫЙ
        # символ — запрос ложится на индекс и отвечает мгновенно.
        ref = None
        for cand in ("BTC/USDT", "ETH/USDT"):
            ref = c.execute("SELECT MAX(time) FROM ohlcv_cache WHERE symbol=? AND timeframe=?",
                            (cand, tf)).fetchone()
            if ref and ref[0]:
                ref = (ref[0], cand)
                break
            ref = None
        if not ref:
            continue
        last = datetime.fromtimestamp(ref[0] / 1000, timezone.utc)
        age = (now - last).total_seconds() / 86400
        flag = "  🔴" if age > a.max_age else ""
        if age > a.max_age:
            stale.append((tf, age))
        print(f"{tf:<6}{last:%Y-%m-%d %H:%M:%S}{'':<5}{age:>10.1f} сут{flag}   эталон {ref[1]}")
    mixed = _mixed_sources(c)
    c.close()
    _store_table()
    if mixed:
        print(f"\n🔴 ДВА ИСТОЧНИКА В ОДНОМ РЯДУ: {len(mixed)} пар «монета+ТФ» (правило 9 паспорта данных).")
        for b_, tf_, srcs in mixed[:5]:
            print(f"      {b_} {tf_}: {srcs}")
        print("   🔑 цены бирж расходятся: экстремумы ноги и уровни будут разными у замера и у графика.")
    if stale:
        print(f"\n🔴 ОТСТАЁТ: {', '.join(f'{t} на {d:.1f} сут' for t, d in stale)}")
        print("   докачать:  python scripts/fetch_binance_vision.py --tfs "
              f"{' '.join(t for t, _ in stale)} --since-day {now.strftime('%Y-%m')}-01")
        print("   🔑 пока не докачано — ЛЮБОЙ замер молча сужается до последнего бара.")
        return 1
    print("\n✅ кэш свежий")
    return 0


if __name__ == "__main__":
    sys.exit(main())
