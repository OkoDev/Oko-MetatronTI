"""DS-317: Проверка орфанов и битых ссылок в Obsidian vault."""
import re
from pathlib import Path

obs = Path("e:/MTF BOT/CURSOR/crypto_volume_bot/obsidian")

# Собрать все wikilink-цели
linked_targets = set()
for f in obs.rglob("*.md"):
    text = f.read_text(encoding="utf-8", errors="replace")
    refs = re.findall(r"\[\[([^\]|#]+)", text)
    for r in refs:
        r = r.strip()
        if r.startswith("../"):
            r = r[3:]
        linked_targets.add(r)

# Проверить орфанов и битые ссылки
orphans = []
broken_links = []
for f in sorted(obs.rglob("*.md")):
    rel = str(f.relative_to(obs)).replace("\\", "/")
    name_no_ext = rel[:-3] if rel.endswith(".md") else rel
    
    # Входящие ссылки
    has_incoming = (rel in linked_targets or name_no_ext in linked_targets or f.stem in linked_targets)
    if not has_incoming:
        orphans.append(rel)
    
    # Исходящие битые ссылки
    text = f.read_text(encoding="utf-8", errors="replace")
    refs = re.findall(r"\[\[([^\]|#]+)", text)
    for r in refs:
        r = r.strip()
        if r.startswith("../"):
            r = r[3:]
        target_path = obs / (r + ".md")
        if not target_path.exists() and not r.startswith("http") and "/" not in r and "." not in r:
            broken_links.append((rel, r))

total = len(list(obs.rglob("*.md")))
print(f"Files: {total}")
print(f"Orphans (no incoming links): {len(orphans)}")
print(f"Broken links: {len(broken_links)}")
print()

if orphans:
    print("=== ORPHANS ===")
    for o in orphans:
        print(f"  {o}")

if broken_links:
    print()
    print("=== BROKEN LINKS ===")
    for src, tgt in broken_links:
        print(f"  {src} -> [[{tgt}]]")
