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
BAR_MIN = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}


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
    c.close()
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
