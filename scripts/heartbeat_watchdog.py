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
LIMITS = {"scan": 480, "tracker": 480}
GRACE_SEC = 300               # после старта бота — не трогаем (лупы прогреваются)
RESTART_COOLDOWN_MIN = 20     # анти-флаппинг
STATE = Path("logs/heartbeat/.watchdog_last_restart")
HB_DIR = Path("logs/heartbeat")


def _pm2_bot() -> dict | None:
    try:
        out = subprocess.run(["pm2", "jlist"], capture_output=True, text=True, timeout=25,
                             shell=True).stdout
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

    if not dead:
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
        subprocess.run(["pm2", "restart", "oko-bot"], capture_output=True, text=True,
                       timeout=60, shell=True)
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(str(time.time()))
        print("[HB-WD] ✅ pm2 restart oko-bot выполнен")
    except Exception as e:
        print(f"[HB-WD] restart FAILED: {e}")


if __name__ == "__main__":
    main()
