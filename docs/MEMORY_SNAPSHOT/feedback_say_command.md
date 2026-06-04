---
name: say command — TTS голос
description: Как использовать команду say (TTS) после завершения задач
type: feedback
triggers:
  - 'завершение задачи'
  - '''готово'''
  - 'конец под-задачи'
---

После завершения задачи или подзадачи — читать результат вслух через Python + PowerShell TTS.

Голос: **Microsoft Irina Desktop** (русский женский). Только русский язык.

**Why:** Пользователь хочет слышать итог работы. Только русский интересует.

**How to apply:** После каждой завершённой задачи запускать:

```python
import subprocess
script = '''
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice("Microsoft Irina Desktop")
$s.Speak("<текст на русском>")
'''
subprocess.run(['powershell', '-NoProfile', '-Command', script])
```
