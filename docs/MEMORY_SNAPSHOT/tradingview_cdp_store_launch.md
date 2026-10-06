---
name: tradingview_cdp_store_launch
description: "TradingView у Егора — Store-версия в WindowsApps, tv_launch её не находит; рабочий запуск с CDP = shell:AppsFolder + ArgumentList, одна команда"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 6be29d28-5351-4bd1-8fa6-e6ec52dc3df7
  modified: 2026-09-05T16:26:22.626Z
---

# ⚡ КАК ПОДКЛЮЧИТЬСЯ К TRADINGVIEW ЗА ОДНУ КОМАНДУ (05.09.2026)

Егор: «ты уже 4 раза одно и то же повторяешь при подключении! найди решение и сделай запись».
Справедливо — ниже готовая команда, больше не искать.

## 🟢 РАБОЧАЯ КОМАНДА (проверена, CDP отвечает Chrome/146)

```powershell
$pfn = "TradingView.Desktop_n534cwy3pjxzj"; $appid = "TradingView.Desktop"
Get-Process -Name TradingView -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 3
Start-Process "shell:AppsFolder\$pfn!$appid" -ArgumentList "--remote-debugging-port=9222"
Start-Sleep -Seconds 12
Invoke-WebRequest "http://127.0.0.1:9222/json/version" -TimeoutSec 4 -UseBasicParsing
```

После этого `mcp__tradingview__tv_health_check` подключается штатно.

## 🔴 ПОЧЕМУ НЕ РАБОТАЕТ ОЧЕВИДНОЕ

1. **`tv_launch` НЕ находит приложение.** Он ищет в `C:\Program Files\TradingView\`,
   `C:\Users\<user>\AppData\Local\TradingView\`, `Program Files (x86)`. У Егора —
   **Store-версия**: `C:\Program Files\WindowsApps\TradingView.Desktop_3.4.0.8149_x64__n534cwy3pjxzj\TradingView.exe`.
   Параметра «путь» у `tv_launch` нет ⇒ он бесполезен на этой машине.

2. **Прямой запуск exe из WindowsApps МОЛЧА НЕ РАБОТАЕТ.** `Start-Process <полный путь>`
   возвращает успех, процесс НЕ поднимается. Store-пакет требует контекста приложения.
   🔴 Так я закрыл Егору работающий TradingView и не смог поднять обратно.

3. **Просто запущенный TradingView НЕ имеет CDP.** Обычный старт (ярлык, меню Пуск) —
   без `--remote-debugging-port`, порт 9222 не слушается, `tv_health_check` падает с
   «CDP connection failed after 5 attempts». Проверка занятости порта:
   `netstat -ano | Select-String "LISTENING"` + сверка pid с процессами TradingView.

## Если приложение надо просто ВЕРНУТЬ (без CDP)

```powershell
$pkg = Get-AppxPackage | Where-Object { $_.Name -like "*TradingView*" }
$appid = (Get-AppxPackageManifest $pkg).Package.Applications.Application.Id
Start-Process "shell:AppsFolder\$($pkg.PackageFamilyName)!$appid"
```

## Как узнать PFN и AppId на другой машине

```powershell
$pkg = Get-AppxPackage | Where-Object { $_.Name -like "*TradingView*" } | Select-Object -First 1
$pkg.PackageFamilyName                                            # → TradingView.Desktop_n534cwy3pjxzj
(Get-AppxPackageManifest $pkg).Package.Applications.Application.Id # → TradingView.Desktop
```

🔑 Ключ решения: **Store-приложение стартует через `shell:AppsFolder\<PFN>!<AppId>`,
и `-ArgumentList` при этом ДОХОДИТ до приложения.** Прямой путь к exe — не доходит.

Связано: [[tradingview_mcp_setup]] · [[feedback_look_at_own_charts]]
