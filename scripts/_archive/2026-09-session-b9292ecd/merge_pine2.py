# -*- coding: utf-8 -*-
"""Склейка: OkoWave (структура+нога) + OkoElliott v2 (канон IKIGAI) в один слот.

Слот Pine у Егора один — лимит 30 скриптов, новые не создаются.
"""
import re
from pathlib import Path

BASE = Path(r"e:\MTF BOT\CURSOR\crypto_volume_bot\docs\reference")
wave = (BASE / "OkoWave_v1.pine").read_text(encoding="utf-8")
ell = (BASE / "OkoElliott_v2.pine").read_text(encoding="utf-8")

# тело Эллиотта = всё после многострочного indicator(...)
lines = ell.split("\n")
start = next(i for i, l in enumerate(lines) if l.startswith("indicator("))
while not lines[start].rstrip().endswith(")"):
    start += 1
body = "\n".join(lines[start + 1:])

# развод конфликтующих имён (у базы свои gS/gT/showTable/c1..c3/d1..d3)
renames = [
    (r"\bgZ\b", "ewGz"), (r"\bgM\b", "ewGm"), (r"\bgS\b", "ewGs"),
    (r"\bgT\b", "ewGt"), (r"\bgD\b", "ewGd"),
    (r"\bshowTable\b", "showTableEW"), (r"\blineW\b", "ewLineW"),
    (r"\btxtIn\b", "ewTxtIn"),
    (r"\bc1\b", "ewC1"), (r"\bc2\b", "ewC2"), (r"\bc3\b", "ewC3"),
    (r"\bd1\b", "ewD1"), (r"\bd2\b", "ewD2"), (r"\bd3\b", "ewD3"),
    (r"\bcf1\b", "ewCf1"), (r"\bcf2\b", "ewCf2"), (r"\bcf3\b", "ewCf3"),
    (r"\bnt1\b", "ewNt1"), (r"\bnt2\b", "ewNt2"), (r"\bnt3\b", "ewNt3"),
    (r"\blg1\b", "ewLg1"), (r"\blg2\b", "ewLg2"), (r"\blg3\b", "ewLg3"),
    (r"\biv1\b", "ewIv1"), (r"\biv2\b", "ewIv2"), (r"\biv3\b", "ewIv3"),
    (r"\btb\b", "ewTb"),
    (r"\bconf\b", "ewConf"),      # в блоке 1 есть своя conf (уверенность фазы)
    (r"\bphase\b", "ewPhase"),
]
for pat, rep in renames:
    body = re.sub(pat, rep, body)

# SZ и его вход объявлены в базовой части — убираем дубли
body = "\n".join(l for l in body.split("\n")
                 if not l.startswith("simple string SZ =")
                 and not l.startswith("ewTxtIn     = input.string"))

# группы инпутов — с префиксом, чтобы не смешивались с блоком 1
body = body.replace('string ewGz = "ZigZag', 'string ewGz = "ВОЛНЫ · ZigZag')
body = body.replace('string ewGm = "Масштабы', 'string ewGm = "ВОЛНЫ · масштабы')
body = body.replace('string ewGs = "Что размечать"', 'string ewGs = "ВОЛНЫ · что размечать"')
body = body.replace('string ewGt = "Цели и зоны"', 'string ewGt = "ВОЛНЫ · цели и зоны"')
body = body.replace('string ewGd = "Отрисовка"', 'string ewGd = "ВОЛНЫ · отрисовка"')

wave = wave.replace("max_lines_count = 50, max_labels_count = 300, max_boxes_count = 20",
                    "max_lines_count = 500, max_labels_count = 500, max_boxes_count = 100")
wave = wave.replace('indicator("OKO Wave [порт WaveService]", "OKO Wave"',
                    'indicator("OKO Wave + Elliott [детекторы бота + канон IKIGAI]", "OKO WE"')

head = (
    "\n\n// ============================================================================\n"
    "// БЛОК 2 — РАЗВОЛНОВКА ПО КАНОНУ IKIGAI (структуры движения и коррекции)\n"
    "// Движок другой, чем в блоке 1: там структура 50/5 и одна нога (oko_sm_engine),\n"
    "// здесь ZigZag + правила из гайдов Егора (docs/Гайд по структурам *.pdf).\n"
    "// ============================================================================\n"
)
out = wave.rstrip() + head + body.strip() + "\n"

dst = BASE / "OkoWaveElliott_v2.pine"
dst.write_text(out, encoding="utf-8")
print(f"собрано: {len(out.splitlines())} строк, {len(out)} символов → {dst.name}")
for probe in ("indicator(", "simple string SZ =", "f_pivotAt(", "showTableEW", "ewC1"):
    print(f"  {probe}: {out.count(probe)}")
