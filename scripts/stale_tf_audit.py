"""Перечень выводов, сделанных на отставших 3m/5m (задача Егора 13.10).

Кэш `ohlcv_cache.db`: 3m стоит с 12.04.2026, 5m с 31.05.2026. Любой замер на этих ТФ, выполненный ПОЗЖЕ,
молча считал по старым данным. Ищем: (1) скрипты, читающие 3m/5m из кэша, с датой последней правки;
(2) заметки замеров в obsidian/Research, упоминающие эти ТФ; (3) записи памяти с выводами по ним.
Дата правки скрипта — ПРОКСИ даты замера: точного журнала прогонов у нас нет.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
STALE_FROM = {"3m": "2026-04-12", "5m": "2026-05-31"}
TF_RE = re.compile(r"""["']([35]m)["']""")


def git_date(path: str) -> str:
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%ad", "--date=format:%Y-%m-%d", "--", path],
                             cwd=ROOT, capture_output=True, text=True, encoding="utf-8").stdout.strip()
        return out or "—"
    except Exception:                                        # noqa: BLE001
        return "—"


print("=" * 108)
print("ПЕРЕЧЕНЬ ДЛЯ ПЕРЕПРОВЕРКИ: что считалось на 3m/5m из отставшего кэша")
print(f"кэш стоит: 3m с {STALE_FROM['3m']} · 5m с {STALE_FROM['5m']}")
print("=" * 108)

rows = []
for f in sorted((ROOT / "scripts").glob("*.py")):
    try:
        src = f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        continue
    if "ohlcv_cache" not in src and "research_harness" not in src:
        continue
    tfs = sorted(set(TF_RE.findall(src)))
    if not tfs:
        continue
    rel = f"scripts/{f.name}"
    d = git_date(rel)
    risky = any(d > STALE_FROM[tf] for tf in tfs if tf in STALE_FROM) if d != "—" else True
    rows.append((d, rel, ",".join(tfs), risky, "harness" if "research_harness" in src else "кэш"))

rows.sort(reverse=True)
risky = [r for r in rows if r[3]]
print(f"\nСкриптов, читающих 3m/5m: {len(rows)} · из них правлены ПОСЛЕ остановки данных: {len(risky)}\n")
print(f"{'правка':<12}{'ТФ':<8}{'через':<9}файл")
for d, rel, tfs, rk, via in risky[:25]:
    print(f"{d:<12}{tfs:<8}{via:<9}{rel}")

print("\n" + "=" * 108)
print("ЗАМЕТКИ ЗАМЕРОВ (obsidian/Research), где упоминаются 3m или 5m:")
res = ROOT / "obsidian" / "Research"
if res.exists():
    hits = []
    for f in sorted(res.glob("*.md")):
        t = f.read_text(encoding="utf-8", errors="replace")
        tfs = sorted(set(TF_RE.findall(t)) | set(re.findall(r"\b([35]m)\b", t)))
        tfs = [x for x in tfs if x in ("3m", "5m")]
        if tfs:
            m = re.match(r"(\d{4}-\d{2}-\d{2})", f.name)
            hits.append((m.group(1) if m else "—", f.name, ",".join(tfs)))
    hits.sort(reverse=True)
    late = [h for h in hits if h[0] != "—" and h[0] > "2026-04-12"]
    print(f"   всего заметок с 3m/5m: {len(hits)} · после 12.04: {len(late)}")
    for d, name, tfs in late[:15]:
        print(f"   {d}  {tfs:<6} {name}")
else:
    print("   папки нет")

print("\n" + "=" * 108)
print("ПАМЯТЬ: записи с выводами по 3m/5m")
mem = Path(r"C:\Users\yogoru\.claude\projects\e--MTF-BOT-CURSOR-crypto-volume-bot\memory")
if mem.exists():
    for f in sorted(mem.glob("*.md")):
        t = f.read_text(encoding="utf-8", errors="replace")
        if re.search(r"\b[35]m\b", t) and f.name != "MEMORY.md":
            first = next((l for l in t.splitlines() if l.startswith("description:")), "")[:150]
            print(f"   {f.name:<48} {first[13:]}")
