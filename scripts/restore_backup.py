# -*- coding: utf-8 -*-
"""Распаковать сжатый бэкап БД обратно в .db.

Бэкапы в `backups/` лежат сжатыми (22.08: 7.6 ГБ → ~0.9 ГБ, sha256 сверен при
сжатии). Восстановление — одна команда, чтобы в нужный момент не пришлось
вспоминать синтаксис gzip под Windows.

    python scripts/restore_backup.py                       # список того, что есть
    python scripts/restore_backup.py 2026-08-20            # распаковать по дате
    python scripts/restore_backup.py 2026-08-20 --out X.db # в своё имя
"""
import argparse, glob, gzip, os, shutil, sqlite3, sys

sys.stdout.reconfigure(encoding="utf-8")
BUF = 8 * 1024 * 1024
ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backups")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?", help="дата или часть имени, напр. 2026-08-20")
    ap.add_argument("--out", help="куда распаковать (по умолчанию рядом, без .gz)")
    a = ap.parse_args()

    arch = sorted(glob.glob(os.path.join(ROOT, "*.db.gz")))
    if not a.date:
        print(f"бэкапы в {ROOT}:")
        for p in arch:
            print(f"  {os.path.getsize(p)/1024**3:5.2f} ГБ  {os.path.basename(p)}")
        print("\nраспаковать:  python scripts/restore_backup.py <дата>")
        return 0

    hits = [p for p in arch if a.date in os.path.basename(p)]
    if len(hits) != 1:
        print(f"🔴 по «{a.date}» найдено {len(hits)} файлов: "
              f"{[os.path.basename(h) for h in hits]}")
        return 1
    src = hits[0]
    dst = a.out or src[:-3]
    if os.path.exists(dst):
        print(f"🔴 {dst} уже существует — укажите --out")
        return 1
    with gzip.open(src, "rb") as fi, open(dst, "wb") as fo:
        shutil.copyfileobj(fi, fo, BUF)
    c = sqlite3.connect(f"file:{dst}?mode=ro", uri=True)
    chk = c.execute("PRAGMA quick_check").fetchone()[0]
    n = c.execute("SELECT COUNT(*) FROM simulated_trades").fetchone()[0]
    c.close()
    print(f"✅ {os.path.basename(dst)} · {os.path.getsize(dst)/1024**3:.2f} ГБ · "
          f"quick_check {chk} · сделок {n:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
