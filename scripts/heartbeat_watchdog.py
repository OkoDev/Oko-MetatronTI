# -*- coding: utf-8 -*-
"""HEARTBEAT-WATCHDOG (16.07) — рестарт бота при ТИХОЙ СМЕРТИ лупов.

Инцидент 15.07 (Егор поймал глазом через 6.5ч): сеть просела в 19:03 → все BingX-запросы
FAIL → scan/tracker/position_sync повисли на ретраях и умерли молча. pm2 показывал `online`
(жил только WS-таск, STATS капали) → авто-рестарта не было. Итог: 12 позиций 6.5ч без
сопровождения (TSL/BE не двигались), шина пустая → дашборд рисовал фантомный «14 DRIFT».

Механика: лупы бьют пульс (core.infra.heartbeat.beat → touch logs/heartbeat/<name>).
Вотчдог читает mtime: пульс старше порога И процесс online → TG-алерт + pm2 restart.
Анти-флаппинг: не чаще RESTART_COOLDOWN_MIN; свежий старт (uptime < GRACE) не трогаем.

pm2 cron: */3 мин. Тест: python scripts/heartbeat_watchdog.py
"""
import sys
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
import json
import subprocess
import time
from pathlib import Path

# порог тишины на луп, сек (запас ×5-8 от нормального цикла: scan 60с, tracker 60с)
# 🔴 18.08 ПОРОГ scan ПОДНЯТ 480 → 1200 (замер по 28 дням лога вотчдога, 13 516 замеров).
# Порог 480с резал ХВОСТ НОРМАЛЬНОГО распределения, а не отделял мёртвый луп:
#   живой scan: медиана 153с, p90 340с, **p99 454с** — вплотную к 480с;
#   178 рестартов: медиана тишины 8.9м, **71% на 8-10м**, ещё 22% на 10-15м.
# То есть ~168 из 178 рестартов убивали ЗДОРОВОГО бота посреди затянувшегося скана
# (500 пар под нагрузкой), плюс 260 раз вотчдог хотел рестартить и его удержал cooldown.
# Настоящая тихая смерть в тех же данных выглядит ИНАЧЕ: 6 случаев >60м, максимум 344м —
# ровно класс инцидента 15.07 (сеть просела, лупы висели 6.5ч), ради которого сторож и написан.
# 1200с (20м) выше p99 живого скана в 2.6× и ловит настоящую смерть за ~23м (порог + подтверждение).
# tracker не трогаем: медиана 40с, p99 109с, за 28 дней НИ ОДНОГО срабатывания.
#
# 🔴 30.08 ТА ЖЕ ОШИБКА ПОВТОРИЛАСЬ НА НОВОМ УРОВНЕ — порог снова встал на край нормы.
# Замер по 6 файлам лога вотчдога (2422 замера scan, 2474 tracker):
#   scan:    медиана 295с, p90 685с, p99 1109с, max 1199с — вплотную к порогу 1200с;
#   tracker: медиана  46с, p90 168с, p99  441с, max  480с — вплотную к порогу 480с.
# ⚠️ выборка УСЕЧЁННАЯ (значения выше порога печатаются не как «пульс Nс назад ✓»), поэтому
# истинный хвост смотрим по самим рестартам: последние 8 подряд — scan с тишиной 20.2-25.9м.
# Итог: 59 рестартов в логе (54 scan, 5 tracker) при 256 рестартах бота — снова убивали
# ЗДОРОВОГО бота посреди затянувшегося скана. Скан деградировал (GlobalRateLimiter-баны,
# OHLCV 44с на пару), 20м стали нормой — а порог остался на 20м.
# Цена рестарта выросла: каждый обрывает EXEC-WS, и все закрытия в окне downtime теряются
# (при sphere_cutover другого пути в БД нет) → 23 зомби-OPEN за двое суток, 70 отказов входа
# по dedup_open на несуществующих позициях. Петля самоусиливается: зомби → больше REST →
# медленнее скан → больше рестартов.
#   scan    1200 → 2700с (45м): в 1.7× выше наблюдаемого хвоста НОРМЫ (26м) и ниже минимума
#           настоящей тихой смерти (>60м, замер 18.08, максимум 344м). Детект смерти ~48м.
#   tracker  480 → 1200с (20м): в 2.7× выше p99 (441с). Все 5 его срабатываний — тишина
#           8-11м, т.е. тот же хвост нормы, а не смерть.
LIMITS = {"scan": 2700, "tracker": 1200}
GRACE_SEC = 300               # после старта бота — не трогаем (лупы прогреваются)
RESTART_COOLDOWN_MIN = 20     # анти-флаппинг
# 11.08 ПОДТВЕРЖДЕНИЕ (инцидент того же дня): вотчдог рестартил ЗДОРОВОГО бота по ОДНОМУ
# просроченному пульсу. За вечер 4 рестарта (18:18, 18:54, 20:21, 20:57 — все на :03,
# т.е. по крону вотчдога), причём в логе pm2 «Stopping app» = намеренная остановка.
# Скан по 500 парам иногда затягивается >8 мин под нагрузкой (параллельные бэктесты,
# сетевые лаги) — это НЕ смерть. Настоящая тихая смерть не проходит сама, поэтому
# требуем ДВА подряд просроченных замера (2 × крон 3мин = 6 мин непрерывной тишины).
# Тот же приём, что спас детектор режима от дёрганья: подтверждение, а не мягкий порог.
CONFIRM_RUNS = 2
STREAK_TTL_SEC = 15 * 60      # серия старше — считаем разорванной (вотчдог сам простаивал)
STATE = Path("logs/heartbeat/.watchdog_last_restart")
STREAK = Path("logs/heartbeat/.watchdog_streak")
HB_DIR = Path("logs/heartbeat")


