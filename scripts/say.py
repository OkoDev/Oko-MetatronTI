#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Озвучка итогов сессии по-русски — КИРИЛЛИЦЕЙ, без транслита.

🔴 Зачем отдельный скрипт. Раньше озвучка шла ТРАНСЛИТОМ латиницей
(`Peresmotr zakonchen...`), потому что кириллица в командной строке ломалась
о кодировку консоли (cp866/cp1251), и был записан обход «писать латиницей».
Русский голос читает латиницу как иностранные слова — Егор 05.10.2026:
«что у тебя с голосом? читаешь с диким акцентом».

Обход лечил симптом и портил результат. Правильно — отдавать PowerShell команду
в его родной кодировке, минуя консоль: `-EncodedCommand` принимает base64 от
UTF-16LE, и перекодировать по пути нечего.

Запуск:
    python scripts/say.py "текст по-русски"
    python scripts/say.py --voice "Microsoft Pavel" "текст"

Голоса в системе (GetInstalledVoices, 05.10.2026):
    Microsoft Irina Desktop  ru-RU женский   ← выбор Егора, по умолчанию
    Microsoft Pavel          ru-RU мужской
    Microsoft David/Zira Desktop  en-US
"""
from __future__ import annotations

import base64
import subprocess
import sys

VOICE = "Microsoft Irina Desktop"


def say(text: str, voice: str = VOICE) -> int:
    """Произносит текст. Возвращает код возврата PowerShell (0 — успех).

    Вывод вида `#< CLIXML … Подготовка модулей к первому использованию` — это
    прогресс `Add-Type`, а НЕ ошибка.
    """
    if not text.strip():
        return 0
    safe = text.replace("'", "''")          # одинарная кавычка в PowerShell удваивается
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.SelectVoice('{voice}'); "
        f"$s.Speak('{safe}')"
    )
    enc = base64.b64encode(ps.encode("utf-16-le")).decode()
    return subprocess.run(
        ["powershell", "-NoProfile", "-EncodedCommand", enc],
        capture_output=True,                # CLIXML-шум не нужен в выводе
    ).returncode


def main() -> int:
    args = sys.argv[1:]
    voice = VOICE
    if args and args[0] == "--voice":
        if len(args) < 2:
            print("--voice требует имя голоса")
            return 2
        voice, args = args[1], args[2:]
    return say(" ".join(args), voice)


if __name__ == "__main__":
    sys.exit(main())
