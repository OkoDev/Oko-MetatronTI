"""Уборка журналов проекта: current_state · DISCUSSION · TASKS. Идемпотентно, без сети.

🔴 ЗАЧЕМ (Егор, 13.10.2026): «DISCUSSION.md и TASKS.md мы договаривались чистить и архивировать при
необходимости — сейчас это работает?! кто-то из роя вроде этим должен был заниматься на постоянной основе».
Проверено 13.10: НЕ работало ни в одном из трёх мест, и в pm2 (39 процессов) задачи уборки не было вовсе.
  · `memory/current_state.md` — шапка обещает «последние ~8 сессий», внутри было 483 записи (283 тыс. токенов);
  · `DISCUSSION.md` — архивы по месяцам существуют с марта, но с 14.06 не применялись: 216 записей (152 тыс.);
  · `TASKS.md` — скрипт `tasks_tidy.py` был, но заклинил на устаревшем списке `must_stay` и отменял сам себя.

Цена простоя: правило старта сессии велит читать эти журналы, а вместе они весили 539 тыс. токенов —
больше двух контекстов. Агент физически не мог их увидеть и каждую сессию «забывал, что в проекте есть».

Запуск:
    python scripts/docs_tidy.py              # что будет сделано (ничего не пишет)
    python scripts/docs_tidy.py --apply      # выполнить
    python scripts/docs_tidy.py --apply --keep-state 8 --keep-months 2
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding="utf-8")

# `--root` нужен, чтобы уборку можно было ПРОВЕРИТЬ ЗАПУСКОМ на песочнице с заведомым мусором:
# на живых файлах после первой уборки всегда «уже чисто», и такой прогон ничего не доказывает.
# Пути пересчитываются в main(); модульные константы — значения по умолчанию.
STATE = ROOT / "memory/current_state.md"
STATE_ARCH = ROOT / "memory/current_state_ARCHIVE.md"
DISC = ROOT / "DISCUSSION.md"
LOG = ROOT / "logs/docs_tidy.log"
MONTH_RU = {"01": "JAN", "02": "FEB", "03": "MAR", "04": "APR", "05": "MAY", "06": "JUN",
            "07": "JUL", "08": "AUG", "09": "SEP", "10": "OCT", "11": "NOV", "12": "DEC"}


def _split(text: str, pat: str) -> tuple[str, list[str]]:
    parts = re.split(pat, text)
    return parts[0], parts[1:]


def _date_of_state(rec: str) -> tuple[int, int] | None:
    """(месяц, день) из заголовка записи handoff'а. Шесть форматов: дата в начале или после времени."""
    h = rec.split("\n", 1)[0]
    m = re.search(r"\[([^\]]*)\]", h)
    if not m:
        return None
    m2 = re.search(r"(\d{2})\.(\d{2})(?:\.(\d{4}))?", m.group(1))
    return (int(m2.group(2)), int(m2.group(1))) if m2 else None


def tidy_state(keep: int, apply: bool) -> str:
    """Держим в current_state только свежие записи: порядок в файле НЕ хронологический, поэтому
    отбираем по дате, а не по позиции, и записи без даты оставляем (их единицы, терять нельзя)."""
    if not STATE.exists():
        return "current_state.md: нет файла"
    text = STATE.read_text(encoding="utf-8")
    head, recs = _split(text, r"(?m)^(?=## \[)")
    dated = [(i, _date_of_state(r)) for i, r in enumerate(recs)]
    known = sorted({d for _, d in dated if d}, reverse=True)[:keep]
    if not known:
        return "current_state.md: даты не распознаны — не трогаю"
    cutoff = min(known)
    keep_idx = {i for i, d in dated if d is None or d >= cutoff}
    if len(keep_idx) == len(recs):
        return f"current_state.md: уже чисто ({len(recs)} записей)"
    new = head + "".join(r for i, r in enumerate(recs) if i in keep_idx)
    move = [r for i, r in enumerate(recs) if i not in keep_idx]
    msg = (f"current_state.md: {len(recs)} → {len(keep_idx)} записей "
           f"(≈{len(text)//3} → ≈{len(new)//3} токенов), в архив {len(move)}")
    if apply:
        shutil.copy2(STATE, STATE.with_suffix(".md.bak_tidy"))
        stamp = datetime.now(timezone.utc).strftime("%d.%m.%Y")
        old = STATE_ARCH.read_text(encoding="utf-8") if STATE_ARCH.exists() else ""
        STATE_ARCH.write_text(old.rstrip("\n") + f"\n\n<!-- Архив {stamp}: {len(move)} записей "
                              f"из current_state (docs_tidy) -->\n" + "".join(move), encoding="utf-8")
        STATE.write_text(new, encoding="utf-8")
    return msg


