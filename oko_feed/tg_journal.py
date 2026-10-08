"""ЖУРНАЛ ОТПРАВОК В TELEGRAM (09.10, аудит TG 08.10: «журнала отправок нет — объёмы восстановлены по косвенным»).

Одна строка JSON на отправку → data/tg_journal/ГГГГ-ММ-ДД.jsonl (UTC). Дописывание в файл, а не БД: пишут ~10
процессов, общая SQLite снова дала бы блокировки (урок subscriptions.db). Журнал не должен ронять отправку —
любые его ошибки глотаются.

Поля: ts · src (процесс) · ch (канал: action/feed/system/news/waves/dm/main) · kind (тип сигнала, если есть) ·
ok · to (сколько получателей, для рассылки бота) · n (длина текста) · head (первые 80 символов).

Сводка: python -m oko_feed.tg_journal [часов=24]
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

DIR = Path(__file__).resolve().parents[1] / "data" / "tg_journal"


def log(channel: str, ok, text: str = "", *, kind: str | None = None, source: str | None = None,
        to: int | None = None) -> None:
    try:
        DIR.mkdir(parents=True, exist_ok=True)
        rec = {"ts": int(time.time()), "src": source or Path(sys.argv[0] or "?").stem, "ch": channel,
               "kind": kind, "ok": bool(ok), "to": to, "n": len(text or ""),
               "head": " ".join((text or "")[:120].split())[:80]}
        with open(DIR / time.strftime("%Y-%m-%d.jsonl", time.gmtime()), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:                                    # noqa: BLE001
        pass


def read(hours: float = 24) -> list[dict]:
    t0 = time.time() - hours * 3600
    out = []
    for f in sorted(DIR.glob("*.jsonl"))[-(int(hours // 24) + 2):]:
        for ln in f.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(ln)
            except Exception:                            # noqa: BLE001
                continue
            if r.get("ts", 0) >= t0:
                out.append(r)
    return out


def summary(hours: float = 24) -> str:
    R = read(hours)
    by_ch = Counter(r["ch"] for r in R)
    by_src = Counter((r["ch"], r["src"], r.get("kind")) for r in R)
    fail = sum(1 for r in R if not r.get("ok"))
    L = [f"отправок за {hours:g} ч: {len(R)} · неудачных {fail}"]
    L += [f"  {ch:<8} {n}" for ch, n in by_ch.most_common()]
    L.append("по источникам:")
    L += [f"  {ch:<8} {src:<22} {kind or '':<18} {n}" for (ch, src, kind), n in by_src.most_common(40)]
    return "\n".join(L)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                    # noqa: BLE001
        pass
    print(summary(float(sys.argv[1]) if len(sys.argv) > 1 else 24))
