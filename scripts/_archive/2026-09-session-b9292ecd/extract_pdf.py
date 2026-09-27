# -*- coding: utf-8 -*-
"""Извлечь текст из гайдов IKIGAI по структурам движения и коррекции."""
import sys
from pathlib import Path

from pypdf import PdfReader

D = Path(r"C:\Users\yogoru\AppData\Local\Temp\claude\e--MTF-BOT-CURSOR-crypto-volume-bot"
         r"\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")

for src, name in ((D / "guide_1.pdf", "motive"), (D / "guide_2.pdf", "corrective")):
    r = PdfReader(str(src))
    out = []
    for i, page in enumerate(r.pages, 1):
        t = (page.extract_text() or "").strip()
        out.append(f"\n=== СТР. {i} ===\n{t}")
    txt = "\n".join(out)
    dst = D / f"{name}.txt"
    dst.write_text(txt, encoding="utf-8")
    print(f"{name}: страниц {len(r.pages)}, символов {len(txt)} → {dst.name}")
