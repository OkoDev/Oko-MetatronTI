# -*- coding: utf-8 -*-
"""ЕЖЕДНЕВНОЕ ОБНОВЛЕНИЕ ИССЛЕДОВАТЕЛЬСКИХ ДАННЫХ (Егор 07.10: «журнал заканчивается 3 сентября? т.е. свежие
данные не собираются?» — не собирались: кэш свечей отстал на 45 дней, метрики без расписания, журнал собран
один раз; страж свежести был, но в расписании не стоял).

Шаги (каждый — отдельный процесс; упавший шаг пишется громко и не роняет следующие):
  1. свечи 15m/1h/4h/1d с data.binance.vision ДНЕВНЫМИ архивами за последние 3 дня
     (запас на поздние публикации; INSERT OR IGNORE — повтор безвреден). 🔴 Binance — только через VPN:
     загрузчик ходит обычным urllib, без привязки к интерфейсу в обход туннеля
  2. позиционирование Binance (fetch_binance_metrics.py докачивает только недостающие дни)
  3. журнал общего состояния — полная пересборка (`joint_state_journal.py run N --force`)
  4. страж свежести кэша — отставание видно в логе

pm2: pm2 start <python.exe> --name joint-daily --interpreter none --cron "30 9 * * *" --no-autorestart
     -- scripts/joint_daily.py          (09:30 МСК = 06:30 UTC: дневные архивы Binance к этому времени есть)
Лог: G:/oko_lab/out/joint_daily.log
"""
from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
LOG = Path("G:/oko_lab/out/joint_daily.log")
PROCS = 6                       # пересборка журнала днём: бот работает рядом, не забирать все ядра


def step(name: str, args: list[str]) -> bool:
    t0 = time.time()
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M} · {name}: {' '.join(args)}\n")
        f.flush()
        r = subprocess.run([PY, *args], cwd=ROOT, stdout=f, stderr=subprocess.STDOUT,
                           env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
        f.write(f"=== {name}: код {r.returncode} · {time.time() - t0:.0f} с"
                f"{'  🔴 ШАГ УПАЛ' if r.returncode else ''}\n")
    return r.returncode == 0


def main() -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    since = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
    ok = step("свечи", ["scripts/fetch_binance_vision.py", "--tfs", "15m", "1h", "4h", "1d",
                        "--since-day", since, "--universe", "cache"])
    ok &= step("метрики", ["scripts/fetch_binance_metrics.py"])
    ok &= step("журнал", ["scripts/joint_state_journal.py", "run", str(PROCS), "--force"])
    step("свежесть", ["scripts/cache_freshness.py"])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
