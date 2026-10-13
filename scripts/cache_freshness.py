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


LAB_TF = Path("G:/oko_lab/tf")          # лабораторные ТФ-паркеты: Binance 1m → ТФ, 477 монет


def _store_table(max_age: float) -> list:
    """Хранилищ ТРИ, у каждого своя работа (решение Егора: одно для замеров, другое для онлайна).

      • `C:/oko_data/market` (`core.infra.market_store`) — ОНЛАЙН: бот, терминал, карточка. Источник BingX.
      • `G:/oko_lab/tf`                                  — ЗАМЕРЫ: Binance 1m → ТФ, 477 монет, читают лабы.
      • `ohlcv_cache.db`                                 — старый общий кэш; его всё ещё читает харнесс.

    🔴 13.10: у них РАЗНАЯ свежесть (онлайн 0 сут · лаборатория 27 · кэш по 3m — 184). «Проверил кэш» ничего
    не говорит о том, на чём работает бой, и наоборот. Возвращает список отставших: (хранилище, ТФ, суток)."""
    stale = []
    try:
        import pandas as pd
        sys.path.insert(0, str(ROOT))
        from core.infra import market_store as ms
    except Exception as e:                                   # noqa: BLE001
        print(f"\n(хранилища parquet не проверены: {type(e).__name__})")
        return stale
    now = pd.Timestamp.utcnow().tz_localize(None)
    tfs = ("3m", "5m", "15m", "1h", "4h", "1d")

    print("\nОНЛАЙН — C:/oko_data/market (бот, терминал, карточка; BingX):")
    for tf in tfs:
        try:
            d = ms.read_bars("BTC", tf)
            if d is None or not len(d):
                print(f"   {tf:<4} пусто")
                continue
            age = (now - pd.Timestamp(d.index[-1]).tz_localize(None)).total_seconds() / 86400
            print(f"   {tf:<4} последний бар {pd.Timestamp(d.index[-1]):%Y-%m-%d %H:%M} · отстаёт {age:6.2f} сут"
                  f"{'  🔴' if age > max_age else ''}")
            if age > max_age:
                stale.append(("онлайн", tf, age))
        except Exception as e:                               # noqa: BLE001
            print(f"   {tf:<4} ошибка: {type(e).__name__}: {e}")

    print("\nЗАМЕРЫ — G:/oko_lab/tf (Binance 1m → ТФ, читают лабы):")
    for tf in tfs:
        f = LAB_TF / tf / "BTCUSDT.parquet"
        if not f.exists():
            print(f"   {tf:<4} нет файла")
            continue
        try:
            d = pd.read_parquet(f)
            last = pd.Timestamp(d.index[-1])
            age = (now - last).total_seconds() / 86400
            print(f"   {tf:<4} последний бар {last:%Y-%m-%d %H:%M} · отстаёт {age:6.1f} сут{'  🔴' if age > max_age else ''}")
            if age > max_age:
                stale.append(("замеры", tf, age))
        except Exception as e:                               # noqa: BLE001
            print(f"   {tf:<4} ошибка: {type(e).__name__}: {e}")
    return stale


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age", type=float, default=2.0, help="допустимое отставание, суток")
    ap.add_argument("--sources", action="store_true",
                    help="искать ряды от разных бирж (GROUP BY по таблице 19 ГБ — идёт минуты)")
    a = ap.parse_args()

    now = datetime.now(timezone.utc)
    c = sqlite3.connect(f"file:{CACHE}?mode=ro", uri=True)
    tfs = [r[0] for r in c.execute("SELECT DISTINCT timeframe FROM ohlcv_cache")]
    print("СТАРЫЙ ОБЩИЙ КЭШ — ohlcv_cache.db (выведен из замеров 13.10, справочно):")
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
        # Старый общий кэш (ohlcv_cache.db) выведен из замеров 13.10 (харнесс → G:/oko_lab/tf), 3m/5m в нём
        # устарели ОСОЗНАННО. Показываем, но в код возврата НЕ включаем — иначе ежедневная проверка всегда красная.
        flag = "  ⚪ (устар., вне замеров)" if age > a.max_age else ""
        print(f"{tf:<6}{last:%Y-%m-%d %H:%M:%S}{'':<5}{age:>10.1f} сут{flag}   эталон {ref[1]}")
    # 🔴 поиск смешанных рядов идёт ~8 мин на таблице 19 ГБ — для ежедневной проверки это дорого,
    # поэтому по умолчанию выключен: разовая ревизия запускается флагом --sources
    mixed = _mixed_sources(c) if a.sources else []
    c.close()
    stale += [(f'{w}/{tf}', age) for w, tf, age in _store_table(a.max_age)]
    if mixed:
        print(f"\n🔴 ДВА ИСТОЧНИКА В ОДНОМ РЯДУ: {len(mixed)} пар «монета+ТФ» (правило 9 паспорта данных).")
        for b_, tf_, srcs in mixed[:5]:
            print(f"      {b_} {tf_}: {srcs}")
        print("   🔑 цены бирж расходятся: экстремумы ноги и уровни будут разными у замера и у графика.")
    if stale:
        cache_tfs = [t for t, _ in stale if "/" not in t]
        lab_tfs = [t.split("/", 1)[1] for t, _ in stale if t.startswith("замеры/")]
        live_tfs = [t.split("/", 1)[1] for t, _ in stale if t.startswith("онлайн/")]
        print(f"\n🔴 ОТСТАЁТ: {', '.join(f'{t} на {d:.1f} сут' for t, d in stale)}")
        if cache_tfs:
            print(f"   общий кэш ({', '.join(cache_tfs)}): python scripts/fetch_binance_vision.py "
                  f"--tfs {' '.join(cache_tfs)} --since-day {now.strftime('%Y-%m')}-01")
        if lab_tfs:
            print(f"   паркеты замеров ({', '.join(lab_tfs)}): пересобрать G:/oko_lab/tf из 1m-паркетов C:/oko_data/history/1m")
        if live_tfs:
            print(f"   🔴 ОНЛАЙН ({', '.join(live_tfs)}) — это данные БОЯ: проверить market-store и поток свечей")
        return 1
    print("\n✅ кэш свежий")
    return 0


if __name__ == "__main__":
    sys.exit(main())
