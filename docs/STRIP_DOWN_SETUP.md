# Strip-Down эксперимент — пошаговый setup

**Цель:** запустить параллельный бот с минимальным набором filters/gates для baseline сравнения с production.

**Гипотеза:** текущая система — patchwork из ≥13 conditional gates, каждый калиброван под фазу рынка. Strip-down проверяет: **patches помогают или вредят** в долгосрочной перспективе.

**Режим strip-бота:** `sim_only` (без биржевого исполнения) — избегает конфликта с production за position-quota на одном VST API key.

---

## Шаг 1 — Скопировать репо

В PowerShell (Windows):

```powershell
robocopy "E:\MTF BOT\CURSOR\crypto_volume_bot" "E:\MTF BOT\CURSOR\crypto_volume_bot_strip" /E `
  /XD subscriptions.db .git node_modules venv .venv __pycache__ `
  /XF "*.log" "subscriptions.db*" "subscriptions.db-shm" "subscriptions.db-wal"
```

Проверить что создалась папка `E:\MTF BOT\CURSOR\crypto_volume_bot_strip\` со всем кодом, без `.git`, без БД, без логов.

---

## Шаг 2 — Подготовить .env

В strip-папке:

1. Скопировать `.env` из main (если не скопировался):
   ```powershell
   copy "E:\MTF BOT\CURSOR\crypto_volume_bot\.env" "E:\MTF BOT\CURSOR\crypto_volume_bot_strip\.env"
   ```

2. Открыть `crypto_volume_bot_strip\.env` и:
   - **Закомментировать или удалить** строку `TELEGRAM_TOKEN=...`
   - **Закомментировать или удалить** `ADMIN_ID=...`
   - VST API ключи (`BINGX_VST_API_KEY`, `BINGX_VST_SECRET_KEY`) — оставить (нужны для `data_collector` чтобы тянуть OHLCV)
   - Если есть `TELEGRAM_TOKEN_STRIP` — поставить тестовый бот, иначе оставить пустым

Без Telegram токена — бот стартует но не подключится к TG, scan/simulator работают.

---

## Шаг 3 — Применить strip config

Открыть `E:\MTF BOT\CURSOR\crypto_volume_bot_strip\config.yaml` и применить **15 изменений**:

### 3.1 — Execution mode

```yaml
trading:
  execution_mode: sim_only          # БЫЛО: vst
```

### 3.2 — Активные стратегии (одна вместо пяти)

```yaml
trading:
  active_strategies:
  - pivot_reversal                   # ТОЛЬКО pivot_reversal
  # удалить: reversal, trend_following, multi_signal, mtf_bias
```

### 3.3 — Regime блок убрать

```yaml
trading:
  blocked_regimes: []                # БЫЛО: [HIGH_VOL]
```

### 3.4-3.13 — Отключить gates

Найти каждый блок и поменять `enabled: true` → `enabled: false`:

| блок в config | расположение |
|---|---|
| `pivot_proximity_filter:` | `trading:` |
| `pivot_touch_staleness:` | `trading:` |
| `future_pp_score_modifier:` | `trading:` |
| `market_event_marker:` | `trading:` |
| `circuit_breaker:` | `trading:` |
| `weekly_bias_filter:` | `trading:` |
| `btc_market_gate:` | `trading:` |
| `verdict_gate:` | `trading:` |
| `range_bounce:` | `trading:` |
| `narrative:` | `trading:` |
| `weekly_bias_gate:` | `signal_quality:` |

### 3.14 — Убрать MTF gate

```yaml
trading:
  mtf_gate_enabled: false             # БЫЛО: true
```

### 3.15 — DEV-186 регим-gate

```yaml
signal_quality:
  dev186_wt_signal_regime_gate: false # БЫЛО: true
```

---

## Шаг 4 — Дашборд на другом порту (опционально)

Если хочешь видеть оба дашборда параллельно — открыть `web/dashboard_server.py` или config и поменять порт strip-бота на **8001**:

```yaml
# где-то в config или в start_dashboard:
dashboard:
  port: 8001
```

(Если порт жёстко зашит в коде — оставить как есть, прибьётся одним из.)

---

## Шаг 5 — Запуск strip-бота

```powershell
cd "E:\MTF BOT\CURSOR\crypto_volume_bot_strip"
C:\Users\yogoru\AppData\Local\Programs\Python\Python312\python.exe bot_with_subscriptions.py
```

Должны увидеть:
- ✅ `Конфигурация загружена успешно`
- ✅ `execution_mode: sim_only`
- ✅ `active_strategies=['pivot_reversal']`
- ❌ Telegram error при отсутствии токена — нормально, можно игнорировать
- ✅ `Запущен мониторинг N пар`
- ✅ Сделки начнут регистрироваться в `crypto_volume_bot_strip\subscriptions.db`

Через ~30 минут — проверить наличие сделок:

```powershell
cd "E:\MTF BOT\CURSOR\crypto_volume_bot_strip"
C:\Users\yogoru\AppData\Local\Programs\Python\Python312\python.exe -c "import sqlite3; print(sqlite3.connect('subscriptions.db').execute('SELECT COUNT(*) FROM simulated_trades').fetchone())"
```

---

## Шаг 6 — Comparison (через 24 / 72 часа)

В **main** папке запустить:

```powershell
cd "E:\MTF BOT\CURSOR\crypto_volume_bot"
C:\Users\yogoru\AppData\Local\Programs\Python\Python312\python.exe scripts/compare_main_vs_strip.py
```

Скрипт читает обе БД и выводит side-by-side:
- WR (effective_status DEV-190)
- avgR
- catastrophic R<-3 rate
- sample overlap (одинаковые символы)
- per-regime / per-hour breakdown

---

## Период наблюдения

**3-4 дня (≥200 closed сделок).** Раньше — статзначимости нет.

---

## Success criteria

| Метрика | Цель strip vs main |
|---|---|
| WR effective | ≥ main WR + 5pp |
| avgR | ≥ main avgR + 0.1R |
| catastrophic R<-3 rate | ≤ main rate |
| n trades за 24ч | 70-130% от main |

**Если strip ≥ main:** patches вредят, применить strip-config в production.
**Если strip < main:** какие-то filters реально работают — пере-добавлять по одному с проверкой.
**Если ≈ равны:** patches нейтральны, упростить production-config до strip уровня (ниже сложность кода).

---

## Откат

Если strip-бот идёт в большой минус (e.g. >-20R за 12 часов) — остановить процесс, не трогая production. Эксперимент — sim_only, реальных денег не теряет.

```powershell
# Найти и завершить strip-процесс:
Get-Process python | Where-Object {$_.Path -like "*crypto_volume_bot_strip*"} | Stop-Process
```

---

## Файлы эксперимента

- `docs/STRIP_DOWN_SETUP.md` — этот документ (в main repo)
- `scripts/compare_main_vs_strip.py` — comparison (в main repo)
- `crypto_volume_bot_strip/config.yaml` — stripped (создаётся вручную по шагам выше)
- `crypto_volume_bot_strip/subscriptions.db` — fresh DB (создаётся ботом автоматически)
