# -*- coding: utf-8 -*-
"""Покрытие локальной сборки записи (ARCH-153, 31.10): сколько пар соберутся без REST.

Зовёт ровно тот хук, что работает в бою (`QueueReaderThread._rebuild_from_store`), по всей
вселенной хранилища Сферы 1. К бирже НЕ ходит: только диск + память читателя.

Зачем: правило «дыра → собрать локально, иначе REST» имеет смысл, лишь если сборка получается.
Замер 31.10 показал главное ограничение: ряды 3m/5m в хранилище сами с дырами (чистый ряд у
178/610), 15m — чистые у 600/610. Поэтому покрытие по ТФ разное, и его надо знать числом.

Использование:
    python scripts/ltf_rebuild_coverage.py            # 3m, 5m, 15m, глубина канона
    python scripts/ltf_rebuild_coverage.py --tf 3m --limit 150
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.infra.api_engine import OhlcvCache, _TF_STEP_MS          # noqa: E402
from core.infra.market_store import ROOT                          # noqa: E402
from core.infra.market_ws_v2 import QueueReaderThread             # noqa: E402


def coverage(tf: str, limit: int) -> Counter:
    """Сколько пар собираются: ok (полная глубина) / short (чистый хвост) / fail."""
    step = _TF_STEP_MS[tf]
    now_bar = int(time.time() * 1000) // step * step
    d = ROOT / "bingx" / tf
    if not d.exists():
        return Counter({"нет хранилища": 1})
    cache = OhlcvCache()
    rd = QueueReaderThread(q=None, cache=cache, shadow=False, spool_tfs=(tf,))
    res: Counter = Counter()
    for p in d.iterdir():
        if not p.is_dir():
            continue
        key = (f"{p.name}/USDT:USDT", tf)
        # как в бою: предыдущий бар закрылся и его держит память читателя, текущий — из WS
        rd._remember_closed(key, {"time": now_bar - step, "open": 1.0, "high": 2.0,
                                  "low": 0.5, "close": 1.2, "volume": 5.0})
        rd._last_row[key] = {"time": now_bar, "open": 1.0, "high": 2.0,
                             "low": 0.5, "close": 1.5, "volume": 10.0}
        df = rd._rebuild_from_store(key, limit)
        if df is None:
            res["fail"] += 1
        elif len(df) >= limit:
            res["ok"] += 1
        else:
            res["short"] += 1
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="покрытие локальной сборки записи по ТФ")
    ap.add_argument("--tf", default="3m,5m,15m", help="ТФ через запятую")
    ap.add_argument("--limit", type=int, default=0, help="глубина (0 = канон ApiEngine)")
    args = ap.parse_args()
    from core.infra.api_engine import _CANON_LIMIT
    for tf in [x.strip() for x in args.tf.split(",") if x.strip()]:
        limit = args.limit or _CANON_LIMIT.get(tf, 150)
        r = coverage(tf, limit)
        total = sum(r.values())
        ok_pct = 100.0 * (r["ok"] + r["short"]) / max(total, 1)
        print(f"{tf:>3} · глубина {limit:>3} · пар {total:>3} · ок {r['ok']:>3} · "
              f"короткий хвост {r['short']:>3} · не собралось {r['fail']:>3} · "
              f"покрытие {ok_pct:.0f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
