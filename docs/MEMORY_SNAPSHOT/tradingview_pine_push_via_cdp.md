---
name: tradingview_pine_push_via_cdp
description: "Как заливать .pine в редактор TradingView: Ctrl+V из ui_keyboard молча не доходит, рабочий способ — CDP Input.insertText кусками по 8 КБ"
metadata: 
  node_type: memory
  type: reference
  originSessionId: b9292ecd-40bf-480f-b583-11c47310bf19
  modified: 2026-09-08T15:08:20.368Z
---

# ⚡ ЗАЛИВКА .PINE В РЕДАКТОР: ЕДИНСТВЕННЫЙ НАДЁЖНЫЙ СПОСОБ (08.09.2026)

`scripts` нет — скрипт лежит в scratchpad как `push_pine3.ps1`, шаблон ниже.
Вызов: `push_pine3.ps1 -Path "...\OkoElliott_v3.pine"` → затем `pine_smart_compile`.

## 🔴 Что НЕ работает (потеряно ~час)

1. **`ui_keyboard` Ctrl+A / Ctrl+V** — после перезапуска TradingView вставка молча не
   доходит до Monaco. Компиляция при этом проходит УСПЕШНО — по старому тексту, и кажется,
   будто правка применена, а на графике ничего не меняется. Проверять так: положить в буфер
   `//@version=6\nindicator("TEST MARKER")\nplot(close)` и посмотреть `pine_get_source`.
2. **ClipboardEvent('paste') с DataTransfer** через `ui_evaluate` — Monaco его игнорирует.
3. **Один `Input.insertText` на 57 КБ** — Chrome молча отбрасывает.
4. **Проверка текста через `document.body.innerText`** — Monaco виртуализирует строки,
   в DOM только видимый экран; отсутствие строки ничего не доказывает.

## ✅ Рабочий рецепт

CDP `Input.insertText` ведёт себя как набор с клавиатуры, Monaco его принимает:

```powershell
# фокус в textarea редактора
Runtime.evaluate: document.querySelector('.monaco-editor textarea').focus()
Input.dispatchKeyEvent  keyDown/keyUp  modifiers=2 key='a'   # Ctrl+A, выделить всё
Input.insertText  кусками по 8000 символов, пауза 250 мс     # первый кусок заменяет выделение
```
Ответы CDP читать НЕ надо (ожидание ответа роняло скрипт по таймауту) — fire-and-forget.

🔴 Кириллица в строковых литералах .ps1 ломает парсер PowerShell 5.1 (файл читается как
ANSI) — сообщения писать латиницей, кириллицу оставлять только в комментариях.

## Дальше по цепочке

`pine_smart_compile` → `pine_save` → кнопка **«Добавить на график»** (её показал Егор):
в тулбаре редактора это вторая кнопка, `[...root.querySelectorAll('button')][1]`, где
root = `.publishButtonTitle-ddmSLPrc` вверх на 6 родителей. Она добавляет НОВЫЙ экземпляр —
старый надо снимать через `chart_manage_indicator remove`, иначе на графике два индикатора.

🔑 Перекомпиляция сама по себе НЕ обновляет study на графике — нужен remove + добавить заново.

Связано: [[tradingview_cdp_store_launch]] · [[okowave_pine_port_verified]] ·
[[elliott_canon_ikigai_implemented]]