def tidy_discussion(keep_months: int, apply: bool) -> str:
    """Месяцы старше последних keep_months уходят в DISCUSSION-ARCHIVE-<MON><YYYY>.md (практика с марта)."""
    if not DISC.exists():
        return "DISCUSSION.md: нет файла"
    text = DISC.read_text(encoding="utf-8")
    head, recs = _split(text, r"(?m)^(?=### \[)")
    groups: dict[tuple[str, str], list[str]] = {}
    keep: list[str] = []
    for r in recs:
        m = re.match(r"### \[(\d{2})\.(\d{2})\.(\d{4})", r)
        groups.setdefault((m.group(3), m.group(2)), []).append(r) if m else keep.append(r)
    months = sorted(groups, reverse=True)[:keep_months]
    move = {k: v for k, v in groups.items() if k not in months}
    if not move:
        return f"DISCUSSION.md: уже чисто ({len(recs)} записей, месяцев {len(groups)})"
    keep += [r for k in sorted(groups) if k in months for r in groups[k]]
    kept_text = head + "".join(r for r in recs if r in keep)
    msg = (f"DISCUSSION.md: {len(recs)} → {len(keep)} записей "
           f"(≈{len(text)//3} → ≈{len(kept_text)//3} токенов); в архивы: "
           + ", ".join(f"{k[1]}.{k[0]}×{len(v)}" for k, v in sorted(move.items())))
    if apply:
        shutil.copy2(DISC, DISC.with_suffix(".md.bak_tidy"))
        stamp = datetime.now(timezone.utc).strftime("%d.%m.%Y")
        for k, v in sorted(move.items()):
            tgt = ROOT / f"DISCUSSION-ARCHIVE-{MONTH_RU[k[1]]}{k[0]}.md"
            if tgt.exists():
                tgt.write_text(tgt.read_text(encoding="utf-8").rstrip("\n")
                               + f"\n\n<!-- Дозапись {stamp}: {len(v)} записей (docs_tidy) -->\n"
                               + "".join(v), encoding="utf-8")
            else:
                tgt.write_text(f"# Архив DISCUSSION — {k[1]}.{k[0]}\n\n> Вынесено {stamp} "
                               f"из DISCUSSION.md (docs_tidy). Порядок записей сохранён.\n\n---\n\n"
                               + "".join(v), encoding="utf-8")
        DISC.write_text(kept_text, encoding="utf-8")
    return msg


def tidy_tasks(apply: bool) -> str:
    """Закрытые ✅ задачи → TASKS-ARCHIVE.md штатным tasks_tidy.py (у него своя защита от утечки активных)."""
    cmd = [sys.executable, "-X", "utf8", str(ROOT / "scripts/tasks_tidy.py")] + (["--apply"] if apply else [])
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=ROOT).stdout
    except Exception as e:                                  # noqa: BLE001
        return f"TASKS.md: tasks_tidy не запустился ({type(e).__name__}: {e})"
    n = re.search(r"в архив \(уверенно ✅\): (\d+)", out)
    leak = "УТЕЧКА" in out
    tail = "🔴 отменено защитой (утечка активных)" if leak else ("записано" if apply else "готово к записи")
    return f"TASKS.md: закрытых к переносу {n.group(1) if n else '?'} — {tail}"


def main() -> int:
    global ROOT, STATE, STATE_ARCH, DISC, LOG
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--keep-state", type=int, default=12, help="сколько последних ДНЕЙ-записей держать")
    ap.add_argument("--keep-months", type=int, default=2, help="сколько последних месяцев держать в DISCUSSION")
    ap.add_argument("--root", default=None, help="корень для проверки на песочнице (по умолчанию — репозиторий)")
    a = ap.parse_args()

    sandbox = a.root is not None
    if sandbox:
        ROOT = Path(a.root).resolve()
        STATE = ROOT / "memory/current_state.md"
        STATE_ARCH = ROOT / "memory/current_state_ARCHIVE.md"
        DISC = ROOT / "DISCUSSION.md"
        LOG = ROOT / "logs/docs_tidy.log"

    print("=== APPLY ===" if a.apply else "=== прогон вхолостую (--apply чтобы выполнить) ===")
    if sandbox:
        print(f"    песочница: {ROOT}")
    lines = [tidy_state(a.keep_state, a.apply), tidy_discussion(a.keep_months, a.apply)]
    # tasks_tidy.py работает только по своему репозиторию (--root не поддерживает) — в песочнице пропускаем,
    # чтобы прогон не трогал живой TASKS.md.
    lines.append("TASKS.md: пропущен (песочница)" if sandbox else tidy_tasks(a.apply))
    for line in lines:
        print(" ·", line)

    if a.apply:
        try:                                    # лог нужен для контрольной проверки через пару дней
            LOG.parent.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(f"[{stamp}] " + " | ".join(lines) + "\n")
            print(f" → записано в {LOG.relative_to(ROOT) if LOG.is_relative_to(ROOT) else LOG}")
        except Exception as e:                  # noqa: BLE001 — уборка не должна падать из-за лога
            print(f" ⚠️ лог не записан: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
