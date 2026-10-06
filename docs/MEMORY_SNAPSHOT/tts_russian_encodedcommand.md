---
name: tts_russian_encodedcommand
description: "🔊 ОЗВУЧКА: звать `python scripts/say.py \"текст\"` — КИРИЛЛИЦЕЙ, никогда транслитом (= дикий акцент, Егор поймал 05.10). Голос — Ирина, выбор Егора. Внутри powershell -EncodedCommand (base64 UTF-16LE)"
metadata:
  node_type: memory
  type: feedback
  originSessionId: ea98197f-5cfa-4b48-ab76-1b2fcebf5d0d
  modified: 2026-10-05T17:04:32.645Z
---

**Егор, 05.10.2026: «что у тебя с голосом? читаешь с диким акцентом и проблемами
с произношением».**

**Причина.** Я озвучивал ТРАНСЛИТОМ латиницей (`Peresmotr zakonchen i vyvod razvalilsya`),
потому что кириллица в командной строке ломалась о кодировку консоли (cp866/cp1251) — был
записан обходной путь «писать латиницей». Русский голос читает латиницу как иностранные
слова, отсюда акцент. Обход лечил симптом и портил результат.

## ✅ КАК ЗВАТЬ (одна строка, лежит в репо — переживает сессию)

```bash
python scripts/say.py "текст по-русски"
python scripts/say.py --voice "Microsoft Pavel" "текст"     # если понадобится другой
```

**Голос — `Microsoft Irina Desktop`, выбор Егора 05.10** («ирина»). Он же дефолт в скрипте.

**Под капотом — отдаём PowerShell команду в его родной кодировке, минуя консоль:**

```python
import base64, subprocess
safe = text.replace("'", "''")                       # экранирование кавычки
ps = ("Add-Type -AssemblyName System.Speech; "
      "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
      f"$s.SelectVoice('Microsoft Irina Desktop'); $s.Speak('{safe}')")
subprocess.run(["powershell", "-NoProfile", "-EncodedCommand",
                base64.b64encode(ps.encode("utf-16-le")).decode()])
```

Готовый помощник: `scratchpad/say.py` → `python say.py "текст по-русски"`.

**Голоса в системе** (`GetInstalledVoices()`, проверено 05.10):

| голос | язык | пол |
|---|---|---|
| `Microsoft Irina Desktop` | ru-RU | женский |
| `Microsoft Pavel` | ru-RU | мужской |
| `Microsoft David Desktop` / `Microsoft Zira Desktop` | en-US | — |

**Проверка успеха:** код возврата 0. Вывод `#< CLIXML … Подготовка модулей к первому
использованию` — это прогресс `Add-Type`, НЕ ошибка, пугаться его не надо.

🔴 **Никогда не озвучивать транслитом.** Если кириллица «не проходит» — чинится кодировка
передачи, а не текст. Тот же класс, что [[law_reproduce_live_config_first]]: обход, который
меняет входные данные, делает результат неверным и выглядит при этом рабочим.
