# Чеклист после рестарта 12.04.2026

> Что проверить после рестарта с DEV-155/156/157 + DEV-110 (ARCH-55)

---

## 1. Сразу после старта (0-5 мин) — логи

### DEV-157: Guard аномального SL
```bash
grep "\[DEV-157\]" logs/bot.log | head -10
```
**Ожидаемо:** если попадётся пара с SL < 0.1% от entry — `ПРОПУСК ... SL слишком близко`.
**Тревога:** если ничего нет в первые 30 мин — норма (редкий кейс, только на экзотических парах).

### DEV-156: Circuit Breaker запустился
```bash
grep "\[CircuitBreaker\]" logs/bot.log | head -5
```
**Ожидаемо:** `status: OFF (WR=XX%)` каждые 15 мин.
**Тревога:** если ни одной строки за 20 мин — задача `circuit_breaker_loop` не стартовала.

### DEV-155: Порог по режиму применяется
```bash
grep "\[DEV-155\]" logs/bot.log | head -10
```
**Ожидаемо:** записи вида `BTCUSDT LONG/HIGH_VOL eff_min_strength=85 (was 50)` при появлении сигналов в HIGH_VOL.
**Норма:** пусто — если HIGH_VOL режима ещё не было с момента старта.

### ARCH-55: RANGE BOUNCE пивот-кеш
```bash
grep "\[ARCH-55\]" logs/bot.log | head -10
```
**Ожидаемо:** `[ARCH-55] BTCUSDT RANGE — pivot_cache загружен: 1D=7 1W=7 уровней`
**Условие:** только если `trading.range_bounce.enabled: true` в config.yaml (сейчас `false` — норма что пусто).

---

## 2. Первые 2 часа — проверка регистрации сделок

```sql
-- Скопировать БД перед запросом (избежать db locked)
cp subscriptions.db /tmp/check.db

sqlite3 /tmp/check.db "
SELECT signal_type, direction,
       strftime('%H:%M', created_at) as time,
       strength, sl_source, regime
FROM simulated_trades
WHERE created_at > datetime('now', '-2 hours')
ORDER BY created_at DESC
LIMIT 20;
"
```

**Смотреть:**
- `sl_source` — должны быть `swing_low/high`, `pivot_s1/r1`, `atr_14`, `tsl_line` (не `range_bounce:pivot` пока не флипнули enabled)
- `regime` — заполняется для новых сделок (TREND_UP/DOWN/RANGE/HIGH_VOL)
- Нет аномальных R_multiple (< -20 или > 20) — DEV-157 должен блокировать

---

## 3. DEV-155 валидация — через 4-6 часов

```sql
sqlite3 /tmp/check.db "
SELECT direction || '_' || regime as key,
       COUNT(*) as n,
       ROUND(SUM(CASE WHEN status IN ('TP','TSL') THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) as WR
FROM simulated_trades
WHERE regime IS NOT NULL AND status != 'OPEN'
  AND created_at > date('now', '-7 days')
GROUP BY direction || '_' || regime
ORDER BY n DESC;
"
```

**Цель:** убедиться что `LONG_HIGH_VOL` и `LONG_RANGE` больше не проваливают WR (было 21-25%).
Эффект будет виден только после накопления 20+ новых сделок в этих режимах.

---

## 4. Флип range_bounce (когда будешь готов)

После 2-4 часов наблюдения и отсутствия критических ошибок:

```yaml
# config.yaml → trading.range_bounce
range_bounce:
  enabled: true          # ← флипнуть с false на true
  sl_buffer_pct: 0.003
  min_tp_r: 3.5
  max_sl_dist_pct: 0.02
```

После флипа проверить:
```bash
grep "\[ARCH-55\]" logs/bot.log | grep "RANGE BOUNCE" | head -10
```
Ожидаемо: `[ARCH-55] XYZUSDT RANGE BOUNCE SL=... TP=... R=3.7`

Критерий через 5-7 дней: **20+ сделок с `sl_source=range_bounce:pivot`** → сравниваем WR с контрольной группой `sl_source=pivot_s1/r1` в том же режиме RANGE.

---

## 5. Если Circuit Breaker активировался (WR < 15%)

```bash
grep "активирован\|OFF\|ON\|WR=" logs/bot.log | grep CircuitBreaker | tail -20
```

CB активировался → min_strength поднят на +10 на 30 мин. Это нормальная защита, не паника.
**Проверить:** через 30 мин — `[CircuitBreaker] OFF — WR=XX%`.
Если CB не снимается >2 часов → смотреть свежие сделки на ложные срабатывания.

---

## 6. Нет сделок вообще?

Если за 2 часа 0 сделок зарегистрировано:
1. `grep "is_actionable.*False\|БЛОК\|min_strength" logs/bot.log | tail -20` — смотреть причину блокировки
2. `grep "scan_one" logs/bot.log | tail -5` — скан вообще работает?
3. `grep "analyze_symbol" logs/bot.log | tail -5` — анализ запускается?

Если DEV-155 установил слишком высокий порог для текущего рынка — проверить `config.yaml`:
```yaml
signal_quality:
  min_strength: 50
  min_strength_by_regime:
    RANGE: 60
    HIGH_VOL: 85
  min_strength_by_direction_regime:
    LONG_RANGE: 75
```
