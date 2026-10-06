---
name: tradingview-mcp-setup
description: "🔌 TradingView MCP (01.07): 78 tools, управляет ЖИВЫМ TW Desktop через Chrome DevTools Protocol (chart state/symbol/tf, screenshot/capture, pine, drawing, indicators, watchlist). Сервер e:/PROJECTS/_hub/tradingview-mcp/src/server.js. Рабочий конфиг = ~/.claude.json (user scope, claude mcp add). НЕ ~/.claude/.mcp.json (не читается Claude Code, там был → .bak). Нужен запущенный TW Desktop с CDP + рестарт сессии чтобы tools подгрузились"
metadata:
  node_type: memory
  type: reference
  originSessionId: 03741574-3261-416f-94b1-b4b7c6de6735
---

**TradingView MCP-сервер — подключение (Егор 01.07.2026).**

## Что это
78 tools, управляет **ЖИВЫМ TradingView Desktop через Chrome DevTools Protocol** (не API, не веб).
Категории: chart (get_state/set_symbol/set_timeframe/set_type), capture (screenshot), pine, data,
drawing, alerts, indicators, watchlist, replay, batch, ui, pane, tab. API-ключи НЕ нужны.

## Расположение сервера
`e:/PROJECTS/_hub/tradingview-mcp/src/server.js` (node v24). Проект: git tradesdontlie/tradingview-mcp.

## 🔴 Правильная регистрация (иначе НЕ подключается)
- **Рабочий конфиг = `~/.claude.json` → mcpServers** (user scope). Добавлено:
  `claude mcp add tradingview --scope user -- node "e:/PROJECTS/_hub/tradingview-mcp/src/server.js"`
- **НЕ `~/.claude/.mcp.json`** — README проекта его советует, но Claude Code его НЕ читает
  (было там → `claude mcp list` не видел → переименован в `.mcp.json.bak` как бэкап).
- Проверка: `claude mcp list` → `tradingview: ✔ Connected`.

## Условия работы
1. **TradingView Desktop должен быть ЗАПУЩЕН** с CDP (remote debugging) — сервер цепляется к окну.
2. **Рестарт сессии Claude Code** — MCP tools грузятся при СТАРТЕ сессии; после `mcp add` в текущей
   сессии их ещё нет (ToolSearch не найдёт). После рестарта — 78 `tradingview_*` tools доступны.

## ⚠️ УТОЧНЕНИЕ 14.08.2026 (версия 3.3.0.7992)
Две ловушки, на которых запуск падает:
1. `-Command` требует **ПОЛНЫЙ ПУТЬ** к exe. `-Command "TradingView.exe"` → диалог
   «Не удаётся найти TradingView.exe». Путь: `C:\Program Files\WindowsApps\TradingView.Desktop_3.3.0.7992_x64__n534cwy3pjxzj\TradingView.exe`
2. `Invoke-CommandInDesktopPackage` **БЛОКИРУЕТ** текущий shell до закрытия TW →
   запускать через `Start-Process powershell -WindowStyle Hidden -ArgumentList ...`, иначе таймаут.

Аварийное восстановление без CDP (если убил процессы, а запуск не вышел):
`explorer.exe "shell:appsFolder\TradingView.Desktop_n534cwy3pjxzj!TradingView.Desktop"`

Проверка успеха: `Get-NetTCPConnection -LocalPort 9222 -State Listen` → слушается,
затем `tv_health_check` → cdp_connected: true.

## ✅✅ РЕШЕНО (01.07): запуск MSIX-TW с CDP через Invoke-CommandInDesktopPackage
**РАБОЧАЯ КОМАНДА (Store/MSIX версия 3.2.0.7916, подтверждено — CDP Chrome/140 на :9222):**
```powershell
taskkill /F /IM TradingView.exe /T          # закрыть все (single-instance иначе перехватит)
# дождаться 0 процессов, затем:
$exe = (Get-AppxPackage -Name '*TradingView*').InstallLocation + '\TradingView.exe'
Invoke-CommandInDesktopPackage -PackageFamilyName 'TradingView.Desktop_n534cwy3pjxzj' `
  -AppId 'TradingView.Desktop' -Command $exe -Args '--remote-debugging-port=9222'
