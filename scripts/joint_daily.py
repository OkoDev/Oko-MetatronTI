# -*- coding: utf-8 -*-
"""ЕЖЕДНЕВНОЕ ОБНОВЛЕНИЕ ИССЛЕДОВАТЕЛЬСКИХ ДАННЫХ (Егор 07.10: «журнал заканчивается 3 сентября? т.е. свежие
данные не собираются?» — не собирались: кэш свечей отстал на 45 дней, метрики без расписания, журнал собран
один раз; страж свежести был, но в расписании не стоял).

Шаги (упавший шаг пишется громко и не роняет следующие):
  1. свечи 15m/1h/4h/1d с data.binance.vision ДНЕВНЫМИ архивами за последние 3 дня
     (запас на поздние публикации; INSERT OR IGNORE — повтор безвреден). 🔴 Binance — только через VPN:
     загрузчик ходит обычным urllib, без привязки к интерфейсу в обход туннеля
  2. позиционирование Binance (fetch_binance_metrics.py докачивает только недостающие дни)
  3. журнал общего состояния — полная пересборка
  4. ячейки ситуационной карты (базовые частоты)
  5. страж свежести кэша — отставание видно в логе

🔴 Шаги — ВНУТРИ одного процесса, не subprocess: консольный дочерний процесс под pm2 открывает Егору окно
терминала на каждый вызов (memory pm2_windows_restart_orphans, 29.09). Пул журнала наследует скрытую консоль pm2.

pm2: pm2 start <python.exe> --name joint-daily --interpreter none --cron "30 9 * * *" --no-autorestart
     --cwd <repo> -- scripts/joint_daily.py   (09:30 МСК = 06:30 UTC: дневные архивы Binance к этому времени есть)
Лог шагов: G:/oko_lab/out/joint_daily.log · подробности — pm2 logs joint-daily
"""
from __future__ import annotations

import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

LOG = Path("G:/oko_lab/out/joint_daily.log")
PROCS = 6                       # пересборка журнала днём: бот работает рядом, не забирать все ядра


def _log(msg: str) -> None:
    print(msg, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(msg + "\n")


def step(name: str, fn) -> bool:
    t0 = time.time()
    _log(f"\n=== {datetime.now():%Y-%m-%d %H:%M} · {name}")
    try:
        rc = fn()
        ok = rc in (None, 0, True)
    except SystemExit as e:
        ok = e.code in (None, 0)
    except Exception:                                    # noqa: BLE001
        _log(traceback.format_exc()[-1500:])
        ok = False
    _log(f"=== {name}: {'ок' if ok else '🔴 ШАГ УПАЛ'} · {time.time() - t0:.0f} с")
    return ok


def _argv(*args):
    """Вызов чужого main() с аргументами командной строки."""
    def run(mod_main):
        old = sys.argv
        sys.argv = ["x", *args]
        try:
            return mod_main()
        finally:
            sys.argv = old
    return run


def main() -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    # защита от двойного прогона: pm2 запускает задачу сразу при регистрации/рестарте, а не только по cron
    files = list(Path("G:/oko_lab/joint/1h").glob("*.parquet"))
    if files and "--force" not in sys.argv:
        age_h = (time.time() - max(f.stat().st_mtime for f in files)) / 3600
        if age_h < 12:
            _log(f"\n=== {datetime.now():%Y-%m-%d %H:%M} · журнал свежий ({age_h:.1f} ч) — пропуск")
            return 0
    since = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
    import fetch_binance_vision as FV
    import fetch_binance_metrics as FM
    import joint_state_journal as JJ
    import situation_card as SC
    import cache_freshness as CF
    ok = step("свечи", lambda: _argv("--tfs", "15m", "1h", "4h", "1d", "--since-day", since,
                                    "--universe", "cache")(FV.main))
    ok &= step("метрики", lambda: _argv()(FM.main))
    ok &= step("журнал", lambda: JJ.run(PROCS, force=True))
    ok &= step("ячейки карты", SC.build_cells)
    step("свежесть", lambda: _argv()(CF.main))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