def _streak_bump(dead: bool) -> int:
    """Счётчик подряд идущих тревог. Возвращает текущую длину серии (0 если всё живо)."""
    now = time.time()
    if not dead:
        try:
            STREAK.unlink(missing_ok=True)
        except Exception:
            pass
        return 0
    n, ts = 0, 0.0
    try:
        n_s, ts_s = STREAK.read_text().strip().split(",")
        n, ts = int(n_s), float(ts_s)
    except Exception:
        pass
    if now - ts > STREAK_TTL_SEC:
        n = 0                                   # серия разорвана — начинаем заново
    n += 1
    try:
        STREAK.parent.mkdir(parents=True, exist_ok=True)
        STREAK.write_text(f"{n},{now}")
    except Exception:
        pass
    return n


def _pm2_bot() -> dict | None:
    try:
        # 17.08: text=True декодировал вывод в cp1251 (локаль) → UnicodeDecodeError в
        # читающем потоке → except ниже глушил всё → «oko-bot не найден» → сторож молча
        # не работал. Тот самый класс тихой смерти, ради которого он и написан.
        out = subprocess.run(["pm2", "jlist"], capture_output=True, timeout=25,
                             shell=True).stdout.decode("utf-8", "replace")
        out = out[out.find("["):]                 # pm2 иногда сыпет баннер перед JSON
        for p in json.loads(out):
            if p.get("name") == "oko-bot":
                return p
    except Exception as e:
        print(f"[HB-WD] pm2 jlist: {e}")
    return None


def main() -> None:
    bot = _pm2_bot()
    if bot is None:
        print("[HB-WD] oko-bot не найден в pm2 — пропуск")
        return
    env = bot.get("pm2_env", {})
    if env.get("status") != "online":
        print(f"[HB-WD] oko-bot status={env.get('status')} — не наше дело (pm2 сам поднимет)")
        return
    uptime_s = max(0, (time.time() * 1000 - float(env.get("pm_uptime") or 0)) / 1000)
    if uptime_s < GRACE_SEC:
        print(f"[HB-WD] бот поднят {uptime_s:.0f}с назад (grace {GRACE_SEC}с) — ждём прогрева")
        return

    dead = []
    for name, limit in LIMITS.items():
        f = HB_DIR / name
        if not f.exists():
            # пульса ещё не было, но бот живёт дольше grace → луп не стартовал
            if uptime_s > GRACE_SEC * 2:
                dead.append(f"{name}: пульса нет вовсе (uptime {uptime_s/60:.0f}м)")
            continue
        age = time.time() - f.stat().st_mtime
        if age > limit:
            dead.append(f"{name}: тишина {age/60:.1f}м (порог {limit/60:.0f}м)")
        else:
            print(f"[HB-WD] {name}: пульс {age:.0f}с назад ✓")

    streak = _streak_bump(bool(dead))
    if not dead:
        return
    if streak < CONFIRM_RUNS:
        print(f"[HB-WD] ⚠ подозрение {streak}/{CONFIRM_RUNS}: {'; '.join(dead)} — "
              f"жду подтверждения (затяжной цикл ≠ смерть)")
        return

    # анти-флаппинг
    try:
        last = float(STATE.read_text().strip())
        if time.time() - last < RESTART_COOLDOWN_MIN * 60:
            print(f"[HB-WD] 🔴 ТИШИНА ({'; '.join(dead)}) — но рестарт был "
                  f"{(time.time()-last)/60:.0f}м назад (cooldown {RESTART_COOLDOWN_MIN}м), жду")
            return
    except Exception:
        pass

    msg = "; ".join(dead)
    print(f"[HB-WD] 🔴 ТИХАЯ СМЕРТЬ ЛУПОВ: {msg} → РЕСТАРТ oko-bot")
    try:
        from oko_feed.alerts import send_tg
        send_tg(f"🔴 <b>HEARTBEAT-WATCHDOG</b>\n\nлупы бота молчат: {msg}\n"
                f"процесс был <code>online</code> (тихая смерть — класс 15.07)\n"
                f"→ авто-рестарт oko-bot\n\n#SYSTEM", channel="system")
    except Exception as e:
        print(f"[HB-WD] TG: {e}")
    try:
        subprocess.run(["pm2", "restart", "oko-bot"], capture_output=True,
                       timeout=60, shell=True)
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(str(time.time()))
        print("[HB-WD] ✅ pm2 restart oko-bot выполнен")
    except Exception as e:
        print(f"[HB-WD] restart FAILED: {e}")


if __name__ == "__main__":
    main()