```
🔑 **КЛЮЧ: -Command = ПОЛНЫЙ путь к exe** (не `'TradingView.exe'` — даёт «не удаётся найти»).
`Invoke-CommandInDesktopPackage` запускает exe В КОНТЕКСТЕ package identity и передаёт аргументы
НАПРЯМУЮ Chromium (обходит UWP-песочницу). После — `tv_health_check` = success.

## ❌ ЧТО НЕ РАБОТАЕТ (не тратить время):
cmdline `--remote-debugging-port` (Store глотает), vbs `ELECTRON_EXTRA_LAUNCH_ARGS` (Process-env),
прямой exe с env, ПОСТОЯННАЯ user-env, перезапуск explorer, COM ApplicationActivationManager.
Только Invoke-CommandInDesktopPackage с полным путём exe.
До установки non-Store версии — MCP tools подключены, но график читать НЕ могут (нет CDP).
tv_launch ищет non-Store пути (%LOCALAPPDATA%/%PROGRAMFILES%), Store не находит.

## ⚠️ tvd-packages.tradingview.com = ТОЖЕ MSIX (переустановка НЕ помогает, 01.07)
Установщик с официального `tvd-packages.tradingview.com` раздаёт ТОТ ЖЕ MSIX-формат (Store-пакет),
НЕ Electron-installer. После установки версия осталась 3.2.0.7916 в WindowsApps, non-Store Electron
НЕ появился (нет в %LOCALAPPDATA%\Programs, нет Start-ярлыков). **Официальный TW для Windows теперь
только MSIX → UWP-песочница → CDP не пробрасывается.** Варианты когда вернёмся: (1) найти/откатить
СТАРУЮ non-MSIX версию TW (где vbs-лаунчер работал); (2) env через реестр/AppExecutionAlias (не
пробовано); (3) отложить MCP-график, работать через mplfinance (`scripts/viz_ote_live.py` + эталон
`scripts/draw_ote_rpl.py`). MCP-инфраструктура готова — блокер только в CDP на MSIX-TW.

## 🔴 ЛОВУШКА pine_set_source/get_source: рассинхрон с ВИДИМЫМ редактором (14.07)
После открытия юзером «Истории версий» (diff-просмотр) pine_set_source/get_source начинают
работать с ОТВЯЗАННОЙ копией кода: get_source возвращает то, что записал set_source, а видимый
Monaco-редактор (и то, что сохраняет Pine Save / видит юзер) — ДРУГОЙ код. pine_open НЕ лечит.
Симптом: smart_compile "success", но юзер говорит «код не изменился». window.monaco из ui_evaluate
недоступен (замыкание webpack, iframe нет).
**Рабочий обход:** PowerShell `Set-Clipboard` (код из файла) → `ui_mouse_click` в область кода →
`ui_keyboard Ctrl+A` → `Ctrl+V` → скриншот-проверка → `Ctrl+S`. ⚠️ Первый Ctrl+A может не сработать
(фокус ещё не в редакторе) — код ДОПИШЕТСЯ в конец; проверить скриншотом число строк и повторить
Ctrl+A+Ctrl+V (буфер цел). Эмодзи в коде через клипборд лучше заменить ASCII (R-/R+).
**Верификация всегда скриншотом** (`capture_screenshot` + Read) — только он показывает видимый код.

## ⚠️ Инстанс индикатора на графике НЕ обновляется при Pine Save (14.07)
Если study добавлен на график раньше/из другой копии — Save скрипта его не трогает. Пересоздание:
`chart_manage_indicator remove (entity_id из chart_get_state)` → клик «Добавить на график» через
`ui_evaluate` (кнопка в редакторе; `ui_click by=text` её НЕ находит, `chart_manage_indicator add`
по имени кастомного скрипта НЕ работает). Настройки старого инстанса при этом сбрасываются.

**Why:** нативный контроль живого TW-графика (скриншоты сетапов, разметка, индикаторы) — для
визуальной проверки OTE-входов вместо ручного mplfinance (`scripts/viz_ote_live.py`, эталон
`scripts/draw_ote_rpl.py`). **How to apply:** после рестарта звать `chart_get_state` первым,
затем set_symbol/capture. Связь: визуальный аудит сетапов ote_nested ([[ote_nested_live_vst_bleeding]]).
