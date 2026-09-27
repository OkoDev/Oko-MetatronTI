# -*- coding: utf-8 -*-
"""Склейка двух индикаторов в один: слот Pine у Егора один (лимит 30 скриптов).

OkoWave (структура + нога) — база. Эллиотт (разволновка) добавляется вторым блоком
с переименованием конфликтующих идентификаторов.
"""
import re
from pathlib import Path

BASE = Path(r"e:\MTF BOT\CURSOR\crypto_volume_bot\docs\reference")
wave = (BASE / "OkoWave_v1.pine").read_text(encoding="utf-8")
ell = (BASE / "OkoElliott_v1.pine").read_text(encoding="utf-8")

# ── из Эллиотта берём всё ПОСЛЕ строки indicator(...) ───────────────────────
ell_body = ell.split("\n")
start = next(i for i, l in enumerate(ell_body) if l.startswith("indicator(")) + 1
ell_body = "\n".join(ell_body[start:])

# конфликтующие имена → уникальные
renames = [
    (r"\bdepth\b", "zzDepth"),
    (r"\batrLen\b", "zzAtrLen"),
    (r"\bshowOte\b", "showOteEW"),
    (r"\bshowTable\b", "showTableEW"),
    (r"\bgZ\b", "ewGz"), (r"\bgM\b", "ewGm"), (r"\bgD\b", "ewGd"),
    (r"\btxtIn\b", "ewTxtIn"),
]
for pat, rep in renames:
    ell_body = re.sub(pat, rep, ell_body)

# SZ объявляется в базовой части — убираем повторное объявление и вход размера
ell_body = "\n".join(l for l in ell_body.split("\n")
                     if not l.startswith("simple string SZ =")
                     and not l.startswith("ewTxtIn    = input.string"))
ell_body = ell_body.replace("simple string sz, simple int lw", "simple string sz, simple int lw")

# группы инпутов Эллиотта — отдельный префикс в UI
ell_body = ell_body.replace('string ewGz = "ZigZag (порт zigzag_atr)"',
                            'string ewGz = "РАЗВОЛНОВКА · ZigZag (порт zigzag_atr)"')
ell_body = ell_body.replace('string ewGm = "Масштабы волн (detect_elliott_mtf)"',
                            'string ewGm = "РАЗВОЛНОВКА · масштабы волн (detect_elliott_mtf)"')
ell_body = ell_body.replace('string ewGd = "Отрисовка"',
                            'string ewGd = "РАЗВОЛНОВКА · отрисовка"')

# лимиты объектов поднимаем — теперь рисуют оба блока
wave = wave.replace("max_lines_count = 50, max_labels_count = 300, max_boxes_count = 20",
                    "max_lines_count = 500, max_labels_count = 500, max_boxes_count = 100")
wave = wave.replace('indicator("OKO Wave [порт WaveService]", "OKO Wave"',
                    'indicator("OKO Wave + Elliott [порт детекторов бота]", "OKO WE"')

out = wave.rstrip() + "\n\n\n" + (
    "// ============================================================================\n"
    "// БЛОК 2 — РАЗВОЛНОВКА 1-2-3-4-5 (порт smc_engine: zigzag_atr + detect_elliott_impulse)\n"
    "// Другой движок, чем блок 1: там структура 50/5 и ОДНА нога, здесь ZigZag и канон\n"
    "// Эллиотта. В боте это тоже два разных модуля, и матрица берёт признаки из обоих.\n"
    "// ============================================================================\n"
) + ell_body.strip() + "\n"

dst = BASE / "OkoWaveElliott_v1.pine"
dst.write_text(out, encoding="utf-8")
print(f"собрано: {len(out.splitlines())} строк → {dst}")
for name in ("f_pivotAt", "f_scale", "f_smSwings", "SZ =", "indicator("):
    print(f"  {name}: {out.count(name)}")
