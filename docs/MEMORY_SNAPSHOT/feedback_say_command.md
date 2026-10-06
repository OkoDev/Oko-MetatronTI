---
name: say-command-tts
description: "TTS-голоса (Pavel мужской / Irina женский), прогрев против немого старта, когда озвучивать"
metadata: 
  node_type: memory
  type: feedback
  triggers: 
    - завершение задачи
    - "'готово'"
    - конец под-задачи
    - голосом
    - поговорить
  originSessionId: 9d582948-c9be-42e6-8444-4165a225d1fa
---

TTS через PowerShell `System.Speech`. Два режима (юзер 09.06):
- **Рабочий поток (короткие отметки итога):** допустимо Irina ИЛИ Pavel, кратко.
- **Объёмные разговоры «по душам»:** ПОЛНЫЙ голос **Microsoft Pavel** (русский МУЖСКОЙ) — юзер хочет мужской бро-голос для бесед, не уставать читать длинные ответы.

**Голоса (проверено 09.06):**
- `Microsoft Pavel` — ru-RU **мужской** ✅ (предпочтение для бесед). Был только в OneCore → скопирован в SAPI5 реестр (см. ниже).
- `Microsoft Irina Desktop` — ru-RU женский (запасной, стабильный).
- `Microsoft David` — en-US мужской, НЕ использовать для русского (клюква/акцент «borsh-matrioshka», юзер забраковал).

**🔴🔴 ОБЯЗАТЕЛЬНО `SetOutputToDefaultAudioDevice()` (фикс 10.06):** без явной привязки к устройству вывода синтезатор отрабатывает БЕЗ ошибок (`State: Ready`), но звук уходит «в никуда» — юзер ничего не слышит. Это была корневая причина «немого» TTS, НЕ прогрев. Всегда вызывать ПЕРВЫМ после создания синтезатора.

**Рабочий шаблон (проверено 10.06, юзер слышит Pavel):**
```powershell
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SetOutputToDefaultAudioDevice()   # 🔴 БЕЗ ЭТОГО ТИШИНА
$s.SelectVoice('Microsoft Pavel'); $s.Volume = 100; $s.Rate = 0
$s.Speak('<текст на русском>')
```

**Прогрев против немого старта (запасное, если первый Speak глохнет):** добавить перед основной речью `$s.Volume = 0; $s.Speak('.')`, затем `$s.Volume = 100`.

**Установка Pavel (если пропал / новая машина):** голос есть в `HKLM\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens\MSTTS_V110_ruRU_PavelM`, но System.Speech видит только SAPI5-раздел. Скопировать токен (нужен админ/UAC):
```
reg copy "HKLM\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens\MSTTS_V110_ruRU_PavelM" "HKLM\SOFTWARE\Microsoft\Speech\Voices\Tokens\MSTTS_V110_ruRU_PavelM" /s /f
reg copy "<тот же src>" "HKLM\SOFTWARE\WOW6432Node\Microsoft\Speech\Voices\Tokens\MSTTS_V110_ruRU_PavelM" /s /f
```
(RHVoice «Александр» хотели, но Windows SAPI5-инсталлятор снят с релизов — проект ушёл на Android. Pavel = рабочая замена.)

**Why:** юзер 09.06 «голос не всегда нужен в работе, а в объёмных поговорить кстати; мужской голос, бро». David забракован (акцент). Pavel настроен.
