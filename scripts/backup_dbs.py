# -*- coding: utf-8 -*-
"""BACKUP-DBS (11.07, Егор — желание №6: «умрёт диск — исчезнет весь трек-рекорд»).

Ежедневный автобэкап КРИТИЧНОГО на ДРУГОЙ физический диск (F: = Seagate HDD; бот на
E: = ADATA SSD → смерть SSD не уносит историю):
  • subscriptions.db        — весь трек-рекорд/форвард (~573 МБ)
  • oko_feed/external_data.db — радар/компас/OI/новости (~5 МБ)
  • config.yaml, .env       — конфиг + ключи
НЕ бэкапим ohlcv_cache.db (17 ГБ) — перекачиваемый кэш цен (fetch_binance_vision).

Метод: sqlite3 online-backup API (безопасно ПОКА бот пишет — не файловая копия, та
рвёт БД на середине записи) → всё в один tar.gz/день. Ротация: 14 ежедневных + по
воскресеньям на 8 недель. Провал/успех → TG SYSTEM.

pm2 cron: 04:10 UTC ежедневно (после ledger-audit 03:15, тихое время).
Тест: python scripts/backup_dbs.py --once
"""
import sys
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
import gzip
import os
import shutil
import sqlite3
import tarfile
import tempfile
import time
import datetime as dt
from pathlib import Path

DEST = Path("F:/oko_backups")
KEEP_DAILY = 14
KEEP_WEEKLY = 8
SQLITE_DBS = ["subscriptions.db", "oko_feed/external_data.db"]
PLAIN_FILES = ["config.yaml", ".env"]


def _hot_backup(src: str, dst: str) -> None:
    """Online-backup: консистентный снимок БД даже при активной записи бота."""
    con = sqlite3.connect(src, timeout=30)
    try:
        bck = sqlite3.connect(dst)
        try:
            con.backup(bck)          # атомарный снимок через SQLite backup API
        finally:
            bck.close()
    finally:
        con.close()


def _rotate() -> None:
    """14 последних ежедневных + воскресные на 8 недель, остальное — удалить."""
    files = sorted(DEST.glob("oko_backup_*.tar.gz"))
    if len(files) <= KEEP_DAILY:
        return
    keep = set(files[-KEEP_DAILY:])                    # последние N дней — всегда
    cutoff = dt.date.today() - dt.timedelta(weeks=KEEP_WEEKLY)
    for f in files[:-KEEP_DAILY]:
        try:
            d = dt.datetime.strptime(f.name[12:20], "%Y%m%d").date()
        except ValueError:
            continue
        if d.weekday() == 6 and d >= cutoff:           # воскресенье в окне 8 недель
            keep.add(f)
    for f in files:
        if f not in keep:
            try:
                f.unlink()
                print(f"[BACKUP] ротация: удалён {f.name}")
            except OSError as e:
                print(f"[BACKUP] ротация {f.name}: {e}")


def run() -> None:
    t0 = time.time()
    DEST.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M")
    out = DEST / f"oko_backup_{stamp}.tar.gz"
    tmp = Path(tempfile.mkdtemp(prefix="oko_bk_"))
    try:
        staged = []
        for db in SQLITE_DBS:
            if not os.path.exists(db):
                print(f"[BACKUP] пропуск (нет файла): {db}")
                continue
            dst = tmp / Path(db).name
            _hot_backup(db, str(dst))
            staged.append((dst, Path(db).name))
        for pf in PLAIN_FILES:
            if os.path.exists(pf):
                dst = tmp / Path(pf).name
                shutil.copy2(pf, dst)
                staged.append((dst, Path(pf).name))
        if not staged:
            raise RuntimeError("нечего бэкапить — все источники отсутствуют")
        with tarfile.open(out, "w:gz", compresslevel=6) as tar:
            for path, arcname in staged:
                tar.add(path, arcname=arcname)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    size_mb = out.stat().st_size / 1048576
    _rotate()
    total = len(list(DEST.glob("oko_backup_*.tar.gz")))
    dur = time.time() - t0
    msg = (f"💾 <b>BACKUP</b> ок: <code>{out.name}</code> "
           f"{size_mb:.0f}МБ за {dur:.0f}с · архивов {total} (F: другой диск)")
    print(f"[BACKUP] {out} — {size_mb:.1f}МБ за {dur:.1f}с, всего {total}")
    try:
        from oko_feed.alerts import send_tg
        send_tg(msg + "\n\n#SYSTEM", channel="system")
    except Exception as e:
        print(f"[BACKUP] tg err: {e}")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print(f"[BACKUP] 🔴 ПРОВАЛ: {e}")
        try:
            from oko_feed.alerts import send_tg
            send_tg(f"🔴 <b>BACKUP ПРОВАЛ</b>: {e}\n<i>трек-рекорд без свежей копии!</i>\n\n#SYSTEM",
                    channel="system")
        except Exception:
            pass
        sys.exit(1)
