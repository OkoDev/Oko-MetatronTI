# -*- coding: utf-8 -*-
"""ВНЕШНИЙ СТОРОЖ PM2 (11.08.2026) — намеренно ВНЕ pm2.

Инцидент 10.08: машина умерла жёстко (в логе «Lock-файл ОСИРОТЕЛ — владелец мёртв»),
демон PM2 перезапустился ПУСТЫМ и не поднял ни одного процесса. Простой 38 часов
(10.08 00:53 → 11.08 15:07), форвард всё это время не набирался.

Штатный hb-watchdog этого не поймал по конструкции: он живёт ВНУТРИ pm2, поэтому
пустой pm2 = мёртвый сторож вместе со всем остальным. Отсюда правило:
СТОРОЖ НЕ МОЖЕТ ЖИТЬ ВНУТРИ ТОГО, ЧТО ОН СТОРОЖИТ.

Ставится в Windows Task Scheduler (каждые 10 минут). Проверяет oko-bot; если он не
online — делает `pm2 resurrect`. Пишет в logs/pm2_guard.log.
Запуск вручную: python scripts/pm2_guard.py [--dry-run]"""
import datetime as dt
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "logs", "pm2_guard.log")
WATCH = "oko-bot"          # ключевой процесс: если он лежит — лежит вся торговля
DRY = "--dry-run" in sys.argv


def log(msg):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    line = f"{dt.datetime.now().isoformat(timespec='seconds')} {msg}"
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)


def pm2(*args, timeout=120):
    """pm2 через shell: на Windows это pm2.cmd, напрямую не запускается."""
    return subprocess.run("pm2 " + " ".join(args), shell=True, capture_output=True,
                          text=True, timeout=timeout, encoding="utf-8", errors="replace")


def online_names():
    r = pm2("jlist")
    if r.returncode != 0 or not r.stdout.strip():
        return None                      # демон не отвечает — это само по себе тревога
    try:
        data = json.loads(r.stdout[r.stdout.index("["):])
    except Exception as e:
        log(f"ОШИБКА разбора jlist: {e}")
        return None
    return {p["name"] for p in data if p.get("pm2_env", {}).get("status") == "online"}


def main():
    names = online_names()
    if names is None:
        log("ТРЕВОГА: pm2 не отвечает или отдал мусор")
    elif WATCH in names:
        log(f"ok {WATCH} online (живых процессов {len(names)})")
        return 0
    else:
        log(f"ТРЕВОГА: {WATCH} НЕ online (живых {len(names)}: {sorted(names)})")
    if DRY:
        log("--dry-run: воскрешение пропущено")
        return 1
    r = pm2("resurrect", timeout=300)
    log(f"resurrect rc={r.returncode} {(r.stdout or '').strip()[-300:]}")
    after = online_names() or set()
    ok = WATCH in after
    log(f"после воскрешения: {WATCH} {'ПОДНЯТ' if ok else 'ВСЁ ЕЩЁ ЛЕЖИТ'} (живых {len(after)})")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
